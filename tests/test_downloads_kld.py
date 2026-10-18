from __future__ import annotations

import hashlib
import pathlib
import tempfile
import unittest

from llm_lab.core import LabError
from llm_lab.downloads import download_artifact, profile_download_lock
from llm_lab.kld import parse_kld_output


class DownloadTests(unittest.TestCase):
    def test_resumes_partial_file_and_verifies_checksum(self) -> None:
        payload = b"0123456789"
        calls: list[int] = []

        def fetch(url: str, destination: pathlib.Path, offset: int) -> None:
            calls.append(offset)
            with destination.open("ab" if offset else "wb") as handle:
                handle.write(payload[offset:])

        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "m.gguf.part").write_bytes(payload[:4])
            artifact = {"repository": "o/r", "file": "sub/m.gguf", "revision": "abc", "sha256": hashlib.sha256(payload).hexdigest()}
            path = download_artifact(root, artifact, fetch=fetch, log=lambda _: None)
            self.assertEqual(path.read_bytes(), payload)
            self.assertEqual(calls, [4])
            self.assertFalse((root / "m.gguf.part").exists())

    def test_rejects_bad_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "m.gguf").write_bytes(b"x")
            with self.assertRaises(LabError):
                download_artifact(root, {"repository": "o/r", "file": "m.gguf", "sha256": "0" * 64}, log=lambda _: None)

    def test_retries_transient_errors(self) -> None:
        attempts = []

        def fetch(url: str, destination: pathlib.Path, offset: int) -> None:
            attempts.append(offset)
            if len(attempts) == 1:
                raise OSError("reset")
            destination.write_bytes(b"ok")

        with tempfile.TemporaryDirectory() as directory:
            path = download_artifact(pathlib.Path(directory), {"repository": "o/r", "file": "m.gguf"}, fetch=fetch, log=lambda _: None)
            self.assertEqual(path.read_bytes(), b"ok")
            self.assertEqual(len(attempts), 2)

    def test_same_profile_lock_is_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory) / "profile"
            with profile_download_lock(root):
                with self.assertRaises(LabError):
                    with profile_download_lock(root):
                        pass


class KldTests(unittest.TestCase):
    def test_parses_llama_perplexity_summary(self) -> None:
        output = """
Mean PPL(Q)                   :   8.123456 ±   0.050000
Mean PPL(base)                :   8.000000 ±   0.049000
Mean PPL(Q)/PPL(base)         :   1.015432 ±   0.001000
Mean    KLD:   0.031234 ±   0.000400
Maximum KLD:   4.500000
99.0%   KLD:   0.420000
Median  KLD:   0.010000
RMS Δp    :  4.321 ± 0.050 %
Same top p: 91.234 ± 0.120 %
"""
        metrics = parse_kld_output(output)
        self.assertAlmostEqual(metrics["meanKld"], 0.031234)
        self.assertAlmostEqual(metrics["sameTopPPercent"], 91.234)
        self.assertAlmostEqual(metrics["pplRatio"], 1.015432)
        self.assertAlmostEqual(metrics["p99Kld"], 0.42)

    def test_missing_kld_is_an_error(self) -> None:
        with self.assertRaises(LabError):
            parse_kld_output("Final estimate: PPL = 8.0")


if __name__ == "__main__":
    unittest.main()

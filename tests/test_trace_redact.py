from __future__ import annotations

import pathlib
import tempfile
import unittest

from llm_lab.traces.redact import RedactionConfig, redact_file, redact_files, redact_text


class TraceRedactionTests(unittest.TestCase):
    def test_redacts_common_secrets_without_placing_values_in_the_report(self) -> None:
        secret = "sk-live-this-value-must-not-leak-1234567890"
        text = (
            f"api_key={secret}\n"
            "OPENAI_API_KEY=another-value-that-must-not-appear\n"
            "password: 'correct horse battery staple'\n"
            "Authorization: Bearer token-that-must-not-appear\n"
            "remote=https://alice:passw0rd@example.invalid/path\n"
            "-----BEGIN PRIVATE KEY-----\nprivate-material\n-----END PRIVATE KEY-----\n"
        )

        result = redact_text(text)

        self.assertNotIn(secret, result.content or "")
        self.assertNotIn("another-value", result.content or "")
        self.assertNotIn("correct horse", result.content or "")
        self.assertNotIn("token-that", result.content or "")
        self.assertNotIn("alice:passw0rd", result.content or "")
        self.assertNotIn("private-material", result.content or "")
        serialized_report = repr(result.report.as_dict())
        self.assertNotIn(secret, serialized_report)
        self.assertNotIn("passw0rd", serialized_report)
        self.assertEqual(result.report.matches, {"key": 2, "password": 1, "private_key": 1, "token": 1, "url_credentials": 1})
        self.assertIn("no sustituye una solución DLP", result.report.warnings[0])

    def test_file_exclusions_and_symlinks_are_omitted_with_safe_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            env = root / ".env.production"
            env.write_text("PASSWORD=do-not-read", encoding="utf-8")
            credential = root / "credenciales" / "login.txt"
            credential.parent.mkdir()
            credential.write_text("password=do-not-read", encoding="utf-8")
            regular = root / "regular.txt"
            regular.write_text("password=remove-me", encoding="utf-8")
            link = root / "linked.txt"
            link.symlink_to(regular)

            env_result = redact_file(env, root=root)
            credential_result = redact_file(credential, root=root)
            link_result = redact_file(link, root=root)

            self.assertEqual(env_result.report.omissions[0].path, ".env.production")
            self.assertEqual(env_result.report.omissions[0].reason, "excluded_path")
            self.assertEqual(credential_result.report.omissions[0].reason, "excluded_path")
            self.assertEqual(link_result.report.omissions[0].reason, "symlink_rejected")
            self.assertEqual(link_result.report.omissions[0].path, "linked.txt")
            self.assertIsNone(link_result.content)

    def test_file_and_total_limits_do_not_include_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            first = root / "first.txt"
            second = root / "second.txt"
            first.write_text("password=first-secret", encoding="utf-8")
            second.write_text("password=second-secret", encoding="utf-8")

            too_large = redact_file(first, root=root, config=RedactionConfig(max_file_bytes=5))
            batch = redact_files(
                [first, second], root=root, config=RedactionConfig(max_total_bytes=first.stat().st_size)
            )

            self.assertIsNone(too_large.content)
            self.assertEqual(too_large.report.omissions[0].reason, "file_limit_exceeded")
            self.assertEqual(list(batch.files), ["first.txt"])
            self.assertEqual(batch.report.omissions[0].reason, "total_limit_exceeded")
            self.assertNotIn("second-secret", repr(batch.report.as_dict()))

    def test_relative_files_are_resolved_against_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source = root / "trace.txt"
            source.write_text("OPENAI_API_KEY=relative-secret", encoding="utf-8")

            result = redact_file("trace.txt", root=root)

            self.assertIn("[REDACTED:KEY]", result.content or "")
            self.assertNotIn("relative-secret", result.content or "")

    def test_outside_root_and_path_traversal_do_not_leak_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary) / "root"
            root.mkdir()
            outside = pathlib.Path(temporary) / "outside.txt"
            outside.write_text("password=outside-secret", encoding="utf-8")

            result = redact_file(outside, root=root)

            self.assertIsNone(result.content)
            self.assertEqual(result.report.omissions[0].path, "outside.txt")
            self.assertEqual(result.report.omissions[0].reason, "outside_root")


if __name__ == "__main__":
    unittest.main()

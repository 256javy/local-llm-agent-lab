from __future__ import annotations

import hashlib
import json
import pathlib
import tempfile
import unittest

from llm_lab.core import LabError
from llm_lab.traces import TraceStore


def event(sequence: int, event_id: str | None = None) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "eventId": event_id or f"event-{sequence}",
        "sequence": sequence,
        "type": "user_message",
        "timestamp": None,
        "sourceRef": {"line": sequence + 1},
        "provenance": "observed",
        "payload": {"text": f"mensaje {sequence}"},
    }


class TraceStoreTests(unittest.TestCase):
    def test_create_trace_preserves_raw_hash_and_normalized_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            raw = root / "source.jsonl"
            raw.write_bytes(b'{"type":"message"}\n')
            store = TraceStore(root / ".local")

            trace = store.create_trace(
                trace_id="trace-fixture",
                source={"client": "pi", "version": "0.84.4", "captureCommand": "fixture"},
                raw_files={"session.jsonl": raw},
                events=[event(0), event(1)],
                warnings=["fixture sintético"],
            )

            manifest = json.loads((trace / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schemaVersion"], 1)
            self.assertEqual(manifest["traceId"], "trace-fixture")
            self.assertEqual(manifest["normalized"]["eventCount"], 2)
            self.assertEqual(manifest["raw"][0]["sha256"], hashlib.sha256(raw.read_bytes()).hexdigest())
            lines = (trace / "normalized/events.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual([json.loads(line)["eventId"] for line in lines], ["event-0", "event-1"])
            self.assertEqual((trace / "raw/session.jsonl").stat().st_mode & 0o777, 0o400)
            self.assertEqual((trace / "manifest.json").stat().st_mode & 0o777, 0o600)

    def test_create_trace_publishes_hashed_artifacts_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            raw = root / "source.json"
            raw.write_text("{}", encoding="utf-8")
            store = TraceStore(root / ".local")

            trace = store.create_trace(
                trace_id="trace-artifacts",
                source={"client": "pi", "version": "unknown", "captureCommand": "trace begin"},
                raw_files={"capture.json": raw},
                events=[],
                artifacts={"repository/initial/snapshot.json": "{\"status\":\"captured\"}\n"},
                manifest_fields={"captureMode": "exact"},
            )

            payload = store.show_trace("trace-artifacts")
            self.assertEqual(payload["manifest"]["captureMode"], "exact")
            self.assertEqual(payload["manifest"]["artifacts"][0]["path"], "repository/initial/snapshot.json")
            self.assertEqual((trace / "repository/initial/snapshot.json").stat().st_mode & 0o777, 0o600)

    def test_rejects_unsafe_artifact_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            raw = root / "source.json"
            raw.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(LabError, "Ruta de artefacto"):
                TraceStore(root / ".local").create_trace(
                    source={"client": "pi", "version": "unknown", "captureCommand": "fixture"},
                    raw_files={"source.json": raw},
                    events=[],
                    artifacts={"../escape.json": "{}"},
                )

    def test_existing_trace_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            raw = root / "source.json"
            raw.write_text("{}", encoding="utf-8")
            store = TraceStore(root / ".local")
            arguments = {
                "trace_id": "trace-same",
                "source": {"client": "opencode", "version": "1.18.25", "captureCommand": "fixture"},
                "raw_files": {"export.json": raw},
                "events": [event(0)],
            }
            first = store.create_trace(**arguments)
            manifest_before = (first / "manifest.json").read_bytes()
            with self.assertRaisesRegex(LabError, "inmutable"):
                store.create_trace(**arguments)
            self.assertEqual((first / "manifest.json").read_bytes(), manifest_before)

    def test_rejects_gaps_duplicate_ids_and_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            raw = root / "source.json"
            raw.write_text("{}", encoding="utf-8")
            store = TraceStore(root / ".local")
            source = {"client": "pi", "version": "0.84.4", "captureCommand": "fixture"}
            with self.assertRaisesRegex(LabError, "Secuencia"):
                store.create_trace(source=source, raw_files={"source.json": raw}, events=[event(1)])
            with self.assertRaisesRegex(LabError, "duplicado"):
                store.create_trace(source=source, raw_files={"source.json": raw}, events=[event(0, "same"), event(1, "same")])
            with self.assertRaisesRegex(LabError, "Nombre de raw"):
                store.create_trace(source=source, raw_files={"../source.json": raw}, events=[])

    def test_validation_failure_leaves_no_partial_trace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            raw = root / "source.json"
            raw.write_text("{}", encoding="utf-8")
            store = TraceStore(root / ".local")
            invalid = event(0)
            invalid["provenance"] = "assumed"
            with self.assertRaisesRegex(LabError, "Procedencia"):
                store.create_trace(
                    trace_id="trace-invalid",
                    source={"client": "pi", "version": "0.84.4", "captureCommand": "fixture"},
                    raw_files={"source.json": raw},
                    events=[invalid],
                )
            self.assertFalse((store.traces_dir / "trace-invalid").exists())

    def test_rejects_trace_without_raw_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = TraceStore(pathlib.Path(temporary) / ".local")
            with self.assertRaisesRegex(LabError, "al menos un archivo raw"):
                store.create_trace(
                    source={"client": "pi", "version": "0.84.4", "captureCommand": "fixture"},
                    raw_files={},
                    events=[],
                )

    def test_list_and_show_read_complete_traces(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            raw = root / "source.json"
            raw.write_text("{}", encoding="utf-8")
            store = TraceStore(root / ".local")
            store.create_trace(
                trace_id="trace-readable",
                source={"client": "opencode", "version": "1.18.25", "captureCommand": "fixture"},
                raw_files={"source.json": raw},
                events=[event(0)],
            )

            self.assertEqual([item["traceId"] for item in store.list_traces()], ["trace-readable"])
            payload = store.show_trace("trace-readable")
            self.assertEqual(payload["manifest"]["traceId"], "trace-readable")
            self.assertEqual(payload["events"][0]["eventId"], "event-0")
            with self.assertRaisesRegex(LabError, "no encontrado"):
                store.show_trace("missing")

    def test_show_rejects_modified_raw_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            raw = root / "source.json"
            raw.write_text("{}", encoding="utf-8")
            store = TraceStore(root / ".local")
            trace = store.create_trace(
                trace_id="trace-tampered",
                source={"client": "pi", "version": "0.84.4", "captureCommand": "fixture"},
                raw_files={"source.json": raw},
                events=[event(0)],
            )
            copied = trace / "raw" / "source.json"
            copied.chmod(0o600)
            copied.write_text('{"changed":true}', encoding="utf-8")
            with self.assertRaisesRegex(LabError, "evidencia raw"):
                store.show_trace("trace-tampered")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..core import LabError
from .models import SCHEMA_VERSION


class EventBuilder:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.warnings: list[str] = []
        self._ids: set[str] = set()

    def add(
        self,
        event_type: str,
        source_ref: dict[str, Any],
        payload: dict[str, Any],
        *,
        event_id: str,
        timestamp: str | None = None,
    ) -> None:
        candidate = event_id or f"event-{len(self.events)}"
        suffix = 2
        while candidate in self._ids:
            candidate = f"{event_id}-{suffix}"
            suffix += 1
        self._ids.add(candidate)
        self.events.append({
            "schemaVersion": SCHEMA_VERSION,
            "eventId": candidate,
            "sequence": len(self.events),
            "type": event_type,
            "timestamp": timestamp,
            "sourceRef": source_ref,
            "provenance": "observed",
            "payload": payload,
        })

    def unknown(
        self,
        *,
        source_ref: dict[str, Any],
        payload: dict[str, Any],
        event_id: str,
        label: str,
        timestamp: str | None = None,
    ) -> None:
        self.warnings.append(f"Tipo de fuente no reconocido preservado como system_event: {label}")
        self.add("system_event", source_ref, payload, event_id=event_id, timestamp=timestamp)


def text_content(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return None
    parts = [item.get("text") for item in value if isinstance(item, dict) and item.get("type") == "text"]
    text = "\n".join(part for part in parts if isinstance(part, str))
    return text or None


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LabError(f"{label} debe ser un objeto JSON", 2)
    return value


def require_array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise LabError(f"{label} debe ser un arreglo JSON", 2)
    return value


def combine_warnings(*groups: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(warning for group in groups for warning in group))

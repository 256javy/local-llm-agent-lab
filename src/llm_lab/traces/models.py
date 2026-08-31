from __future__ import annotations

import datetime
from typing import Any

from ..core import LabError


SCHEMA_VERSION = 1
PROVENANCE_VALUES = {
    "observed",
    "calculated",
    "human_annotated",
    "reviewer_inferred",
}
EVENT_TYPES = {
    "user_message",
    "assistant_message",
    "observed_reasoning",
    "tool_call",
    "tool_result",
    "error",
    "model_change",
    "thinking_level_change",
    "compaction",
    "branch",
    "human_intervention",
    "system_event",
}


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def validate_event(event: dict[str, Any], *, expected_sequence: int | None = None) -> None:
    required = {"schemaVersion", "eventId", "sequence", "type", "sourceRef", "provenance", "payload"}
    missing = sorted(required - event.keys())
    if missing:
        raise LabError(f"Evento normalizado inválido; faltan campos: {', '.join(missing)}", 2)
    if event["schemaVersion"] != SCHEMA_VERSION:
        raise LabError(f"schemaVersion de evento no soportado: {event['schemaVersion']}", 2)
    if not isinstance(event["eventId"], str) or not event["eventId"].strip():
        raise LabError("eventId debe ser un string no vacío", 2)
    if not isinstance(event["sequence"], int) or event["sequence"] < 0:
        raise LabError("sequence debe ser un entero no negativo", 2)
    if expected_sequence is not None and event["sequence"] != expected_sequence:
        raise LabError(
            f"Secuencia de eventos inválida: se esperaba {expected_sequence} y se recibió {event['sequence']}",
            2,
        )
    if event["type"] not in EVENT_TYPES:
        raise LabError(f"Tipo de evento normalizado no soportado: {event['type']}", 2)
    if event["provenance"] not in PROVENANCE_VALUES:
        raise LabError(f"Procedencia de evento no soportada: {event['provenance']}", 2)
    if not isinstance(event["sourceRef"], dict):
        raise LabError("sourceRef debe ser un objeto", 2)
    if not isinstance(event["payload"], dict):
        raise LabError("payload debe ser un objeto", 2)
    if "timestamp" in event and event["timestamp"] is not None and not isinstance(event["timestamp"], str):
        raise LabError("timestamp debe ser un string o null", 2)

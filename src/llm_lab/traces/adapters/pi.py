from __future__ import annotations

import json
import pathlib
from typing import Any

from ...core import LabError
from ..normalize import EventBuilder, text_content


def _message_events(builder: EventBuilder, entry: dict[str, Any], source_ref: dict[str, Any], base_id: str) -> None:
    message = entry.get("message")
    if not isinstance(message, dict):
        builder.unknown(source_ref=source_ref, payload=entry, event_id=base_id, label="message sin objeto message")
        return
    role = message.get("role")
    timestamp = entry.get("timestamp") if isinstance(entry.get("timestamp"), str) else None
    content = message.get("content")
    if role == "user":
        builder.add("user_message", source_ref, {"text": text_content(content), "message": message}, event_id=base_id, timestamp=timestamp)
        return
    if role == "toolResult":
        event_type = "error" if message.get("isError") else "tool_result"
        builder.add(event_type, source_ref, {"toolCallId": message.get("toolCallId"), "toolName": message.get("toolName"), "text": text_content(content), "message": message}, event_id=base_id, timestamp=timestamp)
        return
    if role == "assistant":
        text = text_content(content)
        builder.add("assistant_message", source_ref, {"text": text, "message": message}, event_id=base_id, timestamp=timestamp)
        for index, block in enumerate(content if isinstance(content, list) else []):
            if not isinstance(block, dict):
                continue
            block_ref = {**source_ref, "contentIndex": index}
            block_id = f"{base_id}-{index}"
            if block.get("type") == "thinking":
                builder.add("observed_reasoning", block_ref, {"text": block.get("thinking")}, event_id=f"{block_id}-reasoning", timestamp=timestamp)
            elif block.get("type") == "toolCall":
                builder.add("tool_call", block_ref, {"toolCallId": block.get("id"), "name": block.get("name"), "arguments": block.get("arguments")}, event_id=f"{block_id}-tool", timestamp=timestamp)
        if message.get("errorMessage"):
            builder.add("error", source_ref, {"message": message.get("errorMessage"), "stopReason": message.get("stopReason")}, event_id=f"{base_id}-error", timestamp=timestamp)
        return
    if role == "branchSummary":
        builder.add("branch", source_ref, message, event_id=base_id, timestamp=timestamp)
        return
    if role == "compactionSummary":
        builder.add("compaction", source_ref, message, event_id=base_id, timestamp=timestamp)
        return
    builder.unknown(source_ref=source_ref, payload=entry, event_id=base_id, label=f"message/{role or 'sin rol'}")


def normalize_pi_jsonl(path: pathlib.Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    builder = EventBuilder()
    header: dict[str, Any] | None = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise LabError(f"No se pudo leer la sesión Pi: {exc}", 2) from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LabError(f"JSONL Pi inválido en línea {line_number}: {exc.msg}", 2) from exc
        if not isinstance(entry, dict):
            raise LabError(f"Entrada Pi inválida en línea {line_number}: debe ser un objeto", 2)
        entry_type = entry.get("type")
        source_ref = {"line": line_number, "id": entry.get("id"), "parentId": entry.get("parentId")}
        base_id = str(entry.get("id") or f"pi-line-{line_number}")
        timestamp = entry.get("timestamp") if isinstance(entry.get("timestamp"), str) else None
        if entry_type == "session":
            if header is not None:
                raise LabError("La sesión Pi contiene más de un header", 2)
            header = entry
        elif entry_type == "message":
            _message_events(builder, entry, source_ref, base_id)
        elif entry_type == "model_change":
            builder.add("model_change", source_ref, {"provider": entry.get("provider"), "modelId": entry.get("modelId")}, event_id=base_id, timestamp=timestamp)
        elif entry_type == "thinking_level_change":
            builder.add("thinking_level_change", source_ref, {"thinkingLevel": entry.get("thinkingLevel")}, event_id=base_id, timestamp=timestamp)
        elif entry_type == "compaction":
            builder.add("compaction", source_ref, entry, event_id=base_id, timestamp=timestamp)
        elif entry_type == "branch_summary":
            builder.add("branch", source_ref, entry, event_id=base_id, timestamp=timestamp)
        elif entry_type in {"custom", "custom_message", "label", "session_info"}:
            builder.add("system_event", source_ref, entry, event_id=base_id, timestamp=timestamp)
        else:
            builder.unknown(source_ref=source_ref, payload=entry, event_id=base_id, label=str(entry_type or "sin type"), timestamp=timestamp)
    if header is None:
        raise LabError("La sesión Pi no contiene un header type=session", 2)
    version = header.get("version", 1)
    if not isinstance(version, int) or version < 1:
        raise LabError("Versión de sesión Pi inválida", 2)
    metadata = {"sessionId": header.get("id"), "formatVersion": version, "cwd": header.get("cwd")}
    return metadata, builder.events, builder.warnings

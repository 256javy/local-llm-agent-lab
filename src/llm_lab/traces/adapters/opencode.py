from __future__ import annotations

import json
import pathlib
from typing import Any

from ...core import LabError
from ..normalize import EventBuilder, require_array, require_object


def _timestamp(info: dict[str, Any]) -> str | None:
    value = info.get("time")
    if not isinstance(value, dict):
        return None
    milliseconds = value.get("created")
    if not isinstance(milliseconds, (int, float)):
        return None
    import datetime
    return datetime.datetime.fromtimestamp(milliseconds / 1000, datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_opencode_export(path: pathlib.Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LabError(f"Export OpenCode inválido: {exc.msg}", 2) from exc
    except (OSError, UnicodeError) as exc:
        raise LabError(f"No se pudo leer el export OpenCode: {exc}", 2) from exc
    root = require_object(document, "El export OpenCode")
    session_info = require_object(root.get("info"), "info de OpenCode")
    messages = require_array(root.get("messages"), "messages de OpenCode")
    builder = EventBuilder()
    for message_index, value in enumerate(messages):
        message = require_object(value, f"messages[{message_index}]")
        info = require_object(message.get("info"), f"messages[{message_index}].info")
        parts = require_array(message.get("parts"), f"messages[{message_index}].parts")
        role = info.get("role")
        message_id = str(info.get("id") or f"opencode-message-{message_index}")
        timestamp = _timestamp(info)
        text_parts = [part.get("text") for part in parts if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str)]
        if role in {"user", "assistant"}:
            builder.add(f"{role}_message", {"messageIndex": message_index, "messageId": info.get("id")}, {"text": "\n".join(text_parts) or None, "info": info}, event_id=message_id, timestamp=timestamp)
        else:
            builder.unknown(source_ref={"messageIndex": message_index, "messageId": info.get("id")}, payload=message, event_id=message_id, label=f"message/{role or 'sin rol'}", timestamp=timestamp)
        for part_index, value_part in enumerate(parts):
            if not isinstance(value_part, dict):
                builder.warnings.append(f"Parte OpenCode no-objeto preservada solo en raw: mensaje {message_index}, parte {part_index}")
                continue
            part_type = value_part.get("type")
            part_id = str(value_part.get("id") or f"{message_id}-part-{part_index}")
            source_ref = {"messageIndex": message_index, "messageId": info.get("id"), "partIndex": part_index, "partId": value_part.get("id")}
            if part_type == "reasoning":
                builder.add("observed_reasoning", source_ref, {"text": value_part.get("text"), "metadata": value_part.get("metadata")}, event_id=part_id, timestamp=timestamp)
            elif part_type == "tool":
                state = value_part.get("state") if isinstance(value_part.get("state"), dict) else {}
                builder.add("tool_call", source_ref, {"toolCallId": value_part.get("callID") or value_part.get("id"), "name": value_part.get("tool"), "input": state.get("input"), "status": state.get("status")}, event_id=f"{part_id}-call", timestamp=timestamp)
                if state.get("status") in {"completed", "error"}:
                    event_type = "error" if state.get("status") == "error" else "tool_result"
                    builder.add(event_type, source_ref, {"toolCallId": value_part.get("callID") or value_part.get("id"), "name": value_part.get("tool"), "output": state.get("output"), "error": state.get("error"), "status": state.get("status")}, event_id=f"{part_id}-result", timestamp=timestamp)
            elif part_type in {"text", "file"}:
                continue
            elif part_type in {"compaction", "summary"}:
                builder.add("compaction", source_ref, value_part, event_id=part_id, timestamp=timestamp)
            elif part_type in {"step-start", "step-finish", "snapshot", "patch", "agent", "subtask"}:
                builder.add("system_event", source_ref, value_part, event_id=part_id, timestamp=timestamp)
            else:
                builder.unknown(source_ref=source_ref, payload=value_part, event_id=part_id, label=f"part/{part_type or 'sin type'}", timestamp=timestamp)
    metadata = {"sessionId": session_info.get("id"), "formatVersion": session_info.get("version"), "directory": session_info.get("directory")}
    return metadata, builder.events, builder.warnings

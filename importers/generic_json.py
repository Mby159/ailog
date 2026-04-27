"""
AILog Generic JSON Importer

Fallback importer for JSON conversation data that doesn't match
any specific platform format.

Supports two formats:
  1. Array of conversations with messages
  2. Single conversation object

Expected structure (flexible):
[
  {
    "title": "...",          // optional
    "messages": [
      {"role": "user"|"assistant"|"system", "content": "..."},
      ...
    ]
  }
]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from ailog.core.models import (
    AILogFile,
    AILogFileMetadata,
    Interaction,
    Message,
    SensitivityInfo,
    RiskLevel,
    Role,
    ContentType,
)
from ailog.importers.base import BaseImporter


def _map_role(role_str: str) -> Role:
    mapping = {
        "user": Role.USER,
        "human": Role.USER,
        "assistant": Role.ASSISTANT,
        "ai": Role.ASSISTANT,
        "system": Role.SYSTEM,
        "tool": Role.TOOL,
    }
    return mapping.get(role_str.lower(), Role.USER)


def _parse_conversation(conv: Dict[str, Any], conv_idx: int) -> List[Interaction]:
    """Parse a generic conversation into AILog Interactions."""
    title = conv.get("title", f"Conversation {conv_idx}")
    conv_id = conv.get("id", f"gen_conv_{conv_idx}")
    messages_raw = conv.get("messages", [])
    if not messages_raw:
        return []

    interactions = []
    pending_user_msg = None
    turn_index = 0

    for raw_msg in messages_raw:
        role = _map_role(raw_msg.get("role", "user"))
        content = raw_msg.get("content", "")
        if not content:
            continue

        msg = Message(
            role=role,
            content=content,
            content_type=ContentType.TEXT,
        )

        if role == Role.USER:
            pending_user_msg = msg
        elif role == Role.ASSISTANT:
            turn_index += 1
            messages = []
            if pending_user_msg:
                messages.append(pending_user_msg)
            messages.append(msg)

            interaction = Interaction(
                id=f"ix_gen_{conv_id}_{turn_index}",
                timestamp=conv.get("created_at", ""),
                session_id=f"sess_gen_{conv_id}",
                turn_index=turn_index,
                messages=messages,
                sensitivity=SensitivityInfo(
                    max_risk_level=RiskLevel.LOW,
                    detected_items=[],
                    scanned_by="none",
                ),
                custom={"title": title},
            )
            interactions.append(interaction)
            pending_user_msg = None

    return interactions


class GenericJSONImporter(BaseImporter):
    """Fallback importer for generic JSON conversation data."""

    platform_id = "custom"
    platform_url = None

    def detect(self, source_path: str | Path) -> bool:
        """Accept any JSON with a messages array."""
        source = Path(source_path).resolve()
        if not source.is_file() or source.suffix != ".json":
            return False
        try:
            with open(source, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and len(data) > 0:
                first = data[0]
                return isinstance(first, dict) and "messages" in first
            if isinstance(data, dict):
                return "messages" in data
            return False
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False

    def parse(self, source_path: str | Path) -> AILogFile:
        """Parse generic JSON conversations into ALogFile."""
        source = Path(source_path).resolve()
        with open(source, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            data = [data]

        all_interactions = []
        for conv_idx, conv in enumerate(data):
            interactions = _parse_conversation(conv, conv_idx)
            all_interactions.extend(interactions)

        metadata = self._build_metadata(
            tags=["generic-import"],
            custom={"source_conversations_count": len(data)},
        )

        return AILogFile(
            ailog_version="0.1",
            metadata=metadata,
            interactions=all_interactions,
        )

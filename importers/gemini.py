"""
AILog Gemini Importer

Imports Google Gemini conversations into AILog format.

Gemini doesn't have an official export yet. This importer supports:
  1. Google Takeout JSON export (if available)
  2. Manual conversation JSON (documented below)
  3. Browser extension captured format

Expected JSON format:
[
  {
    "title": "Conversation Title",
    "created_at": "2026-04-26T08:00:00Z",
    "messages": [
      {"role": "user", "content": "..."},
      {"role": "model", "content": "...", "model": "gemini-2.0-flash"}
    ]
  }
]

Note: Gemini uses "model" as the assistant role name (not "assistant").
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


def _map_role(gemini_role: str) -> Role:
    """Map Gemini's role names to AILog Role."""
    mapping = {
        "user": Role.USER,
        "model": Role.ASSISTANT,  # Gemini uses "model" for assistant
        "assistant": Role.ASSISTANT,
        "system": Role.SYSTEM,
    }
    return mapping.get(gemini_role.lower(), Role.USER)


def _parse_conversation(conv: Dict[str, Any], conv_idx: int) -> List[Interaction]:
    """Parse a single Gemini conversation."""
    title = conv.get("title", f"Gemini Conversation {conv_idx}")
    conv_id = conv.get("id", f"gemini_conv_{conv_idx}")
    messages_raw = conv.get("messages", [])
    created_at = conv.get("created_at", "")

    if not messages_raw:
        return []

    interactions = []
    pending_user_msg = None
    turn_index = 0

    for raw_msg in messages_raw:
        role_str = raw_msg.get("role", "user")
        role = _map_role(role_str)
        content = raw_msg.get("content", "")
        if not content:
            continue

        # Handle Gemini's parts format (list of content parts)
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict):
                    parts.append(part.get("text", str(part)))
            content = "\n\n".join(parts)

        content_type = ContentType.MARKDOWN if "```" in content else ContentType.TEXT
        msg_model = raw_msg.get("model", "")
        msg_ts = raw_msg.get("created_at", "")

        msg = Message(
            role=role,
            content=content,
            content_type=content_type,
            timestamp=msg_ts or None,
            model=msg_model or None,
            model_provider="google" if "gemini" in msg_model.lower() else None,
            custom={
                "gemini_conversation_id": conv_id,
                "gemini_title": title,
                "gemini_original_role": role_str,
            },
        )

        if role == Role.USER:
            pending_user_msg = msg
        elif role == Role.ASSISTANT:
            turn_index += 1
            messages = []
            if pending_user_msg:
                messages.append(pending_user_msg)
            messages.append(msg)

            ts = messages[0].timestamp or created_at
            interaction = Interaction(
                id=f"ix_gemini_{conv_id}_{turn_index}",
                timestamp=ts,
                session_id=f"sess_gemini_{conv_id}",
                turn_index=turn_index,
                messages=messages,
                sensitivity=SensitivityInfo(
                    max_risk_level=RiskLevel.LOW,
                    detected_items=[],
                    scanned_by="none",
                ),
                custom={"gemini_title": title},
            )
            interactions.append(interaction)
            pending_user_msg = None

    if pending_user_msg:
        turn_index += 1
        interactions.append(
            Interaction(
                id=f"ix_gemini_{conv_id}_{turn_index}",
                timestamp=pending_user_msg.timestamp or created_at,
                session_id=f"sess_gemini_{conv_id}",
                turn_index=turn_index,
                messages=[pending_user_msg],
                sensitivity=SensitivityInfo(
                    max_risk_level=RiskLevel.LOW,
                    detected_items=[],
                    scanned_by="none",
                ),
                custom={"gemini_title": title},
            )
        )

    return interactions


class GeminiImporter(BaseImporter):
    """Import Gemini conversations into AILog format."""

    platform_id = "gemini"
    platform_url = "https://gemini.google.com"

    def detect(self, source_path: str | Path) -> bool:
        """Detect if source is a Gemini conversation export."""
        source = Path(source_path).resolve()
        if not source.is_file() or source.suffix != ".json":
            return False
        try:
            with open(source, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and len(data) > 0:
                first = data[0]
                if not isinstance(first, dict):
                    return False
                if "mapping" in first:  # ChatGPT format
                    return False
                msgs = first.get("messages", [])
                if not msgs:
                    return False
                # Gemini-specific: "model" role or gemini model names
                roles = {m.get("role", "") for m in msgs}
                models = {m.get("model", "") for m in msgs if m.get("model")}
                if "model" in roles:  # Gemini uses "model" not "assistant"
                    return True
                if any("gemini" in m.lower() for m in models):
                    return True
                return False
            return False
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False

    def parse(self, source_path: str | Path) -> AILogFile:
        """Parse Gemini conversations into ALogFile."""
        source = Path(source_path).resolve()
        with open(source, "r", encoding="utf-8") as f:
            conversations = json.load(f)
        if isinstance(conversations, dict):
            conversations = [conversations]

        all_interactions = []
        for conv_idx, conv in enumerate(conversations):
            interactions = _parse_conversation(conv, conv_idx)
            all_interactions.extend(interactions)

        all_interactions.sort(key=lambda ix: ix.timestamp or "")

        metadata = self._build_metadata(
            tags=["gemini-export"],
            custom={
                "source_conversations_count": len(conversations),
                "source_interactions_count": len(all_interactions),
            },
        )

        return AILogFile(
            ailog_version="0.1",
            metadata=metadata,
            interactions=all_interactions,
        )

"""
AILog Claude Importer

Imports Claude conversations into AILog format.

Claude doesn't have an official export, so this importer supports:
  1. Manual copy-paste JSON format (documented below)
  2. Claude Projects export (if available)
  3. Browser extension captured format

Expected JSON format:
[
  {
    "title": "Conversation Title",
    "created_at": "2026-04-26T08:00:00Z",
    "messages": [
      {"role": "human", "content": "...", "created_at": "..."},
      {"role": "assistant", "content": "...", "model": "claude-3-5-sonnet", "created_at": "..."}
    ]
  }
]
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ailog.core.models import (
    AILogFile,
    AILogFileMetadata,
    Interaction,
    Message,
    SensitivityInfo,
    RiskLevel,
    Role,
    ContentType,
    OwnerInfo,
    OwnerIdType,
)
from ailog.importers.base import BaseImporter


def _map_role(claude_role: str) -> Role:
    """Map Claude's role names to AILog Role."""
    mapping = {
        "human": Role.USER,
        "user": Role.USER,
        "assistant": Role.ASSISTANT,
        "system": Role.SYSTEM,
    }
    return mapping.get(claude_role.lower(), Role.USER)


def _parse_conversation(conv: Dict[str, Any], conv_idx: int) -> List[Interaction]:
    """Parse a single Claude conversation into AILog Interactions."""
    conv_title = conv.get("title", f"Claude Conversation {conv_idx}")
    conv_id = conv.get("id", f"claude_conv_{conv_idx}")
    messages_raw = conv.get("messages", [])
    created_at = conv.get("created_at", "")

    if not messages_raw:
        return []

    interactions = []
    pending_user_msg = None
    pending_user_idx = None
    turn_index = 0

    for msg_idx, raw_msg in enumerate(messages_raw):
        role_str = raw_msg.get("role", "user")
        role = _map_role(role_str)
        content = raw_msg.get("content", "")
        if not content:
            continue

        content_type = ContentType.MARKDOWN if "```" in content else ContentType.TEXT
        msg_model = raw_msg.get("model", "")
        msg_ts = raw_msg.get("created_at", "")

        msg = Message(
            role=role,
            content=content,
            content_type=content_type,
            timestamp=msg_ts or None,
            model=msg_model or None,
            model_provider="anthropic" if msg_model else None,
            custom={
                "claude_conversation_id": conv_id,
                "claude_title": conv_title,
            },
        )

        if role == Role.USER:
            pending_user_msg = msg
            pending_user_idx = msg_idx
        elif role == Role.ASSISTANT:
            turn_index += 1
            messages = []
            if pending_user_msg:
                messages.append(pending_user_msg)
            messages.append(msg)

            ts = messages[0].timestamp or created_at
            interaction = Interaction(
                id=f"ix_claude_{conv_id}_{turn_index}",
                timestamp=ts,
                session_id=f"sess_claude_{conv_id}",
                turn_index=turn_index,
                messages=messages,
                sensitivity=SensitivityInfo(
                    max_risk_level=RiskLevel.LOW,
                    detected_items=[],
                    scanned_by="none",
                ),
                custom={"claude_title": conv_title},
            )
            interactions.append(interaction)
            pending_user_msg = None
            pending_user_idx = None

    # Orphan user message
    if pending_user_msg:
        turn_index += 1
        interactions.append(
            Interaction(
                id=f"ix_claude_{conv_id}_{turn_index}",
                timestamp=pending_user_msg.timestamp or created_at,
                session_id=f"sess_claude_{conv_id}",
                turn_index=turn_index,
                messages=[pending_user_msg],
                sensitivity=SensitivityInfo(
                    max_risk_level=RiskLevel.LOW,
                    detected_items=[],
                    scanned_by="none",
                ),
                custom={"claude_title": conv_title},
            )
        )

    return interactions


class ClaudeImporter(BaseImporter):
    """Import Claude conversations into AILog format."""

    platform_id = "claude"
    platform_url = "https://claude.ai"

    def detect(self, source_path: str | Path) -> bool:
        """Detect if source is a Claude conversation export."""
        source = Path(source_path).resolve()
        if not source.is_file() or source.suffix != ".json":
            return False
        try:
            with open(source, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and len(data) > 0:
                first = data[0]
                # Claude format: has "messages" with "human"/"assistant" roles
                msgs = first.get("messages", [])
                if msgs:
                    roles = {m.get("role", "") for m in msgs}
                    return "human" in roles or "assistant" in roles
            return False
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False

    def parse(self, source_path: str | Path) -> AILogFile:
        """Parse Claude conversations into ALogFile."""
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
            tags=["claude-export"],
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

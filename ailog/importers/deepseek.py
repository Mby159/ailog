"""
AILog DeepSeek Importer

Imports DeepSeek conversations into AILog format.

DeepSeek doesn't have an official export feature. This importer supports:
  1. DeepSeek Chat Exporter Chrome extension JSON output
  2. Manual conversation JSON (documented below)

Expected JSON format (from Chrome extension or manual capture):
[
  {
    "title": "Conversation Title",
    "created_at": "2026-04-26T08:00:00Z",
    "messages": [
      {"role": "user", "content": "..."},
      {"role": "assistant", "content": "...", "model": "deepseek-chat"}
    ]
  }
]

DeepSeek uses the same role names as OpenAI (user/assistant/system),
so the role mapping is straightforward.
"""

from __future__ import annotations

import json
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
)
from ailog.importers.base import BaseImporter


def _parse_conversation(conv: Dict[str, Any], conv_idx: int) -> List[Interaction]:
    """Parse a single DeepSeek conversation into AILog Interactions."""
    title = conv.get("title", f"DeepSeek Conversation {conv_idx}")
    conv_id = conv.get("id", f"ds_conv_{conv_idx}")
    messages_raw = conv.get("messages", [])
    created_at = conv.get("created_at", "")

    if not messages_raw:
        return []

    interactions = []
    pending_user_msg = None
    turn_index = 0

    for raw_msg in messages_raw:
        role_str = raw_msg.get("role", "user").lower()
        role = Role.USER if role_str == "user" else (
            Role.ASSISTANT if role_str == "assistant" else (
                Role.SYSTEM if role_str == "system" else Role.USER
            )
        )
        content = raw_msg.get("content", "")
        if not content:
            continue

        # DeepSeek thinking content (R1 models)
        reasoning = raw_msg.get("reasoning_content", "") or raw_msg.get("thinking", "")
        if reasoning and role == Role.ASSISTANT:
            content = f"<think>\n{reasoning}\n</think>\n\n{content}"

        content_type = ContentType.MARKDOWN if "```" in content else ContentType.TEXT
        msg_model = raw_msg.get("model", "")
        msg_ts = raw_msg.get("created_at", "")

        msg = Message(
            role=role,
            content=content,
            content_type=content_type,
            timestamp=msg_ts or None,
            model=msg_model or None,
            model_provider="deepseek" if "deepseek" in msg_model.lower() else None,
            custom={
                "deepseek_conversation_id": conv_id,
                "deepseek_title": title,
                "deepseek_has_thinking": bool(reasoning),
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
                id=f"ix_ds_{conv_id}_{turn_index}",
                timestamp=ts,
                session_id=f"sess_ds_{conv_id}",
                turn_index=turn_index,
                messages=messages,
                sensitivity=SensitivityInfo(
                    max_risk_level=RiskLevel.LOW,
                    detected_items=[],
                    scanned_by="none",
                ),
                custom={"deepseek_title": title},
            )
            interactions.append(interaction)
            pending_user_msg = None

    # Orphan user message
    if pending_user_msg:
        turn_index += 1
        interactions.append(
            Interaction(
                id=f"ix_ds_{conv_id}_{turn_index}",
                timestamp=pending_user_msg.timestamp or created_at,
                session_id=f"sess_ds_{conv_id}",
                turn_index=turn_index,
                messages=[pending_user_msg],
                sensitivity=SensitivityInfo(
                    max_risk_level=RiskLevel.LOW,
                    detected_items=[],
                    scanned_by="none",
                ),
                custom={"deepseek_title": title},
            )
        )

    return interactions


class DeepSeekImporter(BaseImporter):
    """Import DeepSeek conversations into AILog format."""

    platform_id = "deepseek"
    platform_url = "https://chat.deepseek.com"

    def detect(self, source_path: str | Path) -> bool:
        """Detect if source is a DeepSeek conversation export."""
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
                # DeepSeek uses user/assistant (like OpenAI) but has
                # deepseek-specific model names or no mapping field
                msgs = first.get("messages", [])
                if not msgs:
                    return False
                # Distinguish from ChatGPT: no "mapping" field
                if "mapping" in first:
                    return False
                # Check for DeepSeek-specific indicators
                models = {m.get("model", "") for m in msgs if m.get("model")}
                if any("deepseek" in m.lower() for m in models):
                    return True
                # If no model info, check for reasoning_content (R1 feature)
                has_reasoning = any(
                    m.get("reasoning_content") or m.get("thinking")
                    for m in msgs
                )
                if has_reasoning:
                    return True
                # Fallback: user/assistant roles without mapping → could be DeepSeek
                # But this overlaps with Claude (human/assistant) and Generic
                # So we only claim if explicitly deepseek-related
                return False
            return False
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False

    def parse(self, source_path: str | Path) -> AILogFile:
        """Parse DeepSeek conversations into ALogFile."""
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
            tags=["deepseek-export"],
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

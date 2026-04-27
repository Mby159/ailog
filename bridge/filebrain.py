"""
AILog 鈫?File Brain Bridge

Indexes .ailog files into File Brain's SimpleSearchEngine,
enabling keyword and vector search over AI interaction logs.

Each interaction becomes a separate index entry, so search hits
are precise down to the conversation turn level.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ailog.core.models import AILogFile, Interaction, Role


def _interaction_to_index_entry(ix: Interaction) -> Dict[str, Any]:
    """Convert an Interaction to a File Brain index entry."""
    # Build searchable text from all messages
    parts = []
    for msg in ix.messages:
        role_label = {
            Role.USER: "User",
            Role.ASSISTANT: "Assistant",
            Role.SYSTEM: "System",
            Role.TOOL: "Tool",
        }.get(msg.role, msg.role.value)
        parts.append(f"[{role_label}] {msg.content}")

    # Add artifact content if available
    for art in ix.artifacts:
        if art.content:
            parts.append(f"[Artifact: {art.name}] {art.content}")

    content = "\n\n".join(parts)
    title = ix.custom.get("chatgpt_title", "") or f"Turn {ix.turn_index}"

    return {
        "content": content,
        "file_type": ".ailog",
        "title": f"{title} - Turn {ix.turn_index}",
        "size": len(content.encode("utf-8")),
        "modified": datetime.now(timezone.utc).timestamp(),
        # AILog-specific metadata
        "ailog_interaction_id": ix.id,
        "ailog_session_id": ix.session_id,
        "ailog_turn_index": ix.turn_index,
        "ailog_timestamp": ix.timestamp,
        "ailog_sensitivity": ix.sensitivity.max_risk_level.value if ix.sensitivity else "none",
    }


def index_ailog_file(
    engine,
    ailog_path: str | Path,
) -> Dict[str, int]:
    """
    Index an .ailog file into a File Brain SimpleSearchEngine.

    Args:
        engine: SimpleSearchEngine instance
        ailog_path: Path to .ailog file

    Returns:
        Stats dict with success/failed counts
    """
    ailog = AILogFile.load(Path(ailog_path))
    stats = {"success": 0, "failed": 0, "skipped": 0}

    for ix in ailog.interactions:
        try:
            entry = _interaction_to_index_entry(ix)
            # Use interaction_id as the source key for unique identification
            source = f"ailog://{ailog_path}#{ix.id}"
            engine.index[source] = entry
            # Compute vector if available
            if hasattr(engine, "_compute_vector") and engine.use_vector:
                vec = engine._compute_vector(entry["content"])
                if vec:
                    engine._vectors[source] = vec
            stats["success"] += 1
        except Exception:
            stats["failed"] += 1

    # Save index
    if hasattr(engine, "_save_index"):
        engine._save_index()
    if hasattr(engine, "_save_vectors"):
        engine._save_vectors()

    return stats


def search_ailog(
    engine,
    query: str,
    top_k: int = 10,
) -> List[Dict[str, Any]]:
    """
    Search .ailog content in File Brain index.

    Only returns entries that came from .ailog files
    (identified by file_type == '.ailog').

    Args:
        engine: SimpleSearchEngine instance
        query: Search query
        top_k: Max results

    Returns:
        List of matching interactions with metadata
    """
    all_results = engine.search(query, top_k=top_k * 3)  # Over-fetch to filter
    ailog_results = [r for r in all_results if r.get("file_type") == ".ailog"]

    # Enhance with AILog metadata from the index
    for r in ailog_results:
        source = r.get("source", "")
        if source in engine.index:
            entry = engine.index[source]
            r["interaction_id"] = entry.get("ailog_interaction_id", "")
            r["session_id"] = entry.get("ailog_session_id", "")
            r["turn_index"] = entry.get("ailog_turn_index", 0)
            r["sensitivity"] = entry.get("ailog_sensitivity", "none")

    return ailog_results[:top_k]


def ailog_to_markdown(ailog: AILogFile) -> str:
    """
    Convert an AILogFile to Markdown for Obsidian/note-taking export.
    Each session becomes a section, each turn a subsection.
    """
    sessions: Dict[str, List[Interaction]] = {}
    for ix in ailog.interactions:
        sessions.setdefault(ix.session_id, []).append(ix)

    lines = []
    lines.append(f"# AILog Export: {ailog.metadata.source_platform}")
    lines.append(f"Exported: {ailog.metadata.export_timestamp}")
    lines.append(f"Interactions: {len(ailog.interactions)}")
    lines.append("")

    for session_id, interactions in sessions.items():
        title = interactions[0].custom.get("chatgpt_title", session_id) if interactions[0].custom else session_id
        lines.append(f"## {title}")
        lines.append(f"Session: `{session_id}`")
        lines.append("")

        for ix in interactions:
            lines.append(f"### Turn {ix.turn_index}")
            lines.append(f"*{ix.timestamp}*")
            lines.append("")

            for msg in ix.messages:
                role_label = msg.role.value.capitalize()
                if msg.content_type.value == "code" or msg.content_type.value == "markdown":
                    lines.append(f"**{role_label}:**")
                    lines.append("")
                    lines.append(msg.content)
                    lines.append("")
                else:
                    lines.append(f"**{role_label}:** {msg.content}")
                    lines.append("")

            if ix.artifacts:
                lines.append("**Artifacts:**")
                for art in ix.artifacts:
                    lines.append(f"- [{art.type.value}] {art.name}")
                    if art.content:
                        lines.append(f"  ```{art.language or ''}")
                        for line in art.content.split("\n")[:20]:
                            lines.append(f"  {line}")
                        if art.content.count("\n") > 20:
                            lines.append("  ... (truncated)")
                        lines.append("  ```")
                lines.append("")

            if ix.sensitivity and ix.sensitivity.max_risk_level.value != "low":
                lines.append(f"> 鈿狅笍 Sensitivity: {ix.sensitivity.max_risk_level.value}")
                for item in ix.sensitivity.detected_items:
                    lines.append(f"> - {item.info_type} ({item.risk_level.value})")
                lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)

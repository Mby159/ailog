"""
AILog Obsidian Exporter

Exports AILogFile to Obsidian-compatible Markdown files.
Each session becomes a separate .md file in the vault.

Obsidian features used:
  - YAML frontmatter (tags, date, source_platform)
  - Wikilinks for session cross-references
  - Callouts for sensitivity warnings
  - Code blocks with syntax highlighting
  - Tags from metadata
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List

from ailog.core.models import AILogFile, Interaction, Role, RiskLevel
from ailog.exporters.base import BaseExporter


def _frontmatter(ailog: AILogFile, ix: Interaction) -> str:
    """Generate YAML frontmatter for an Obsidian note."""
    meta = ailog.metadata
    title = ix.custom.get("chatgpt_title") or ix.custom.get("claude_title") or ix.custom.get("deepseek_title") or f"Turn {ix.turn_index}"

    tags = list(meta.tags) if meta.tags else []
    tags.append(f"platform/{meta.source_platform}")
    if ix.sensitivity and ix.sensitivity.max_risk_level.value != "low":
        tags.append("sensitive")

    lines = [
        "---",
        f"title: \"{title}\"",
        f"ailog_version: {ailog.ailog_version}",
        f"source_platform: {meta.source_platform}",
        f"session_id: {ix.session_id}",
        f"turn_index: {ix.turn_index}",
        f"timestamp: {ix.timestamp}",
        f"tags: [{', '.join(tags)}]",
        "---",
    ]
    return "\n".join(lines)


def _format_message(msg, ix: Interaction) -> str:
    """Format a single message for Obsidian."""
    role_label = {
        Role.USER: "馃懁 User",
        Role.ASSISTANT: "馃 Assistant",
        Role.SYSTEM: "鈿欙笍 System",
        Role.TOOL: "馃敡 Tool",
    }.get(msg.role, msg.role.value)

    lines = [f"### {role_label}"]

    if msg.model:
        lines.append(f"*Model: `{msg.model}`*")

    lines.append("")

    # Handle thinking blocks (DeepSeek R1)
    content = msg.content
    if "<think/>" in content:
        parts = content.split("<think/>", 1)
        if len(parts) == 2:
            lines.append("> [!note] Thinking Process")
            lines.append(f"> {parts[0].strip()}")
            lines.append("")
            content = parts[1].strip()

    # Code blocks
    if "```" in content:
        lines.append(content)
    else:
        lines.append(content)

    lines.append("")
    return "\n".join(lines)


class ObsidianExporter(BaseExporter):
    """Export AILogFile to Obsidian Markdown files."""

    target_format = "obsidian"
    file_extension = ".md"

    def export_string(self, ailog: AILogFile) -> str:
        """Export all interactions as a single Markdown string."""
        return self._render_all(ailog)

    def export(self, ailog: AILogFile, output_path: str | Path) -> Path:
        """
        Export AILog to Obsidian vault.

        If output_path is a directory, creates one .md per session.
        If output_path is a file, writes everything to that file.
        """
        output = Path(output_path)
        if output.suffix == ".md":
            # Single file output
            output.write_text(self.export_string(ailog), encoding="utf-8")
            return output

        # Directory output 鈥?one file per session
        output.mkdir(parents=True, exist_ok=True)

        sessions: Dict[str, List[Interaction]] = {}
        for ix in ailog.interactions:
            sessions.setdefault(ix.session_id, []).append(ix)

        created_files = []
        for session_id, interactions in sessions.items():
            title = interactions[0].custom.get("chatgpt_title") or interactions[0].custom.get("claude_title") or interactions[0].custom.get("deepseek_title") or session_id
            # Safe filename
            safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)[:80]
            filename = f"{safe_title}.md"
            filepath = output / filename

            content = self._render_session(ailog, interactions)
            filepath.write_text(content, encoding="utf-8")
            created_files.append(filepath)

        # Create index file
        index_content = self._render_index(ailog, sessions)
        index_path = output / "_ailog_index.md"
        index_path.write_text(index_content, encoding="utf-8")
        created_files.append(index_path)

        return output

    def _render_all(self, ailog: AILogFile) -> str:
        """Render all interactions as single Markdown."""
        lines = []
        meta = ailog.metadata

        # Header
        lines.append(f"# AILog: {meta.source_platform}")
        lines.append(f"*Exported: {meta.export_timestamp}*")
        lines.append(f"*Interactions: {len(ailog.interactions)}*")
        lines.append("")

        for ix in ailog.interactions:
            title = ix.custom.get("chatgpt_title") or ix.custom.get("claude_title") or ix.custom.get("deepseek_title") or f"Turn {ix.turn_index}"
            lines.append(f"## {title}")
            lines.append(f"*Session: `{ix.session_id}` | Turn {ix.turn_index} | {ix.timestamp}*")
            lines.append("")

            for msg in ix.messages:
                lines.append(_format_message(msg, ix))

            # Artifacts
            if ix.artifacts:
                lines.append("### Artifacts")
                for art in ix.artifacts:
                    lines.append(f"- **{art.name}** ({art.type.value})")
                    if art.content:
                        lines.append(f"  ```{art.language or ''}")
                        for line in art.content.split("\n")[:30]:
                            lines.append(f"  {line}")
                        lines.append("  ```")
                lines.append("")

            # Sensitivity warning
            if ix.sensitivity and ix.sensitivity.max_risk_level.value != "low":
                lines.append(f"> [!warning] Sensitive Content ({ix.sensitivity.max_risk_level.value})")
                for item in ix.sensitivity.detected_items:
                    lines.append(f"> - {item.info_type} ({item.risk_level.value})")
                lines.append("")

            lines.append("---")
            lines.append("")

        return "\n".join(lines)

    def _render_session(self, ailog: AILogFile, interactions: List[Interaction]) -> str:
        """Render a single session's interactions."""
        lines = []
        first = interactions[0]
        title = first.custom.get("chatgpt_title") or first.custom.get("claude_title") or first.custom.get("deepseek_title") or first.session_id

        lines.append(_frontmatter(ailog, first))
        lines.append("")
        lines.append(f"# {title}")
        lines.append("")

        for ix in interactions:
            lines.append(f"## Turn {ix.turn_index}")
            lines.append(f"*{ix.timestamp}*")
            lines.append("")

            for msg in ix.messages:
                lines.append(_format_message(msg, ix))

            if ix.artifacts:
                lines.append("### Artifacts")
                for art in ix.artifacts:
                    lines.append(f"- **{art.name}** ({art.type.value})")
                    if art.content:
                        lines.append(f"  ```{art.language or ''}")
                        for line in art.content.split("\n")[:30]:
                            lines.append(f"  {line}")
                        lines.append("  ```")
                lines.append("")

            if ix.sensitivity and ix.sensitivity.max_risk_level.value != "low":
                lines.append(f"> [!warning] Sensitive Content ({ix.sensitivity.max_risk_level.value})")
                for item in ix.sensitivity.detected_items:
                    lines.append(f"> - {item.info_type} ({item.risk_level.value})")
                lines.append("")

        return "\n".join(lines)

    def _render_index(self, ailog: AILogFile, sessions: Dict[str, List[Interaction]]) -> str:
        """Render vault index file."""
        meta = ailog.metadata
        lines = [
            "---",
            f"tags: [ailog-index, platform/{meta.source_platform}]",
            "---",
            "",
            f"# AILog Index: {meta.source_platform}",
            f"*Exported: {meta.export_timestamp}*",
            f"*Sessions: {len(sessions)} | Interactions: {len(ailog.interactions)}*",
            "",
            "## Sessions",
            "",
        ]

        for session_id, interactions in sessions.items():
            title = interactions[0].custom.get("chatgpt_title") or interactions[0].custom.get("claude_title") or interactions[0].custom.get("deepseek_title") or session_id
            safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)[:80]
            lines.append(f"- [[{safe_title}|{title}]] ({len(interactions)} turns)")

        lines.append("")
        return "\n".join(lines)

"""
AILog Notion Exporter v0.1
Exports AILogFile sessions to Notion pages.

Design:
  - Each session (Interaction) → one Notion page
  - Each message → blocks appended to the page
  - No local file output; makes API calls only

Requires:
  - NOTION_API_KEY env var (or pass api_key to __init__)
  - NOTION_PARENT_PAGE_ID env var (or pass parent_page_id to __init__)
  - notion_client >= 3.0.0

Usage:
  exporter = NotionExporter(parent_page_id="...", api_key="secret_...")
  page_ids = await exporter.export_async(ailog)
  # CLI wrapper (sync):
  page_ids = exporter.export(ailog)
"""

from __future__ import annotations

import asyncio
import os
import re
import textwrap
from dataclasses import asdict
from datetime import datetime
from typing import Any, Optional

from notion_client import AsyncClient

from ailog.core.models import (
    AILogFile,
    Interaction,
    Message,
    Artifact,
    SensitivityInfo,
    Role,
)


# ── Notion block type constants ──────────────────────────────────────────────

NOTION_RICH_TEXT_MAX = 2000  # Notion API limit per rich_text array item


def _rich_text(text: str, bold: bool = False, code: bool = False,
               mention: bool = False) -> list[dict]:
    """Build a Notion rich_text array from a plain string."""
    # Notion limits each rich_text item; split if needed
    chunks: list[str] = []
    if len(text) > NOTION_RICH_TEXT_MAX:
        chunks = textwrap.wrap(text, NOTION_RICH_TEXT_MAX)
    else:
        chunks = [text]

    return [
        {
            "type": "equation" if mention else "text",
            "text": {"content": chunk, "link": None},
            "annotations": {
                "bold": bold,
                "italic": False,
                "strikethrough": False,
                "underline": False,
                "code": code,
                "color": "default",
            },
            "plain_text": chunk,
            "href": None,
        }
        for chunk in chunks
    ]


def _plain_text(text: str) -> list[dict]:
    """Rich text without annotations."""
    return _rich_text(text, bold=False, code=False)


# ── Block builders ─────────────────────────────────────────────────────────────

def block_paragraph(rich_text: list[dict], color: str = "default") -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": rich_text,
            "color": color,
        },
    }


def block_heading(text: str, level: int = 2) -> dict:
    """level: 1, 2, or 3."""
    key = f"heading_{level}"
    return {
        "object": "block",
        "type": key,
        key: {
            "rich_text": _rich_text(text),
            "color": "default",
            "is_toggleable": False,
        },
    }


def block_code(code: str, language: str = "plain text") -> dict:
    return {
        "object": "block",
        "type": "code",
        "code": {
            "rich_text": _rich_text(code[:_NOTION_CODE_MAX()]),
            "language": _map_language(language),
            "caption": [],
        },
    }


def _NOTION_CODE_MAX() -> int:
    return 50000  # generous; Notion has per-block limits


def block_callout(
    text: str,
    icon: str = "💡",
    color: str = "yellow_background",
) -> dict:
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": _rich_text(text),
            "icon": {"emoji": icon, "type": "emoji"},
            "color": color,
        },
    }


def block_divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def _map_language(lang: str) -> str:
    """Map common language names to Notion's language enum."""
    mapping = {
        "python": "python", "py": "python",
        "javascript": "javascript", "js": "javascript",
        "typescript": "typescript", "ts": "typescript",
        "bash": "bash", "sh": "bash", "shell": "bash",
        "json": "json",
        "yaml": "yaml", "yml": "yaml",
        "html": "html", "xml": "xml",
        "css": "css",
        "sql": "sql",
        "markdown": "markdown", "md": "markdown",
        "rust": "rust", "go": "go",
        "java": "java", "c": "c", "cpp": "c++",
        "plain text": "plain text", "text": "plain text",
    }
    return mapping.get(lang.lower(), "plain text")


def _sensitivity_color(level: str) -> tuple[str, str]:
    """Return (notion_callout_color, emoji) for a sensitivity level."""
    mapping = {
        "low":    ("gray_background", "🟢"),
        "medium": ("yellow_background", "🟡"),
        "high":   ("orange_background", "🟠"),
        "critical": ("red_background", "🔴"),
    }
    return mapping.get(level.lower(), ("gray_background", "⚪"))


# ── Content renderers ─────────────────────────────────────────────────────────

def render_message(msg: Message) -> list[dict]:
    """
    Convert a Message to a list of Notion blocks.
    - Role → bold paragraph header
    - Content → paragraph or code block
    - thinking_content → callout
    """
    blocks: list[dict] = []

    # Role label
    role_label = msg.role.upper()
    role_color_map = {
        "USER": "blue_background",
        "ASSISTANT": "green_background",
        "SYSTEM": "gray_background",
        "TOOL": "purple_background",
    }
    blocks.append(block_paragraph(
        _rich_text(f"[{role_label}] ", bold=True),
        color=role_color_map.get(role_label, "default"),
    ))

    content = (msg.content or "").strip()

    if not content:
        return blocks

    # Detect code blocks (heuristic: long, has indent or common keywords)
    is_code = (
        msg.content_type.value in ("code", "html")
        or _looks_like_code(content)
    )

    if is_code:
        lang = _infer_language(msg.content_type.value, content)
        blocks.append(block_code(content, lang))
    else:
        # Wrap long text
        wrapped = textwrap.fill(content, width=120)
        blocks.append(block_paragraph(_plain_text(wrapped)))

    return blocks


def render_artifacts(artifacts: list[Artifact]) -> list[dict]:
    """Convert a list of Artifacts to Notion callout blocks."""
    blocks: list[dict] = []
    blocks.append(block_heading("📦 Artifacts", level=2))
    for i, artifact in enumerate(artifacts, 1):
        lines = [
            f"**Artifact {i}**: {artifact.name or artifact.type.value}",
        ]
        if artifact.url:
            lines.append(f"URL: {artifact.url}")
        if artifact.language:
            lines.append(f"Language: `{artifact.language}`")
        if artifact.content:
            preview = artifact.content[:300]
            if len(artifact.content) > 300:
                preview += "..."
            lines.append(f"```\n{preview}\n```")
        blocks.append(block_callout(
            "\n".join(lines),
            icon="📦",
            color="blue_background",
        ))
    return blocks


def render_sensitivity(info: SensitivityInfo) -> list[dict]:
    """Convert SensitivityInfo to a warning callout."""
    level_val = info.max_risk_level.value
    color, emoji = _sensitivity_color(level_val)
    parts = [f"**Privacy Level: {level_val.upper()}**"]
    if info.detected_items:
        types = [item.info_type for item in info.detected_items]
        parts.append(f"Detected: {', '.join(types)}")
    return [
        block_heading(f"{emoji} Sensitivity Warning", level=2),
        block_callout("\n".join(parts), icon=emoji, color=color),
    ]


def _looks_like_code(text: str) -> bool:
    """Heuristic: does text look like source code?"""
    score = 0
    indicators = [
        r"^\s*(def |class |import |from |function |const |let |var |return |if |for |while )\b",
        r"^\s*(\{|\}|\[|\])",
        r"^\s*//", r"^\s*#", r"^\s*<!--",
        r"=\s*(True|False|None)\s*$",
        r"^\s*<[a-z]+[^>]*>",
        r"```",
    ]
    for line in text.splitlines()[:10]:
        for pattern in indicators:
            if re.match(pattern, line, re.IGNORECASE):
                score += 1
    return score >= 1


def _infer_language(content_type: str, content: str) -> str:
    if content_type != "text":
        return content_type
    first_line = content.splitlines()[0] if content else ""
    if first_line.startswith("```"):
        lang = first_line.removeprefix("```").strip()
        if lang:
            return lang
    return "plain text"


# ── Main Exporter ─────────────────────────────────────────────────────────────

class NotionExporterError(Exception):
    """Raised when Notion API call fails."""

    def __init__(self, message: str, status_code: int | None = None):
        self.status_code = status_code
        super().__init__(message)


class NotionExporter:
    """
    Export AILogFile sessions to Notion pages.

    Each Interaction becomes one Notion page under the parent_page_id.
    Messages, artifacts, and sensitivity info become blocks.

    For CLI use (sync), use export() → runs asyncio.run() internally.
    For programmatic async use, use export_async() directly.
    """

    def __init__(
        self,
        parent_page_id: str | None = None,
        api_key: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("NOTION_API_KEY")
        self.parent_page_id = (
            parent_page_id
            or os.environ.get("NOTION_PARENT_PAGE_ID")
        )
        if not self.api_key:
            raise ValueError(
                "Missing NOTION_API_KEY. "
                "Set env var or pass api_key to __init__."
            )
        if not self.parent_page_id:
            raise ValueError(
                "Missing NOTION_PARENT_PAGE_ID. "
                "Set env var or pass parent_page_id to __init__."
            )
        self._client: AsyncClient | None = None

    @property
    def client(self) -> AsyncClient:
        if self._client is None:
            self._client = AsyncClient(auth=self.api_key)
        return self._client

    # ── Public sync entry (for CLI) ──────────────────────────────────────────

    def export(self, ailog: AILogFile) -> list[str]:
        """
        Synchronous export. Creates one Notion page per Interaction.
        Returns list of created page IDs.
        """
        return asyncio.run(self.export_async(ailog))

    # ── Public async entry (for programmatic use) ───────────────────────────

    async def export_async(self, ailog: AILogFile) -> list[str]:
        """
        Async export. Creates one Notion page per Interaction.
        Returns list of created page IDs.
        """
        parent = self.parent_page_id
        page_ids: list[str] = []

        for idx, interaction in enumerate(ailog.interactions):
            page_id = await self._create_page(interaction, parent)
            page_ids.append(page_id)

        return page_ids

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _page_title(self, interaction: Interaction) -> str:
        """Build a readable page title from interaction metadata."""
        meta = interaction.metadata or {}

        model = meta.get("model", "unknown model")
        # date
        start = meta.get("start_time") or meta.get("created_at")
        if start:
            try:
                dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                date_str = str(start)
        else:
            date_str = f"#{interaction.session_id[:8]}"

        title = f"{model} · {date_str}"
        return title[:200]  # Notion title limit

    async def _create_page(self, interaction: Interaction, parent: str) -> str:
        """
        Create one Notion page for an Interaction.
        Returns the page ID.
        """
        title = self._page_title(interaction)

        # Create page with title
        page = await self.client.pages.create(
            parent={"type": "page_id", "page_id": parent},
            properties={
                "title": {
                    "title": _rich_text(title),
                },
            },
            children=[],  # will append children below
        )
        page_id: str = page["id"]

        # Build all blocks for this page
        blocks = self._build_blocks(interaction)
        if blocks:
            await self._append_blocks(page_id, blocks)

        return page_id

    def _build_blocks(self, interaction: Interaction) -> list[dict]:
        """Convert one Interaction to Notion blocks."""
        blocks: list[dict] = []

        # Metadata header
        meta = interaction.metadata or {}
        model = meta.get("model")
        if model:
            blocks.append(block_heading(f"Model: {model}", level=2))

        messages = interaction.messages or []
        for msg in messages:
            blocks.extend(render_message(msg))

        # Artifacts
        artifacts = interaction.artifacts or []
        if artifacts:
            blocks.append(block_divider())
            blocks.extend(render_artifacts(artifacts))

        # Sensitivity
        sensitivity = interaction.sensitivity
        if sensitivity:
            blocks.append(block_divider())
            blocks.extend(render_sensitivity(sensitivity))

        return blocks

    async def _append_blocks(
        self, block_id: str, blocks: list[dict], max_chunk: int = 100
    ) -> None:
        """
        Append blocks to a page (or any block container).
        Notion limits ~100 children per append call; chunk if needed.
        """
        for i in range(0, len(blocks), max_chunk):
            chunk = blocks[i : i + max_chunk]
            await self.client.blocks.children.append(
                block_id,
                children=chunk,
            )

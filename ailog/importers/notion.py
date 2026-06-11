"""
AILog Notion Importer v0.1
Imports conversations from Notion pages back into .ailog format.

Two modes:
  1. API mode — Given a parent page ID, fetch child pages via Notion API,
     parse blocks back into AILog Interactions.
  2. File mode — Parse a Notion JSON export file.

Design:
  - Reverses the NotionExporter mapping:
    [USER] / [ASSISTANT] bold labels → Message.role
    paragraph blocks → Message.content
    code blocks → Message (content_type=code)
    callout blocks → thinking / artifact / sensitivity
    heading_2 → section dividers (metadata extraction)
  - Pure async (notion_client 3.x), with sync wrapper for CLI.

Usage:
  # API mode
  importer = NotionImporter(api_key="secret_...", parent_page_id="...")
  ailog = await importer.parse_async()
  # or sync:
  ailog = importer.parse_from_api()

  # File mode (BaseImporter interface)
  importer = NotionImporter()
  ailog = importer.parse("notion_export.json")
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ailog.core.models import (
    AILogFile,
    AILogFileMetadata,
    Artifact,
    ArtifactType,
    ContentType,
    Interaction,
    Message,
    OwnerInfo,
    OwnerIdType,
    Role,
    RiskLevel,
    SensitivityInfo,
    SensitivityItem,
)
from ailog.importers.base import BaseImporter


# ── Constants ────────────────────────────────────────────────────────────────

ROLE_LABELS = {
    "USER": Role.USER,
    "ASSISTANT": Role.ASSISTANT,
    "SYSTEM": Role.SYSTEM,
    "TOOL": Role.TOOL,
}

SENSITIVITY_EMOJI_TO_LEVEL = {
    "🟢": "low",
    "🟡": "medium",
    "🟠": "high",
    "🔴": "critical",
    "⚪": "low",
}

NOTION_BLOCK_COLORS = {
    "gray_background",
    "yellow_background",
    "orange_background",
    "red_background",
    "blue_background",
    "green_background",
    "purple_background",
    "pink_background",
}


# ── Rich text extraction ────────────────────────────────────────────────────

def _extract_plain_text(rich_text_array: list[dict]) -> str:
    """Extract plain text from a Notion rich_text array."""
    parts = []
    for rt in rich_text_array or []:
        parts.append(rt.get("plain_text", ""))
    return "".join(parts)


def _extract_bold_prefix(rich_text_array: list[dict]) -> Tuple[str, str]:
    """
    If the first rich_text item is bold, return (bold_text, remaining_plain_text).
    Otherwise return ("", full_plain_text).
    """
    if not rich_text_array:
        return "", ""

    first = rich_text_array[0]
    is_bold = first.get("annotations", {}).get("bold", False)
    first_text = first.get("plain_text", "")

    if is_bold and first_text.startswith("[") and "]" in first_text:
        # e.g. "[USER] " → role="USER", rest=remaining text
        bracket_end = first_text.index("]") + 1
        bold_part = first_text[:bracket_end]
        remainder_first = first_text[bracket_end:].lstrip()
        rest_parts = [rt.get("plain_text", "") for rt in rich_text_array[1:]]
        rest_text = remainder_first + "".join(rest_parts)
        # Strip the brackets: [USER] → USER
        role_str = bold_part.strip("[]")
        return role_str, rest_text

    # Not a role label
    full = _extract_plain_text(rich_text_array)
    return "", full


# ── Block parsing ────────────────────────────────────────────────────────────

def _parse_code_block(block: dict) -> Message:
    """Parse a code block into a Message."""
    code_obj = block.get("code", {})
    content = _extract_plain_text(code_obj.get("rich_text", []))
    language = code_obj.get("language", "plain text")

    return Message(
        role=Role.ASSISTANT,
        content=content,
        content_type=ContentType.CODE,
        custom={"language": language},
    )


def _parse_paragraph_block(block: dict) -> Optional[Message]:
    """
    Parse a paragraph block into a Message.
    Detects role labels like [USER], [ASSISTANT], etc.
    Returns None if the block is just a role label with no content.
    """
    para = block.get("paragraph", {})
    rich_text = para.get("rich_text", [])
    color = para.get("color", "default")

    role_str, content = _extract_bold_prefix(rich_text)

    if not content.strip():
        # Role label only, no content — skip
        return None

    # Determine role from label or color hint
    role = ROLE_LABELS.get(role_str.upper(), Role.ASSISTANT)

    # Detect if content looks like code
    content_type = ContentType.TEXT
    if _looks_like_code(content):
        content_type = ContentType.CODE

    return Message(
        role=role,
        content=content.strip(),
        content_type=content_type,
    )


def _parse_callout_block(block: dict) -> Optional[dict]:
    """
    Parse a callout block. Returns a dict with type info:
    {"type": "thinking", "content": "..."}
    {"type": "artifact", "content": "..."}
    {"type": "sensitivity", "content": "...", "level": "high"}
    Returns None for unrecognized callouts.
    """
    callout = block.get("callout", {})
    rich_text = callout.get("rich_text", [])
    icon = callout.get("icon", {})
    emoji = icon.get("emoji", "")
    color = callout.get("color", "default")
    text = _extract_plain_text(rich_text)

    if not text.strip():
        return None

    # Detect thinking blocks
    if emoji in ("💭", "🧠", "💡") or "thinking" in text.lower()[:30]:
        return {"type": "thinking", "content": text.strip()}

    # Detect artifact blocks
    if emoji == "📦" or "artifact" in text.lower()[:30]:
        return {"type": "artifact", "content": text.strip()}

    # Detect sensitivity blocks
    if emoji in SENSITIVITY_EMOJI_TO_LEVEL or color in (
        "orange_background", "red_background", "yellow_background"
    ):
        level = SENSITIVITY_EMOJI_TO_LEVEL.get(emoji, "medium")
        # Try to extract level from text like "Privacy Level: HIGH"
        level_match = re.search(
            r"privacy level[:\s]*(low|medium|high|critical)",
            text, re.IGNORECASE
        )
        if level_match:
            level = level_match.group(1).lower()
        # Try to extract detected types
        detected = []
        det_match = re.search(r"detected[:\s]*(.+)", text, re.IGNORECASE)
        if det_match:
            detected = [t.strip() for t in det_match.group(1).split(",")]
        return {
            "type": "sensitivity",
            "content": text.strip(),
            "level": level,
            "detected_types": detected,
        }

    # Generic callout — treat as thinking/note
    return {"type": "thinking", "content": text.strip()}


def _parse_heading_block(block: dict) -> Optional[dict]:
    """
    Parse a heading block. May contain metadata like "Model: gpt-4".
    Returns {"type": "metadata", "key": "model", "value": "gpt-4"} or None.
    """
    for level in (1, 2, 3):
        key = f"heading_{level}"
        if key in block:
            text = _extract_plain_text(block[key].get("rich_text", []))
            # Extract "Model: xxx"
            model_match = re.match(r"model[:\s]+(.+)", text, re.IGNORECASE)
            if model_match:
                return {"type": "metadata", "key": "model", "value": model_match.group(1).strip()}
            break
    return None


def _looks_like_code(text: str) -> bool:
    """Heuristic: does text look like source code?"""
    score = 0
    indicators = [
        r"^\s*(def |class |import |from |function |const |let |var |return )\b",
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


# ── Page → Interaction conversion ────────────────────────────────────────────

def _blocks_to_interaction(
    blocks: list[dict],
    page_id: str = "",
    page_title: str = "",
) -> Interaction:
    """
    Convert a list of Notion blocks into one AILog Interaction.
    Blocks are assumed to come from one Notion page (one conversation).
    """
    messages: list[Message] = []
    artifacts: list[Artifact] = []
    sensitivity: Optional[SensitivityInfo] = None
    metadata: Dict[str, Any] = {}

    # Current role context (for blocks that follow a role label)
    current_role = Role.USER
    current_content_parts: list[str] = []
    current_content_type = ContentType.TEXT
    current_custom: Dict[str, Any] = {}
    has_pending_message = False

    def _flush_pending():
        """Flush accumulated content as a Message."""
        nonlocal has_pending_message, current_content_parts
        if has_pending_message and current_content_parts:
            full_content = "\n".join(current_content_parts).strip()
            if full_content:
                messages.append(Message(
                    role=current_role,
                    content=full_content,
                    content_type=current_content_type,
                    custom=current_custom.copy(),
                ))
        current_content_parts = []
        has_pending_message = False
        current_custom.clear()

    for block in blocks:
        block_type = block.get("type", "")

        # Skip dividers
        if block_type == "divider":
            _flush_pending()
            continue

        # Headings — may contain metadata
        if block_type.startswith("heading_"):
            _flush_pending()
            meta = _parse_heading_block(block)
            if meta and meta["type"] == "metadata":
                metadata[meta["key"]] = meta["value"]
            continue

        # Code blocks — always a new message
        if block_type == "code":
            _flush_pending()
            msg = _parse_code_block(block)
            if msg:
                # Attach to previous message's role if available
                if messages and messages[-1].role in (Role.USER, Role.ASSISTANT):
                    msg.role = messages[-1].role
                messages.append(msg)
            continue

        # Paragraph blocks — may have role labels
        if block_type == "paragraph":
            para = block.get("paragraph", {})
            rich_text = para.get("rich_text", [])
            role_str, content = _extract_bold_prefix(rich_text)

            if role_str.upper() in ROLE_LABELS:
                # New role label → flush previous, start new message
                _flush_pending()
                current_role = ROLE_LABELS[role_str.upper()]
                if content.strip():
                    current_content_parts = [content.strip()]
                    has_pending_message = True
                else:
                    # Role label only — wait for next block
                    has_pending_message = False
            elif content.strip():
                # Continuation of current message
                current_content_parts.append(content.strip())
                has_pending_message = True
            continue

        # Callout blocks — thinking / artifact / sensitivity
        if block_type == "callout":
            _flush_pending()
            parsed = _parse_callout_block(block)
            if not parsed:
                continue

            if parsed["type"] == "thinking":
                # Add as a message with thinking context
                messages.append(Message(
                    role=Role.ASSISTANT,
                    content=parsed["content"],
                    content_type=ContentType.TEXT,
                    custom={"thinking": True},
                ))
            elif parsed["type"] == "artifact":
                # Parse artifact details from text
                art = _parse_artifact_text(parsed["content"])
                if art:
                    artifacts.append(art)
            elif parsed["type"] == "sensitivity":
                level = parsed.get("level", "medium")
                detected_types = parsed.get("detected_types", [])
                items = [
                    SensitivityItem(
                        info_type=t,
                        risk_level=RiskLevel(level),
                        field=f"message[{len(messages)}]",
                    )
                    for t in detected_types
                ]
                sensitivity = SensitivityInfo(
                    max_risk_level=RiskLevel(level),
                    detected_items=items,
                    scanned_by="notion-importer",
                    scan_timestamp=datetime.now(timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z"),
                )
            continue

        # Other block types (bulleted_list, numbered_list, etc.)
        # Extract text and append to current message
        for bt in ("bulleted_list_item", "numbered_list_item", "toggle", "quote"):
            if block_type == bt:
                rt = block.get(bt, {}).get("rich_text", [])
                text = _extract_plain_text(rt)
                if text.strip():
                    current_content_parts.append(text.strip())
                    has_pending_message = True
                break

    # Flush any remaining content
    _flush_pending()

    # Build interaction
    # Extract model from metadata or title
    model = metadata.get("model", "")
    if not model and page_title:
        # Title format: "gpt-4 · 2026-04-27 08:30"
        title_match = re.match(r"^(.+?)\s*[·•\-–]\s*", page_title)
        if title_match:
            model = title_match.group(1).strip()

    # Generate timestamp from title or use now
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if page_title:
        # Try to extract date from title
        date_match = re.search(
            r"(\d{4}[-/]\d{2}[-/]\d{2}\s*\d{2}:\d{2})",
            page_title,
        )
        if date_match:
            try:
                dt = datetime.fromisoformat(date_match.group(1).replace("/", "-"))
                timestamp = dt.isoformat() + "Z"
            except ValueError:
                pass

    return Interaction(
        id=page_id or str(uuid.uuid4()),
        timestamp=timestamp,
        session_id=_derive_session_id(page_id, page_title),
        turn_index=0,
        messages=messages,
        artifacts=artifacts,
        sensitivity=sensitivity,
        custom={
            "notion_page_id": page_id,
            "notion_page_title": page_title,
            **metadata,
        },
    )


def _parse_artifact_text(text: str) -> Optional[Artifact]:
    """Parse artifact info from callout text."""
    # Format: "**Artifact 1**: code\nURL: ...\nLanguage: `python`\n```\n...\n```"
    name_match = re.match(r"\*?\*?Artifact \d+\*?\*?:\s*(.+)", text)
    name = name_match.group(1).strip() if name_match else "unknown"

    url = None
    url_match = re.search(r"URL:\s*(\S+)", text)
    if url_match:
        url = url_match.group(1)

    language = None
    lang_match = re.search(r"Language:\s*`?(\w+)`?", text)
    if lang_match:
        language = lang_match.group(1)

    # Extract code content between ```
    content = None
    code_match = re.search(r"```\n(.+?)```", text, re.DOTALL)
    if code_match:
        content = code_match.group(1).strip()

    return Artifact(
        id=str(uuid.uuid4()),
        type=ArtifactType.CODE,
        name=name,
        content=content,
        url=url,
        language=language,
    )


def _derive_session_id(page_id: str, title: str) -> str:
    """Derive a stable session ID from page metadata."""
    if page_id:
        # Notion page IDs are stable, use a namespace
        return f"notion-{page_id.replace('-', '')[:16]}"
    # Fallback: hash the title
    return f"notion-{uuid.uuid5(uuid.NAMESPACE_URL, title or 'unknown').hex[:16]}"


# ── Main Importer ────────────────────────────────────────────────────────────

class NotionImporter(BaseImporter):
    """
    Import AI conversations from Notion pages into .ailog format.

    Two modes:
      1. API mode: parse_from_api() / parse_async() — reads from Notion API
      2. File mode: parse() — reads from a Notion JSON export file

    The BaseImporter.detect() and parse() support file mode only.
    API mode requires explicit initialization with api_key + parent_page_id.
    """

    platform_id = "notion"
    platform_url = "https://notion.so"

    def __init__(
        self,
        api_key: str | None = None,
        parent_page_id: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("NOTION_API_KEY")
        self.parent_page_id = (
            parent_page_id
            or os.environ.get("NOTION_PARENT_PAGE_ID")
        )
        self._client = None

    @property
    def client(self):
        """Lazy-init Notion AsyncClient."""
        if self._client is None:
            if not self.api_key:
                raise ValueError(
                    "Missing NOTION_API_KEY. "
                    "Set env var or pass api_key to __init__."
                )
            from notion_client import AsyncClient
            self._client = AsyncClient(auth=self.api_key)
        return self._client

    # ── BaseImporter interface (file mode) ────────────────────────────────

    def detect(self, source_path: str | Path) -> bool:
        """Detect if source is a Notion export JSON file."""
        path = Path(source_path)
        if not path.exists():
            return False
        if path.suffix != ".json":
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            # Notion export format has specific structure
            return bool(
                isinstance(data, dict)
                and (
                    "results" in data  # API response format
                    or "id" in data and "created_time" in data  # Single page
                    or isinstance(data, list)  # Array of pages
                )
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False

    def parse(self, source_path: str | Path) -> AILogFile:
        """Parse a Notion export JSON file into AILogFile."""
        path = Path(source_path)
        if not path.exists():
            raise FileNotFoundError(f"Source not found: {path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        interactions = []

        if isinstance(data, list):
            # Array of page objects
            for page_data in data:
                ix = self._parse_page_data(page_data)
                if ix and ix.messages:
                    interactions.append(ix)
        elif isinstance(data, dict):
            if "results" in data:
                # API response with results array
                for page_data in data["results"]:
                    ix = self._parse_page_data(page_data)
                    if ix and ix.messages:
                        interactions.append(ix)
            elif "id" in data:
                # Single page object
                ix = self._parse_page_data(data)
                if ix and ix.messages:
                    interactions.append(ix)
            elif "interactions" in data or "ailog_version" in data:
                # Already an ailog format — skip
                raise ValueError(
                    "This file appears to be an .ailog file, not a Notion export."
                )

        return AILogFile(
            ailog_version="0.1",
            metadata=self._build_metadata(
                tags=["notion-import"],
                custom={"source_file": str(path)},
            ),
            interactions=interactions,
        )

    # ── API mode ─────────────────────────────────────────────────────────

    def parse_from_api(
        self,
        parent_page_id: str | None = None,
    ) -> AILogFile:
        """
        Sync entry: fetch pages from Notion API and parse into AILogFile.
        """
        return asyncio.run(self.parse_async(parent_page_id))

    async def parse_async(
        self,
        parent_page_id: str | None = None,
    ) -> AILogFile:
        """
        Async entry: fetch child pages from Notion API, parse each page's
        blocks into an Interaction.
        """
        parent = parent_page_id or self.parent_page_id
        if not parent:
            raise ValueError(
                "Missing parent_page_id. "
                "Set NOTION_PARENT_PAGE_ID env var or pass parent_page_id."
            )

        # Fetch child blocks/pages under the parent
        pages = await self._fetch_child_pages(parent)
        interactions = []

        for page in pages:
            page_id = page["id"]
            title = self._extract_page_title(page)

            # Fetch all blocks for this page
            blocks = await self._fetch_all_blocks(page_id)
            ix = _blocks_to_interaction(blocks, page_id, title)

            if ix.messages:
                # Assign turn_index based on order
                ix.turn_index = len(interactions)
                interactions.append(ix)

        return AILogFile(
            ailog_version="0.1",
            metadata=self._build_metadata(
                tags=["notion-import", "api"],
                custom={"parent_page_id": parent},
            ),
            interactions=interactions,
        )

    # ── Internal: API helpers ────────────────────────────────────────────

    async def _fetch_child_pages(self, parent_id: str) -> list[dict]:
        """Fetch all child pages under a parent page/block."""
        pages = []
        cursor = None

        while True:
            kwargs: Dict[str, Any] = {
                "block_id": parent_id,
                "page_size": 100,
            }
            if cursor:
                kwargs["start_cursor"] = cursor

            response = await self.client.blocks.children.list(**kwargs)
            results = response.get("results", [])

            # Filter for child_page and linked_database types
            for block in results:
                if block.get("type") == "child_page":
                    # child_page blocks contain the page ID
                    child_page_id = block["id"]
                    # Fetch full page object
                    try:
                        page = await self.client.pages.retrieve(child_page_id)
                        pages.append(page)
                    except Exception:
                        # If page fetch fails, create a minimal page object
                        pages.append({
                            "id": child_page_id,
                            "properties": {
                                "title": {
                                    "title": block.get("child_page", {}).get("title", "Untitled")
                                }
                            },
                        })

            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")

        return pages

    async def _fetch_all_blocks(self, page_id: str) -> list[dict]:
        """Fetch all blocks from a page, handling pagination."""
        blocks = []
        cursor = None

        while True:
            kwargs: Dict[str, Any] = {
                "block_id": page_id,
                "page_size": 100,
            }
            if cursor:
                kwargs["start_cursor"] = cursor

            response = await self.client.blocks.children.list(**kwargs)
            blocks.extend(response.get("results", []))

            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")

        # Recursively fetch children for blocks that have them
        expanded = []
        for block in blocks:
            expanded.append(block)
            if block.get("has_children"):
                children = await self._fetch_all_blocks(block["id"])
                expanded.extend(children)

        return expanded

    def _extract_page_title(self, page: dict) -> str:
        """Extract title from a Notion page object."""
        props = page.get("properties", {})
        # Title is usually in "title" or "Name" or "名前" property
        for prop_name in ("title", "Name", "名前", "名称"):
            if prop_name in props:
                title_array = props[prop_name].get("title", [])
                if title_array:
                    return _extract_plain_text(title_array)
        # Fallback: search all properties for title type
        for prop_data in props.values():
            if prop_data.get("type") == "title":
                title_array = prop_data.get("title", [])
                if title_array:
                    return _extract_plain_text(title_array)
        return "Untitled"

    def _parse_page_data(self, page_data: dict) -> Optional[Interaction]:
        """
        Parse a page data dict (from JSON export) into an Interaction.
        If the page has blocks inline, parse them; otherwise create minimal interaction.
        """
        page_id = page_data.get("id", str(uuid.uuid4()))
        title = "Untitled"
        props = page_data.get("properties", {})
        for prop_data in props.values():
            if prop_data.get("type") == "title":
                title_array = prop_data.get("title", [])
                if title_array:
                    title = _extract_plain_text(title_array)
                break

        # If page has children/blocks inline
        blocks = page_data.get("children", [])
        if not blocks and "content" in page_data:
            # Some export formats use "content" key
            blocks = page_data["content"]

        if blocks:
            return _blocks_to_interaction(blocks, page_id, title)

        # Minimal interaction from page metadata
        created = page_data.get("created_time", "")
        return Interaction(
            id=page_id,
            timestamp=created or datetime.now(timezone.utc).isoformat() + "Z",
            session_id=_derive_session_id(page_id, title),
            turn_index=0,
            messages=[Message(
                role=Role.ASSISTANT,
                content=title,
                content_type=ContentType.TEXT,
            )],
            custom={"notion_page_id": page_id},
        )

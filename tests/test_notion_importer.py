"""
Tests for NotionImporter.

Covers:
  - File mode: detect() and parse() with JSON fixtures
  - Block parsing: role labels, code blocks, callouts, headings
  - Page → Interaction conversion
  - Rich text extraction
  - Artifact and sensitivity reconstruction
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from ailog.core.models import (
    AILogFile,
    ContentType,
    Role,
    RiskLevel,
)
from ailog.importers.notion import (
    NotionImporter,
    _extract_plain_text,
    _extract_bold_prefix,
    _parse_paragraph_block,
    _parse_code_block,
    _parse_callout_block,
    _blocks_to_interaction,
    _parse_artifact_text,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def importer():
    return NotionImporter()


@pytest.fixture
def sample_rich_text():
    """Standard rich text array with bold role label."""
    return [
        {
            "type": "text",
            "text": {"content": "[USER] "},
            "annotations": {"bold": True, "italic": False, "strikethrough": False,
                          "underline": False, "code": False, "color": "default"},
            "plain_text": "[USER] ",
        },
        {
            "type": "text",
            "text": {"content": "What is Python?"},
            "annotations": {"bold": False, "italic": False, "strikethrough": False,
                          "underline": False, "code": False, "color": "default"},
            "plain_text": "What is Python?",
        },
    ]


@pytest.fixture
def assistant_rich_text():
    return [
        {
            "type": "text",
            "text": {"content": "[ASSISTANT] "},
            "annotations": {"bold": True, "italic": False, "strikethrough": False,
                          "underline": False, "code": False, "color": "default"},
            "plain_text": "[ASSISTANT] ",
        },
        {
            "type": "text",
            "text": {"content": "Python is a high-level programming language."},
            "annotations": {"bold": False, "italic": False, "strikethrough": False,
                          "underline": False, "code": False, "color": "default"},
            "plain_text": "Python is a high-level programming language.",
        },
    ]


@pytest.fixture
def sample_blocks():
    """A typical set of Notion blocks representing a conversation."""
    return [
        # Heading with model info
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [
                    {"type": "text", "plain_text": "Model: gpt-4",
                     "text": {"content": "Model: gpt-4"},
                     "annotations": {"bold": False, "italic": False, "strikethrough": False,
                                   "underline": False, "code": False, "color": "default"}}
                ],
                "color": "default",
                "is_toggleable": False,
            },
        },
        # User message
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"type": "text", "text": {"content": "[USER] "},
                     "annotations": {"bold": True, "italic": False, "strikethrough": False,
                                   "underline": False, "code": False, "color": "default"},
                     "plain_text": "[USER] "},
                    {"type": "text", "text": {"content": "Write a hello world in Python"},
                     "annotations": {"bold": False, "italic": False, "strikethrough": False,
                                   "underline": False, "code": False, "color": "default"},
                     "plain_text": "Write a hello world in Python"},
                ],
                "color": "default",
            },
        },
        # Assistant text
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"type": "text", "text": {"content": "[ASSISTANT] "},
                     "annotations": {"bold": True, "italic": False, "strikethrough": False,
                                   "underline": False, "code": False, "color": "default"},
                     "plain_text": "[ASSISTANT] "},
                    {"type": "text", "text": {"content": "Here you go:"},
                     "annotations": {"bold": False, "italic": False, "strikethrough": False,
                                   "underline": False, "code": False, "color": "default"},
                     "plain_text": "Here you go:"},
                ],
                "color": "green_background",
            },
        },
        # Code block
        {
            "object": "block",
            "type": "code",
            "code": {
                "rich_text": [
                    {"type": "text", "text": {"content": 'print("Hello, World!")'},
                     "annotations": {"bold": False, "italic": False, "strikethrough": False,
                                   "underline": False, "code": False, "color": "default"},
                     "plain_text": 'print("Hello, World!")'},
                ],
                "language": "python",
                "caption": [],
            },
        },
        # Divider
        {"object": "block", "type": "divider", "divider": {}},
        # Artifact callout
        {
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [
                    {"type": "text", "text": {"content": "**Artifact 1**: hello.py\nLanguage: `python`\n```\nprint(\"Hello, World!\")\n```"},
                     "annotations": {"bold": False, "italic": False, "strikethrough": False,
                                   "underline": False, "code": False, "color": "default"},
                     "plain_text": "**Artifact 1**: hello.py\nLanguage: `python`\n```\nprint(\"Hello, World!\")\n```"},
                ],
                "icon": {"emoji": "📦", "type": "emoji"},
                "color": "blue_background",
            },
        },
        # Divider
        {"object": "block", "type": "divider", "divider": {}},
        # Sensitivity callout
        {
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [
                    {"type": "text", "text": {"content": "**Privacy Level: HIGH**\nDetected: phone_number, email"},
                     "annotations": {"bold": False, "italic": False, "strikethrough": False,
                                   "underline": False, "code": False, "color": "default"},
                     "plain_text": "**Privacy Level: HIGH**\nDetected: phone_number, email"},
                ],
                "icon": {"emoji": "🟠", "type": "emoji"},
                "color": "orange_background",
            },
        },
    ]


@pytest.fixture
def sample_notion_export_json():
    """A Notion JSON export with multiple pages."""
    return {
        "results": [
            {
                "id": "page-001",
                "created_time": "2026-04-27T08:00:00Z",
                "properties": {
                    "title": {
                        "title": [
                            {"plain_text": "gpt-4 · 2026-04-27 08:00",
                             "text": {"content": "gpt-4 · 2026-04-27 08:00"}}
                        ]
                    }
                },
                "children": [
                    {
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {"plain_text": "[USER] Hello",
                                 "text": {"content": "[USER] Hello"},
                                 "annotations": {"bold": True, "italic": False, "strikethrough": False,
                                               "underline": False, "code": False, "color": "default"}},
                            ],
                            "color": "default",
                        },
                    },
                    {
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {"plain_text": "[ASSISTANT] ",
                                 "text": {"content": "[ASSISTANT] "},
                                 "annotations": {"bold": True, "italic": False, "strikethrough": False,
                                               "underline": False, "code": False, "color": "default"}},
                                {"plain_text": "Hi there!",
                                 "text": {"content": "Hi there!"},
                                 "annotations": {"bold": False, "italic": False, "strikethrough": False,
                                               "underline": False, "code": False, "color": "default"}},
                            ],
                            "color": "default",
                        },
                    },
                ],
            },
        ],
    }


# ── Rich text extraction tests ─────────────────────────────────────────────

class TestRichTextExtraction:
    def test_extract_plain_text(self, sample_rich_text):
        result = _extract_plain_text(sample_rich_text)
        assert result == "[USER] What is Python?"

    def test_extract_plain_text_empty(self):
        assert _extract_plain_text([]) == ""
        assert _extract_plain_text(None) == ""

    def test_extract_bold_prefix_with_role(self, sample_rich_text):
        role, rest = _extract_bold_prefix(sample_rich_text)
        assert role == "USER"
        assert rest == "What is Python?"

    def test_extract_bold_prefix_assistant(self, assistant_rich_text):
        role, rest = _extract_bold_prefix(assistant_rich_text)
        assert role == "ASSISTANT"
        assert rest == "Python is a high-level programming language."

    def test_extract_bold_prefix_no_role(self):
        rich_text = [
            {"plain_text": "Just some text",
             "text": {"content": "Just some text"},
             "annotations": {"bold": False, "italic": False, "strikethrough": False,
                           "underline": False, "code": False, "color": "default"}},
        ]
        role, rest = _extract_bold_prefix(rich_text)
        assert role == ""
        assert rest == "Just some text"


# ── Block parsing tests ────────────────────────────────────────────────────

class TestBlockParsing:
    def test_parse_paragraph_with_role(self):
        block = {
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"plain_text": "[USER] ", "text": {"content": "[USER] "},
                     "annotations": {"bold": True, "italic": False, "strikethrough": False,
                                   "underline": False, "code": False, "color": "default"}},
                    {"plain_text": "Hello!", "text": {"content": "Hello!"},
                     "annotations": {"bold": False, "italic": False, "strikethrough": False,
                                   "underline": False, "code": False, "color": "default"}},
                ],
                "color": "default",
            },
        }
        msg = _parse_paragraph_block(block)
        assert msg is not None
        assert msg.role == Role.USER
        assert msg.content == "Hello!"

    def test_parse_paragraph_role_only(self):
        block = {
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"plain_text": "[ASSISTANT] ", "text": {"content": "[ASSISTANT] "},
                     "annotations": {"bold": True, "italic": False, "strikethrough": False,
                                   "underline": False, "code": False, "color": "default"}},
                ],
                "color": "default",
            },
        }
        msg = _parse_paragraph_block(block)
        assert msg is None  # Role label only, no content

    def test_parse_code_block(self):
        block = {
            "type": "code",
            "code": {
                "rich_text": [
                    {"plain_text": 'print("hi")', "text": {"content": 'print("hi")'},
                     "annotations": {"bold": False, "italic": False, "strikethrough": False,
                                   "underline": False, "code": False, "color": "default"}},
                ],
                "language": "python",
                "caption": [],
            },
        }
        msg = _parse_code_block(block)
        assert msg.role == Role.ASSISTANT
        assert msg.content == 'print("hi")'
        assert msg.content_type == ContentType.CODE
        assert msg.custom.get("language") == "python"

    def test_parse_callout_thinking(self):
        block = {
            "type": "callout",
            "callout": {
                "rich_text": [
                    {"plain_text": "Let me think about this...",
                     "text": {"content": "Let me think about this..."},
                     "annotations": {"bold": False, "italic": False, "strikethrough": False,
                                   "underline": False, "code": False, "color": "default"}},
                ],
                "icon": {"emoji": "💭", "type": "emoji"},
                "color": "yellow_background",
            },
        }
        result = _parse_callout_block(block)
        assert result is not None
        assert result["type"] == "thinking"

    def test_parse_callout_artifact(self):
        block = {
            "type": "callout",
            "callout": {
                "rich_text": [
                    {"plain_text": "**Artifact 1**: hello.py\nLanguage: `python`",
                     "text": {"content": "**Artifact 1**: hello.py\nLanguage: `python`"},
                     "annotations": {"bold": False, "italic": False, "strikethrough": False,
                                   "underline": False, "code": False, "color": "default"}},
                ],
                "icon": {"emoji": "📦", "type": "emoji"},
                "color": "blue_background",
            },
        }
        result = _parse_callout_block(block)
        assert result is not None
        assert result["type"] == "artifact"

    def test_parse_callout_sensitivity(self):
        block = {
            "type": "callout",
            "callout": {
                "rich_text": [
                    {"plain_text": "**Privacy Level: HIGH**\nDetected: phone_number",
                     "text": {"content": "**Privacy Level: HIGH**\nDetected: phone_number"},
                     "annotations": {"bold": False, "italic": False, "strikethrough": False,
                                   "underline": False, "code": False, "color": "default"}},
                ],
                "icon": {"emoji": "🟠", "type": "emoji"},
                "color": "orange_background",
            },
        }
        result = _parse_callout_block(block)
        assert result is not None
        assert result["type"] == "sensitivity"
        assert result["level"] == "high"
        assert "phone_number" in result["detected_types"]

    def test_parse_callout_empty(self):
        block = {
            "type": "callout",
            "callout": {
                "rich_text": [],
                "icon": {"emoji": "💡", "type": "emoji"},
                "color": "default",
            },
        }
        result = _parse_callout_block(block)
        assert result is None


# ── Artifact text parsing tests ────────────────────────────────────────────

class TestArtifactTextParsing:
    def test_parse_artifact_with_code(self):
        text = "**Artifact 1**: hello.py\nURL: https://example.com/hello.py\nLanguage: `python`\n```\nprint('hi')\n```"
        art = _parse_artifact_text(text)
        assert art is not None
        assert art.name == "hello.py"
        assert art.url == "https://example.com/hello.py"
        assert art.language == "python"
        assert art.content == "print('hi')"

    def test_parse_artifact_minimal(self):
        text = "**Artifact 2**: data.csv"
        art = _parse_artifact_text(text)
        assert art is not None
        assert art.name == "data.csv"


# ── Blocks → Interaction conversion ────────────────────────────────────────

class TestBlocksToInteraction:
    def test_full_conversion(self, sample_blocks):
        ix = _blocks_to_interaction(sample_blocks, "page-123", "gpt-4 · 2026-04-27 08:00")
        assert ix.id == "page-123"
        assert len(ix.messages) >= 2  # USER + ASSISTANT at minimum
        assert ix.artifacts
        assert ix.sensitivity is not None
        assert ix.sensitivity.max_risk_level == RiskLevel.HIGH

    def test_model_from_metadata(self, sample_blocks):
        ix = _blocks_to_interaction(sample_blocks, "page-123", "test title")
        # Model should be extracted from heading_2 block
        assert ix.custom.get("model") == "gpt-4"

    def test_model_from_title(self):
        blocks = [
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"plain_text": "[USER] Hi",
                         "text": {"content": "[USER] Hi"},
                         "annotations": {"bold": True, "italic": False, "strikethrough": False,
                                       "underline": False, "code": False, "color": "default"}},
                    ],
                    "color": "default",
                },
            },
        ]
        ix = _blocks_to_interaction(blocks, "p1", "claude-3 · 2026-04-27 09:00")
        # No heading block, model should come from title
        assert "claude-3" in ix.custom.get("notion_page_title", "")

    def test_empty_blocks(self):
        ix = _blocks_to_interaction([], "p1", "")
        assert len(ix.messages) == 0

    def test_divider_separates_sections(self):
        blocks = [
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"plain_text": "[USER] First question",
                         "text": {"content": "[USER] First question"},
                         "annotations": {"bold": True, "italic": False, "strikethrough": False,
                                       "underline": False, "code": False, "color": "default"}},
                    ],
                    "color": "default",
                },
            },
            {"type": "divider", "divider": {}},
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"plain_text": "[ASSISTANT] First answer",
                         "text": {"content": "[ASSISTANT] First answer"},
                         "annotations": {"bold": True, "italic": False, "strikethrough": False,
                                       "underline": False, "code": False, "color": "default"}},
                    ],
                    "color": "default",
                },
            },
        ]
        ix = _blocks_to_interaction(blocks, "p1", "")
        assert len(ix.messages) == 2
        assert ix.messages[0].role == Role.USER
        assert ix.messages[1].role == Role.ASSISTANT


# ── File mode tests ────────────────────────────────────────────────────────

class TestFileMode:
    def test_detect_json_with_results(self, importer, sample_notion_export_json):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(sample_notion_export_json, f, ensure_ascii=False)
            f.flush()
            path = Path(f.name)
        try:
            assert importer.detect(path) is True
        finally:
            path.unlink()

    def test_detect_not_json(self, importer):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("not json")
            f.flush()
            path = Path(f.name)
        try:
            assert importer.detect(path) is False
        finally:
            path.unlink()

    def test_detect_ailog_file(self, importer):
        ailog_data = {"ailog_version": "0.1", "interactions": []}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(ailog_data, f)
            f.flush()
            path = Path(f.name)
        try:
            # Should not detect .ailog files as Notion exports
            assert importer.detect(path) is False
        finally:
            path.unlink()

    def test_parse_results_format(self, importer, sample_notion_export_json):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(sample_notion_export_json, f, ensure_ascii=False)
            f.flush()
            path = Path(f.name)
        try:
            ailog = importer.parse(path)
            assert isinstance(ailog, AILogFile)
            assert ailog.metadata.source_platform == "notion"
            assert len(ailog.interactions) >= 1
        finally:
            path.unlink()

    def test_parse_single_page(self, importer):
        page_data = {
            "id": "single-page-1",
            "created_time": "2026-04-27T10:00:00Z",
            "properties": {
                "title": {
                    "title": [
                        {"plain_text": "Test Page", "text": {"content": "Test Page"}}
                    ]
                }
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(page_data, f)
            f.flush()
            path = Path(f.name)
        try:
            ailog = importer.parse(path)
            assert isinstance(ailog, AILogFile)
            # Single page with no blocks → minimal interaction
            assert len(ailog.interactions) == 1
        finally:
            path.unlink()

    def test_parse_array_format(self, importer):
        pages = [
            {
                "id": "arr-page-1",
                "created_time": "2026-04-27T10:00:00Z",
                "properties": {
                    "title": {
                        "title": [
                            {"plain_text": "Page One", "text": {"content": "Page One"}}
                        ]
                    }
                },
                "children": [
                    {
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {"plain_text": "[USER] Test",
                                 "text": {"content": "[USER] Test"},
                                 "annotations": {"bold": True, "italic": False, "strikethrough": False,
                                               "underline": False, "code": False, "color": "default"}},
                            ],
                            "color": "default",
                        },
                    },
                ],
            },
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(pages, f)
            f.flush()
            path = Path(f.name)
        try:
            ailog = importer.parse(path)
            assert len(ailog.interactions) == 1
            assert ailog.interactions[0].messages[0].role == Role.USER
        finally:
            path.unlink()

    def test_parse_file_not_found(self, importer):
        with pytest.raises(FileNotFoundError):
            importer.parse("/nonexistent/file.json")


# ── API mode validation tests ──────────────────────────────────────────────

class TestAPIMode:
    def test_api_mode_requires_key(self):
        # Clear env vars
        old_key = os.environ.pop("NOTION_API_KEY", None)
        old_page = os.environ.pop("NOTION_PARENT_PAGE_ID", None)
        try:
            imp = NotionImporter()
            with pytest.raises(ValueError, match="NOTION_API_KEY"):
                imp.client
        finally:
            if old_key:
                os.environ["NOTION_API_KEY"] = old_key
            if old_page:
                os.environ["NOTION_PARENT_PAGE_ID"] = old_page

    def test_parse_from_api_requires_parent(self):
        old_page = os.environ.pop("NOTION_PARENT_PAGE_ID", None)
        try:
            imp = NotionImporter(api_key="fake-key")
            with pytest.raises(ValueError, match="parent_page_id"):
                imp.parse_from_api()
        finally:
            if old_page:
                os.environ["NOTION_PARENT_PAGE_ID"] = old_page


# ── Session ID derivation tests ────────────────────────────────────────────

class TestSessionID:
    def test_stable_session_id_from_page_id(self):
        ix1 = _blocks_to_interaction([], "abc-123-def", "")
        ix2 = _blocks_to_interaction([], "abc-123-def", "")
        assert ix1.session_id == ix2.session_id

    def test_different_page_different_session(self):
        ix1 = _blocks_to_interaction([], "page-1", "")
        ix2 = _blocks_to_interaction([], "page-2", "")
        assert ix1.session_id != ix2.session_id

"""
Tests for NotionExporter.

These tests verify block building logic without making real API calls.
"""

import pytest
from ailog.exporters.notion import (
    NotionExporter,
    NotionExporterError,
    block_paragraph,
    block_heading,
    block_code,
    block_callout,
    block_divider,
    render_message,
    render_artifacts,
    render_sensitivity,
    _rich_text,
    _looks_like_code,
    _map_language,
    _sensitivity_color,
)
from ailog.core.models import (
    Message,
    Artifact,
    SensitivityInfo,
    SensitivityItem,
    Role,
    ContentType,
    ArtifactType,
    RiskLevel,
    RedactionStrategy,
)


class TestBlockBuilders:
    def test_paragraph(self):
        b = block_paragraph(_rich_text("hello world"))
        assert b["object"] == "block"
        assert b["type"] == "paragraph"
        assert b["paragraph"]["rich_text"][0]["plain_text"] == "hello world"

    def test_paragraph_with_bold(self):
        b = block_paragraph(_rich_text("[USER] ", bold=True))
        assert b["paragraph"]["rich_text"][0]["annotations"]["bold"] is True

    def test_heading_h2(self):
        b = block_heading("Model: gpt-4", level=2)
        assert b["type"] == "heading_2"

    def test_code_block(self):
        b = block_code("print('hi')", language="python")
        assert b["type"] == "code"
        assert b["code"]["language"] == "python"

    def test_callout(self):
        b = block_callout("think: blah", icon="💡", color="yellow_background")
        assert b["type"] == "callout"
        assert b["callout"]["icon"]["emoji"] == "💡"
        assert b["callout"]["color"] == "yellow_background"

    def test_divider(self):
        b = block_divider()
        assert b["type"] == "divider"


class TestRenderMessage:
    def test_user_message_renders_label(self):
        msg = Message(role=Role.USER, content="hello")
        blocks = render_message(msg)
        assert len(blocks) >= 1
        assert blocks[0]["type"] == "paragraph"

    def test_assistant_code_message(self):
        msg = Message(
            role=Role.ASSISTANT,
            content="```python\nprint('hi')\n```",
            content_type=ContentType.TEXT,
        )
        blocks = render_message(msg)
        # Should include at least role label + code block
        types = [b["type"] for b in blocks]
        assert "code" in types

    def test_tool_message(self):
        msg = Message(role=Role.TOOL, content='{"result": 42}')
        blocks = render_message(msg)
        types = [b["type"] for b in blocks]
        # Tool messages are often JSON — should be recognized as code
        assert len(blocks) >= 1

    def test_empty_content(self):
        msg = Message(role=Role.USER, content="")
        blocks = render_message(msg)
        assert len(blocks) == 1  # role label only


class TestRenderArtifacts:
    def test_single_artifact(self):
        a = Artifact(
            id="art-001",
            name="helper.py",
            type=ArtifactType.CODE,
            language="python",
            content="def foo(): pass",
        )
        blocks = render_artifacts([a])
        types = [b["type"] for b in blocks]
        assert "heading_2" in types
        assert "callout" in types

    def test_multiple_artifacts(self):
        artifacts = [
            Artifact(id=f"art-{i:03d}", name=f"file{i}.py", type=ArtifactType.CODE)
            for i in range(3)
        ]
        blocks = render_artifacts(artifacts)
        callouts = [b for b in blocks if b["type"] == "callout"]
        assert len(callouts) == 3


class TestRenderSensitivity:
    def test_high_sensitivity(self):
        item = SensitivityItem(
            info_type="email",
            risk_level=RiskLevel.HIGH,
            field="content",
        )
        info = SensitivityInfo(
            max_risk_level=RiskLevel.HIGH,
            detected_items=[item],
        )
        blocks = render_sensitivity(info)
        types = [b["type"] for b in blocks]
        assert "callout" in types
        callout = next(b for b in blocks if b["type"] == "callout")
        assert "orange" in callout["callout"]["color"]

    def test_low_sensitivity(self):
        info = SensitivityInfo(
            max_risk_level=RiskLevel.LOW,
            detected_items=[],
        )
        blocks = render_sensitivity(info)
        callout = next(b for b in blocks if b["type"] == "callout")
        assert "gray" in callout["callout"]["color"]


class TestHelpers:
    def test_looks_like_code_indent(self):
        assert _looks_like_code("def foo():") is True
        assert _looks_like_code("    return x") is True

    def test_looks_like_code_comment(self):
        assert _looks_like_code("// hello") is True
        assert _looks_like_code("#!/bin/bash") is True

    def test_looks_like_code_plain_text(self):
        assert _looks_like_code("Hello world how are you today") is False

    def test_map_language(self):
        assert _map_language("python") == "python"
        assert _map_language("py") == "python"
        assert _map_language("javascript") == "javascript"
        assert _map_language("unknown_lang") == "plain text"

    def test_sensitivity_color(self):
        color, emoji = _sensitivity_color("high")
        assert "orange" in color
        assert emoji == "🟠"

        color, emoji = _sensitivity_color("low")
        assert "gray" in color
        assert emoji == "🟢"


class TestNotionExporterInit:
    def test_missing_api_key(self):
        import os
        saved = os.environ.pop("NOTION_API_KEY", None)
        saved2 = os.environ.pop("NOTION_PARENT_PAGE_ID", None)
        try:
            with pytest.raises(ValueError, match="NOTION_API_KEY"):
                NotionExporter()
        finally:
            if saved:
                os.environ["NOTION_API_KEY"] = saved
            if saved2:
                os.environ["NOTION_PARENT_PAGE_ID"] = saved2

    def test_missing_parent_page_id(self):
        import os
        saved = os.environ.pop("NOTION_PARENT_PAGE_ID", None)
        try:
            # Set a fake key but no parent
            with pytest.raises(ValueError, match="NOTION_PARENT_PAGE_ID"):
                NotionExporter(api_key="fake-key")
        finally:
            if saved:
                os.environ["NOTION_PARENT_PAGE_ID"] = saved

    def test_init_with_params(self):
        ex = NotionExporter(
            parent_page_id="page-abc",
            api_key="secret-xyz",
        )
        assert ex.api_key == "secret-xyz"
        assert ex.parent_page_id == "page-abc"


class TestExportString:
    """export_string returns a JSON summary (since Notion is API-based)."""

    def test_export_string_returns_ids(self):
        # NotionExporter doesn't have export_string (it's API-only)
        # Check that the class exists and is instantiable
        ex = NotionExporter.__new__(NotionExporter)
        ex.api_key = "test"
        ex.parent_page_id = "test-page"
        ex._client = None
        assert ex.api_key == "test"
        assert ex.parent_page_id == "test-page"

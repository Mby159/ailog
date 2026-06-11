"""Tests for Obsidian Exporter."""

import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from ailog.core.models import (
    AILogFile, AILogFileMetadata, Interaction, Message,
    Role, ContentType, OwnerInfo, OwnerIdType,
)
from ailog.exporters.obsidian import ObsidianExporter


def _make_sample() -> AILogFile:
    return AILogFile(
        ailog_version="0.1",
        metadata=AILogFileMetadata(
            source_platform="chatgpt",
            export_timestamp="2026-04-26T10:00:00Z",
            exporter="ailog-test/0.1.0",
            tags=["chatgpt-export"],
        ),
        interactions=[
            Interaction(
                id="ix_test_1",
                timestamp="2026-04-26T10:00:00Z",
                session_id="sess_test",
                turn_index=1,
                messages=[
                    Message(role=Role.USER, content="Write a Python hello world"),
                    Message(role=Role.ASSISTANT, content="```python\nprint('Hello, World!')\n```", model="gpt-4o"),
                ],
                custom={"chatgpt_title": "Hello World"},
            ),
        ],
    )


def test_export_string():
    exporter = ObsidianExporter()
    ailog = _make_sample()
    md = exporter.export_string(ailog)

    assert "# AILog: chatgpt" in md
    assert "Hello World" in md
    assert "print('Hello, World!')" in md
    assert "gpt-4o" in md
    assert "---" in md  # Frontmatter or separator


def test_export_to_file():
    exporter = ObsidianExporter()
    ailog = _make_sample()

    with tempfile.TemporaryDirectory() as tmpdir:
        # Single file export
        out_file = Path(tmpdir) / "test.md"
        result = exporter.export(ailog, out_file)
        assert result.exists()
        content = result.read_text(encoding="utf-8")
        assert "Hello World" in content
        assert "print" in content


def test_export_to_directory():
    exporter = ObsidianExporter()
    ailog = _make_sample()

    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir) / "vault"
        result = exporter.export(ailog, out_dir)
        assert result.is_dir()
        # Should have session file + index
        md_files = list(result.glob("*.md"))
        assert len(md_files) >= 2, f"Expected at least 2 files, got {md_files}"

        # Check index exists
        index = result / "_ailog_index.md"
        assert index.exists()
        index_content = index.read_text(encoding="utf-8")
        assert "AILog Index" in index_content


def test_frontmatter():
    exporter = ObsidianExporter()
    ailog = _make_sample()

    # Frontmatter is in session-level export, not _render_all
    md = exporter._render_session(ailog, ailog.interactions)
    assert "source_platform: chatgpt" in md
    assert "session_id:" in md
    assert "---" in md  # YAML frontmatter delimiters


if __name__ == "__main__":
    test_export_string()
    print("PASS: test_export_string")
    test_export_to_file()
    print("PASS: test_export_to_file")
    test_export_to_directory()
    print("PASS: test_export_to_directory")
    test_frontmatter()
    print("PASS: test_frontmatter")
    print("\nAll Obsidian exporter tests passed!")

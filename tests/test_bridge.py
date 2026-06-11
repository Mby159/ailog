"""Tests for File Brain bridge and search."""

import json
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from ailog.core.models import (
    AILogFile, AILogFileMetadata, Interaction, Message,
    Role, ContentType, OwnerInfo, OwnerIdType,
)
from ailog.bridge.filebrain import (
    index_ailog_file,
    search_ailog,
    ailog_to_markdown,
)


def _make_sample_ailog() -> AILogFile:
    """Create a sample AILogFile for testing."""
    return AILogFile(
        ailog_version="0.1",
        metadata=AILogFileMetadata(
            source_platform="chatgpt",
            export_timestamp="2026-04-26T08:00:00Z",
            exporter="ailog-test/0.1.0",
        ),
        interactions=[
            Interaction(
                id="ix_test_1",
                timestamp="2026-04-26T08:00:00Z",
                session_id="sess_test",
                turn_index=1,
                messages=[
                    Message(role=Role.USER, content="How does quicksort work?"),
                    Message(role=Role.ASSISTANT, content="Quicksort is a divide-and-conquer algorithm...", model="gpt-4o"),
                ],
                custom={"chatgpt_title": "Sorting Algorithms"},
            ),
            Interaction(
                id="ix_test_2",
                timestamp="2026-04-26T08:01:00Z",
                session_id="sess_test",
                turn_index=2,
                messages=[
                    Message(role=Role.USER, content="What about mergesort?"),
                    Message(role=Role.ASSISTANT, content="Mergesort is also divide-and-conquer but guarantees O(n log n)...", model="gpt-4o"),
                ],
                custom={"chatgpt_title": "Sorting Algorithms"},
            ),
        ],
    )


def test_markdown_export():
    """Test AILog to Markdown conversion."""
    ailog = _make_sample_ailog()
    md = ailog_to_markdown(ailog)

    assert "# AILog Export: chatgpt" in md
    assert "## Sorting Algorithms" in md
    assert "Turn 1" in md
    assert "Turn 2" in md
    assert "quicksort" in md.lower()
    assert "mergesort" in md.lower()


def test_index_and_search():
    """Test indexing .ailog into SimpleSearchEngine and searching."""
    # We need SimpleSearchEngine from file-brain-mcp
    sys.path.insert(0, str(Path(__file__).parent.parent / "file-brain-mcp"))
    try:
        from file_brain_mcp import SimpleSearchEngine
    except ImportError:
        print("SKIP: file-brain-mcp not available")
        return

    ailog = _make_sample_ailog()

    # Save to temp file
    with tempfile.TemporaryDirectory() as tmpdir:
        ailog_path = Path(tmpdir) / "test.ailog"
        ailog.save(ailog_path)

        # Index
        engine = SimpleSearchEngine(index_dir=str(Path(tmpdir) / "indexes"))
        stats = index_ailog_file(engine, ailog_path)

        assert stats["success"] == 2, f"Expected 2 indexed, got {stats}"
        assert stats["failed"] == 0

        # Search for quicksort
        results = search_ailog(engine, "quicksort", top_k=5)
        assert len(results) >= 1, "Should find quicksort"
        assert any("quicksort" in r.get("title", "").lower() or "quicksort" in r.get("context", "").lower() for r in results)

        # Search for mergesort
        results2 = search_ailog(engine, "mergesort", top_k=5)
        assert len(results2) >= 1, "Should find mergesort"


if __name__ == "__main__":
    test_markdown_export()
    print("PASS: test_markdown_export")
    test_index_and_search()
    print("PASS: test_index_and_search")
    print("\nAll bridge tests passed!")

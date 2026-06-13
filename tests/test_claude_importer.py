"""Tests for Claude Importer."""

import json
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from ailog.importers.claude import ClaudeImporter
from ailog.core.models import AILogFile, Role


FIXTURES = Path(__file__).parent / "fixtures"


def test_detect_claude():
    importer = ClaudeImporter()
    result = importer.detect(FIXTURES / "claude_conversations.json")
    assert result is True, "Should detect Claude conversations.json"


def test_detect_not_claude():
    importer = ClaudeImporter()
    # ChatGPT format should not be detected as Claude
    result = importer.detect(FIXTURES / "chatgpt_conversations.json")
    assert result is False, "ChatGPT format should not be detected as Claude"


def test_parse_claude():
    importer = ClaudeImporter()
    ailog = importer.parse(FIXTURES / "claude_conversations.json")

    # Should have 2 interactions (2 user+assistant pairs)
    assert len(ailog.interactions) == 2, f"Expected 2 interactions, got {len(ailog.interactions)}"

    # Check first interaction
    ix1 = ailog.interactions[0]
    assert ix1.messages[0].role == Role.USER
    assert ix1.messages[1].role == Role.ASSISTANT
    assert "CLI" in ix1.messages[0].content or "CLI" in ix1.messages[1].content
    assert ix1.messages[1].model == "claude-3-5-sonnet-20241022"
    assert ix1.messages[1].model_provider == "anthropic"

    # Check metadata
    assert ailog.metadata.source_platform == "claude"
    assert "claude" in ailog.metadata.exporter

    # Check custom fields
    assert ix1.custom.get("claude_title") == "Rust vs Go"


def test_round_trip_claude():
    """Test save and load for Claude-imported data."""
    importer = ClaudeImporter()
    ailog = importer.parse(FIXTURES / "claude_conversations.json")

    with tempfile.TemporaryDirectory() as tmpdir:
        jsonl_path = Path(tmpdir) / "claude.ailog"
        ailog.save(jsonl_path, fmt="jsonl")
        loaded = AILogFile.load(jsonl_path)
        assert len(loaded.interactions) == 2
        assert loaded.metadata.source_platform == "claude"


if __name__ == "__main__":
    test_detect_claude()
    print("PASS: test_detect_claude")
    test_detect_not_claude()
    print("PASS: test_detect_not_claude")
    test_parse_claude()
    print("PASS: test_parse_claude")
    test_round_trip_claude()
    print("PASS: test_round_trip_claude")
    print("\nAll Claude importer tests passed!")

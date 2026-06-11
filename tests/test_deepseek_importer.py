"""Tests for DeepSeek Importer."""

import json
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from ailog.importers.deepseek import DeepSeekImporter
from ailog.core.models import AILogFile, Role


FIXTURES = Path(__file__).parent / "fixtures"


def test_detect_deepseek():
    importer = DeepSeekImporter()
    result = importer.detect(FIXTURES / "deepseek_conversations.json")
    assert result is True, "Should detect DeepSeek conversations with reasoning"


def test_not_chatgpt():
    importer = DeepSeekImporter()
    result = importer.detect(FIXTURES / "chatgpt_conversations.json")
    assert result is False, "ChatGPT format should not be detected as DeepSeek"


def test_parse_deepseek():
    importer = DeepSeekImporter()
    ailog = importer.parse(FIXTURES / "deepseek_conversations.json")

    # Should have 2 interactions
    assert len(ailog.interactions) == 2, f"Expected 2, got {len(ailog.interactions)}"

    # Check first interaction — has reasoning_content
    ix1 = ailog.interactions[0]
    assert ix1.messages[0].role == Role.USER
    assert ix1.messages[1].role == Role.ASSISTANT

    # Check that thinking content is embedded
    assistant_msg = ix1.messages[1]
    assert "1+1等于2" in assistant_msg.content
    assert "这是一个简单的加法" in assistant_msg.content  # reasoning included

    # Check deepseek-specific custom fields
    assert assistant_msg.custom.get("deepseek_has_thinking") is True
    assert assistant_msg.model == "deepseek-reasoner"
    assert assistant_msg.model_provider == "deepseek"

    # Check second interaction — has "thinking" field (alternative key)
    ix2 = ailog.interactions[1]
    assert "2+2等于4" in ix2.messages[1].content
    assert "和上面一样" in ix2.messages[1].content  # thinking included

    # Metadata
    assert ailog.metadata.source_platform == "deepseek"


def test_round_trip_deepseek():
    importer = DeepSeekImporter()
    ailog = importer.parse(FIXTURES / "deepseek_conversations.json")

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "ds.ailog"
        ailog.save(path, fmt="jsonl")
        loaded = AILogFile.load(path)
        assert len(loaded.interactions) == 2
        assert loaded.metadata.source_platform == "deepseek"


if __name__ == "__main__":
    test_detect_deepseek()
    print("PASS: test_detect_deepseek")
    test_not_chatgpt()
    print("PASS: test_not_chatgpt")
    test_parse_deepseek()
    print("PASS: test_parse_deepseek")
    test_round_trip_deepseek()
    print("PASS: test_round_trip_deepseek")
    print("\nAll DeepSeek importer tests passed!")

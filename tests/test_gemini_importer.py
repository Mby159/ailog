"""Tests for Gemini Importer."""

import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from ailog.importers.gemini import GeminiImporter
from ailog.core.models import AILogFile, Role


FIXTURES = Path(__file__).parent / "fixtures"


def test_detect_gemini():
    importer = GeminiImporter()
    result = importer.detect(FIXTURES / "gemini_conversations.json")
    assert result is True, "Should detect Gemini (has 'model' role)"


def test_not_chatgpt():
    importer = GeminiImporter()
    result = importer.detect(FIXTURES / "chatgpt_conversations.json")
    assert result is False, "ChatGPT has 'mapping', not Gemini"


def test_not_claude():
    importer = GeminiImporter()
    result = importer.detect(FIXTURES / "claude_conversations.json")
    assert result is False, "Claude uses 'human/assistant', not 'model'"


def test_parse_gemini():
    importer = GeminiImporter()
    ailog = importer.parse(FIXTURES / "gemini_conversations.json")

    assert len(ailog.interactions) == 2, f"Expected 2, got {len(ailog.interactions)}"

    ix1 = ailog.interactions[0]
    assert ix1.messages[0].role == Role.USER
    assert ix1.messages[1].role == Role.ASSISTANT  # "model" mapped to ASSISTANT
    assert ix1.messages[1].model == "gemini-2.0-flash"
    assert ix1.messages[1].model_provider == "google"
    assert ix1.messages[1].custom.get("gemini_original_role") == "model"

    assert ailog.metadata.source_platform == "gemini"
    assert ix1.custom.get("gemini_title") == "Gemini Multimodal Test"


def test_round_trip_gemini():
    importer = GeminiImporter()
    ailog = importer.parse(FIXTURES / "gemini_conversations.json")

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "gemini.ailog"
        ailog.save(path, fmt="jsonl")
        loaded = AILogFile.load(path)
        assert len(loaded.interactions) == 2
        assert loaded.metadata.source_platform == "gemini"


if __name__ == "__main__":
    test_detect_gemini()
    print("PASS: test_detect_gemini")
    test_not_chatgpt()
    print("PASS: test_not_chatgpt")
    test_not_claude()
    print("PASS: test_not_claude")
    test_parse_gemini()
    print("PASS: test_parse_gemini")
    test_round_trip_gemini()
    print("PASS: test_round_trip_gemini")
    print("\nAll Gemini importer tests passed!")

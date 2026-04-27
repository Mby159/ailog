"""Tests for ChatGPT Importer."""

import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ailog.importers.chatgpt import ChatGPTImporter
from ailog.core.models import AILogFile, Role, ContentType, RiskLevel

FIXTURES = Path(__file__).parent / "fixtures"


def test_detect_json():
    importer = ChatGPTImporter()
    result = importer.detect(FIXTURES / "chatgpt_conversations.json")
    assert result is True, "Should detect ChatGPT conversations.json"


def test_detect_non_chatgpt():
    importer = ChatGPTImporter()
    # A random JSON file should not be detected
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False, encoding="utf-8") as f:
        json.dump({"not": "chatgpt"}, f)
        tmp = f.name
    result = importer.detect(tmp)
    assert result is False, "Should not detect random JSON"
    Path(tmp).unlink()


def test_parse_conversations():
    importer = ChatGPTImporter()
    ailog = importer.parse(FIXTURES / "chatgpt_conversations.json")

    # Should have 2 conversations = 2 sessions
    session_ids = set(ix.session_id for ix in ailog.interactions)
    assert len(session_ids) == 2, f"Expected 2 sessions, got {len(session_ids)}"

    # Should have 3 interactions total (2 from conv_001 + 1 from conv_002)
    # Debug: print what we got
    # for ix in ailog.interactions:
    #     print(f"  {ix.id} | session={ix.session_id} | turn={ix.turn_index} | msgs={len(ix.messages)}")
    assert len(ailog.interactions) == 3, f"Expected 3 interactions, got {len(ailog.interactions)}"

    # Check first interaction (conv_001, turn 1)
    ix1 = ailog.interactions[0]
    assert ix1.session_id == "sess_conv_001"
    assert ix1.turn_index == 1
    assert len(ix1.messages) == 2  # user + assistant
    assert ix1.messages[0].role == Role.USER
    assert ix1.messages[1].role == Role.ASSISTANT
    assert "quicksort" in ix1.messages[1].content

    # Check second interaction (conv_001, turn 2) — contains phone
    ix2 = ailog.interactions[1]
    assert "13812345678" in ix2.messages[0].content
    assert ix2.messages[0].role == Role.USER

    # Check third interaction (conv_002) — contains API key
    ix3 = ailog.interactions[2]
    assert "sk-proj" in ix3.messages[0].content

    # Metadata
    assert ailog.metadata.source_platform == "chatgpt"
    assert ailog.metadata.exporter.startswith("ailog-importer-chatgpt")


def test_round_trip():
    """Test that parsed ALogFile can be saved and loaded back."""
    importer = ChatGPTImporter()
    ailog = importer.parse(FIXTURES / "chatgpt_conversations.json")

    # Save as JSONL
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        jsonl_path = Path(tmpdir) / "test.ailog"
        ailog.save(jsonl_path, fmt="jsonl")

        # Load back
        loaded = AILogFile.load(jsonl_path)
        assert len(loaded.interactions) == len(ailog.interactions)
        assert loaded.metadata.source_platform == "chatgpt"

        # Save as JSON and load back
        json_path = Path(tmpdir) / "test.ailog.json"
        ailog.save(json_path, fmt="json")
        loaded_json = AILogFile.load(json_path)
        assert len(loaded_json.interactions) == len(ailog.interactions)


def test_metadata_custom():
    """Test that ChatGPT-specific custom fields are preserved."""
    importer = ChatGPTImporter()
    ailog = importer.parse(FIXTURES / "chatgpt_conversations.json")

    # Check that custom fields contain ChatGPT conversation ID and title
    ix = ailog.interactions[0]
    assert "chatgpt_conversation_id" in ix.messages[0].custom
    assert "chatgpt_title" in ix.messages[0].custom
    assert ix.custom.get("chatgpt_title") == "Python Quick Sort"


if __name__ == "__main__":
    test_detect_json()
    print("PASS: test_detect_json")
    test_detect_non_chatgpt()
    print("PASS: test_detect_non_chatgpt")
    test_parse_conversations()
    print("PASS: test_parse_conversations")
    test_round_trip()
    print("PASS: test_round_trip")
    test_metadata_custom()
    print("PASS: test_metadata_custom")
    print("\nAll tests passed!")

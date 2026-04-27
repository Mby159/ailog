"""Tests for YouTube and Bilibili Importers."""

import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ailog.importers.youtube import YouTubeImporter
from ailog.importers.bilibili import BilibiliImporter
from ailog.core.models import AILogFile, Role


FIXTURES = Path(__file__).parent / "fixtures"


# ── YouTube ──

def test_detect_youtube():
    importer = YouTubeImporter()
    result = importer.detect(FIXTURES / "youtube_transcript.json")
    assert result is True, "Should detect YouTube transcript"


def test_parse_youtube():
    importer = YouTubeImporter()
    ailog = importer.parse(FIXTURES / "youtube_transcript.json")

    # 11 segments grouped into chunks of 10 → 2 chunks
    assert len(ailog.interactions) >= 1, "Should have at least 1 chunk"
    assert ailog.metadata.source_platform == "youtube"

    ix1 = ailog.interactions[0]
    assert ix1.messages[0].role == Role.ASSISTANT
    assert "AI" in ix1.messages[0].content or "Welcome" in ix1.messages[0].content
    assert ix1.custom.get("youtube_title") == "AI Evolution 2026"
    assert ix1.custom.get("youtube_video_id") == "dQw4w9WgXcQ"


def test_youtube_round_trip():
    importer = YouTubeImporter()
    ailog = importer.parse(FIXTURES / "youtube_transcript.json")

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "yt.ailog"
        ailog.save(path, fmt="jsonl")
        loaded = AILogFile.load(path)
        assert loaded.metadata.source_platform == "youtube"


# ── Bilibili ──

def test_detect_bilibili():
    importer = BilibiliImporter()
    result = importer.detect(FIXTURES / "bilibili_subtitles.json")
    assert result is True, "Should detect Bilibili subtitles"


def test_parse_bilibili():
    importer = BilibiliImporter()
    ailog = importer.parse(FIXTURES / "bilibili_subtitles.json")

    # 10 segments → 1 chunk
    assert len(ailog.interactions) >= 1
    assert ailog.metadata.source_platform == "bilibili"

    ix1 = ailog.interactions[0]
    assert ix1.messages[0].role == Role.ASSISTANT
    assert "量子" in ix1.messages[0].content or "频道" in ix1.messages[0].content


def test_bilibili_round_trip():
    importer = BilibiliImporter()
    ailog = importer.parse(FIXTURES / "bilibili_subtitles.json")

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "bili.ailog"
        ailog.save(path, fmt="jsonl")
        loaded = AILogFile.load(path)
        assert loaded.metadata.source_platform == "bilibili"


# ── Cross-detection ──

def test_youtube_not_bilibili():
    yt = YouTubeImporter()
    result = yt.detect(FIXTURES / "bilibili_subtitles.json")
    # Bilibili format has "content"/"from"/"to", not "text"/"start"/"duration"
    # So YouTube shouldn't detect it
    assert result is False, "YouTube should not detect Bilibili format"


def test_bilibili_not_youtube():
    bili = BilibiliImporter()
    result = bili.detect(FIXTURES / "youtube_transcript.json")
    # YouTube format has "transcript"/"video_id", not "bvid"/"subtitles"
    assert result is False, "Bilibili should not detect YouTube format"


if __name__ == "__main__":
    test_detect_youtube()
    print("PASS: test_detect_youtube")
    test_parse_youtube()
    print("PASS: test_parse_youtube")
    test_youtube_round_trip()
    print("PASS: test_youtube_round_trip")
    test_detect_bilibili()
    print("PASS: test_detect_bilibili")
    test_parse_bilibili()
    print("PASS: test_parse_bilibili")
    test_bilibili_round_trip()
    print("PASS: test_bilibili_round_trip")
    test_youtube_not_bilibili()
    print("PASS: test_youtube_not_bilibili")
    test_bilibili_not_youtube()
    print("PASS: test_bilibili_not_youtube")
    print("\nAll video importer tests passed!")

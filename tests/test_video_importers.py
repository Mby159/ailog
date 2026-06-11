"""Tests for YouTube and Bilibili Importers."""

import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from ailog.importers.youtube import (
    YouTubeImporter,
    extract_video_id,
    _group_segments_into_chunks,
)
from ailog.importers.bilibili import BilibiliImporter
from ailog.core.models import AILogFile, Role


FIXTURES = Path(__file__).parent / "fixtures"


# ── YouTube URL parsing ──

def test_extract_video_id_standard():
    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_short():
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_shorts():
    assert extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_embed():
    assert extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_live():
    assert extract_video_id("https://www.youtube.com/live/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_bare():
    assert extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_invalid():
    assert extract_video_id("not a youtube url") is None
    assert extract_video_id("") is None


def test_is_youtube_url():
    importer = YouTubeImporter()
    assert importer.is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is True
    assert importer.is_youtube_url("https://youtu.be/dQw4w9WgXcQ") is True
    assert importer.is_youtube_url("dQw4w9WgXcQ") is True
    assert importer.is_youtube_url("/path/to/video.json") is False


# ── YouTube fetch_and_parse (mocked) ──

def test_fetch_and_parse():
    """Test fetch_and_parse with mocked transcript API."""
    mock_data = {
        "video_id": "dQw4w9WgXcQ",
        "title": "Test Video",
        "channel": "Test Channel",
        "language": "en",
        "is_generated": False,
        "transcript": [
            {"text": "Hello world", "start": 0.0, "duration": 3.0},
            {"text": "This is a test", "start": 3.0, "duration": 4.0},
        ],
    }

    with patch("ailog.importers.youtube._fetch_transcript", return_value=mock_data):
        importer = YouTubeImporter()
        ailog = importer.fetch_and_parse("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

        assert len(ailog.interactions) >= 1
        assert ailog.metadata.source_platform == "youtube"
        assert "youtube-transcript" in ailog.metadata.tags

        ix = ailog.interactions[0]
        assert ix.custom.get("youtube_video_id") == "dQw4w9WgXcQ"
        assert ix.custom.get("youtube_title") == "Test Video"
        assert ix.custom.get("youtube_channel") == "Test Channel"


def test_fetch_and_parse_auto_generated():
    """Test that auto-generated transcripts get correct tag."""
    mock_data = {
        "video_id": "dQw4w9WgXcQ",
        "title": "Auto Video",
        "channel": "",
        "language": "en",
        "is_generated": True,
        "transcript": [{"text": "Auto generated text", "start": 0.0, "duration": 5.0}],
    }

    with patch("ailog.importers.youtube._fetch_transcript", return_value=mock_data):
        importer = YouTubeImporter()
        ailog = importer.fetch_and_parse("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

        assert "youtube-auto-transcript" in ailog.metadata.tags
        assert ailog.interactions[0].custom.get("youtube_auto_generated") is True


def test_fetch_and_parse_error():
    """Test that fetch errors propagate nicely."""
    with patch("ailog.importers.youtube._fetch_transcript", side_effect=Exception("Transcripts disabled")):
        importer = YouTubeImporter()
        try:
            importer.fetch_and_parse("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            assert False, "Should have raised"
        except Exception as e:
            assert "Transcripts disabled" in str(e)


def test_fetch_and_parse_invalid_url():
    """Test that invalid URLs raise ValueError."""
    importer = YouTubeImporter()
    try:
        importer.fetch_and_parse("not a youtube url")
        assert False, "Should have raised"
    except ValueError as e:
        assert "Could not extract video ID" in str(e)


# ── YouTube file-based ──

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


def test_youtube_srt_detect():
    importer = YouTubeImporter()
    # SRT files are detected
    assert importer.detect(FIXTURES / "sample.srt") is True


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
    assert result is False, "YouTube should not detect Bilibili format"


def test_bilibili_not_youtube():
    bili = BilibiliImporter()
    result = bili.detect(FIXTURES / "youtube_transcript.json")
    assert result is False, "Bilibili should not detect YouTube format"


if __name__ == "__main__":
    tests = [
        ("extract_video_id_standard", test_extract_video_id_standard),
        ("extract_video_id_short", test_extract_video_id_short),
        ("extract_video_id_shorts", test_extract_video_id_shorts),
        ("extract_video_id_embed", test_extract_video_id_embed),
        ("extract_video_id_live", test_extract_video_id_live),
        ("extract_video_id_bare", test_extract_video_id_bare),
        ("extract_video_id_invalid", test_extract_video_id_invalid),
        ("is_youtube_url", test_is_youtube_url),
        ("fetch_and_parse", test_fetch_and_parse),
        ("fetch_and_parse_auto_generated", test_fetch_and_parse_auto_generated),
        ("fetch_and_parse_error", test_fetch_and_parse_error),
        ("fetch_and_parse_invalid_url", test_fetch_and_parse_invalid_url),
        ("detect_youtube", test_detect_youtube),
        ("parse_youtube", test_parse_youtube),
        ("youtube_round_trip", test_youtube_round_trip),
        ("youtube_srt_detect", test_youtube_srt_detect),
        ("detect_bilibili", test_detect_bilibili),
        ("parse_bilibili", test_parse_bilibili),
        ("bilibili_round_trip", test_bilibili_round_trip),
        ("youtube_not_bilibili", test_youtube_not_bilibili),
        ("bilibili_not_youtube", test_bilibili_not_youtube),
    ]
    for name, fn in tests:
        fn()
        print(f"PASS: {name}")
    print(f"\nAll {len(tests)} video importer tests passed!")

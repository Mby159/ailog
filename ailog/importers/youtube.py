"""
AILog YouTube Importer

Converts YouTube video subtitles/transcripts into AILog format.
Treats each video as a "session" and subtitle segments as "interactions".

This is a key differentiator for AILog — video content becomes
searchable AI interaction data.

Input formats:
  1. YouTube URL (auto-fetch subtitles via youtube-transcript-api)
  2. YouTube JSON transcript (from youtube-transcript-api or manual export)
  3. SRT subtitle file
  4. VTT subtitle file
  5. Plain text transcript

Expected JSON format (from youtube-transcript-api):
[
  {"text": "Hello everyone", "start": 0.0, "duration": 3.5},
  {"text": "Today we'll discuss AI", "start": 3.5, "duration": 4.0},
  ...
]

Or with video metadata:
{
  "video_id": "abc123",
  "title": "AI Explained",
  "channel": "Tech Channel",
  "published_at": "2026-04-20T00:00:00Z",
  "transcript": [
    {"text": "...", "start": 0.0, "duration": 3.5}
  ]
}
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from ailog.core.models import (
    AILogFile,
    AILogFileMetadata,
    Interaction,
    Message,
    SensitivityInfo,
    RiskLevel,
    Role,
    ContentType,
    Artifact,
    ArtifactType,
)
from ailog.importers.base import BaseImporter


# ── URL parsing ────────────────────────────────────────────────────────────────

_YOUTUBE_PATTERNS = [
    # Standard
    r"(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})",
    # Short
    r"(?:https?://)?(?:www\.)?youtu\.be/([a-zA-Z0-9_-]{11})",
    # Embed
    r"(?:https?://)?(?:www\.)?youtube\.com/embed/([a-zA-Z0-9_-]{11})",
    # Shorts
    r"(?:https?://)?(?:www\.)?youtube\.com/shorts/([a-zA-Z0-9_-]{11})",
    # /live/
    r"(?:https?://)?(?:www\.)?youtube\.com/live/([a-zA-Z0-9_-]{11})",
]


def extract_video_id(url_or_id: str) -> Optional[str]:
    """Extract video ID from a YouTube URL or bare video ID."""
    url = url_or_id.strip()
    for pattern in _YOUTUBE_PATTERNS:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    # Maybe it's already a bare ID
    if re.match(r"^[a-zA-Z0-9_-]{11}$", url):
        return url
    return None


# ── Transcript fetching ───────────────────────────────────────────────────────

def _fetch_transcript(video_id: str) -> Dict[str, Any]:
    """
    Auto-fetch transcript from YouTube video using youtube-transcript-api.
    Returns dict with video metadata + transcript segments.

    Raises:
        ImportError: if youtube-transcript-api not installed
        Exception: if transcript unavailable
    """
    try:
        from youtube_transcript_api import (
            YouTubeTranscriptApi,
            TranscriptsDisabled,
            NoTranscriptFound,
        )
    except ImportError:
        raise ImportError(
            "youtube-transcript-api not installed. "
            "Run: pip install youtube-transcript-api"
        )

    try:
        # Try to get manually-created transcripts first, then auto-generated
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        # Prefer manually-created transcripts (usually higher quality)
        transcript = None
        try:
            transcript = transcript_list.find_manually_created_transcript(['en'])
        except Exception:
            pass

        if transcript is None:
            try:
                transcript = transcript_list.find_generated_transcript(['en'])
            except Exception:
                pass

        # Fallback: any available transcript
        if transcript is None:
            all_transcripts = list(transcript_list)
            if all_transcripts:
                transcript = all_transcripts[0]
            else:
                raise Exception(f"No transcripts available for video {video_id}")

        # Fetch transcript data
        transcript_data = transcript.fetch()

        # Get video metadata
        try:
            video_title = transcript.video_title
        except Exception:
            video_title = f"YouTube Video {video_id}"

        try:
            video_channel = transcript.channel_id or ""
        except Exception:
            video_channel = ""

        # Determine language
        lang = transcript.language_code or "en"
        is_generated = transcript.is_generated

        return {
            "video_id": video_id,
            "title": video_title,
            "channel": video_channel,
            "language": lang,
            "is_generated": is_generated,
            "transcript": [
                {"text": seg.text, "start": seg.start, "duration": seg.duration}
                for seg in transcript_data
            ],
        }

    except (TranscriptsDisabled, NoTranscriptFound) as e:
        raise Exception(f"Transcripts disabled or not found for {video_id}: {e}")
    except Exception as e:
        raise Exception(f"Failed to fetch transcript for {video_id}: {e}")


# ── Subtitle file parsers ─────────────────────────────────────────────────────

def _parse_srt(srt_content: str) -> List[Dict[str, Any]]:
    """Parse SRT subtitle format into segment list."""
    segments = []
    blocks = re.split(r"\n\s*\n", srt_content.strip())
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        text = " ".join(lines[2:])
        segments.append({"text": text})
    return segments


def _parse_vtt(vtt_content: str) -> List[Dict[str, Any]]:
    """Parse WebVTT subtitle format into segment list."""
    segments = []
    blocks = re.split(r"\n\s*\n", vtt_content.strip())
    for block in blocks:
        lines = block.strip().split("\n")
        if not lines or "WEBVTT" in lines[0]:
            continue
        text_lines = []
        for line in lines:
            if "-->" in line:
                continue
            if line.strip().isdigit():
                continue
            text_lines.append(line)
        if text_lines:
            segments.append({"text": " ".join(text_lines)})
    return segments


def _group_segments_into_chunks(
    segments: List[Dict[str, Any]],
    chunk_size: int = 10,
) -> List[Dict[str, Any]]:
    """Group subtitle segments into chunks of ~chunk_size segments each."""
    chunks = []
    for i in range(0, len(segments), chunk_size):
        chunk_segments = segments[i : i + chunk_size]
        text = " ".join(s.get("text", "") for s in chunk_segments)
        start = chunk_segments[0].get("start", 0)
        duration = sum(s.get("duration", 0) for s in chunk_segments)
        chunks.append({
            "text": text,
            "start": start,
            "duration": duration,
            "segment_count": len(chunk_segments),
        })
    return chunks


# ── Video → Interactions ───────────────────────────────────────────────────────

def _parse_video(data: Dict[str, Any], video_idx: int) -> List[Interaction]:
    """Parse a single video's transcript into AILog Interactions."""
    video_id = data.get("video_id", f"yt_{video_idx}")
    title = data.get("title", f"YouTube Video {video_idx}")
    channel = data.get("channel", data.get("channel_name", ""))
    published_at = data.get("published_at", data.get("published", ""))
    language = data.get("language", "en")
    is_generated = data.get("is_generated", False)

    # Get transcript segments
    transcript = data.get("transcript", data.get("subtitles", []))
    if not transcript and "text" in data:
        paragraphs = [p.strip() for p in data["text"].split("\n\n") if p.strip()]
        transcript = [{"text": p} for p in paragraphs]

    if not transcript:
        return []

    # Group into chunks for manageable interaction sizes
    chunks = _group_segments_into_chunks(transcript, chunk_size=10)

    interactions = []
    for chunk_idx, chunk in enumerate(chunks):
        text = chunk["text"]
        start = chunk.get("start", 0)
        duration = chunk.get("duration", 0)

        minutes, seconds = divmod(int(start), 60)
        timestamp_str = f"{minutes:02d}:{seconds:02d}"

        msg = Message(
            role=Role.ASSISTANT,
            content=text,
            content_type=ContentType.TEXT,
            custom={
                "youtube_video_id": video_id,
                "youtube_timestamp": start,
                "youtube_duration": duration,
                "youtube_timestamp_display": timestamp_str,
            },
        )

        # Tags for generated vs manual transcript
        source_tag = "youtube-auto-transcript" if is_generated else "youtube-transcript"

        interaction = Interaction(
            id=f"ix_yt_{video_id}_{chunk_idx + 1}",
            timestamp=published_at or "",
            session_id=f"sess_yt_{video_id}",
            turn_index=chunk_idx + 1,
            messages=[msg],
            sensitivity=SensitivityInfo(
                max_risk_level=RiskLevel.LOW,
                detected_items=[],
                scanned_by="none",
            ),
            custom={
                "youtube_title": title,
                "youtube_channel": channel,
                "youtube_video_id": video_id,
                "youtube_timestamp": timestamp_str,
                "youtube_language": language,
                "youtube_auto_generated": is_generated,
            },
        )
        interactions.append(interaction)

    return interactions


# ── YouTubeImporter ─────────────────────────────────────────────────────────────

class YouTubeImporter(BaseImporter):
    """
    Import YouTube video transcripts into AILog format.

    Supports:
    - YouTube URL: auto-fetches transcript via youtube-transcript-api
    - JSON file: raw transcript or metadata+transcript
    - SRT file: parsed into segments
    - VTT file: parsed into segments
    - Plain text: split into paragraphs
    """

    platform_id = "youtube"
    platform_url = "https://youtube.com"

    def detect(self, source_path: str | Path) -> bool:
        """Detect if source is a YouTube transcript/subtitle file."""
        source = Path(source_path).resolve()
        if not source.is_file():
            return False

        if source.suffix == ".srt":
            return True
        if source.suffix == ".vtt":
            return True

        if source.suffix != ".json":
            return False

        try:
            with open(source, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, dict):
                if "video_id" in data or "transcript" in data:
                    return True
                if "subtitles" in data:
                    return True
                return False

            if isinstance(data, list) and len(data) > 0:
                first = data[0]
                if isinstance(first, dict):
                    has_transcript_fields = (
                        "text" in first and ("start" in first or "duration" in first)
                    )
                    return has_transcript_fields
                return False

            return False
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False

    @staticmethod
    def is_youtube_url(source: str) -> bool:
        """Check if source looks like a YouTube URL."""
        return extract_video_id(source) is not None

    def parse(self, source_path: str | Path) -> AILogFile:
        """Parse YouTube transcript into ALogFile."""
        source = Path(source_path).resolve()

        if source.suffix == ".srt":
            return self._parse_srt_file(source)
        if source.suffix == ".vtt":
            return self._parse_vtt_file(source)

        with open(source, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            if len(data) > 0 and isinstance(data[0], dict):
                first = data[0]
                if "transcript" in first or "subtitles" in first or "video_id" in first:
                    return self._parse_multiple_videos(data)
                elif "text" in first and ("start" in first or "duration" in first):
                    return self._parse_single_transcript(data, source.stem)
            return self._parse_single_transcript(data, source.stem)

        if isinstance(data, dict):
            return self._parse_single_video(data)

        return self._build_empty()

    def fetch_and_parse(self, url_or_id: str) -> AILogFile:
        """
        Fetch transcript from YouTube URL/video ID and parse into AILog.

        This is the main auto-transcript feature: pass a YouTube URL,
        get back a fully structured AILogFile.

        Args:
            url_or_id: YouTube video URL or bare video ID

        Returns:
            AILogFile with all interactions parsed from the transcript

        Raises:
            Exception: if video not found or transcripts unavailable
        """
        video_id = extract_video_id(url_or_id)
        if not video_id:
            raise ValueError(f"Could not extract video ID from: {url_or_id}")

        print(f"Fetching transcript for video: {video_id}")
        data = _fetch_transcript(video_id)
        print(f"Got {len(data.get('transcript', []))} transcript segments")
        print(f"Title: {data.get('title', 'Unknown')}")

        # Track if auto-generated
        is_gen = data.get("is_generated", False)
        lang = data.get("language", "en")
        if is_gen:
            print(f"Note: Using auto-generated transcript ({lang})")
        else:
            print(f"Note: Using manually-created transcript ({lang})")

        interactions = _parse_video(data, 0)
        source_tag = "youtube-auto-transcript" if is_gen else "youtube-transcript"

        return self._build_ailog(interactions, [source_tag, f"lang:{lang}"])

    def _parse_single_video(self, data: Dict[str, Any]) -> AILogFile:
        """Parse a single video with metadata."""
        interactions = _parse_video(data, 0)
        return self._build_ailog(interactions, data.get("tags", ["youtube-transcript"]))

    def _parse_multiple_videos(self, videos: List[Dict[str, Any]]) -> AILogFile:
        """Parse multiple videos."""
        all_interactions = []
        for idx, video in enumerate(videos):
            interactions = _parse_video(video, idx)
            all_interactions.extend(interactions)
        return self._build_ailog(all_interactions, ["youtube-transcript"])

    def _parse_single_transcript(
        self, segments: List[Dict[str, Any]], title: str
    ) -> AILogFile:
        """Parse raw transcript segments as a single video."""
        video_data = {"title": title, "transcript": segments}
        interactions = _parse_video(video_data, 0)
        return self._build_ailog(interactions, ["youtube-transcript"])

    def _parse_srt_file(self, source: Path) -> AILogFile:
        """Parse SRT subtitle file."""
        content = source.read_text(encoding="utf-8", errors="ignore")
        segments = _parse_srt(content)
        video_data = {"title": source.stem, "transcript": segments}
        interactions = _parse_video(video_data, 0)
        return self._build_ailog(interactions, ["youtube-transcript", "srt"])

    def _parse_vtt_file(self, source: Path) -> AILogFile:
        """Parse WebVTT subtitle file."""
        content = source.read_text(encoding="utf-8", errors="ignore")
        segments = _parse_vtt(content)
        video_data = {"title": source.stem, "transcript": segments}
        interactions = _parse_video(video_data, 0)
        return self._build_ailog(interactions, ["youtube-transcript", "vtt"])

    def _build_ailog(
        self, interactions: List[Interaction], tags: List[str]
    ) -> AILogFile:
        """Build ALogFile from interactions."""
        metadata = self._build_metadata(
            tags=tags,
            custom={
                "source_videos_count": len(
                    set(ix.session_id for ix in interactions)
                ),
                "source_interactions_count": len(interactions),
            },
        )
        return AILogFile(
            ailog_version="0.1",
            metadata=metadata,
            interactions=interactions,
        )

    def _build_empty(self) -> AILogFile:
        """Build empty ALogFile."""
        return self._build_ailog([], ["youtube-transcript"])


# ── CLI fetch helper ──────────────────────────────────────────────────────────

def fetch_youtube(url_or_id: str, output: Optional[str] = None) -> str:
    """
    One-shot CLI helper: fetch YouTube transcript and save as .ailog.

    Args:
        url_or_id: YouTube video URL or bare video ID
        output: Output file path (default: <video_id>.ailog)

    Returns:
        Path to saved .ailog file
    """
    importer = YouTubeImporter()
    ailog = importer.fetch_and_parse(url_or_id)

    video_id = extract_video_id(url_or_id)
    out_path = Path(output) if output else Path(f"yt_{video_id}.ailog")

    out_fmt = "jsonl" if out_path.suffix == ".ailog" else "json"
    ailog.save(str(out_path), fmt=out_fmt)
    return str(out_path)

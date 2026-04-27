"""
AILog YouTube Importer

Converts YouTube video subtitles/transcripts into AILog format.
Treats each video as a "session" and subtitle segments as "interactions".

This is a key differentiator for AILog — video content becomes
searchable AI interaction data.

Input formats:
  1. YouTube JSON transcript (from youtube-transcript-api or manual export)
  2. SRT subtitle file
  3. Plain text transcript

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
from typing import Any, Dict, List, Optional

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


def _parse_srt(srt_content: str) -> List[Dict[str, Any]]:
    """Parse SRT subtitle format into segment list."""
    segments = []
    blocks = re.split(r"\n\s*\n", srt_content.strip())
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        # Skip sequence number (line 0), parse timestamp (line 1)
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
        # Find timestamp line
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


def _parse_video(data: Dict[str, Any], video_idx: int) -> List[Interaction]:
    """Parse a single video's transcript into AILog Interactions."""
    video_id = data.get("video_id", f"yt_{video_idx}")
    title = data.get("title", f"YouTube Video {video_idx}")
    channel = data.get("channel", data.get("channel_name", ""))
    published_at = data.get("published_at", data.get("published", ""))

    # Get transcript segments
    transcript = data.get("transcript", data.get("subtitles", []))
    if not transcript and "text" in data:
        # Single text block — split into paragraphs
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

        # Format timestamp for display
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
            },
        )
        interactions.append(interaction)

    return interactions


class YouTubeImporter(BaseImporter):
    """Import YouTube video transcripts into AILog format."""

    platform_id = "youtube"
    platform_url = "https://youtube.com"

    def detect(self, source_path: str | Path) -> bool:
        """Detect if source is a YouTube transcript/subtitle file."""
        source = Path(source_path).resolve()
        if not source.is_file():
            return False

        # Check by extension
        if source.suffix == ".srt":
            return True
        if source.suffix == ".vtt":
            return True

        if source.suffix != ".json":
            return False

        try:
            with open(source, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Single video with metadata
            if isinstance(data, dict):
                if "video_id" in data or "transcript" in data:
                    return True
                if "subtitles" in data:
                    return True
                return False

            # Array of segments (raw transcript)
            if isinstance(data, list) and len(data) > 0:
                first = data[0]
                if isinstance(first, dict):
                    # Raw transcript: has "text" + "start" + "duration"
                    has_transcript_fields = (
                        "text" in first and ("start" in first or "duration" in first)
                    )
                    return has_transcript_fields
                return False

            return False
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False

    def parse(self, source_path: str | Path) -> AILogFile:
        """Parse YouTube transcript into ALogFile."""
        source = Path(source_path).resolve()

        if source.suffix == ".srt":
            return self._parse_srt_file(source)
        if source.suffix == ".vtt":
            return self._parse_vtt_file(source)

        # JSON format
        with open(source, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            # Could be: array of videos, or raw transcript segments
            if len(data) > 0 and isinstance(data[0], dict):
                first = data[0]
                if "transcript" in first or "subtitles" in first or "video_id" in first:
                    # Array of videos
                    return self._parse_multiple_videos(data)
                elif "text" in first and ("start" in first or "duration" in first):
                    # Raw transcript segments — treat as single video
                    return self._parse_single_transcript(data, source.stem)
            # Fallback
            return self._parse_single_transcript(data, source.stem)

        if isinstance(data, dict):
            # Single video with metadata
            return self._parse_single_video(data)

        return self._build_empty()

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

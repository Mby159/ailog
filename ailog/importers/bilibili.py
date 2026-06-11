"""
AILog Bilibili Importer

Converts Bilibili video subtitles into AILog format.

Input formats:
  1. Bilibili JSON subtitle (from API or browser extension)
  2. SRT file (same as YouTube, shares parser)

Bilibili subtitle JSON format:
{
  "bvid": "BV1xx...",
  "title": "视频标题",
  "uploader": "UP主",
  "published_at": "2026-04-20T00:00:00Z",
  "subtitles": [
    {"content": "大家好", "from": 0.0, "to": 3.5},
    {"content": "今天讨论AI", "from": 3.5, "to": 7.0}
  ]
}

Or raw subtitle list:
[
  {"content": "...", "from": 0.0, "to": 3.5}
]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from ailog.core.models import (
    AILogFile,
    AILogFileMetadata,
    Interaction,
    Message,
    SensitivityInfo,
    RiskLevel,
    Role,
    ContentType,
)
from ailog.importers.base import BaseImporter
from ailog.importers.youtube import _group_segments_into_chunks


def _normalize_segments(subtitles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize Bilibili subtitle format to common segment format."""
    segments = []
    for sub in subtitles:
        text = sub.get("content", sub.get("text", ""))
        start = sub.get("from", sub.get("start", 0))
        duration = sub.get("to", start + 5) - start
        segments.append({"text": text, "start": start, "duration": max(duration, 0)})
    return segments


def _parse_video(data: Dict[str, Any], video_idx: int) -> List[Interaction]:
    """Parse a single Bilibili video."""
    bvid = data.get("bvid", f"bili_{video_idx}")
    title = data.get("title", f"Bilibili Video {video_idx}")
    uploader = data.get("uploader", data.get("author", ""))
    published_at = data.get("published_at", data.get("created", ""))

    subtitles = data.get("subtitles", data.get("subtitle", []))
    if not subtitles:
        return []

    segments = _normalize_segments(subtitles)
    chunks = _group_segments_into_chunks(segments, chunk_size=10)

    interactions = []
    for chunk_idx, chunk in enumerate(chunks):
        text = chunk["text"]
        start = chunk.get("start", 0)
        minutes, seconds = divmod(int(start), 60)
        timestamp_str = f"{minutes:02d}:{seconds:02d}"

        msg = Message(
            role=Role.ASSISTANT,
            content=text,
            content_type=ContentType.TEXT,
            custom={
                "bilibili_bvid": bvid,
                "bilibili_timestamp": start,
                "bilibili_timestamp_display": timestamp_str,
            },
        )

        interaction = Interaction(
            id=f"ix_bili_{bvid}_{chunk_idx + 1}",
            timestamp=published_at or "",
            session_id=f"sess_bili_{bvid}",
            turn_index=chunk_idx + 1,
            messages=[msg],
            sensitivity=SensitivityInfo(
                max_risk_level=RiskLevel.LOW,
                detected_items=[],
                scanned_by="none",
            ),
            custom={
                "bilibili_title": title,
                "bilibili_uploader": uploader,
                "bilibili_bvid": bvid,
                "bilibili_timestamp": timestamp_str,
            },
        )
        interactions.append(interaction)

    return interactions


class BilibiliImporter(BaseImporter):
    """Import Bilibili video subtitles into AILog format."""

    platform_id = "bilibili"
    platform_url = "https://bilibili.com"

    def detect(self, source_path: str | Path) -> bool:
        """Detect if source is a Bilibili subtitle file."""
        source = Path(source_path).resolve()
        if not source.is_file() or source.suffix != ".json":
            return False
        try:
            with open(source, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, dict):
                # Bilibili-specific: bvid field
                if "bvid" in data:
                    return True
                # Has subtitles with "content"/"from"/"to" (Bilibili format)
                subs = data.get("subtitles", data.get("subtitle", []))
                if subs and isinstance(subs, list) and len(subs) > 0:
                    first = subs[0]
                    if "content" in first and ("from" in first or "to" in first):
                        return True
                return False

            if isinstance(data, list) and len(data) > 0:
                first = data[0]
                if isinstance(first, dict) and "content" in first:
                    return True
                return False

            return False
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False

    def parse(self, source_path: str | Path) -> AILogFile:
        """Parse Bilibili subtitles into ALogFile."""
        source = Path(source_path).resolve()
        with open(source, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            # Could be raw subtitle list or list of videos
            if len(data) > 0 and isinstance(data[0], dict):
                first = data[0]
                if "bvid" in first or "subtitles" in first:
                    # List of videos
                    all_interactions = []
                    for idx, video in enumerate(data):
                        interactions = _parse_video(video, idx)
                        all_interactions.extend(interactions)
                    return self._build_result(all_interactions)
                elif "content" in first:
                    # Raw subtitle segments
                    video_data = {"title": source.stem, "subtitles": data}
                    interactions = _parse_video(video_data, 0)
                    return self._build_result(interactions)

        if isinstance(data, dict):
            interactions = _parse_video(data, 0)
            return self._build_result(interactions)

        return self._build_result([])

    def _build_result(self, interactions: List[Interaction]) -> AILogFile:
        metadata = self._build_metadata(
            tags=["bilibili-subtitle"],
            custom={
                "source_videos_count": len(
                    set(ix.session_id for ix in interactions)
                ),
            },
        )
        return AILogFile(
            ailog_version="0.1",
            metadata=metadata,
            interactions=interactions,
        )

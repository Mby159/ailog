"""
AILog Incremental Sync — Watch & incremental import for AI conversation directories.

Core concept:
  - Track "known node IDs" per source file in a .ailog.state.json sidecar
  - On re-import, diff against current source to find only NEW nodes
  - Return only the new interactions, leaving the base .ailog untouched
  - For CLI: merge new interactions into the existing .ailog, update state

Supported importers: chatgpt, claude, deepseek, gemini, youtube, bilibili, generic_json
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── local import to avoid circular deps ──────────────────────────────────────
from ailog.core.models import AILogFile


# ── State file format ─────────────────────────────────────────────────────────

@dataclass
class SourceState:
    """Per-source tracking: which node IDs we've already imported."""
    source_path: str
    platform: str
    last_import_ts: str            # ISO 8601
    known_node_ids: list[str]      # all node IDs seen so far
    known_interaction_ids: list[str]
    total_imported: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SourceState":
        return cls(**data)


@dataclass
class SyncState:
    """Root sync state: collection of per-source SourceState entries."""
    version: str = "1"
    last_sync_ts: str = ""
    sources: dict[str, SourceState] = field(default_factory=dict)

    def source(self, source_path: str) -> SourceState | None:
        return self.sources.get(source_path)

    def set_source(self, source_path: str, state: SourceState) -> None:
        self.sources[source_path] = state

    @classmethod
    def load(cls, path: Path) -> "SyncState":
        if not path.exists():
            return cls()
        try:
            with path.open(encoding="utf-8") as f:
                raw = json.load(f)
            sources = {k: SourceState.from_dict(v) for k, v in raw.get("sources", {}).items()}
            return cls(
                version=raw.get("version", "1"),
                last_sync_ts=raw.get("last_sync_ts", ""),
                sources=sources,
            )
        except (json.JSONDecodeError, TypeError, KeyError):
            return cls()

    def save(self, path: Path) -> None:
        raw = {
            "version": self.version,
            "last_sync_ts": self.last_sync_ts,
            "sources": {k: v.to_dict() for k, v in self.sources.items()},
        }
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Incremental import ────────────────────────────────────────────────────────

def _get_importer_for_platform(platform: str):
    """Lazy-load importer by platform name."""
    if platform == "chatgpt":
        from ailog.importers.chatgpt import ChatGPTImporter
        return ChatGPTImporter()
    elif platform == "claude":
        from ailog.importers.claude import ClaudeImporter
        return ClaudeImporter()
    elif platform == "deepseek":
        from ailog.importers.deepseek import DeepSeekImporter
        return DeepSeekImporter()
    elif platform == "gemini":
        from ailog.importers.gemini import GeminiImporter
        return GeminiImporter()
    elif platform == "youtube":
        from ailog.importers.youtube import YouTubeImporter
        return YouTubeImporter()
    elif platform == "bilibili":
        from ailog.importers.bilibili import BilibiliImporter
        return BilibiliImporter()
    elif platform == "generic_json":
        from ailog.importers.generic_json import GenericJSONImporter
        return GenericJSONImporter()
    else:
        raise ValueError(f"Unknown platform: {platform}")


def _collect_node_ids(ailog: AILogFile) -> tuple[list[str], list[str]]:
    """
    Extract all node/interaction IDs from an AILogFile.
    node_id = interaction id (session-scoped)
    """
    node_ids = []
    interaction_ids = []
    for ix in ailog.interactions:
        node_ids.append(ix.id)
        interaction_ids.append(ix.id)
    return node_ids, interaction_ids


def _reparse_and_diff(
    source_path: Path,
    platform: str,
    known_node_ids: set[str],
) -> AILogFile:
    """
    Re-parse the source file and return ONLY new interactions whose IDs
    are not in known_node_ids.
    """
    importer = _get_importer_for_platform(platform)
    full_ailog = importer.parse(source_path)

    new_interactions = [
        ix for ix in full_ailog.interactions
        if ix.id not in known_node_ids
    ]

    if not new_interactions:
        return AILogFile(interactions=[], metadata=full_ailog.metadata)

    # Build a new AILogFile with only the new interactions
    result = AILogFile(
        interactions=new_interactions,
        metadata=full_ailog.metadata,
    )
    return result


# ── Public API ───────────────────────────────────────────────────────────────

@dataclass
class SyncResult:
    """Result of a sync operation."""
    source_path: str
    platform: str
    status: str              # "new" | "updated" | "unchanged" | "error"
    new_count: int = 0
    total_count: int = 0
    error_message: str = ""

    def changed(self) -> bool:
        return self.status in ("new", "updated")


def sync(
    source_path: Path,
    state_path: Path,
    platform: str,
    auto_import: bool = False,
    base_ailog_path: Path | None = None,
) -> SyncResult:
    """
    Incremental sync for one source file.

    Args:
        source_path:  Path to the raw export (e.g. conversations.json)
        state_path:   Path to the .ailog.state.json sidecar
        platform:     Platform ID (chatgpt, claude, etc.)
        auto_import:  If True, merge new interactions into base_ailog_path
        base_ailog_path: Path to existing .ailog to merge into

    Returns:
        SyncResult describing what happened
    """
    source_str = str(source_path.resolve())

    # Load existing state
    state = SyncState.load(state_path)
    prev = state.source(source_str)

    if prev is None:
        # First time: full import
        try:
            importer = _get_importer_for_platform(platform)
            ailog = importer.parse(source_path)
            node_ids, interaction_ids = _collect_node_ids(ailog)
            total = len(ailog.interactions)
        except Exception as e:
            return SyncResult(
                source_path=source_str,
                platform=platform,
                status="error",
                error_message=str(e),
            )

        # Save full import to .ailog
        if auto_import and base_ailog_path:
            ailog.save(str(base_ailog_path))

        # Record state
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        new_state = SourceState(
            source_path=source_str,
            platform=platform,
            last_import_ts=now,
            known_node_ids=node_ids,
            known_interaction_ids=interaction_ids,
            total_imported=total,
        )
        state.set_source(source_str, new_state)
        state.last_sync_ts = now
        state.save(state_path)

        return SyncResult(
            source_path=source_str,
            platform=platform,
            status="new",
            new_count=total,
            total_count=total,
        )

    # Subsequent: diff
    known_set = set(prev.known_node_ids)
    try:
        new_ailog = _reparse_and_diff(source_path, platform, known_set)
    except Exception as e:
        return SyncResult(
            source_path=source_str,
            platform=platform,
            status="error",
            error_message=str(e),
        )

    new_count = len(new_ailog.interactions)
    if new_count == 0:
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        prev.last_import_ts = now
        state.last_sync_ts = now
        state.save(state_path)
        return SyncResult(
            source_path=source_str,
            platform=platform,
            status="unchanged",
            total_count=prev.total_imported,
        )

    # Merge into base
    if auto_import and base_ailog_path:
        if base_ailog_path.exists():
            base = AILogFile.load(base_ailog_path)
            # Reload from source to get full picture for metadata
            full_ailog = _get_importer_for_platform(platform).parse(source_path)
            # Append new interactions, reassign turn_index
            start_turn = max((ix.turn_index for ix in base.interactions), default=-1) + 1
            for i, ix in enumerate(new_ailog.interactions):
                ix.turn_index = start_turn + i
            base.interactions.extend(new_ailog.interactions)
            base.metadata = full_ailog.metadata  # update to latest
            base.save(str(base_ailog_path))
        else:
            new_ailog.save(str(base_ailog_path))

    # Update state
    full_node_ids, full_interaction_ids = _collect_node_ids(
        _get_importer_for_platform(platform).parse(source_path)
    )
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    new_state = SourceState(
        source_path=source_str,
        platform=platform,
        last_import_ts=now,
        known_node_ids=full_node_ids,
        known_interaction_ids=full_interaction_ids,
        total_imported=prev.total_imported + new_count,
    )
    state.set_source(source_str, new_state)
    state.last_sync_ts = now
    state.save(state_path)

    return SyncResult(
        source_path=source_str,
        platform=platform,
        status="updated",
        new_count=new_count,
        total_count=prev.total_imported + new_count,
    )


def sync_directory(
    directory: Path,
    state_dir: Path,
    platform: str,
    pattern: str = "*.json",
) -> list[SyncResult]:
    """
    Sync all files matching pattern in a directory.

    State is stored per-source as <source_stem>.ailog.state.json
    Merged .ailog is stored as <source_stem>.ailog
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for src in sorted(directory.glob(pattern)):
        state_path = state_dir / (src.stem + ".ailog.state.json")
        base_ailog = state_dir / (src.stem + ".ailog")
        result = sync(src, state_path, platform, auto_import=True, base_ailog_path=base_ailog)
        results.append(result)
    return results


# ── CLI helpers ───────────────────────────────────────────────────────────────

def print_sync_results(results: list[SyncResult]) -> None:
    for r in results:
        icon = {"new": "🆕", "updated": "🔄", "unchanged": "✅", "error": "❌"}[r.status]
        if r.status == "error":
            print(f"  {icon} {Path(r.source_path).name}: ERROR — {r.error_message}")
        elif r.status == "unchanged":
            print(f"  {icon} {Path(r.source_path).name}: 无更新")
        else:
            print(f"  {icon} {Path(r.source_path).name}: {r.new_count} 条新交互 (累计 {r.total_count})")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AILog Incremental Sync")
    sub = parser.add_subparsers(dest="cmd")

    p_sync = sub.add_parser("sync", help="Incremental sync a source file")
    p_sync.add_argument("source", help="Source file or directory")
    p_sync.add_argument("--platform", "-p", required=True,
                        choices=["chatgpt", "claude", "deepseek", "gemini", "youtube", "bilibili", "generic_json"],
                        help="Platform")
    p_sync.add_argument("--state", "-s", help="State file path (default: <source>.ailog.state.json)")
    p_sync.add_argument("--output", "-o", help="Output .ailog path (default: <source>.ailog)")

    p_watch = sub.add_parser("watch", help="Watch a directory for changes")
    p_watch.add_argument("directory", help="Directory to watch")
    p_watch.add_argument("--platform", "-p", required=True, choices=["chatgpt", "claude", "deepseek", "gemini", "youtube", "bilibili", "generic_json"])
    p_watch.add_argument("--state-dir", "-d", default=".", help="Directory for state + .ailog files")
    p_watch.add_argument("--pattern", default="*.json", help="File pattern to watch")
    p_watch.add_argument("--interval", type=int, default=60, help="Poll interval in seconds")

    args = parser.parse_args()

    if args.cmd == "sync":
        src = Path(args.source)
        state_p = Path(args.state) if args.state else src.with_suffix(".ailog.state.json")
        out_p = Path(args.output) if args.output else src.with_suffix(".ailog")

        result = sync(src, state_p, args.platform, auto_import=True, base_ailog_path=out_p)
        print_sync_results([result])

    elif args.cmd == "watch":
        import time
        from pathlib import Path as P
        src_dir = P(args.directory)
        state_dir = P(args.state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)

        print(f"Watching {src_dir} for changes (polling every {args.interval}s)...")
        seen = set()
        while True:
            try:
                results = sync_directory(src_dir, state_dir, args.platform, args.pattern)
                # Only report non-unchanged results
                changed = [r for r in results if r.changed()]
                if changed:
                    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 检测到更新:")
                    print_sync_results(changed)
                elif not seen:
                    print_sync_results(results)
                seen |= set(str(r.source_path) for r in results)
                time.sleep(args.interval)
            except KeyboardInterrupt:
                print("\nStopped.")
                break

    else:
        parser.print_help()

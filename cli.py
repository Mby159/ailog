"""
AILog CLI 鈥?Command-line tool for AI interaction log management.

Usage:
  python -m ailog.cli import <source> [--format auto|chatgpt|json] [--output out.ailog]
  python -m ailog.cli info <file.ailog>
  python -m ailog.cli scan <file.ailog> [--auto-redact]
  python -m ailog.cli convert <file.ailog> [--to json|jsonl]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from ailog.core.models import AILogFile


# 鈹€鈹€ Lazy importer loading 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

def _get_importer(format_name: str):
    """Get importer by format name."""
    if format_name == "chatgpt":
        from ailog.importers.chatgpt import ChatGPTImporter
        return ChatGPTImporter()
    elif format_name == "claude":
        from ailog.importers.claude import ClaudeImporter
        return ClaudeImporter()
    elif format_name == "deepseek":
        from ailog.importers.deepseek import DeepSeekImporter
        return DeepSeekImporter()
    elif format_name == "gemini":
        from ailog.importers.gemini import GeminiImporter
        return GeminiImporter()
    elif format_name == "youtube":
        from ailog.importers.youtube import YouTubeImporter
        return YouTubeImporter()
    elif format_name == "bilibili":
        from ailog.importers.bilibili import BilibiliImporter
        return BilibiliImporter()
    elif format_name == "notion":
        from ailog.importers.notion import NotionImporter
        return NotionImporter()
    elif format_name == "generic_json":
        from ailog.importers.generic_json import GenericJSONImporter
        return GenericJSONImporter()
    else:
        raise ValueError(f"Unknown format: {format_name}")


def _auto_detect_format(source_path: Path) -> str:
    """Auto-detect source format."""
    # Try specific platforms first (most constrained → least)
    try:
        from ailog.importers.chatgpt import ChatGPTImporter
        if ChatGPTImporter().detect(source_path):
            return "chatgpt"
    except Exception:
        pass
    try:
        from ailog.importers.gemini import GeminiImporter
        if GeminiImporter().detect(source_path):
            return "gemini"
    except Exception:
        pass
    try:
        from ailog.importers.deepseek import DeepSeekImporter
        if DeepSeekImporter().detect(source_path):
            return "deepseek"
    except Exception:
        pass
    try:
        from ailog.importers.claude import ClaudeImporter
        if ClaudeImporter().detect(source_path):
            return "claude"
    except Exception:
        pass
    try:
        from ailog.importers.youtube import YouTubeImporter
        if YouTubeImporter().detect(source_path):
            return "youtube"
    except Exception:
        pass
    try:
        from ailog.importers.bilibili import BilibiliImporter
        if BilibiliImporter().detect(source_path):
            return "bilibili"
    except Exception:
        pass
    try:
        from ailog.importers.notion import NotionImporter
        if NotionImporter().detect(source_path):
            return "notion"
    except Exception:
        pass
    return "generic_json"


# 鈹€鈹€ Commands 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

def cmd_import(args):
    """Import AI conversations into .ailog format."""
    source = Path(args.source)
    if not source.exists():
        print(f"Error: Source not found: {source}", file=sys.stderr)
        sys.exit(1)

    # Determine format
    fmt = args.format
    if fmt == "auto":
        fmt = _auto_detect_format(source)
        print(f"Auto-detected format: {fmt}")

    # Import
    importer = _get_importer(fmt)
    print(f"Importing from {source} using {fmt} importer...")
    ailog = importer.parse(source)
    print(f"Parsed {len(ailog.interactions)} interactions from {ailog.metadata.source_platform}")

    # Scan for privacy if requested
    if args.scan:
        from ailog.bridge.ghostguard import scan_ailog_file, get_scan_status
        status = get_scan_status()
        print(f"Privacy scanner: {status['primary']}")
        ailog = scan_ailog_file(ailog, strategy="placeholder", auto_redact=args.auto_redact)
        # Count sensitive interactions
        sensitive_count = sum(
            1 for ix in ailog.interactions
            if ix.sensitivity and ix.sensitivity.max_risk_level.value != "low"
        )
        print(f"Privacy scan: {sensitive_count} interactions contain sensitive info")

    # Determine output path
    output = args.output
    if output is None:
        output = source.stem + ".ailog"

    # Save
    out_fmt = "jsonl" if output.endswith(".ailog") else "json"
    ailog.save(output, fmt=out_fmt)
    print(f"Saved to {output} ({out_fmt} format)")


def cmd_info(args):
    """Show info about an .ailog file."""
    path = Path(args.file)
    if not path.exists():
        print(f"Error: File not found: {path}", file=sys.stderr)
        sys.exit(1)

    ailog = AILogFile.load(path)
    meta = ailog.metadata

    print(f"AILog Version: {ailog.ailog_version}")
    print(f"Platform: {meta.source_platform}")
    print(f"Exporter: {meta.exporter}")
    print(f"Export Time: {meta.export_timestamp}")
    if meta.source_url:
        print(f"Source URL: {meta.source_url}")
    if meta.tags:
        print(f"Tags: {', '.join(meta.tags)}")
    print(f"Interactions: {len(ailog.interactions)}")

    # Session breakdown
    sessions = {}
    for ix in ailog.interactions:
        sessions.setdefault(ix.session_id, []).append(ix)
    print(f"Sessions: {len(sessions)}")

    # Sensitivity summary
    sensitive = sum(
        1 for ix in ailog.interactions
        if ix.sensitivity and ix.sensitivity.max_risk_level.value != "low"
    )
    if sensitive > 0:
        print(f"Sensitive interactions: {sensitive}")
    # Artifact summary
    total_artifacts = sum(len(ix.artifacts) for ix in ailog.interactions)
    if total_artifacts > 0:
        print(f"Artifacts: {total_artifacts}")

    # Show first few session titles
    if args.verbose and sessions:
        print("\nSessions:")
        for sid, ixs in list(sessions.items())[:10]:
            title = ixs[0].custom.get("chatgpt_title", "") or ixs[0].custom.get("claude_title", "Untitled") if ixs[0].custom else "Untitled"
            print(f"  {title} ({len(ixs)} turns)")


def cmd_scan(args):
    """Scan an .ailog file for sensitive information."""
    path = Path(args.file)
    if not path.exists():
        print(f"Error: File not found: {path}", file=sys.stderr)
        sys.exit(1)

    from ailog.bridge.ghostguard import scan_ailog_file, get_scan_status
    status = get_scan_status()

    if status["primary"] == "none":
        print("Warning: No privacy scanner available.")
        print("Install GhostGuard: pip install ghostguard")
        print("Or install privacy-guard: pip install privacy-guard")
        sys.exit(1)

    print(f"Using scanner: {status['primary']}")
    ailog = AILogFile.load(path)
    ailog = scan_ailog_file(ailog, strategy="placeholder", auto_redact=args.auto_redact)

    # Report
    for ix in ailog.interactions:
        if ix.sensitivity and ix.sensitivity.detected_items:
            print(f"\nInteraction {ix.id} (turn {ix.turn_index}):")
            print(f"  Risk: {ix.sensitivity.max_risk_level.value}")
            for item in ix.sensitivity.detected_items:
                redacted = " [REDACTED]" if item.redacted else ""
                print(f"  - {item.info_type} ({item.risk_level.value}) at {item.field}{redacted}")

    # Save if output specified
    if args.output:
        ailog.save(args.output)
        print(f"\nSaved scanned result to {args.output}")


def cmd_convert(args):
    """Convert .ailog between JSONL and JSON formats."""
    path = Path(args.file)
    if not path.exists():
        print(f"Error: File not found: {path}", file=sys.stderr)
        sys.exit(1)

    ailog = AILogFile.load(path)
    to_fmt = args.to

    if to_fmt == "json":
        output = args.output or path.with_suffix(".ailog.json")
        ailog.save(output, fmt="json")
    elif to_fmt == "jsonl":
        output = args.output or path.with_suffix(".ailog")
        ailog.save(output, fmt="jsonl")
    else:
        print(f"Unknown target format: {to_fmt}", file=sys.stderr)
        sys.exit(1)

    print(f"Converted to {output} ({to_fmt} format)")


def cmd_sync(args):
    """Incremental sync AI conversations from a source file or directory."""
    from pathlib import Path
    from ailog.sync import sync, sync_directory, print_sync_results

    src = Path(args.source)
    platform = args.platform
    state_dir = Path(args.state_dir) if args.state_dir else src.parent

    if src.is_dir():
        print(f"Syncing directory: {src}")
        results = sync_directory(src, state_dir, platform, args.pattern)
        print_sync_results(results)
    else:
        if not src.exists():
            print(f"Error: Source not found: {src}", file=sys.stderr)
            sys.exit(1)
        state_p = Path(args.state) if args.state else src.with_suffix(".ailog.state.json")
        out_p = Path(args.output) if args.output else src.with_suffix(".ailog")
        print(f"Syncing: {src}")
        from ailog.sync import sync as _sync
        result = _sync(src, state_p, platform, auto_import=True, base_ailog_path=out_p)
        print_sync_results([result])


def cmd_notion_import(args):
    """Import conversations from Notion pages into .ailog format."""
    from ailog.importers.notion import NotionImporter

    notion_key = os.environ.get("NOTION_API_KEY")
    if not notion_key and not args.api_key:
        print("Error: NOTION_API_KEY env var not set, or pass --api-key.", file=sys.stderr)
        sys.exit(1)

    parent_page_id = args.parent_page_id or os.environ.get("NOTION_PARENT_PAGE_ID")
    if not parent_page_id:
        print(
            "Error: --parent-page-id required, or set NOTION_PARENT_PAGE_ID env var.",
            file=sys.stderr,
        )
        sys.exit(1)

    importer = NotionImporter(api_key=notion_key or args.api_key, parent_page_id=parent_page_id)
    ailog = importer.parse_from_api(parent_page_id)

    output = args.output or "notion_import.ailog"
    out_fmt = "jsonl" if output.endswith(".ailog") else "json"
    ailog.save(output, fmt=out_fmt)
    print(f"Imported {len(ailog.interactions)} interactions from Notion")
    print(f"Saved to {output} ({out_fmt} format)")


def cmd_export(args):
    """Export .ailog to other formats."""
    path = Path(args.file)
    if not path.exists():
        print(f"Error: File not found: {path}", file=sys.stderr)
        sys.exit(1)

    ailog = AILogFile.load(path)
    fmt = args.format

    if fmt == "obsidian":
        from ailog.exporters.obsidian import ObsidianExporter
        exporter = ObsidianExporter()
    elif fmt == "html":
        from ailog.exporters.html import HTMLExporter
        exporter = HTMLExporter()
    elif fmt == "pdf":
        from ailog.exporters.pdf import PDFExporter
        exporter = PDFExporter()
    elif fmt == "notion":
        from ailog.exporters.notion import NotionExporter
        notion_page_id = args.notion_page_id or os.environ.get("NOTION_PARENT_PAGE_ID")
        if not notion_page_id:
            print(
                "Error: --notion-page-id required for notion export, "
                "or set NOTION_PARENT_PAGE_ID env var.",
                file=sys.stderr,
            )
            sys.exit(1)
        notion_key = os.environ.get("NOTION_API_KEY")
        if not notion_key:
            print("Error: NOTION_API_KEY env var not set.", file=sys.stderr)
            sys.exit(1)
        exporter = NotionExporter(parent_page_id=notion_page_id, api_key=notion_key)
        page_ids = exporter.export(ailog)
        ids_str = ', '.join(page_ids)
        print(f"Created {len(page_ids)} Notion pages: {ids_str}")
        return
        print(f"Unknown export format: {fmt}", file=sys.stderr)
        sys.exit(1)

    output = args.output
    if output is None:
        if fmt == "obsidian":
            output = path.stem + "_obsidian"
        elif fmt == "html":
            output = path.stem + ".html"
        else:
            output = path.stem + "_export"

    result = exporter.export(ailog, output)
    if result.is_dir():
        print(f"Exported to {result}/ (directory)")
    else:
        print(f"Exported to {result}")


# 鈹€鈹€ Main 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

def main():
    parser = argparse.ArgumentParser(
        prog="ailog",
        description="AILog 鈥?AI interaction log management tool",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # import
    p_import = sub.add_parser("import", help="Import AI conversations into .ailog format")
    p_import.add_argument("source", help="Source file/directory (ChatGPT export, zip, json)")
    p_import.add_argument("--format", default="auto", choices=["auto", "chatgpt", "claude", "deepseek", "gemini", "youtube", "bilibili", "notion", "generic_json"], help="Source format (default: auto-detect)")
    p_import.add_argument("--output", "-o", help="Output file path (default: <source>.ailog)")
    p_import.add_argument("--scan", action="store_true", help="Scan for sensitive information after import")
    p_import.add_argument("--auto-redact", action="store_true", help="Auto-redact sensitive info during scan")
    p_import.set_defaults(func=cmd_import)

    # info
    p_info = sub.add_parser("info", help="Show info about an .ailog file")
    p_info.add_argument("file", help=".ailog file path")
    p_info.add_argument("--verbose", "-v", action="store_true", help="Show session details")
    p_info.set_defaults(func=cmd_info)

    # scan
    p_scan = sub.add_parser("scan", help="Scan .ailog file for sensitive information")
    p_scan.add_argument("file", help=".ailog file path")
    p_scan.add_argument("--output", "-o", help="Save scanned result to new file")
    p_scan.add_argument("--auto-redact", action="store_true", help="Auto-redact sensitive info")
    p_scan.set_defaults(func=cmd_scan)

    # convert
    p_convert = sub.add_parser("convert", help="Convert between .ailog formats")
    p_convert.add_argument("file", help=".ailog file path")
    p_convert.add_argument("--to", default="json", choices=["json", "jsonl"], help="Target format")
    p_convert.add_argument("--output", "-o", help="Output file path")
    p_convert.set_defaults(func=cmd_convert)

    # export
    p_export = sub.add_parser("export", help="Export .ailog to other formats")
    p_export.add_argument("file", help=".ailog file path")
    p_export.add_argument("--format", default="html", choices=["obsidian", "html", "pdf", "notion"], help="Target format (default: html)")
    p_export.add_argument("--output", "-o", help="Output path (file or directory)")
    p_export.add_argument("--notion-page-id", help="Notion parent page ID (or set NOTION_PARENT_PAGE_ID env var)")
    p_export.set_defaults(func=cmd_export)

    # sync
    p_sync = sub.add_parser("sync", help="Incremental sync: import only NEW interactions")
    p_sync.add_argument("source", help="Source file (conversations.json) or directory")
    p_sync.add_argument("--platform", "-p", required=True,
                        choices=["chatgpt", "claude", "deepseek", "gemini", "youtube", "bilibili", "notion", "generic_json"],
                        help="Platform format")
    p_sync.add_argument("--state", "-s", help="State file path (default: <source>.ailog.state.json)")
    p_sync.add_argument("--output", "-o", help="Output .ailog path (default: <source>.ailog)")
    p_sync.add_argument("--state-dir", "-d", help="Directory for state files (for directory mode)")
    p_sync.add_argument("--pattern", default="*.json", help="File pattern for directory mode")
    p_sync.set_defaults(func=cmd_sync)

    # notion-import
    p_ni = sub.add_parser("notion-import", help="Import conversations from Notion API into .ailog format")
    p_ni.add_argument("--parent-page-id", help="Notion parent page ID (or set NOTION_PARENT_PAGE_ID env var)")
    p_ni.add_argument("--api-key", help="Notion API key (or set NOTION_API_KEY env var)")
    p_ni.add_argument("--output", "-o", help="Output .ailog file path (default: notion_import.ailog)")
    p_ni.set_defaults(func=cmd_notion_import)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()

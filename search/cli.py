"""
Search CLI subcommands for ailog search.

Usage:
  ailog search build [--ailog <path>] [--all] [--index-dir <dir>] [--force]
  ailog search query "<query>" [--top-k 5] [--index-dir <dir>]
  ailog search stats [--index-dir <dir>]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def cmd_search(args) -> None:
    """Dispatch search subcommands."""
    sub = args.search_subcommand

    if sub == "build":
        cmd_search_build(args)
    elif sub == "query":
        cmd_search_query(args)
    elif sub == "stats":
        cmd_search_stats(args)
    else:
        print(f"Unknown subcommand: {sub}", file=sys.stderr)
        sys.exit(1)


def cmd_search_build(args) -> None:
    """Build or update the search index."""
    from ailog.search.engine import IndexBuilder

    paths = [Path(p) for p in args.ailog] if args.ailog else []

    if args.all:
        cwd = Path.cwd()
        cwd_ailogs = list(cwd.glob("**/*.ailog")) + list(cwd.glob("**/*.ailog.json"))
        paths = cwd_ailogs
        print(f"Found {len(paths)} .ailog files in current directory", file=sys.stderr)

    if not paths:
        print(
            "Error: No .ailog files specified.\n"
            "  Use: ailog search build --ailog <path>\n"
            "  Or:  ailog search build --all (index all .ailog in current dir)",
            file=sys.stderr,
        )
        sys.exit(1)

    index_dir = Path(args.index_dir) if args.index_dir else Path.cwd() / ".ailog_search"
    builder = IndexBuilder(index_dir, paths)

    result = builder.build(
        ailog_paths=paths,
        batch_size=args.batch_size,
        force=args.force,
    )
    print(f"Build complete: {result.get('chunks', 0)} chunks indexed, {result.get('new', 0)} new")


def cmd_search_query(args) -> None:
    """Query the search index."""
    from ailog.search.engine import SearchEngine

    index_dir = Path(args.index_dir) if args.index_dir else Path.cwd() / ".ailog_search"
    engine = SearchEngine(index_dir)

    try:
        engine.load()
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        print("Run: ailog search build --ailog <your_file.ailog>", file=sys.stderr)
        sys.exit(1)

    results = engine.search(args.query, top_k=args.top_k)

    if not results:
        print(f"No results found for: \"{args.query}\"")
        return

    print(f"\n=== Top {len(results)} results for: \"{args.query}\" ===\n")
    for i, chunk in enumerate(results, 1):
        text_preview = chunk.text[:300].replace("\n", " ")
        if len(chunk.text) > 300:
            text_preview += "..."
        print(f"[{i}] Score: {chunk.similarity_score:.4f}")
        print(f"    Title:    {chunk.title or '(untitled)'}")
        print(f"    Role:     {chunk.role}  |  Platform: {chunk.platform}")
        print(f"    Session:  {chunk.session_id[:20]}...")
        print(f"    Text:     {text_preview}")
        if chunk.url:
            print(f"    URL:      {chunk.url}")
        print()


def cmd_search_stats(args) -> None:
    """Show index statistics."""
    from ailog.search.engine import SearchEngine

    index_dir = Path(args.index_dir) if args.index_dir else Path.cwd() / ".ailog_search"
    engine = SearchEngine(index_dir)

    try:
        engine.load()
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    stats = engine.stats()
    print(f"Index statistics:")
    print(f"  Chunks:     {stats['chunk_count']}")
    print(f"  Backend:    {stats['backend']}")
    print(f"  Dimension:   {stats['dimension']}")
    print(f"  Index dir:  {index_dir}")


def add_search_parser(subparsers) -> None:
    """Add 'search' subcommand to the CLI argument parser."""
    p_search = subparsers.add_parser(
        "search", help="Semantic search across .ailog files"
    )
    sp = p_search.add_subparsers(dest="search_subcommand", help="Search subcommands")

    # search build
    p_build = sp.add_parser("build", help="Build/update the search index")
    p_build.add_argument(
        "--ailog", "-a", nargs="+", help=".ailog file(s) to index"
    )
    p_build.add_argument(
        "--all", action="store_true",
        help="Index all .ailog files in the current directory"
    )
    p_build.add_argument(
        "--index-dir", "-d", help="Index directory (default: ./.ailog_search)"
    )
    p_build.add_argument(
        "--batch-size", "-b", type=int, default=32,
        help="Embedding batch size (default: 32)"
    )
    p_build.add_argument(
        "--force", "-f", action="store_true",
        help="Force rebuild from scratch (ignore existing index)"
    )
    p_build.set_defaults(func=cmd_search)

    # search query
    p_query = sp.add_parser("query", help="Query the search index")
    p_query.add_argument("query", help="Natural language search query")
    p_query.add_argument(
        "--top-k", "-k", type=int, default=5,
        help="Number of results to return (default: 5)"
    )
    p_query.add_argument(
        "--index-dir", "-d", help="Index directory (default: ./.ailog_search)"
    )
    p_query.set_defaults(func=cmd_search)

    # search stats
    p_stats = sp.add_parser("stats", help="Show index statistics")
    p_stats.add_argument(
        "--index-dir", "-d", help="Index directory (default: ./.ailog_search)"
    )
    p_stats.set_defaults(func=cmd_search)
    p_search.set_defaults(func=cmd_search)

"""
AILog MCP Server 鈥?Expose .ailog files to MCP clients.

Tools provided:
  - ailog_import: Import AI conversations into .ailog format
  - ailog_search: Search interactions in .ailog files
  - ailog_info: Get info about an .ailog file
  - ailog_scan: Scan for sensitive information
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from mcp.server import Server
    from mcp.types import Tool, TextContent
    from mcp.server.stdio import stdio_server

    HAS_MCP = True
except ImportError:
    HAS_MCP = False

from ailog.core.models import AILogFile, Interaction
from ailog.importers.base import BaseImporter


def _get_importer(platform: str) -> Optional[BaseImporter]:
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
    return None


def _search_interactions(
    ailog: AILogFile, query: str, top_k: int = 10
) -> List[Dict[str, Any]]:
    """Search interactions by keyword in messages."""
    query_lower = query.lower()
    results = []
    for ix in ailog.interactions:
        score = 0
        matched_msgs = []
        for msg in ix.messages:
            if query_lower in msg.content.lower():
                score += msg.content.lower().count(query_lower)
                matched_msgs.append({
                    "role": msg.role.value,
                    "content": msg.content[:200],
                })
        # Also search artifacts
        for art in ix.artifacts:
            if art.content and query_lower in art.content.lower():
                score += 1
                matched_msgs.append({
                    "role": "artifact",
                    "content": f"[{art.type.value}] {art.name}: {art.content[:100]}",
                })
        if score > 0:
            results.append({
                "interaction_id": ix.id,
                "session_id": ix.session_id,
                "turn_index": ix.turn_index,
                "timestamp": ix.timestamp,
                "score": score,
                "matched_messages": matched_msgs[:3],
                "title": ix.custom.get("chatgpt_title", ""),
            })
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def _format_search_results(results: List[Dict[str, Any]]) -> str:
    """Format search results for display."""
    if not results:
        return "No matching interactions found."
    lines = []
    for r in results:
        title = r["title"] or r["session_id"]
        lines.append(f"## {title} (turn {r['turn_index']}, score: {r['score']})")
        lines.append(f"ID: {r['interaction_id']} | Time: {r['timestamp']}")
        for msg in r["matched_messages"]:
            lines.append(f"  [{msg['role']}] {msg['content']}")
        lines.append("")
    return "\n".join(lines)


async def run_mcp_server():
    if not HAS_MCP:
        print("Error: MCP not installed. Run: pip install mcp", file=sys.stderr)
        sys.exit(1)

    server = Server("ailog")

    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name="ailog_import",
                description="Import AI conversations into .ailog format. Supports ChatGPT exports.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "source_path": {
                            "type": "string",
                            "description": "Path to source file (ChatGPT conversations.json, zip, or directory)",
                        },
                        "platform": {
                            "type": "string",
                            "description": "Source platform: chatgpt (default: auto-detect)",
                            "default": "auto",
                        },
                        "output_path": {
                            "type": "string",
                            "description": "Output .ailog file path",
                        },
                        "scan_privacy": {
                            "type": "boolean",
                            "description": "Scan for sensitive info after import",
                            "default": False,
                        },
                    },
                    "required": ["source_path", "output_path"],
                },
            ),
            Tool(
                name="ailog_search",
                description="Search interactions in .ailog files by keyword",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "ailog_path": {
                            "type": "string",
                            "description": "Path to .ailog file",
                        },
                        "query": {
                            "type": "string",
                            "description": "Search query",
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Max results (default: 10)",
                            "default": 10,
                        },
                    },
                    "required": ["ailog_path", "query"],
                },
            ),
            Tool(
                name="ailog_info",
                description="Get info about an .ailog file",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "ailog_path": {
                            "type": "string",
                            "description": "Path to .ailog file",
                        },
                    },
                    "required": ["ailog_path"],
                },
            ),
            Tool(
                name="ailog_scan",
                description="Scan .ailog file for sensitive information using GhostGuard",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "ailog_path": {
                            "type": "string",
                            "description": "Path to .ailog file",
                        },
                        "auto_redact": {
                            "type": "boolean",
                            "description": "Auto-redact sensitive content",
                            "default": False,
                        },
                        "output_path": {
                            "type": "string",
                            "description": "Save scanned result to new file",
                        },
                    },
                    "required": ["ailog_path"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: Dict[str, Any]):
        if name == "ailog_import":
            source = Path(arguments["source_path"])
            output = Path(arguments["output_path"])
            platform = arguments.get("platform", "auto")

            # Auto-detect platform
            if platform == "auto":
                for p in ["chatgpt", "gemini", "deepseek", "claude"]:
                    imp = _get_importer(p)
                    if imp and imp.detect(source):
                        platform = p
                        break
                if platform == "auto":
                    return [TextContent(type="text", text=f"Could not auto-detect platform for {source}")]

            importer = _get_importer(platform)
            if not importer:
                return [TextContent(type="text", text=f"Unsupported platform: {platform}")]

            ailog = importer.parse(source)

            # Scan privacy if requested
            if arguments.get("scan_privacy"):
                from ailog.bridge.ghostguard import scan_ailog_file, get_scan_status
                status = get_scan_status()
                if status["primary"] != "none":
                    ailog = scan_ailog_file(ailog, auto_redact=False)

            ailog.save(output)
            info = (
                f"Imported {len(ailog.interactions)} interactions from {platform}\n"
                f"Sessions: {len(set(ix.session_id for ix in ailog.interactions))}\n"
                f"Saved to: {output}"
            )
            return [TextContent(type="text", text=info)]

        elif name == "ailog_search":
            ailog_path = Path(arguments["ailog_path"])
            query = arguments["query"]
            top_k = arguments.get("top_k", 10)

            ailog = AILogFile.load(ailog_path)
            results = _search_interactions(ailog, query, top_k)
            text = _format_search_results(results)
            return [TextContent(type="text", text=text)]

        elif name == "ailog_info":
            ailog_path = Path(arguments["ailog_path"])
            ailog = AILogFile.load(ailog_path)
            meta = ailog.metadata

            sessions = {}
            for ix in ailog.interactions:
                sessions.setdefault(ix.session_id, []).append(ix)

            sensitive = sum(
                1 for ix in ailog.interactions
                if ix.sensitivity and ix.sensitivity.max_risk_level.value != "low"
            )
            artifacts = sum(len(ix.artifacts) for ix in ailog.interactions)

            info = (
                f"AILog v{ailog.ailog_version}\n"
                f"Platform: {meta.source_platform}\n"
                f"Exporter: {meta.exporter}\n"
                f"Interactions: {len(ailog.interactions)}\n"
                f"Sessions: {len(sessions)}\n"
            )
            if sensitive:
                info += f"Sensitive interactions: {sensitive}\n"
            if artifacts:
                info += f"Artifacts: {artifacts}\n"
            if meta.tags:
                info += f"Tags: {', '.join(meta.tags)}\n"
            return [TextContent(type="text", text=info)]

        elif name == "ailog_scan":
            ailog_path = Path(arguments["ailog_path"])
            auto_redact = arguments.get("auto_redact", False)
            output_path = arguments.get("output_path")

            from ailog.bridge.ghostguard import scan_ailog_file, get_scan_status
            status = get_scan_status()
            if status["primary"] == "none":
                return [TextContent(type="text", text="No privacy scanner available. Install GhostGuard or privacy-guard.")]

            ailog = AILogFile.load(ailog_path)
            ailog = scan_ailog_file(ailog, auto_redact=auto_redact)

            results = []
            for ix in ailog.interactions:
                if ix.sensitivity and ix.sensitivity.detected_items:
                    items_str = ", ".join(
                        f"{it.info_type}({it.risk_level.value})" for it in ix.sensitivity.detected_items
                    )
                    results.append(f"  {ix.id} turn {ix.turn_index}: {items_str}")

            text = f"Scanned with {status['primary']}\n"
            if results:
                text += f"Found sensitive info in {len(results)} interactions:\n" + "\n".join(results)
            else:
                text += "No sensitive information detected."

            if output_path:
                ailog.save(output_path)
                text += f"\nSaved to: {output_path}"

            return [TextContent(type="text", text=text)]

        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main():
    """Entry point for MCP server."""
    if not HAS_MCP:
        print("MCP dependencies not installed. Run: pip install mcp", file=sys.stderr)
        sys.exit(1)
    import asyncio
    asyncio.run(run_mcp_server())


if __name__ == "__main__":
    main()

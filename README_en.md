# AILog

> AI Interaction Artifacts — Personal Data Sovereignty Protocol

**Platform-agnostic open format for AI conversation records** — Unify conversations from ChatGPT, Claude, Gemini, and more into a single open standard, so you truly own your AI interaction data.

> English | [中文](README_zh.md)

---

## Why AILog?

Your AI conversations are scattered across platforms: ChatGPT, Claude, Gemini, DeepSeek... Every platform is a data silo with its own export format. There's no unified way to search, analyze, or migrate them.

AILog defines an open format (`.ailog`) that makes all AI conversations:

- 🔍 **Unified Search** — Semantic search across all conversations with File Brain
- 🔒 **Privacy Annotation** — GhostGuard auto-detects sensitive info
- 📦 **Free Migration** — Import/export without platform lock-in
- 📝 **Knowledge Harvesting** — Export to Obsidian Markdown for knowledge management

## Quick Start

### Installation

```bash
# Clone the project
git clone https://github.com/Mby159/ailog.git
cd ailog

# Install as a package (recommended)
pip install -e .

# Or use directly without installation
python -m ailog.cli --help
```

### Import ChatGPT Conversations

```bash
# From conversations.json
python -m ailog.cli import conversations.json -o my-chats.ailog

# From ChatGPT-exported zip
python -m ailog.cli import chatgpt-export.zip -o my-chats.ailog

# Auto-detect format
python -m ailog.cli import data.json --format auto -o output.ailog
```

### Import Claude Conversations

```bash
python -m ailog.cli import claude-conversations.json -o claude-chats.ailog
```

### View File Info

```bash
python -m ailog.cli info my-chats.ailog -v
```

Output example:
```
AILog Version: 0.1
Platform: chatgpt
Interactions: 42
Sessions: 7

Sessions:
  Python Quick Sort (5 turns)
  API Key Question (3 turns)
  ...
```

### Privacy Scan

```bash
# Scan for sensitive information
python -m ailog.cli scan my-chats.ailog

# Auto-redact
python -m ailog.cli scan my-chats.ailog --auto-redact -o redacted.ailog
```

### Incremental Sync

```bash
# First sync: imports all
ailog sync conversations.json -p chatgpt -o synced.ailog

# Second sync: only imports new messages (skips already-imported ones)
ailog sync conversations.json -p chatgpt -o synced.ailog
```

### Format Conversion

```bash
# Export to Obsidian Markdown
python -m ailog.cli export my-chats.ailog --to obsidian -o ./obsidian-vault/

# Export to HTML (Claude-style, light/dark theme)
python -m ailog.cli export my-chats.ailog --to html -o my-chats.html

# Export to PDF
python -m ailog.cli export my-chats.ailog --to pdf -o my-chats.pdf

# JSONL → JSON
python -m ailog.cli convert my-chats.ailog --to json -o my-chats.json
```

## .ailog Format

`.ailog` uses JSONL format (one JSON object per line):

- **Line 1**: Metadata (source platform, export time, exporter version)
- **Line 2+**: Interaction records (one user+assistant turn per line)

### Core Fields (7 required)

| Field | Type | Description |
|-------|------|------------|
| `id` | string | Unique interaction ID |
| `timestamp` | ISO 8601 | Timestamp |
| `session_id` | string | Session ID |
| `turn_index` | integer | Turn number |
| `messages` | Message[] | Message list |
| `messages[].role` | string | user/assistant/system/tool |
| `messages[].content` | string | Message content |

### Full Specification

See [`spec/FORMAT.md`](spec/FORMAT.md)

### Example

```jsonl
{"ailog_version":"0.1","type":"metadata","metadata":{"source_platform":"chatgpt","export_timestamp":"2026-04-26T08:00:00Z","exporter":"ailog-importer-chatgpt/0.1.0"}}
{"ailog_version":"0.1","type":"interaction","id":"ix_01JABC123","timestamp":"2026-04-26T08:00:00Z","session_id":"sess_01JXYZ456","turn_index":1,"messages":[{"role":"user","content":"Write a Python quicksort for me"},{"role":"assistant","content":"```python\ndef quicksort(arr): ...\n```","model":"gpt-4o","model_provider":"openai"}],"artifacts":[{"id":"art_001","type":"code","name":"quicksort.py","language":"python"}],"sensitivity":{"max_risk_level":"low","detected_items":[]}}
```

## Supported Platforms

| Platform | Status | Import | Export |
|----------|--------|--------|--------|
| ChatGPT | ✅ Ready | conversations.json / zip | — |
| Claude | ✅ Ready | JSON conversation format | — |
| DeepSeek | ✅ Ready | JSON + R1 reasoning chain | — |
| Gemini | ✅ Ready | JSON (model role) | — |
| YouTube | ✅ Ready | JSON / SRT / VTT subtitles | — |
| Bilibili | ✅ Ready | JSON (content/from/to) | — |
| Generic JSON | ✅ Ready | messages array format | — |
| Notion | 🔜 Planned | — | .ailog → Notion |
| Obsidian | ✅ Ready | — | .ailog → Markdown |
| HTML | ✅ Ready | — | .ailog → Claude-style HTML |
| PDF | ✅ Ready | — | .ailog → PDF |

## Architecture

```
.ailog Open Format
    │
    ├── importers/         ← Platform → .ailog
    │   ├── chatgpt.py      ← ChatGPT (mapping tree traversal)
    │   ├── claude.py       ← Claude (human/assistant)
    │   ├── deepseek.py     ← DeepSeek (R1 reasoning chain)
    │   ├── gemini.py       ← Gemini (model role)
    │   ├── youtube.py      ← YouTube subtitles (JSON/SRT/VTT)
    │   ├── bilibili.py     ← Bilibili subtitles (content/from/to)
    │   └── generic_json.py ← Generic JSON fallback
    │
    ├── exporters/         ← .ailog → Platform
    │   ├── obsidian.py     ← Markdown + YAML frontmatter
    │   ├── html.py         ← Claude-style HTML (light/dark)
    │   ├── pdf.py          ← Print-ready PDF
    │   └── notion.py       ← Notion pages (async)
    │
    ├── bridge/            ← Tool integrations
    │   ├── ghostguard.py   ← Privacy scanning
    │   └── filebrain.py    ← Semantic search + Markdown export
    │
    ├── sync.py            ← Incremental sync (delta import)
    │
    ├── core/              ← Data models
    │   └── models.py
    │
    ├── cli.py             ← CLI (5 subcommands)
    └── mcp_server.py       ← MCP server (4 tools)
```

## Design Principles

1. **Minimal Format** — 7 required fields, parser in 5 minutes
2. **Annotation, Not Encryption** — Privacy at format level; GhostGuard handles redaction
3. **Artifacts Are First-Class** — Code/images generated by AI are not second-class citizens
4. **JSONL-First** — Streamable, appendable, friendly for large files
5. **custom for Extensions** — Platform-specific fields don't crowd the core

## Related Projects

| Project | Role |
|---------|------|
| [GhostGuard](https://github.com/Mby159/ghostguard) | Privacy scanning engine |
| [privacy-guard](https://github.com/Mby159/privacy-guard) | Lightweight privacy engine |
| [privacy-proxy](https://github.com/Mby159/privacy-proxy) | OpenAI-compatible privacy proxy |
| [SplitMind](https://github.com/Mby159/splitmind) | Multi-AI task orchestration |
| [File Brain](https://github.com/Mby159/file-brain) | Local file semantic search |

## Run Tests

```bash
python -m pytest ailog/tests/ -v
```

## License

MIT

---

> **Three Laws of Digital Cognitive Sovereignty**:
> 1. **Readability** — Users have the right to read all their AI interaction records
> 2. **Portability** — Users have the right to migrate records to any platform
> 3. **Controllability** — Users have the right to control who can access what data

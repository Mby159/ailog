"""
AILog HTML Exporter - Claude Style
纵向流水布局，暖灰奶白色系，无外部依赖
"""

from __future__ import annotations
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List
from ailog.core.models import AILogFile, Interaction, Message, Role, ContentType, RiskLevel, ArtifactType
from ailog.exporters.base import BaseExporter


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _get_title(ix: Interaction) -> str:
    return (ix.custom.get("chatgpt_title") or ix.custom.get("claude_title") 
            or ix.custom.get("deepseek_title") or ix.custom.get("gemini_title")
            or f"Turn {ix.turn_index}")


_TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
:root {{
  --bg: #faf9f6; --bg-card: #ffffff; --bg-code: #f4f4f5;
  --text: #292929; --text-muted: #737373; --text-light: #a1a1aa;
  --border: #e4e4e7; --border-strong: #d4d4d8;
  --user-bg: #f4f4f5; --assistant-bg: #ffffff;
  --accent: #d97706; --accent-light: #fef3c7;
  --tag-user: #6366f1; --tag-assistant: #10b981; --tag-system: #f59e0b; --tag-tool: #8b5cf6;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #18181b; --bg-card: #1f1f23; --bg-code: #27272a;
    --text: #fafafa; --text-muted: #a1a1aa; --text-light: #71717a;
    --border: #3f3f46; --border-strong: #52525b;
    --user-bg: #27272a; --assistant-bg: #1f1f23;
    --accent-light: #422006;
  }}
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif; line-height: 1.7; font-size: 16px; }}
.container {{ max-width: 720px; margin: 0 auto; padding: 40px 20px; }}
header {{ margin-bottom: 32px; padding-bottom: 24px; border-bottom: 1px solid var(--border); }}
header h1 {{ font-size: 1.5em; font-weight: 600; margin-bottom: 8px; letter-spacing: -0.02em; }}
header .meta {{ color: var(--text-muted); font-size: 0.875em; }}
.stats {{ display: flex; gap: 24px; flex-wrap: wrap; margin-bottom: 32px; color: var(--text-muted); font-size: 0.875em; }}
.stat {{ display: flex; align-items: baseline; gap: 6px; }}
.stat-num {{ font-size: 1.25em; font-weight: 600; color: var(--text); }}
.search-box {{ margin-bottom: 24px; }}
.search-box input {{ width: 100%; padding: 12px 16px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-card); color: var(--text); font-size: 0.95em; outline: none; }}
.search-box input:focus {{ border-color: var(--border-strong); }}
.search-box input::placeholder {{ color: var(--text-light); }}
.session {{ margin-bottom: 48px; }}
.session-header {{ margin-bottom: 16px; }}
.session-title {{ font-size: 1.125em; font-weight: 600; margin-bottom: 4px; }}
.session-meta {{ font-size: 0.8em; color: var(--text-light); }}
.turn {{ margin-bottom: 24px; padding: 16px 20px; border-radius: 12px; background: var(--bg-card); border: 1px solid var(--border); }}
.turn.user {{ background: var(--user-bg); }}
.turn.assistant {{ background: var(--assistant-bg); }}
.turn-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }}
.tag {{ display: inline-flex; align-items: center; padding: 2px 10px; border-radius: 999px; font-size: 0.75em; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; }}
.tag.user {{ background: rgba(99,102,241,0.1); color: var(--tag-user); }}
.tag.assistant {{ background: rgba(16,185,129,0.1); color: var(--tag-assistant); }}
.tag.system {{ background: rgba(245,158,11,0.1); color: var(--tag-system); }}
.tag.tool {{ background: rgba(139,92,246,0.1); color: var(--tag-tool); }}
.model {{ font-size: 0.75em; color: var(--text-light); margin-left: auto; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
.content {{ white-space: pre-wrap; word-wrap: break-word; }}
.content p {{ margin-bottom: 12px; }}
.content p:last-child {{ margin-bottom: 0; }}
.content pre {{ background: var(--bg-code); padding: 16px; border-radius: 8px; overflow-x: auto; margin: 12px 0; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.875em; line-height: 1.5; }}
.content code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
.content code:not(pre code) {{ background: var(--bg-code); padding: 2px 6px; border-radius: 4px; font-size: 0.9em; }}
.thinking {{ background: var(--accent-light); border-left: 3px solid var(--accent); padding: 12px 16px; margin: 12px 0; border-radius: 0 8px 8px 0; }}
.thinking-label {{ font-size: 0.75em; font-weight: 600; color: var(--accent); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px; }}
.artifact {{ background: var(--bg-code); border: 1px solid var(--border); border-radius: 8px; padding: 12px 16px; margin: 12px 0; }}
.artifact-header {{ font-size: 0.875em; font-weight: 500; margin-bottom: 8px; }}
.sensitivity {{ background: rgba(239,68,68,0.05); border: 1px solid rgba(239,68,68,0.2); border-radius: 8px; padding: 12px 16px; margin: 12px 0; font-size: 0.875em; }}
.sensitivity-badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.75em; font-weight: 600; background: rgba(239,68,68,0.1); color: #dc2626; margin-left: 8px; }}
.hidden {{ display: none; }}
@media (max-width: 640px) {{ .container {{ padding: 20px 16px; }} .turn {{ padding: 12px 14px; }} }}
</style>
</head>
<body>
<div class="container">
<header>
  <h1>{header_title}</h1>
  <div class="meta">{header_meta}</div>
</header>
<div class="stats">{stats_html}</div>
<div class="search-box"><input type="text" id="search" placeholder="搜索对话内容..." oninput="filter()"></div>
<div id="content">{content_html}</div>
</div>
<script>
function filter() {{
  const q = document.getElementById('search').value.toLowerCase();
  document.querySelectorAll('.turn').forEach(el => {{
    el.classList.toggle('hidden', q && !el.textContent.toLowerCase().includes(q));
  }});
  document.querySelectorAll('.session').forEach(s => {{
    const turns = s.querySelectorAll('.turn:not(.hidden)');
    s.classList.toggle('hidden', q && turns.length === 0);
  }});
}}
</script>
</body>
</html>'''


def _render_content(text: str) -> str:
    """处理 markdown 代码块，转为 HTML"""
    parts = []
    i = 0
    while i < len(text):
        if text[i:i+3] == '```':
            end = text.find('```', i + 3)
            if end != -1:
                block = text[i+3:end]
                nl = block.find('\n')
                lang = block[:nl].strip() if nl != -1 else ''
                code = block[nl+1:] if nl != -1 else block
                parts.append(f'<pre><code class="language-{lang or "text"}">{_esc(code)}</code></pre>')
                i = end + 3
            else:
                parts.append(_esc(text[i:]))
                break
        else:
            nxt = text.find('```', i)
            if nxt == -1:
                parts.append(_esc(text[i:]))
                break
            parts.append(_esc(text[i:nxt]))
            i = nxt
    # 简单段落处理
    html_out = ''.join(parts)
    # 把连续非 pre 的文本用 p 包起来
    return html_out


def _render_msg(msg: Message) -> str:
    role = msg.role.value
    tag_cls = role
    label = role.capitalize()
    
    model_html = f'<span class="model">{_esc(msg.model)}</span>' if msg.model else ''
    
    content = msg.content
    thinking_html = ''
    if '<think/>' in content:
        parts = content.split('<think/>', 1)
        if len(parts) == 2:
            thinking_html = f'<div class="thinking"><div class="thinking-label">Thinking</div><pre>{_esc(parts[0].strip())}</pre></div>'
            content = parts[1].strip()
    
    content_html = _render_content(content)
    
    return f'''<div class="turn {role}">
<div class="turn-header"><span class="tag {tag_cls}">{label}</span>{model_html}</div>
{thinking_html}
<div class="content">{content_html}</div>
</div>'''


def _render_artifacts(ix: Interaction) -> str:
    if not ix.artifacts:
        return ''
    parts = []
    for a in ix.artifacts:
        code = ''
        if a.content:
            lines = '\n'.join(a.content.split('\n')[:30])
            code = f'<pre><code class="language-{a.language or "text"}">{_esc(lines)}</code></pre>'
        parts.append(f'<div class="artifact"><div class="artifact-header">{_esc(a.name)} <span style="color:var(--text-light)">({a.type.value})</span></div>{code}</div>')
    return '\n'.join(parts)


def _render_sensitivity(ix: Interaction) -> str:
    if not ix.sensitivity or ix.sensitivity.max_risk_level == RiskLevel.LOW:
        return ''
    level = ix.sensitivity.max_risk_level.value
    items = ''.join(f'<li>{_esc(i.info_type)} ({i.risk_level.value})</li>' for i in ix.sensitivity.detected_items)
    return f'<div class="sensitivity"><strong>敏感内容</strong><span class="sensitivity-badge">{level.upper()}</span><ul>{items}</ul></div>'


class HTMLExporter(BaseExporter):
    target_format = "html"
    file_extension = ".html"

    def export_string(self, ailog: AILogFile) -> str:
        meta = ailog.metadata
        title = f"AILog · {meta.source_platform}"
        header_meta = f"导出时间: {meta.export_timestamp} · 来源: {meta.source_platform}"
        
        # Stats
        total_turns = len(ailog.interactions)
        sessions: Dict[str, List[Interaction]] = {}
        for ix in ailog.interactions:
            sessions.setdefault(ix.session_id, []).append(ix)
        total_sessions = len(sessions)
        total_msgs = sum(len(ix.messages) for ix in ailog.interactions)
        
        stats_html = f'<div class="stat"><span class="stat-num">{total_sessions}</span> 会话</div><div class="stat"><span class="stat-num">{total_turns}</span> 轮对话</div><div class="stat"><span class="stat-num">{total_msgs}</span> 条消息</div>'
        
        # Content
        sess_parts = []
        for sid, ixs in sessions.items():
            title = _esc(_get_title(ixs[0]))
            ts = ixs[0].timestamp
            turns_html = ''
            for ix in ixs:
                for msg in ix.messages:
                    turns_html += _render_msg(msg)
                turns_html += _render_artifacts(ix)
                turns_html += _render_sensitivity(ix)
            sess_parts.append(f'''<div class="session">
<div class="session-header"><div class="session-title">{title}</div><div class="session-meta">{len(ixs)} 轮 · {ts}</div></div>
{turns_html}
</div>''')
        
        content_html = '\n'.join(sess_parts)
        
        page_title = f"AILog · {meta.source_platform}"
        return _TEMPLATE.format(
            title=_esc(page_title), header_title=_esc(page_title), header_meta=header_meta,
            stats_html=stats_html, content_html=content_html
        )

    def export(self, ailog: ALogFile, output_path: str | Path) -> Path:
        output = Path(output_path)
        if output.is_dir() or output.suffix == '':
            output.mkdir(parents=True, exist_ok=True)
            fn = f"ailog_{ailog.metadata.source_platform}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            output = output / fn
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(self.export_string(ailog), encoding='utf-8')
        return output

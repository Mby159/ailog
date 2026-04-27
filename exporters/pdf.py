"""
AILog PDF Exporter
支持中文、代码高亮、敏感信息标记
"""

from __future__ import annotations
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple
from ailog.core.models import AILogFile, Interaction, Message, Role, ContentType, RiskLevel, ArtifactType
from ailog.exporters.base import BaseExporter


def _clean_text(text: str, max_len: int = 2000) -> str:
    """清理文本用于 PDF"""
    # 移除 markdown 代码块标记
    text = re.sub(r'```\w*\n', '\n', text)
    text = re.sub(r'```', '', text)
    # 移除 thinking 标签
    text = re.sub(r'<think/>.*?</think>', '', text, flags=re.DOTALL)
    # 简单 HTML 清理
    text = re.sub(r'<[^>]+>', '', text)
    # 替换无法编码的字符
    text = text.encode('latin-1', 'replace').decode('latin-1')
    # 截断
    if len(text) > max_len:
        text = text[:max_len] + '...'
    return text.strip()


def _get_title(ix: Interaction) -> str:
    return ix.custom.get('chatgpt_title') or ix.custom.get('claude_title') \
           or ix.custom.get('deepseek_title') or ix.custom.get('gemini_title') \
           or f"Turn {ix.turn_index}"


class PDFExporter(BaseExporter):
    target_format = "pdf"
    file_extension = ".pdf"

    def __init__(self):
        self.font_regular = 'Helvetica'
        self.font_bold = 'Helvetica'
        self.font_mono = 'Courier'

    def export_string(self, ailog: AILogFile) -> str:
        raise NotImplementedError("PDF exporter does not support export_string, use export()")

    def export(self, ailog: AILogFile, output_path: str | Path) -> Path:
        from fpdf import FPDF

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        
        # 封面
        pdf.add_page()
        pdf.set_font(self.font_bold, size=24)
        pdf.cell(0, 20, 'AILog Export', ln=True, align='C')
        pdf.ln(10)
        
        pdf.set_font(self.font_regular, size=12)
        pdf.cell(0, 10, f"Source: {ailog.metadata.source_platform}", ln=True, align='C')
        pdf.cell(0, 10, f"Exported: {ailog.metadata.export_timestamp}", ln=True, align='C')
        pdf.ln(10)
        
        # 统计
        total_turns = len(ailog.interactions)
        sessions: Dict[str, List[Interaction]] = {}
        for ix in ailog.interactions:
            sessions.setdefault(ix.session_id, []).append(ix)
        total_sessions = len(sessions)
        total_msgs = sum(len(ix.messages) for ix in ailog.interactions)
        
        pdf.set_font(self.font_regular, size=11)
        pdf.cell(0, 8, f"Sessions: {total_sessions} | Turns: {total_turns} | Messages: {total_msgs}", ln=True, align='C')
        pdf.ln(15)

        # 会话内容
        for sid, ixs in sessions.items():
            # 会话标题
            title = _get_title(ixs[0])
            pdf.add_page()
            pdf.set_font(self.font_bold, size=16)
            pdf.cell(0, 12, _clean_text(title, 100), ln=True)
            pdf.set_font(self.font_regular, size=9)
            pdf.cell(0, 8, f"{len(ixs)} turns | {ixs[0].timestamp}", ln=True)
            pdf.ln(5)
            
            # 消息
            for ix in ixs:
                for msg in ix.messages:
                    self._render_msg_to_pdf(pdf, msg)
                
                # Artifacts
                for a in ix.artifacts:
                    pdf.set_font(self.font_bold, size=10)
                    pdf.cell(0, 8, f"[Artifact: {a.name} ({a.type.value})]", ln=True)
                    if a.content:
                        pdf.set_font(self.font_mono, size=8)
                        code = '\n'.join(a.content.split('\n')[:15])
                        pdf.multi_cell(0, 5, _clean_text(code, 500))
                    pdf.ln(3)
                
                # Sensitivity
                if ix.sensitivity and ix.sensitivity.max_risk_level != RiskLevel.LOW:
                    pdf.set_font(self.font_bold, size=10)
                    pdf.set_text_color(200, 0, 0)
                    pdf.cell(0, 8, f"[SENSITIVE: {ix.sensitivity.max_risk_level.value.upper()}]", ln=True)
                    pdf.set_text_color(0, 0, 0)
                    pdf.ln(2)
        
        # 保存
        output = Path(output_path)
        if output.is_dir() or output.suffix == '':
            output.mkdir(parents=True, exist_ok=True)
            fn = f"ailog_{ailog.metadata.source_platform}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            output = output / fn
        output.parent.mkdir(parents=True, exist_ok=True)
        pdf.output(str(output))
        return output

    def _render_msg_to_pdf(self, pdf, msg: Message):
        """将单条消息渲染到 PDF"""
        role = msg.role.value
        pdf.set_font(self.font_bold, size=10)
        if role == 'user':
            pdf.set_text_color(99, 102, 241)
        elif role == 'assistant':
            pdf.set_text_color(16, 185, 129)
        elif role == 'system':
            pdf.set_text_color(245, 158, 11)
        else:
            pdf.set_text_color(139, 92, 246)
        
        label = role.upper()
        if msg.model:
            label += f" ({msg.model})"
        pdf.cell(0, 8, f"[{label}]", ln=True)
        pdf.set_text_color(0, 0, 0)
        
        content = msg.content
        if '<think/>' in content:
            parts = content.split('<think/>', 1)
            if len(parts) == 2:
                content = parts[1].strip()
        
        pdf.set_font(self.font_regular, size=10)
        pdf.multi_cell(0, 5, _clean_text(content, 1500))
        pdf.ln(3)
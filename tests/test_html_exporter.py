"""Tests for HTML Exporter."""

import json
import sys
from pathlib import Path

import pytest

from ailog.core.models import (
    AILogFile, AILogFileMetadata, Interaction, Message, Role,
    ContentType, SensitivityInfo, SensitivityItem, RiskLevel, Artifact, ArtifactType,
)
from ailog.exporters.html import HTMLExporter


@pytest.fixture
def sample_ailog():
    return AILogFile(
        ailog_version="0.1",
        metadata=AILogFileMetadata(
            source_platform="chatgpt",
            export_timestamp="2026-04-27T00:00:00Z",
            exporter="ailog/0.1.0",
            tags=["test"],
        ),
        interactions=[
            Interaction(
                id="ix_001",
                timestamp="2026-04-27T00:01:00Z",
                session_id="sess_001",
                turn_index=0,
                messages=[
                    Message(role=Role.USER, content="Hello, write a quicksort in Python"),
                    Message(
                        role=Role.ASSISTANT,
                        content="Here is quicksort:\n\n```python\ndef quicksort(arr):\n    if len(arr) <= 1:\n        return arr\n    pivot = arr[len(arr) // 2]\n    left = [x for x in arr if x < pivot]\n    return quicksort(left) + quicksort(right)\n```",
                        model="gpt-4",
                        content_type=ContentType.MARKDOWN,
                    ),
                ],
                custom={"chatgpt_title": "Python Quick Sort"},
            ),
            Interaction(
                id="ix_002",
                timestamp="2026-04-27T00:02:00Z",
                session_id="sess_001",
                turn_index=1,
                messages=[
                    Message(role=Role.USER, content="My phone is 13812345678, register a test account"),
                    Message(
                        role=Role.ASSISTANT,
                        content="I've registered using 138****5678.",
                        model="gpt-4",
                    ),
                ],
                sensitivity=SensitivityInfo(
                    max_risk_level=RiskLevel.HIGH,
                    detected_items=[
                        SensitivityItem(info_type="phone_number", risk_level=RiskLevel.HIGH, field="messages[0].content"),
                    ],
                    scanned_by="ghostguard",
                ),
                custom={"chatgpt_title": "Python Quick Sort"},
            ),
            Interaction(
                id="ix_003",
                timestamp="2026-04-27T00:03:00Z",
                session_id="sess_002",
                turn_index=0,
                messages=[
                    Message(role=Role.USER, content="Explain quantum computing"),
                    Message(
                        role=Role.ASSISTANT,
                        content="<think/>Let me think step by step.\n\nQuantum computing uses qubits that can be 0 and 1 simultaneously via superposition.",
                        model="deepseek-r1",
                    ),
                ],
                custom={"deepseek_title": "Quantum Computing"},
                artifacts=[
                    Artifact(id="art_001", type=ArtifactType.CODE, name="bell_state.py", content="from qiskit import QuantumCircuit\nqc = QuantumCircuit(2)\nqc.h(0)\nqc.cx(0, 1)", language="python"),
                ],
            ),
        ],
    )


def test_html_export_string(sample_ailog):
    exporter = HTMLExporter()
    result = exporter.export_string(sample_ailog)

    # Basic structure
    assert "<!DOCTYPE html>" in result
    assert "<html" in result
    assert "</html>" in result
    assert "AILog · chatgpt" in result
    assert "chatgpt" in result

    # Stats
    assert ">2<" in result  # 2 sessions
    assert ">3<" in result  # 3 interactions

    # Code blocks with Prism
    assert 'class="language-python"' in result

    # Sensitivity badge
    assert "sensitivity-badge" in result
    assert "HIGH" in result

    # Thinking block
    assert "Thinking" in result

    # Artifact
    assert "bell_state.py" in result
    assert "artifact" in result

    # Theme toggle
    assert "prefers-color-scheme" in result
    assert "function filter()" in result


def test_html_export_to_file(sample_ailog, tmp_path):
    exporter = HTMLExporter()
    output = exporter.export(sample_ailog, tmp_path / "test_output.html")

    assert output.exists()
    content = output.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content
    assert "Python Quick Sort" in content


def test_html_export_to_directory(sample_ailog, tmp_path):
    exporter = HTMLExporter()
    outdir = tmp_path / "output"
    output = exporter.export(sample_ailog, outdir)

    assert output.exists()
    assert output.suffix == ".html"
    content = output.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content


def test_html_escape_special_chars():
    ailog = AILogFile(
        metadata=AILogFileMetadata(
            source_platform="test",
            export_timestamp="2026-01-01T00:00:00Z",
            exporter="test/1.0",
        ),
        interactions=[
            Interaction(
                id="ix_evil",
                timestamp="2026-01-01T00:00:00Z",
                session_id="s1",
                turn_index=0,
                messages=[
                    Message(role=Role.USER, content='<script>alert("xss")</script>'),
                    Message(role=Role.ASSISTANT, content='& "quotes" <tags>'),
                ],
            ),
        ],
    )

    exporter = HTMLExporter()
    result = exporter.export_string(ailog)

    # Escaped, not raw
    assert "<script>" not in result or "&lt;script&gt;" in result
    assert "&lt;" in result
    assert "&amp;" in result


def test_html_empty_ailog():
    ailog = AILogFile(
        metadata=AILogFileMetadata(
            source_platform="empty",
            export_timestamp="2026-01-01T00:00:00Z",
            exporter="test/1.0",
        ),
        interactions=[],
    )

    exporter = HTMLExporter()
    result = exporter.export_string(ailog)

    assert "<!DOCTYPE html>" in result
    assert "AILog · empty" in result
    assert ">0<" in result  # 0 sessions, 0 interactions


def test_html_system_and_tool_messages():
    ailog = AILogFile(
        metadata=AILogFileMetadata(
            source_platform="test",
            export_timestamp="2026-01-01T00:00:00Z",
            exporter="test/1.0",
        ),
        interactions=[
            Interaction(
                id="ix_sys",
                timestamp="2026-01-01T00:00:00Z",
                session_id="s1",
                turn_index=0,
                messages=[
                    Message(role=Role.SYSTEM, content="You are a helpful assistant."),
                    Message(role=Role.USER, content="Hi"),
                    Message(role=Role.ASSISTANT, content="Hello!"),
                    Message(role=Role.TOOL, content='{"result": 42}'),
                ],
            ),
        ],
    )

    exporter = HTMLExporter()
    result = exporter.export_string(ailog)

    assert "turn system" in result
    assert "turn user" in result
    assert "turn assistant" in result
    assert "turn tool" in result

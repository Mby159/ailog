"""
Regression tests for P0 security fixes in ailog.

P0#5: GhostGuard not installed → must warn and set CRITICAL risk level
P0#6: DeepSeek importer must set CRITICAL instead of hard-coded LOW
"""

import json
import warnings
from pathlib import Path

import pytest

from ailog.core.models import (
    AILogFile,
    AILogFileMetadata,
    RiskLevel,
    Interaction,
    Message,
    Role,
)
from ailog.importers.deepseek import _parse_conversation
from ailog.bridge import ghostguard as gg_module


# ------------------------------------------------------------------
# P0#5: GhostGuard fallback behavior
# ------------------------------------------------------------------
class TestGhostGuardFallback:
    def test_uninstalled_scanner_returns_critical(self, monkeypatch):
        """When GhostGuard is not installed, scan must return CRITICAL, not silently pass."""
        monkeypatch.setattr(gg_module, "_HAS_GHOSTGUARD", False)
        monkeypatch.setattr(gg_module, "_HAS_PRIVACY_GUARD", False)

        interaction = Interaction(
            id="test-1",
            timestamp="2026-01-01T00:00:00Z",
            session_id="sess-1",
            turn_index=1,
            messages=[Message(role=Role.USER, content="Hello 13812345678")],
        )

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = gg_module.scan_interaction_ghostguard(interaction)

        assert result.sensitivity.max_risk_level == RiskLevel.CRITICAL
        assert len(w) == 1
        assert "not installed" in str(w[0].message).lower()

    def test_uninstalled_privacy_guard_returns_critical(self, monkeypatch):
        """privacy-guard fallback also returns CRITICAL when missing."""
        monkeypatch.setattr(gg_module, "_HAS_GHOSTGUARD", False)
        monkeypatch.setattr(gg_module, "_HAS_PRIVACY_GUARD", False)

        interaction = Interaction(
            id="test-2",
            timestamp="2026-01-01T00:00:00Z",
            session_id="sess-1",
            turn_index=1,
            messages=[Message(role=Role.USER, content="Hello")],
        )

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = gg_module.scan_interaction_privacy_guard(interaction)

        assert result.sensitivity.max_risk_level == RiskLevel.CRITICAL
        assert len(w) == 1
        assert "not installed" in str(w[0].message).lower()

    def test_scan_ailog_file_no_scanner(self, monkeypatch):
        """scan_ailog_file with no scanner marks all interactions CRITICAL."""
        monkeypatch.setattr(gg_module, "_HAS_GHOSTGUARD", False)
        monkeypatch.setattr(gg_module, "_HAS_PRIVACY_GUARD", False)

        ailog = AILogFile(
            ailog_version="0.1",
            metadata=AILogFileMetadata(
                source_platform="test",
                export_timestamp="2026-01-01T00:00:00Z",
                exporter="pytest",
            ),
            interactions=[
                Interaction(
                    id="ix-1",
                    timestamp="2026-01-01T00:00:00Z",
                    session_id="s-1",
                    turn_index=1,
                    messages=[Message(role=Role.USER, content="test")],
                )
            ],
        )

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = gg_module.scan_ailog_file(ailog)

        for ix in result.interactions:
            assert ix.sensitivity.max_risk_level == RiskLevel.CRITICAL
            assert ix.sensitivity.scanned_by and "WARNING" in ix.sensitivity.scanned_by


# ------------------------------------------------------------------
# P0#6: DeepSeek importer hard-coded risk level
# ------------------------------------------------------------------
class TestDeepSeekImporterRiskLevel:
    def test_import_sets_critical_not_low(self):
        """DeepSeek importer must set RiskLevel.CRITICAL, not hard-coded LOW."""
        conversation = {
            "title": "Test",
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there"},
            ],
        }
        interactions = _parse_conversation(conversation, 0)
        assert len(interactions) == 1
        assert interactions[0].sensitivity.max_risk_level == RiskLevel.CRITICAL
        assert (
            interactions[0].sensitivity.scanned_by
            and "pending scan" in interactions[0].sensitivity.scanned_by.lower()
        )

    def test_orphan_user_message_also_critical(self):
        """Orphan user message (no assistant reply) also gets CRITICAL."""
        conversation = {
            "title": "Orphan",
            "messages": [
                {"role": "user", "content": "Unanswered question"},
            ],
        }
        interactions = _parse_conversation(conversation, 0)
        assert len(interactions) == 1
        assert interactions[0].sensitivity.max_risk_level == RiskLevel.CRITICAL

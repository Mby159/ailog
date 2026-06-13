"""
AILog ↔ GhostGuard Bridge

Scans AILog interactions for sensitive information using GhostGuard,
and annotates the `sensitivity` field on each interaction.

Design: 
  - GhostGuard is optional (graceful fallback if not installed)
  - Also supports privacy-guard as a fallback scanner
  - Returns the same AILogFile with sensitivity fields populated
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# AILog core models
from ailog.core.models import (
    AILogFile,
    Interaction,
    SensitivityInfo,
    SensitivityItem,
    RiskLevel,
    RedactionStrategy,
    Message,
)

# Try importing GhostGuard
_HAS_GHOSTGUARD = False
_HAS_PRIVACY_GUARD = False

try:
    from ghostguard import GhostGuard
    _HAS_GHOSTGUARD = True
except ImportError:
    pass

if not _HAS_GHOSTGUARD:
    # Fallback: prefer an installed privacy-guard package. If unavailable,
    # fall back to a sibling checkout for local monorepo-style development.
    try:
        from privacy_guard import PrivacyGuard
        _HAS_PRIVACY_GUARD = True
    except ImportError:
        try:
            _pg_path = Path(__file__).parent.parent.parent.parent / "privacy-guard"
            if _pg_path.is_dir() and str(_pg_path) not in sys.path:
                sys.path.insert(0, str(_pg_path))
            from privacy_guard import PrivacyGuard
            _HAS_PRIVACY_GUARD = True
        except ImportError:
            pass


def _ghostguard_risk_to_ailog(risk_str: str) -> RiskLevel:
    """Map GhostGuard SensitivityLevel to AILog RiskLevel."""
    mapping = {
        "low": RiskLevel.LOW,
        "medium": RiskLevel.MEDIUM,
        "high": RiskLevel.HIGH,
        "critical": RiskLevel.CRITICAL,
    }
    return mapping.get(risk_str, RiskLevel.LOW)


def _strategy_to_ailog(strategy_str: str) -> Optional[RedactionStrategy]:
    """Map GhostGuard RedactionStrategy to AILog RedactionStrategy."""
    mapping = {
        "placeholder": RedactionStrategy.PLACEHOLDER,
        "mask": RedactionStrategy.MASK,
        "remove": RedactionStrategy.REMOVE,
        "hash": RedactionStrategy.HASH,
    }
    return mapping.get(strategy_str)


def scan_interaction_ghostguard(
    interaction: Interaction,
    strategy: str = "placeholder",
    auto_redact: bool = False,
) -> Interaction:
    """
    Scan a single interaction using GhostGuard.
    
    Args:
        interaction: The interaction to scan
        strategy: Redaction strategy (placeholder/mask/remove/hash)
        auto_redact: If True, redact sensitive content in messages
    
    Returns:
        The same interaction with sensitivity field populated
    """
    if not _HAS_GHOSTGUARD:
        return interaction

    guard = GhostGuard()
    all_items: List[SensitivityItem] = []
    max_risk = RiskLevel.LOW
    _risk_order = [
        RiskLevel.LOW,
        RiskLevel.MEDIUM,
        RiskLevel.HIGH,
        RiskLevel.CRITICAL,
    ]

    for msg_idx, message in enumerate(interaction.messages):
        if not message.content:
            continue

        # Detect
        result = guard.process_input(message.content)
        detections = result.detections if hasattr(result, 'detections') else []

        for det in detections:
            risk = _ghostguard_risk_to_ailog(det.risk_level.value if hasattr(det.risk_level, 'value') else str(det.risk_level))
            item = SensitivityItem(
                info_type=det.info_type,
                risk_level=risk,
                field=f"messages[{msg_idx}].content",
                redacted=auto_redact,
                strategy=_strategy_to_ailog(strategy) if auto_redact else None,
            )
            all_items.append(item)
            if _risk_order.index(risk) > _risk_order.index(max_risk):
                max_risk = risk

        # Auto-redact if requested
        if auto_redact and detections:
            redacted = guard.redact(message.content, strategy=strategy)
            message.content = redacted["text"]

    interaction.sensitivity = SensitivityInfo(
        max_risk_level=max_risk,
        detected_items=all_items,
        scanned_by="ghostguard/0.1.0",
        scan_timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    return interaction


def scan_interaction_privacy_guard(
    interaction: Interaction,
    strategy: str = "placeholder",
    auto_redact: bool = False,
) -> Interaction:
    """
    Scan a single interaction using privacy-guard (fallback).
    
    Similar to scan_interaction_ghostguard but uses the simpler privacy-guard API.
    """
    if not _HAS_PRIVACY_GUARD:
        return interaction

    guard = PrivacyGuard()
    all_items: List[SensitivityItem] = []
    max_risk = RiskLevel.LOW
    _risk_order = [
        RiskLevel.LOW,
        RiskLevel.MEDIUM,
        RiskLevel.HIGH,
        RiskLevel.CRITICAL,
    ]

    for msg_idx, message in enumerate(interaction.messages):
        if not message.content:
            continue

        # Detect
        detection = guard.detect(message.content)
        for item in detection:
            risk = _ghostguard_risk_to_ailog(item.get("risk_level", "low"))
            si = SensitivityItem(
                info_type=item.get("info_type", "unknown"),
                risk_level=risk,
                field=f"messages[{msg_idx}].content",
                redacted=auto_redact,
                strategy=_strategy_to_ailog(strategy) if auto_redact else None,
            )
            all_items.append(si)
            if _risk_order.index(risk) > _risk_order.index(max_risk):
                max_risk = risk

        # Auto-redact if requested
        if auto_redact and detection:
            redacted = guard.redact(message.content, strategy=strategy)
            message.content = redacted["text"]

    interaction.sensitivity = SensitivityInfo(
        max_risk_level=max_risk,
        detected_items=all_items,
        scanned_by="privacy-guard/0.1.0",
        scan_timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    return interaction


def scan_ailog_file(
    ailog: AILogFile,
    strategy: str = "placeholder",
    auto_redact: bool = False,
) -> AILogFile:
    """
    Scan an entire AILogFile for sensitive information.
    
    Uses GhostGuard if available, falls back to privacy-guard,
    or skips scanning if neither is installed.
    
    Args:
        ailog: The AILogFile to scan
        strategy: Redaction strategy
        auto_redact: Whether to auto-redact sensitive content
    
    Returns:
        The same AILogFile with sensitivity fields populated
    """
    if _HAS_GHOSTGUARD:
        scanner = scan_interaction_ghostguard
    elif _HAS_PRIVACY_GUARD:
        scanner = scan_interaction_privacy_guard
    else:
        # No scanner available, mark as unscanned
        for interaction in ailog.interactions:
            interaction.sensitivity = SensitivityInfo(
                max_risk_level=RiskLevel.LOW,
                detected_items=[],
                scanned_by="none",
            )
        return ailog

    for interaction in ailog.interactions:
        scanner(interaction, strategy=strategy, auto_redact=auto_redact)

    return ailog


def get_scan_status() -> dict:
    """Return info about available privacy scanners."""
    return {
        "ghostguard": _HAS_GHOSTGUARD,
        "privacy_guard": _HAS_PRIVACY_GUARD,
        "primary": "ghostguard" if _HAS_GHOSTGUARD else ("privacy_guard" if _HAS_PRIVACY_GUARD else "none"),
    }
"""
AILog ↔ LocalChain Bridge

Hot path: AILog interactions are written to a LocalChain server as
tamper-evident records. Each anchored interaction stores its
``localchain_anchor`` metadata in ``Interaction.custom`` so it can be
verified later.

Design notes:
  - LocalChain is the local tamper-evident ledger; it is content-agnostic.
  - This bridge sends a stable, sorted JSON record per interaction so the
    leaf hash on both sides is reproducible.
  - The LocalChain SDK is a Node project; communication is over HTTP.
  - Network access is optional. If the server is unreachable, the bridge
    raises ``LocalChainUnavailable`` instead of corrupting the AILogFile.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ailog.core.models import AILogFile, Interaction


DEFAULT_SERVER_URL = "http://localhost:3456"


# ──────────────────────────────────────────────
# Errors
# ──────────────────────────────────────────────


class LocalChainError(Exception):
    """Base error for the LocalChain bridge."""


class LocalChainUnavailable(LocalChainError):
    """LocalChain server cannot be reached or returned a transport error."""


class LocalChainRejected(LocalChainError):
    """LocalChain server reached but rejected the request."""


# ──────────────────────────────────────────────
# Record shape
# ──────────────────────────────────────────────


def _stable_json(obj: Any) -> str:
    """Stable JSON for hashing/transport — sorted keys, no extra spacing."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(obj: Any) -> str:
    return hashlib.sha256(_stable_json(obj).encode("utf-8")).hexdigest()


def _leaf_hash(record: Dict[str, Any]) -> str:
    """Hash of the JSON.stringify(record) — matches LocalChain core/merkle.js."""
    return hashlib.sha256(_stable_json(record).encode("utf-8")).hexdigest()


def _interaction_record(interaction: Interaction, ailog_version: str) -> Dict[str, Any]:
    """Build the stable record that AILog hands to LocalChain.

    Only includes the parts that should be evidence-fixed: id, timestamp,
    session_id, turn_index, and a digest of the messages/artifacts.

    We do NOT send the full message bodies here. The AILogFile remains the
    source of truth; LocalChain stores a fingerprint so tampering is
    detectable.
    """

    payload: Dict[str, Any] = {
        "type": "ailog.interaction",
        "ailog_version": ailog_version,
        "id": interaction.id,
        "timestamp": interaction.timestamp,
        "session_id": interaction.session_id,
        "turn_index": interaction.turn_index,
        "messages_digest": _digest([m.to_dict() for m in interaction.messages]),
    }
    if interaction.artifacts:
        payload["artifacts_digest"] = _digest(
            [a.to_dict() for a in interaction.artifacts]
        )
    if interaction.sensitivity is not None and interaction.sensitivity.overall_risk is not None:
        payload["sensitivity_level"] = interaction.sensitivity.overall_risk.value
    return payload


# ──────────────────────────────────────────────
# HTTP client
# ──────────────────────────────────────────────


@dataclass
class LocalChainAnchorResult:
    block_index: int
    leaf_index: int
    leaf_hash: str
    server_url: str
    anchored_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "block_index": self.block_index,
            "leaf_index": self.leaf_index,
            "leaf_hash": self.leaf_hash,
            "server_url": self.server_url,
            "anchored_at": self.anchored_at,
        }


class LocalChainClient:
    """Minimal HTTP client for the LocalChain server.

    Only depends on the standard library so AILog stays lightweight.
    """

    def __init__(self, server_url: str = DEFAULT_SERVER_URL, timeout: float = 5.0):
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout

    def _request(
        self, method: str, path: str, body: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        url = f"{self.server_url}{path}"
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = _stable_json(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                payload = json.loads(e.read().decode("utf-8"))
            except Exception:
                payload = {"error": str(e)}
            raise LocalChainRejected(
                f"LocalChain rejected {method} {path}: {e.code} {payload}"
            )
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise LocalChainUnavailable(
                f"LocalChain unreachable at {self.server_url}: {e}"
            )

    def health(self) -> Dict[str, Any]:
        return self._request("GET", "/api/health")

    def anchor_records(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not records:
            raise ValueError("records must be a non-empty list")
        return self._request("POST", "/api/chain/blocks", {"records": records})

    def verify_record(
        self, record: Dict[str, Any], block_index: int, leaf_index: int
    ) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/api/chain/verify",
            {"record": record, "blockIndex": block_index, "leafIndex": leaf_index},
        )


# ──────────────────────────────────────────────
# Bridge API
# ──────────────────────────────────────────────


def anchor_ailog_file(
    ailog_file: AILogFile,
    *,
    client: Optional[LocalChainClient] = None,
    server_url: str = DEFAULT_SERVER_URL,
    only_unanchored: bool = True,
) -> Tuple[AILogFile, List[LocalChainAnchorResult]]:
    """Anchor every (un-anchored) interaction in ``ailog_file`` to LocalChain.

    Returns the same AILogFile with ``custom.localchain_anchor`` populated
    on each anchored interaction, plus the list of results in order.
    """

    cli = client or LocalChainClient(server_url=server_url)

    selected: List[Tuple[int, Interaction, Dict[str, Any]]] = []
    for idx, interaction in enumerate(ailog_file.interactions):
        if only_unanchored and "localchain_anchor" in (interaction.custom or {}):
            continue
        record = _interaction_record(interaction, ailog_file.ailog_version)
        selected.append((idx, interaction, record))

    if not selected:
        return ailog_file, []

    records = [r for _, _, r in selected]
    response = cli.anchor_records(records)

    block = response.get("block") if isinstance(response, dict) else None
    if block is None:
        block = response
    block_index = None
    if isinstance(block, dict):
        block_index = block.get("index")
    if block_index is None:
        raise LocalChainRejected(f"unexpected anchor response: {response}")

    anchored_at = datetime.now(timezone.utc).isoformat()
    results: List[LocalChainAnchorResult] = []

    for leaf_index, (_, interaction, record) in enumerate(selected):
        result = LocalChainAnchorResult(
            block_index=int(block_index),
            leaf_index=leaf_index,
            leaf_hash=_leaf_hash(record),
            server_url=cli.server_url,
            anchored_at=anchored_at,
        )
        custom = dict(interaction.custom or {})
        custom["localchain_anchor"] = result.to_dict()
        interaction.custom = custom
        results.append(result)

    return ailog_file, results


def verify_ailog_file(
    ailog_file: AILogFile,
    *,
    client: Optional[LocalChainClient] = None,
    server_url: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Verify every anchored interaction against LocalChain.

    Returns one report dict per interaction; interactions without an
    anchor get ``{"status": "unanchored", ...}``.
    """

    reports: List[Dict[str, Any]] = []
    cached_clients: Dict[str, LocalChainClient] = {}

    for interaction in ailog_file.interactions:
        anchor = (interaction.custom or {}).get("localchain_anchor")
        if not anchor:
            reports.append(
                {"interaction_id": interaction.id, "status": "unanchored"}
            )
            continue

        target_url = server_url or anchor.get("server_url") or DEFAULT_SERVER_URL
        if client is not None:
            cli = client
        else:
            cli = cached_clients.get(target_url)
            if cli is None:
                cli = LocalChainClient(server_url=target_url)
                cached_clients[target_url] = cli

        record = _interaction_record(interaction, ailog_file.ailog_version)
        local_leaf_hash = _leaf_hash(record)
        block_index = int(anchor.get("block_index"))
        leaf_index = int(anchor.get("leaf_index"))

        try:
            resp = cli.verify_record(record, block_index, leaf_index)
            valid = bool(resp.get("valid"))
            reports.append(
                {
                    "interaction_id": interaction.id,
                    "status": "ok" if valid else "tampered",
                    "valid": valid,
                    "block_index": block_index,
                    "leaf_index": leaf_index,
                    "leaf_hash": local_leaf_hash,
                    "expected_leaf_hash": anchor.get("leaf_hash"),
                    "server_url": target_url,
                }
            )
        except LocalChainError as e:
            reports.append(
                {
                    "interaction_id": interaction.id,
                    "status": "error",
                    "error": str(e),
                    "server_url": target_url,
                }
            )

    return reports


__all__ = [
    "DEFAULT_SERVER_URL",
    "LocalChainError",
    "LocalChainUnavailable",
    "LocalChainRejected",
    "LocalChainClient",
    "LocalChainAnchorResult",
    "anchor_ailog_file",
    "verify_ailog_file",
]

"""Tests for the AILog ↔ LocalChain bridge.

The default smoke runs against an in-process Python HTTP server that
implements the LocalChain HTTP contract. An optional integration test
runs against the real LocalChain Node server when a sibling checkout is
available at ``../local-chain`` or ``LOCAL_CHAIN_REPO`` is set.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

from ailog.bridge.localchain import (
    LocalChainClient,
    LocalChainUnavailable,
    anchor_ailog_file,
    verify_ailog_file,
    export_anchor_artifact,
    _stable_json,
)
from ailog.core.models import (
    AILogFile,
    AILogFileMetadata,
    Interaction,
    Message,
    Role,
    ContentType,
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_ailog_file(num: int = 2) -> AILogFile:
    interactions: List[Interaction] = []
    for i in range(num):
        interactions.append(
            Interaction(
                id=f"int-{i}",
                timestamp=f"2026-06-17T10:0{i}:00Z",
                session_id="sess-test",
                turn_index=i,
                messages=[
                    Message(role=Role.USER, content_type=ContentType.TEXT, content=f"hi {i}"),
                    Message(
                        role=Role.ASSISTANT,
                        content_type=ContentType.TEXT,
                        content=f"hello {i}",
                    ),
                ],
            )
        )
    return AILogFile(
        ailog_version="0.1",
        metadata=AILogFileMetadata(
            source_platform="test",
            export_timestamp="2026-06-17T10:00:00Z",
            exporter="ailog-tests/0.1",
        ),
        interactions=interactions,
    )


# ──────────────────────────────────────────────
# In-process Python mock implementing the LocalChain HTTP contract
# ──────────────────────────────────────────────


class _MockChain:
    def __init__(self) -> None:
        self.blocks: List[Dict[str, Any]] = []

    @staticmethod
    def _h(s: str) -> str:
        return hashlib.sha256(s.encode("utf-8")).hexdigest()

    def add_block(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        leaves = [self._h(_stable_json(r)) for r in records]
        block = {"index": len(self.blocks), "leaves": leaves}
        self.blocks.append(block)
        return {"index": block["index"]}

    def verify_record(self, record: Dict[str, Any], bi: int, li: int) -> bool:
        if bi < 0 or bi >= len(self.blocks):
            return False
        block = self.blocks[bi]
        if li < 0 or li >= len(block["leaves"]):
            return False
        return self._h(_stable_json(record)) == block["leaves"][li]

    def tamper(self, bi: int, li: int) -> None:
        if 0 <= bi < len(self.blocks) and 0 <= li < len(self.blocks[bi]["leaves"]):
            self.blocks[bi]["leaves"][li] = "deadbeef" * 8


class _MockServer:
    def __init__(self) -> None:
        self.chain = _MockChain()
        self.port = _free_port()
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> str:
        chain_ref = self.chain

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return

            def _read_json(self) -> Dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0") or "0")
                if not length:
                    return {}
                return json.loads(self.rfile.read(length).decode("utf-8"))

            def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/api/health":
                    return self._send_json(200, {"status": "ok", "chain": len(chain_ref.blocks)})
                self._send_json(404, {"error": "not found"})

            def do_POST(self):
                if self.path == "/api/chain/blocks":
                    body = self._read_json()
                    records = body.get("records") or []
                    if not records:
                        return self._send_json(400, {"error": "records required"})
                    block = chain_ref.add_block(records)
                    return self._send_json(201, {"index": block["index"]})
                if self.path == "/api/chain/verify":
                    body = self._read_json()
                    valid = chain_ref.verify_record(
                        body.get("record"),
                        int(body.get("blockIndex", -1)),
                        int(body.get("leafIndex", -1)),
                    )
                    return self._send_json(200, {"valid": valid})
                self._send_json(404, {"error": "not found"})

        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()


# ──────────────────────────────────────────────
# Mock-server tests (always run)
# ──────────────────────────────────────────────


class LocalChainBridgeMockTests(unittest.TestCase):
    def setUp(self):
        self.mock = _MockServer()
        self.url = self.mock.start()

    def tearDown(self):
        self.mock.stop()

    def test_unreachable_raises_clean_error(self):
        cli = LocalChainClient(server_url="http://127.0.0.1:1", timeout=1.0)
        with self.assertRaises(LocalChainUnavailable):
            cli.health()

    def test_anchor_then_verify_round_trip(self):
        ailog = _make_ailog_file(num=3)
        client = LocalChainClient(server_url=self.url, timeout=5.0)

        anchored, results = anchor_ailog_file(ailog, client=client)
        self.assertEqual(len(results), 3)
        self.assertTrue(all(r.block_index == 0 for r in results))
        self.assertEqual([r.leaf_index for r in results], [0, 1, 2])
        for r in results:
            self.assertEqual(len(r.leaf_hash), 64)

        for ix in anchored.interactions:
            self.assertIn("localchain_anchor", ix.custom)

        reports = verify_ailog_file(anchored, client=client)
        self.assertEqual(len(reports), 3)
        for rep in reports:
            self.assertEqual(rep["status"], "ok", rep)
            self.assertTrue(rep["valid"])

    def test_export_anchor_artifact_helper_and_cli(self):
        ailog = _make_ailog_file(num=2)
        client = LocalChainClient(server_url=self.url, timeout=5.0)
        anchored, _ = anchor_ailog_file(ailog, client=client)

        exported = export_anchor_artifact(anchored.interactions[1], anchored.ailog_version)
        self.assertEqual(exported["artifact"]["id"], "int-1")
        self.assertEqual(exported["anchor"]["block_index"], 0)
        self.assertEqual(exported["anchor"]["leaf_index"], 1)

        tmp = Path(tempfile.mkdtemp(prefix="ailog-export-test-"))
        try:
            ailog_path = tmp / "sample.ailog"
            artifact_path = tmp / "artifact.json"
            anchor_path = tmp / "anchor.json"
            ailog_path.write_text(anchored.to_json(), encoding="utf-8")

            res = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ailog.cli",
                    "export-anchor-artifact",
                    str(ailog_path),
                    "--interaction",
                    "int-1",
                    "--artifact-out",
                    str(artifact_path),
                    "--anchor-out",
                    str(anchor_path),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
            cli_artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            cli_anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
            self.assertEqual(cli_artifact, exported["artifact"])
            self.assertEqual(cli_anchor, exported["anchor"])

            res_index = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ailog.cli",
                    "export-anchor-artifact",
                    str(ailog_path),
                    "--interaction",
                    "1",
                    "--json",
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(res_index.returncode, 0, res_index.stderr + res_index.stdout)
            combined = json.loads(res_index.stdout)
            self.assertEqual(combined["artifact"], exported["artifact"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_export_anchor_artifact_rejects_unanchored(self):
        ailog = _make_ailog_file(num=1)
        with self.assertRaises(ValueError):
            export_anchor_artifact(ailog.interactions[0], ailog.ailog_version)

        tmp = Path(tempfile.mkdtemp(prefix="ailog-export-unanchored-"))
        try:
            ailog_path = tmp / "sample.ailog"
            ailog_path.write_text(ailog.to_json(), encoding="utf-8")
            res = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ailog.cli",
                    "export-anchor-artifact",
                    str(ailog_path),
                    "--interaction",
                    "int-0",
                    "--json",
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(res.returncode, 2)
            self.assertIn("not anchored", res.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_only_unanchored_skips_already_anchored(self):
        ailog = _make_ailog_file(num=2)
        client = LocalChainClient(server_url=self.url, timeout=5.0)

        _, first = anchor_ailog_file(ailog, client=client)
        self.assertEqual(len(first), 2)

        # Second pass should be a no-op since both are anchored
        _, second = anchor_ailog_file(ailog, client=client)
        self.assertEqual(second, [])
        self.assertEqual(len(self.mock.chain.blocks), 1)

    def test_tampered_leaf_is_detected(self):
        ailog = _make_ailog_file(num=2)
        client = LocalChainClient(server_url=self.url, timeout=5.0)

        anchored, _ = anchor_ailog_file(ailog, client=client)
        # Simulate a tamper by mutating the chain state.
        self.mock.chain.tamper(bi=0, li=1)

        reports = verify_ailog_file(anchored, client=client)
        self.assertEqual(reports[0]["status"], "ok")
        self.assertEqual(reports[1]["status"], "tampered")
        self.assertFalse(reports[1]["valid"])

    def test_verify_reports_unanchored(self):
        ailog = _make_ailog_file(num=1)
        client = LocalChainClient(server_url=self.url, timeout=5.0)
        # Don't anchor; verify should report unanchored.
        reports = verify_ailog_file(ailog, client=client)
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["status"], "unanchored")

    def test_anchor_idempotency_via_custom(self):
        ailog = _make_ailog_file(num=1)
        client = LocalChainClient(server_url=self.url, timeout=5.0)

        anchor_ailog_file(ailog, client=client)
        anchor_meta = ailog.interactions[0].custom["localchain_anchor"]

        # Force a second anchor attempt with only_unanchored=False
        anchor_ailog_file(ailog, client=client, only_unanchored=False)
        anchor_meta2 = ailog.interactions[0].custom["localchain_anchor"]

        # Re-anchoring updates index but leaf_hash should be the same
        # (record content is unchanged; only block_index advances).
        self.assertEqual(anchor_meta["leaf_hash"], anchor_meta2["leaf_hash"])
        self.assertEqual(anchor_meta2["block_index"], 1)


# ──────────────────────────────────────────────
# Optional integration test against the real LocalChain Node server
# ──────────────────────────────────────────────


def _find_local_chain_repo() -> Optional[Path]:
    env = os.environ.get("LOCAL_CHAIN_REPO")
    if env:
        p = Path(env).expanduser().resolve()
        if (p / "packages" / "server" / "index.js").is_file():
            return p
    sibling = Path(__file__).resolve().parent.parent.parent / "local-chain"
    if (sibling / "packages" / "server" / "index.js").is_file():
        return sibling
    return None


def _node_available() -> bool:
    return shutil.which("node") is not None


@unittest.skipUnless(_node_available() and _find_local_chain_repo() is not None,
                     "node + sibling local-chain repo not available")
class LocalChainBridgeRealServerTests(unittest.TestCase):
    proc: Optional[subprocess.Popen] = None
    tmp: Optional[Path] = None
    port: int = 0
    url: str = ""

    @classmethod
    def setUpClass(cls):
        repo = _find_local_chain_repo()
        assert repo is not None
        cls.port = _free_port()
        cls.tmp = Path(__file__).resolve().parent / f"_lc_tmp_{cls.port}"
        if cls.tmp.exists():
            shutil.rmtree(cls.tmp)
        cls.tmp.mkdir(parents=True, exist_ok=True)
        bootstrap = cls.tmp / "bootstrap.js"
        server_path = (repo / "packages" / "server").resolve()
        bootstrap.write_text(
            f"const {{ createServer }} = require({json.dumps(str(server_path))})\n"
            f"const port = {cls.port}\n"
            f"const dir = {json.dumps(str(cls.tmp / 'chain'))}\n"
            "createServer(dir, { port }).listen()\n",
            encoding="utf-8",
        )
        # node needs to resolve relative imports from the repo root
        cls.proc = subprocess.Popen(
            ["node", str(bootstrap)],
            cwd=str(repo),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        cls.url = f"http://127.0.0.1:{cls.port}"
        # Wait for /api/health to come up.
        deadline = time.time() + 15.0
        last_err: Optional[Exception] = None
        while time.time() < deadline:
            if cls.proc.poll() is not None:
                out = cls.proc.stdout.read().decode("utf-8", "replace") if cls.proc.stdout else ""
                raise RuntimeError(f"local-chain server died on startup: {out}")
            try:
                LocalChainClient(server_url=cls.url, timeout=1.0).health()
                return
            except Exception as e:
                last_err = e
                time.sleep(0.3)
        raise RuntimeError(f"local-chain server did not become healthy: {last_err}")

    @classmethod
    def tearDownClass(cls):
        if cls.proc is not None and cls.proc.poll() is None:
            cls.proc.terminate()
            try:
                cls.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.proc.kill()
        if cls.tmp is not None and cls.tmp.exists():
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_round_trip_against_real_server(self):
        ailog = _make_ailog_file(num=2)
        client = LocalChainClient(server_url=self.url, timeout=10.0)

        anchored, results = anchor_ailog_file(ailog, client=client)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.block_index >= 1 for r in results))

        reports = verify_ailog_file(anchored, client=client)
        for rep in reports:
            self.assertEqual(rep["status"], "ok", rep)


if __name__ == "__main__":
    unittest.main()

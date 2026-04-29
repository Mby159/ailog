"""Tests for DeepSearch engine."""

import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ailog.search.engine import (
    SearchChunk,
    IndexBuilder,
    SearchEngine,
    _TfidfBackend,
)
from ailog.core.models import AILogFile, AILogFileMetadata, Interaction, Message, Role, ContentType


FIXTURES = Path(__file__).parent / "fixtures"


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_test_ailog() -> AILogFile:
    """Create a small AILogFile for testing."""
    meta = AILogFileMetadata(
        source_platform="chatgpt",
        source_url="",
        exporter="test",
        export_timestamp="2026-04-29T10:00:00Z",
        tags=["test", "ai"],
    )
    interactions = [
        Interaction(
            id="ix_1",
            timestamp="2026-04-29T10:00:00Z",
            session_id="sess_1",
            turn_index=1,
            messages=[
                Message(role=Role.USER, content="What is machine learning?", content_type=ContentType.TEXT),
                Message(role=Role.ASSISTANT, content="Machine learning is a subset of artificial intelligence that enables systems to learn from data.", content_type=ContentType.TEXT),
            ],
        ),
        Interaction(
            id="ix_2",
            timestamp="2026-04-29T10:01:00Z",
            session_id="sess_1",
            turn_index=2,
            messages=[
                Message(role=Role.USER, content="How does it work?", content_type=ContentType.TEXT),
                Message(role=Role.ASSISTANT, content="It works by finding patterns in data using algorithms that improve automatically through experience.", content_type=ContentType.TEXT),
            ],
        ),
        Interaction(
            id="ix_3",
            timestamp="2026-04-29T10:02:00Z",
            session_id="sess_2",
            turn_index=1,
            messages=[
                Message(role=Role.ASSISTANT, content="Deep learning uses neural networks with many layers.", content_type=ContentType.TEXT),
            ],
        ),
    ]
    return AILogFile(ailog_version="0.1", metadata=meta, interactions=interactions)


def make_test_ailog_file(tmpdir: Path) -> Path:
    """Create a test .ailog file and return its path."""
    ailog = make_test_ailog()
    path = tmpdir / "test.ailog"
    ailog.save(str(path), fmt="jsonl")
    return path


# ── SearchChunk ───────────────────────────────────────────────────────────────

def test_search_chunk_serialization():
    chunk = SearchChunk(
        chunk_id="ix_test_1_m0_s0",
        text="Hello world, this is a test.",
        interaction_id="ix_test_1",
        session_id="sess_test",
        turn_index=1,
        role="assistant",
        platform="chatgpt",
        timestamp="2026-04-27T10:00:00Z",
        tags=["chatgpt", "test"],
        title="Test Session",
        url=None,
        chunk_index=0,
        similarity_score=0.95,
    )
    s = chunk.to_json()
    restored = SearchChunk.from_json(s)
    assert restored.chunk_id == chunk.chunk_id
    assert restored.text == chunk.text
    assert restored.similarity_score == 0.95


def test_search_chunk_from_json_minimal():
    s = '{"chunk_id":"x","text":"hi","interaction_id":"i","session_id":"s","turn_index":1,"role":"u","platform":"p","timestamp":"","tags":[],"title":"","url":null,"chunk_index":0,"similarity_score":0.0}'
    c = SearchChunk.from_json(s)
    assert c.chunk_id == "x"
    assert c.similarity_score == 0.0


# ── TfidfBackend ──────────────────────────────────────────────────────────────

def test_tfidf_backend_basic():
    backend = _TfidfBackend()
    texts = ["hello world", "foo bar baz", "hello foo world bar"]
    emb = backend.encode(texts)
    # Tfidf dimension = actual vocabulary size (not 5000 cap)
    assert emb.shape[0] == 3
    assert emb.shape[1] > 0
    assert emb.dtype == "float32"
    # Cosine similarity = 1 for identical text (each vector dot itself)
    norms = [emb[i] @ emb[i] for i in range(len(texts))]
    assert all(0.99 <= n <= 1.01 for n in norms)


def test_tfidf_backend_same_text():
    backend = _TfidfBackend()
    texts = ["machine learning algorithms", "machine learning algorithms"]
    emb = backend.encode(texts)
    # Identical texts → identical embeddings
    sim = emb[0] @ emb[1]
    assert sim > 0.99


# ── IndexBuilder ──────────────────────────────────────────────────────────────

def test_extract_chunks_from_ailog():
    """Test chunk extraction from an AILogFile."""
    builder = IndexBuilder(tempfile.mkdtemp())
    ailog = make_test_ailog()
    chunks = builder.extract_chunks(ailog)

    assert len(chunks) > 0, "Should extract at least one chunk"
    assert all(c.text.strip() for c in chunks), "No empty chunks"
    assert all(c.platform == "chatgpt" for c in chunks), "All should be chatgpt platform"


def test_split_into_chunks():
    """Test text splitting at sentence boundaries."""
    builder = IndexBuilder(tempfile.mkdtemp())
    # Short text: no split
    assert builder._split_into_chunks("short text") == ["short text"]
    # Long text: split
    long_text = "Hello world. This is a test. " * 20
    chunks = builder._split_into_chunks(long_text, max_chars=50)
    assert len(chunks) > 1, "Long text should be split"
    assert all(len(c) <= 50 for c in chunks), "All chunks <= max_chars"


def test_build_index_tfidf():
    """Test building a FAISS index with Tfidf backend."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        ailog_path = make_test_ailog_file(tmp)

        builder = IndexBuilder(tmp / "search_idx")
        result = builder.build([ailog_path], batch_size=8, force=True)

        assert result["status"] == "ok"
        assert result["chunks"] > 0
        assert result["backend"] == "sklearn-tfidf"
        assert result["new"] > 0
        # Check files
        idx_dir = builder.index_dir
        assert (idx_dir / "index.faiss").exists()
        assert (idx_dir / "meta.json").exists()
        assert (idx_dir / "chunks.jsonl").exists()


def test_rebuild_deduplicates():
    """Test that rebuilding doesn't duplicate chunks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        ailog_path = make_test_ailog_file(tmp)

        builder = IndexBuilder(tmp / "search_idx")
        builder.build([ailog_path], force=False)
        r2 = builder.build([ailog_path], force=False)

        assert r2["new"] == 0, "Should not duplicate existing chunks"


def test_force_rebuild():
    """Test that --force rebuilds from scratch."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        ailog_path = make_test_ailog_file(tmp)

        builder = IndexBuilder(tmp / "search_idx")
        builder.build([ailog_path], force=False)
        r = builder.build([ailog_path], force=True)

        assert r["new"] > 0, "Force rebuild should treat all as new"


# ── SearchEngine ──────────────────────────────────────────────────────────────

def test_search_returns_results():
    """Test that search finds relevant results."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        ailog_path = make_test_ailog_file(tmp)

        builder = IndexBuilder(tmp / "search_idx")
        builder.build([ailog_path], force=True)

        engine = SearchEngine(tmp / "search_idx")
        engine.load()

        results = engine.search("machine learning", top_k=3)
        assert len(results) > 0, "Should find results for relevant query"
        assert all(isinstance(r, SearchChunk) for r in results)
        assert all(r.similarity_score >= 0 for r in results)


def test_search_top_k_respects_limit():
    """Test that top_k parameter limits results."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        ailog_path = make_test_ailog_file(tmp)

        builder = IndexBuilder(tmp / "search_idx")
        builder.build([ailog_path], force=True)

        engine = SearchEngine(tmp / "search_idx")
        engine.load()

        results = engine.search("machine", top_k=2)
        assert len(results) <= 2


def test_search_scores_descending():
    """Test that results are sorted by score descending."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        ailog_path = make_test_ailog_file(tmp)

        builder = IndexBuilder(tmp / "search_idx")
        builder.build([ailog_path], force=True)

        engine = SearchEngine(tmp / "search_idx")
        engine.load()

        results = engine.search("neural network", top_k=5)
        if len(results) >= 2:
            for i in range(len(results) - 1):
                assert results[i].similarity_score >= results[i + 1].similarity_score


def test_get_context():
    """Test context retrieval around a matched chunk."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        ailog_path = make_test_ailog_file(tmp)

        builder = IndexBuilder(tmp / "search_idx")
        builder.build([ailog_path], force=True)

        engine = SearchEngine(tmp / "search_idx")
        engine.load()

        results = engine.search("machine learning", top_k=1)
        assert len(results) > 0
        ctx = engine.get_context(results[0], window=1)
        assert len(ctx) >= 1
        assert all(c.session_id == results[0].session_id for c in ctx)


def test_stats():
    """Test index statistics."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        ailog_path = make_test_ailog_file(tmp)

        builder = IndexBuilder(tmp / "search_idx")
        builder.build([ailog_path], force=True)

        engine = SearchEngine(tmp / "search_idx")
        stats = engine.stats()

        assert stats["chunk_count"] > 0
        assert "backend" in stats
        assert "dimension" in stats


if __name__ == "__main__":
    tests = [
        ("search_chunk_serialization", test_search_chunk_serialization),
        ("search_chunk_from_json_minimal", test_search_chunk_from_json_minimal),
        ("tfidf_backend_basic", test_tfidf_backend_basic),
        ("tfidf_backend_same_text", test_tfidf_backend_same_text),
        ("extract_chunks_from_ailog", test_extract_chunks_from_ailog),
        ("split_into_chunks", test_split_into_chunks),
        ("build_index_tfidf", test_build_index_tfidf),
        ("rebuild_deduplicates", test_rebuild_deduplicates),
        ("force_rebuild", test_force_rebuild),
        ("search_returns_results", test_search_returns_results),
        ("search_top_k_respects_limit", test_search_top_k_respects_limit),
        ("search_scores_descending", test_search_scores_descending),
        ("get_context", test_get_context),
        ("stats", test_stats),
    ]
    passed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS: {name}")
            passed += 1
        except Exception as e:
            print(f"FAIL: {name}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")

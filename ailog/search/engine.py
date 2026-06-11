"""
AILog DeepSearch — Semantic + Keyword Hybrid Search Engine

Provides natural-language search across .ailog files using:
  - Primary: sentence-transformers + FAISS (high-quality embeddings)
  - Fallback: sklearn TfidfVectorizer + FAISS (always works, no network)

Architecture:
  ailog/search/
    engine.py   — IndexBuilder + SearchEngine + SearchChunk + Embedding backends
    cli.py      — CLI subcommands

Usage:
  ailog search build [--ailog <path>] [--index-dir <dir>]
  ailog search query "<natural language query>" [--top-k 5] [--index-dir <dir>]
  ailog search rebuild [--ailog <path>] [--index-dir <dir>]
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from ailog.core.models import AILogFile


# ── Dataclass (must be before IndexBuilder) ───────────────────────────────────

@dataclass
class SearchChunk:
    """A searchable unit in the index."""
    chunk_id: str
    text: str
    interaction_id: str
    session_id: str
    turn_index: int
    role: str
    platform: str
    timestamp: str
    tags: List[str]
    title: str
    url: Optional[str]
    chunk_index: int
    similarity_score: float = 0.0

    def to_json(self) -> str:
        return json.dumps(
            {
                "chunk_id": self.chunk_id,
                "text": self.text,
                "interaction_id": self.interaction_id,
                "session_id": self.session_id,
                "turn_index": self.turn_index,
                "role": self.role,
                "platform": self.platform,
                "timestamp": self.timestamp,
                "tags": self.tags,
                "title": self.title,
                "url": self.url,
                "chunk_index": self.chunk_index,
                "similarity_score": self.similarity_score,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def from_json(s: str) -> "SearchChunk":
        d = json.loads(s)
        return SearchChunk(
            chunk_id=d["chunk_id"],
            text=d["text"],
            interaction_id=d["interaction_id"],
            session_id=d["session_id"],
            turn_index=d["turn_index"],
            role=d["role"],
            platform=d["platform"],
            timestamp=d["timestamp"],
            tags=d.get("tags", []),
            title=d.get("title", ""),
            url=d.get("url"),
            chunk_index=d.get("chunk_index", 0),
            similarity_score=d.get("similarity_score", 0.0),
        )


# ── Embedding Backends ─────────────────────────────────────────────────────────

_ST_MODEL = None  # global singleton for sentence-transformer model


def _get_embedding_backend():
    """
    Return the best available embedding backend.
    Priority: sentence-transformers > TfidfVectorizer
    """
    # Try sentence-transformers first
    try:
        from sentence_transformers import SentenceTransformer
        return _SentenceTransformerBackend()
    except Exception:
        pass

    # Fallback: TfidfVectorizer
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        return _TfidfBackend()
    except Exception:
        pass

    raise ImportError(
        "No search backend available. Install at least one of:\n"
        "  pip install sentence-transformers faiss-cpu  (recommended)\n"
        "  pip install scikit-learn faiss-cpu          (fallback)"
    )


class _SentenceTransformerBackend:
    """sentence-transformers + FAISS backend (primary)."""

    name = "sentence-transformers"

    def __init__(self):
        pass

    @property
    def dim(self) -> int:
        model = _load_sentence_transformer()
        return model.get_sentence_embedding_dimension()

    def encode(self, texts: List[str]) -> np.ndarray:
        model = _load_sentence_transformer()
        embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return embeddings.astype("float32")

    def batch_size(self) -> int:
        return 32


def _load_sentence_transformer():
    """Lazy-load the sentence-transformer model (singleton)."""
    global _ST_MODEL
    if _ST_MODEL is None:
        from sentence_transformers import SentenceTransformer
        _ST_MODEL = SentenceTransformer(
            "all-MiniLM-L6-v2",
            cache_folder=os.environ.get("SENTENCE_TRANSFORMERS_HOME"),
        )
    return _ST_MODEL


class _TfidfBackend:
    """sklearn TfidfVectorizer backend (fallback, no network required)."""

    name = "sklearn-tfidf"
    _vectorizer = None
    _fitted = False

    @property
    def dim(self) -> int:
        # Tfidf dimension is dynamic; use 5000 as upper bound for FAISS index
        return 5000

    def encode(self, texts: List[str]) -> np.ndarray:
        from sklearn.feature_extraction.text import TfidfVectorizer
        self._vectorizer = TfidfVectorizer(
            max_features=5000,
            ngram_range=(1, 3),
            min_df=1,
        )
        embeddings = self._vectorizer.fit_transform(texts).toarray().astype("float32")
        # Normalize for cosine similarity
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-8)
        return embeddings / norms


# ── Index Builder ─────────────────────────────────────────────────────────────

class IndexBuilder:
    """
    Build and manage the FAISS index from .ailog files.

    Data stored in index_dir/:
      index.faiss     — FAISS index (flat L2)
      meta.json       — index metadata
      chunks.jsonl    — all SearchChunks
      doc_ids.json    — chunk_id → FAISS position mapping
    """

    def __init__(self, index_dir: Path | str, ailog_paths: List[Path | str] | None = None):
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.ailog_paths = [Path(p) for p in (ailog_paths or [])]
        self._backend = None

    @property
    def backend(self):
        if self._backend is None:
            self._backend = _get_embedding_backend()
            print(f"Using embedding backend: {self._backend.name}", file=sys.stderr)
        return self._backend

    def extract_chunks(self, ailog: AILogFile) -> List[SearchChunk]:
        """Extract searchable chunks from an AILogFile."""
        chunks = []
        for ix in ailog.interactions:
            title = (
                ix.custom.get("chatgpt_title", "")
                or ix.custom.get("claude_title", "")
                or ix.custom.get("youtube_title", "")
                or ix.custom.get("bilibili_title", "")
                or ix.custom.get("notion_title", "")
                or ""
            )
            url = ix.custom.get("source_url", "")

            for msg_idx, msg in enumerate(ix.messages):
                if not msg.content or not msg.content.strip():
                    continue

                text = msg.content.strip()
                role = msg.role.value if msg.role else "unknown"
                sub_chunks = self._split_into_chunks(text, max_chars=500)

                for sub_idx, sub_text in enumerate(sub_chunks):
                    chunk = SearchChunk(
                        chunk_id=f"{ix.id}_m{msg_idx}_s{sub_idx}",
                        text=sub_text,
                        interaction_id=ix.id,
                        session_id=ix.session_id,
                        turn_index=ix.turn_index,
                        role=role,
                        platform=ailog.metadata.source_platform or "unknown",
                        timestamp=ix.timestamp or "",
                        tags=ailog.metadata.tags or [],
                        title=title,
                        url=url,
                        chunk_index=sub_idx,
                        similarity_score=0.0,
                    )
                    chunks.append(chunk)
        return chunks

    def _split_into_chunks(self, text: str, max_chars: int = 500) -> List[str]:
        """Split long text into smaller chunks at sentence boundaries."""
        if len(text) <= max_chars:
            return [text]
        # Split on sentence-ending punctuation
        sentences = re.split(r"(?<=[。！？.!?])\s+", text)
        chunks, current = [], ""
        for sent in sentences:
            if len(current) + len(sent) <= max_chars:
                current += sent
            else:
                if current:
                    chunks.append(current.strip())
                current = sent
        if current.strip():
            chunks.append(current.strip())
        return chunks or [text[:max_chars]]

    def build(
        self,
        ailog_paths: List[Path | str] | None = None,
        batch_size: int = 32,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Build or update the FAISS search index."""
        paths = [Path(p) for p in (ailog_paths or self.ailog_paths)]

        # Load existing chunks
        existing_chunks: Dict[str, SearchChunk] = {}
        if not force and (self.index_dir / "chunks.jsonl").exists():
            existing_chunks = self._load_existing_chunks()
            print(f"Loaded {len(existing_chunks)} existing chunks", file=sys.stderr)

        all_chunks = list(existing_chunks.values())
        new_count = 0

        for path in paths:
            if not path.exists():
                print(f"Warning: {path} not found, skipping", file=sys.stderr)
                continue
            try:
                ailog = AILogFile.load(path)
            except Exception as e:
                print(f"Warning: Failed to load {path}: {e}", file=sys.stderr)
                continue

            new_chunks = self.extract_chunks(ailog)
            for chunk in new_chunks:
                if chunk.chunk_id not in existing_chunks:
                    all_chunks.append(chunk)
                    new_count += 1
            print(f"  {path.name}: +{len(new_chunks)} chunks", file=sys.stderr)

        if not all_chunks:
            print("No chunks to index.", file=sys.stderr)
            return {"chunks": 0, "new": 0, "status": "empty"}

        # Embed and index
        dim = self.backend.dim
        print(f"Embedding {len(all_chunks)} chunks (dim={dim})...", file=sys.stderr)
        texts = [c.text for c in all_chunks]

        embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            batch_emb = self.backend.encode(batch)
            embeddings.append(batch_emb)
        embeddings = np.vstack(embeddings).astype("float32")

        # Track max L2 distance for score normalization
        max_l2 = float(np.max(np.linalg.norm(embeddings, axis=1)))

        import faiss
        index = faiss.IndexFlatL2(dim)
        index.add(embeddings)

        # Persist
        faiss.write_index(index, str(self.index_dir / "index.faiss"))
        with open(self.index_dir / "meta.json", "w", encoding="utf-8") as f:
            json.dump({
                "backend": self.backend.name,
                "dimension": dim,
                "chunk_count": len(all_chunks),
                "max_l2_distance": round(max_l2, 4),
                "version": "0.1",
            }, f, ensure_ascii=False, indent=2)

        with open(self.index_dir / "chunks.jsonl", "w", encoding="utf-8") as f:
            for chunk in all_chunks:
                f.write(chunk.to_json() + "\n")

        doc_ids = {c.chunk_id: idx for idx, c in enumerate(all_chunks)}
        with open(self.index_dir / "doc_ids.json", "w", encoding="utf-8") as f:
            json.dump(doc_ids, f)

        result = {
            "chunks": len(all_chunks),
            "new": new_count,
            "dimension": dim,
            "backend": self.backend.name,
            "status": "ok",
        }
        print(f"Index built: {result}", file=sys.stderr)
        return result

    def _load_existing_chunks(self) -> Dict[str, SearchChunk]:
        chunks = {}
        path = self.index_dir / "chunks.jsonl"
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                chunk = SearchChunk.from_json(line)
                chunks[chunk.chunk_id] = chunk
        return chunks


# ── Search Engine ──────────────────────────────────────────────────────────────

class SearchEngine:
    """
    Semantic search over .ailog files using FAISS.

    Usage:
        engine = SearchEngine("ailog/search/")
        engine.load()
        results = engine.search("how to implement RAG?", top_k=5)
    """

    def __init__(self, index_dir: Path | str):
        self.index_dir = Path(index_dir)
        self._backend = None
        self._index = None
        self._chunks: List[SearchChunk] = []
        self._meta: Dict[str, Any] = {}

    @property
    def backend(self):
        if self._backend is None:
            self._backend = _get_embedding_backend()
        return self._backend

    def load(self):
        """Load the index from disk."""
        import faiss
        meta_path = self.index_dir / "meta.json"
        if not meta_path.exists():
            raise FileNotFoundError(
                f"Index not found at {self.index_dir}. Run: ailog search build"
            )
        with open(meta_path, "r", encoding="utf-8") as f:
            self._meta = json.load(f)

        self._index = faiss.read_index(str(self.index_dir / "index.faiss"))

        self._chunks = []
        with open(self.index_dir / "chunks.jsonl", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                self._chunks.append(SearchChunk.from_json(line))

        print(
            f"Loaded index: {len(self._chunks)} chunks, backend={self._meta.get('backend', '?')}",
            file=sys.stderr,
        )

    def search(
        self,
        query: str,
        top_k: int = 5,
        filters: Dict[str, Any] | None = None,
    ) -> List[SearchChunk]:
        """
        Search with a natural-language query.

        Args:
            query: Natural language search query
            top_k: Number of results to return
            filters: Optional filters (platform, tags, session_id)

        Returns:
            List of SearchChunks sorted by relevance (descending)
        """
        if self._index is None:
            self.load()

        query_emb = self.backend.encode([query]).astype("float32")
        k = min(top_k * 4, len(self._chunks))
        distances, indices = self._index.search(query_emb, k)

        max_l2 = self._meta.get("max_l2_distance", 100.0)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(self._chunks):
                continue
            chunk = self._chunks[idx]
            score = max(0.0, 1.0 - (dist / max_l2 if max_l2 > 0 else 0.0))
            scored_chunk = SearchChunk(
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                interaction_id=chunk.interaction_id,
                session_id=chunk.session_id,
                turn_index=chunk.turn_index,
                role=chunk.role,
                platform=chunk.platform,
                timestamp=chunk.timestamp,
                tags=chunk.tags,
                title=chunk.title,
                url=chunk.url,
                chunk_index=chunk.chunk_index,
                similarity_score=round(score, 4),
            )

            # Apply filters
            if filters:
                skip = False
                if "platform" in filters and chunk.platform != filters["platform"]:
                    skip = True
                if "tags" in filters and not any(t in chunk.tags for t in filters["tags"]):
                    skip = True
                if "session_id" in filters and chunk.session_id != filters["session_id"]:
                    skip = True
                if skip:
                    continue

            results.append(scored_chunk)

        results.sort(key=lambda c: c.similarity_score, reverse=True)
        return results[:top_k]

    def get_context(
        self, chunk: SearchChunk, window: int = 2
    ) -> List[SearchChunk]:
        """Get surrounding chunks from the same session for context."""
        if self._index is None:
            self.load()

        session_chunks = sorted(
            [c for c in self._chunks if c.session_id == chunk.session_id],
            key=lambda c: (c.turn_index, c.chunk_index),
        )
        for i, c in enumerate(session_chunks):
            if c.chunk_id == chunk.chunk_id:
                start = max(0, i - window)
                end = min(len(session_chunks), i + window + 1)
                return session_chunks[start:end]
        return [chunk]

    def stats(self) -> Dict[str, Any]:
        """Return index statistics."""
        if self._index is None:
            self.load()
        return {
            "chunk_count": len(self._chunks),
            "backend": self._meta.get("backend", "unknown"),
            "dimension": self._meta.get("dimension", 0),
        }

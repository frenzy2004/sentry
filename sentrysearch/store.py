"""ChromaDB vector store."""

import hashlib
import os
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import chromadb


DEFAULT_DB_PATH = Path.home() / ".sentrysearch" / "db"
DB_PATH_ENV = "SENTRYSEARCH_DB_PATH"
LIBRARY_ROOT_ENV = "SENTRYSEARCH_LIBRARY_ROOT"


class BackendMismatchError(RuntimeError):
    """Raised when search backend/model doesn't match the indexed backend/model."""


def _collection_name(backend: str, model: str | None = None) -> str:
    """Return ChromaDB collection name for a backend and optional model."""
    if backend == "gemini":
        return "dashcam_chunks"
    if backend == "openrouter":
        suffix = _collection_safe_model_key(model or "google_gemini_2_5_flash")
        return _fit_collection_name(f"dashcam_chunks_openrouter_{suffix}")
    if model:
        return f"dashcam_chunks_local_{model}"
    # Legacy: local backend without model distinction
    return "dashcam_chunks_local"


def _collection_safe_model_key(model: str) -> str:
    """Return a Chroma collection-safe model suffix."""
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", model).strip("_-").lower()
    return safe or "default"


def _fit_collection_name(name: str) -> str:
    """Keep generated Chroma collection names within Chroma's length limit."""
    if len(name) <= 63:
        return name
    digest = hashlib.sha256(name.encode()).hexdigest()[:8]
    return f"{name[:54]}_{digest}"


def default_db_path() -> Path:
    """Return the configured Chroma DB path."""
    configured = os.environ.get(DB_PATH_ENV)
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_DB_PATH


@lru_cache(maxsize=256)
def _find_library_file(root: str, basename: str) -> str | None:
    """Find a file by basename under a configured portable library root."""
    root_path = Path(root)
    direct = root_path / basename
    if direct.is_file():
        return str(direct.resolve())

    basename_lower = basename.lower()
    try:
        for candidate in root_path.rglob("*"):
            if candidate.is_file() and candidate.name.lower() == basename_lower:
                return str(candidate.resolve())
    except OSError:
        return None
    return None


def remap_source_file(source_file: str) -> str:
    """Map indexed source paths to a local portable library when configured."""
    source_path = Path(source_file).expanduser()
    if source_path.is_file():
        return str(source_path.resolve())

    root = os.environ.get(LIBRARY_ROOT_ENV)
    if not root:
        return source_file

    root_path = Path(root).expanduser().resolve()
    parts = list(source_path.parts)
    lower_parts = [p.lower() for p in parts]
    candidates: list[Path] = []

    for idx, part in enumerate(lower_parts[:-1]):
        if part == "drive_videos" and lower_parts[idx + 1] == "library":
            candidates.append(root_path.joinpath(*parts[idx + 2:]))
            break

    candidates.append(root_path / source_path.name)

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())

    found = _find_library_file(str(root_path), source_path.name)
    return found or source_file


def detect_index(db_path: str | Path | None = None) -> tuple[str | None, str | None]:
    """Return ``(backend, model)`` for the first index with data.

    Returns ``(None, None)`` when no index contains data.
    Checks gemini first, then OpenRouter, then model-specific local
    collections, then the legacy ``dashcam_chunks_local`` collection
    (treated as qwen8b).
    """
    db_path = str(db_path or default_db_path())
    if not Path(db_path).exists():
        return None, None
    client = chromadb.PersistentClient(path=db_path)
    existing = {c.name for c in client.list_collections()}

    # Gemini first (default / legacy)
    if "dashcam_chunks" in existing:
        col = client.get_collection("dashcam_chunks")
        if col.count() > 0:
            return "gemini", None

    # OpenRouter Gemini caption indexes
    for name in sorted(existing):
        if name.startswith("dashcam_chunks_openrouter_"):
            col = client.get_collection(name)
            if col.count() > 0:
                meta = col.metadata or {}
                return "openrouter", meta.get("embedding_model")

    # Model-specific local collections (dashcam_chunks_local_<model>)
    for name in sorted(existing):
        if name.startswith("dashcam_chunks_local_"):
            col = client.get_collection(name)
            if col.count() > 0:
                meta = col.metadata or {}
                model = meta.get("embedding_model")
                if model is None:
                    model = name.removeprefix("dashcam_chunks_local_")
                return "local", model

    # Legacy local collection (no model suffix) — treat as qwen8b
    if "dashcam_chunks_local" in existing:
        col = client.get_collection("dashcam_chunks_local")
        if col.count() > 0:
            meta = col.metadata or {}
            return "local", meta.get("embedding_model", "qwen8b")

    return None, None


def detect_backend(db_path: str | Path | None = None) -> str | None:
    """Return the backend that has indexed data, or None if empty."""
    backend, _ = detect_index(db_path)
    return backend


def _make_chunk_id(source_file: str, start_time: float) -> str:
    """Deterministic chunk ID from source file + start time."""
    raw = f"{source_file}:{start_time}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class SentryStore:
    """Persistent vector store backed by ChromaDB."""

    def __init__(self, db_path: str | Path | None = None, backend: str = "gemini",
                 model: str | None = None):
        db_path = str(db_path or default_db_path())
        Path(db_path).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=db_path)
        self._backend = backend
        self._model = model
        # Separate collection per backend+model so incompatible vectors never mix.
        col_name = _collection_name(backend, model)
        metadata = {"hnsw:space": "cosine", "embedding_backend": backend}
        if model:
            metadata["embedding_model"] = model
        self._collection = self._client.get_or_create_collection(
            name=col_name,
            metadata=metadata,
        )

    @property
    def collection(self) -> chromadb.Collection:
        return self._collection

    def get_backend(self) -> str:
        """Return the backend this index was built with."""
        meta = self._collection.metadata or {}
        return meta.get("embedding_backend", "gemini")

    def get_model(self) -> str | None:
        """Return the model this index was built with, or None."""
        meta = self._collection.metadata or {}
        return meta.get("embedding_model")

    def check_backend(self, backend: str) -> None:
        """Raise BackendMismatchError if *backend* doesn't match the index."""
        indexed_backend = self.get_backend()
        if indexed_backend != backend:
            raise BackendMismatchError(
                f"This index was built with the {indexed_backend} backend. "
                f"Search with --backend {indexed_backend} or re-index with "
                f"--backend {backend}."
            )

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def add_chunk(
        self,
        chunk_id: str,
        embedding: list[float],
        metadata: dict,
    ) -> None:
        """Store a single chunk embedding with metadata.

        Required metadata keys: source_file, start_time, end_time.
        An indexed_at ISO timestamp is added automatically.
        """
        meta = {
            "source_file": metadata["source_file"],
            "start_time": float(metadata["start_time"]),
            "end_time": float(metadata["end_time"]),
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        }
        # Carry over any extra metadata the caller provides
        for key in metadata:
            if key not in meta and key != "embedding":
                meta[key] = metadata[key]

        self._collection.upsert(
            ids=[chunk_id],
            embeddings=[embedding],
            metadatas=[meta],
        )

    def add_chunks(self, chunks: list[dict]) -> None:
        """Batch-store chunks. Each dict must have 'embedding' and metadata keys."""
        now = datetime.now(timezone.utc).isoformat()
        ids = []
        embeddings = []
        metadatas = []

        for chunk in chunks:
            chunk_id = _make_chunk_id(chunk["source_file"], chunk["start_time"])
            ids.append(chunk_id)
            embeddings.append(chunk["embedding"])
            metadatas.append({
                "source_file": chunk["source_file"],
                "start_time": float(chunk["start_time"]),
                "end_time": float(chunk["end_time"]),
                "indexed_at": now,
            })

        self._collection.upsert(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def search(
        self,
        query_embedding: list[float],
        n_results: int = 5,
    ) -> list[dict]:
        """Return top N results with distances and metadata."""
        count = self._collection.count()
        if count == 0:
            return []

        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=min(n_results, count),
        )

        hits = []
        for i in range(len(results["ids"][0])):
            meta = results["metadatas"][0][i]
            distance = results["distances"][0][i]
            hit = {
                "source_file": remap_source_file(meta["source_file"]),
                "start_time": meta["start_time"],
                "end_time": meta["end_time"],
                "score": 1.0 - distance,  # cosine distance → similarity
                "distance": distance,
            }
            for key, value in meta.items():
                if key not in hit:
                    hit[key] = value
            hits.append(hit)
        return hits

    def is_indexed(self, source_file: str) -> bool:
        """Check whether any chunks from source_file are already stored."""
        results = self._collection.get(
            where={"source_file": source_file},
            limit=1,
        )
        return len(results["ids"]) > 0

    def has_chunk(self, chunk_id: str) -> bool:
        """Check whether a specific chunk ID is already stored."""
        results = self._collection.get(ids=[chunk_id], limit=1)
        return len(results["ids"]) > 0

    def make_chunk_id(self, source_file: str, start_time: float) -> str:
        """Return the deterministic chunk ID used by this store."""
        return _make_chunk_id(source_file, start_time)

    def remove_file(self, source_file: str) -> int:
        """Remove all chunks for a given source file. Returns count removed."""
        results = self._collection.get(where={"source_file": source_file})
        ids = results["ids"]
        if ids:
            self._collection.delete(ids=ids)
        return len(ids)

    def get_stats(self) -> dict:
        """Return store statistics."""
        total = self._collection.count()
        if total == 0:
            return {"total_chunks": 0, "unique_source_files": 0, "source_files": []}

        # Fetch all metadata (only the fields we need)
        all_meta = self._collection.get(include=["metadatas"])
        source_files = sorted({
            remap_source_file(m["source_file"])
            for m in all_meta["metadatas"]
        })
        return {
            "total_chunks": total,
            "unique_source_files": len(source_files),
            "source_files": source_files,
        }

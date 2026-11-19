"""RAG hybride sur le profil (cv.md, preferences.md...) : vecteurs + BM25, fusion RRF, reranking FlashRank.

Le profil ne contient que quelques dizaines de passages : un index numpy en mémoire (mis en cache
sur disque) est plus rapide et bien plus léger qu'une base vectorielle complète."""
import asyncio
import hashlib
import logging
import re
import threading
from collections import defaultdict

import numpy as np

from ..config import settings
from .embeddings import embed

log = logging.getLogger("radar.rag")
CHUNK_CHARS = 700


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _split_markdown(text: str, source: str) -> list[dict]:
    """Découpe par titres Markdown, puis par taille. Chaque chunk garde son titre (chunking contextuel)."""
    sections, title, buffer = [], "", []
    for line in text.splitlines():
        if line.startswith("#"):
            if buffer:
                sections.append((title, "\n".join(buffer).strip()))
            title, buffer = line.lstrip("# ").strip(), []
        else:
            buffer.append(line)
    if buffer:
        sections.append((title, "\n".join(buffer).strip()))
    chunks = []
    for title, body in sections:
        if not body:
            continue
        for start in range(0, len(body), CHUNK_CHARS):
            part = body[start:start + CHUNK_CHARS]
            chunks.append({"text": f"[{source} > {title}]\n{part}" if title else f"[{source}]\n{part}",
                           "source": source})
    return chunks


class ProfileIndex:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hash: str | None = None
        self.chunks: list[dict] = []
        self._bm25 = None
        self._vectors: np.ndarray | None = None
        self._ranker = None
        self._ranker_failed = False
        self._building = False

    def build(self, force: bool = False) -> None:
        with self._lock:
            files = sorted(settings.profile_dir.glob("*.md"))
            texts = [(p.name, p.read_text(encoding="utf-8")) for p in files]
            digest = hashlib.sha256("".join(n + t for n, t in texts).encode()).hexdigest()
            if not force and digest == self._hash:
                return
            chunks = [c for name, text in texts for c in _split_markdown(text, name)]

            from rank_bm25 import BM25Okapi

            cache = settings.data_dir / "profile_index.npz"
            vectors = None
            if cache.exists():
                stored = np.load(cache)
                if str(stored["digest"]) == digest:
                    vectors = stored["vectors"]
            if vectors is None:
                vectors = embed([c["text"] for c in chunks]) if chunks else np.zeros((0, 1), dtype=np.float32)
                np.savez(cache, digest=digest, vectors=vectors)
            self.chunks = chunks
            self._bm25 = BM25Okapi([_tokens(c["text"]) for c in chunks]) if chunks else None
            self._vectors = vectors
            self._hash = digest
            log.info("Profil indexé : %s chunks", len(chunks))

    def _rerank(self, query: str, ids: list[int]) -> list[tuple[int, float]]:
        if not self._ranker_failed and self._ranker is None:
            try:
                from flashrank import Ranker
                self._ranker = Ranker(model_name=settings.reranker_model, cache_dir=str(settings.models_dir))
            except Exception as exc:  # noqa: BLE001
                log.warning("Reranker indisponible, ordre RRF conservé : %s", exc)
                self._ranker_failed = True
        if self._ranker is None:
            return [(i, 1.0 / (rank + 1)) for rank, i in enumerate(ids)]
        from flashrank import RerankRequest
        passages = [{"id": i, "text": self.chunks[i]["text"]} for i in ids]
        ranked = self._ranker.rerank(RerankRequest(query=query, passages=passages))
        return [(int(r["id"]), float(r["score"])) for r in ranked]

    def search(self, query: str, k: int = 3) -> list[dict]:
        if self._hash is None:
            self.build()
        if not self.chunks:
            return []
        n = min(8, len(self.chunks))
        vector = embed([query])[0]
        vector_ids = [int(i) for i in np.argsort(-(self._vectors @ vector))[:n]]
        bm25_ids = [int(i) for i in np.argsort(-self._bm25.get_scores(_tokens(query)))[:n]]

        fused = defaultdict(float)  # Reciprocal Rank Fusion
        for ranking in (vector_ids, bm25_ids):
            for rank, idx in enumerate(ranking):
                fused[idx] += 1.0 / (60 + rank + 1)
        candidates = sorted(fused, key=fused.get, reverse=True)[:8]
        return [{**self.chunks[i], "score": round(s, 4)} for i, s in self._rerank(query, candidates)[:k]]

    def build_in_background(self) -> None:
        if self._building:
            return
        self._building = True

        def run() -> None:
            try:
                self.build()
            except Exception as exc:  # noqa: BLE001
                log.warning("Indexation du profil reportée : %s", exc)
            finally:
                self._building = False
        threading.Thread(target=run, name="profile-index", daemon=True).start()

    def fallback(self) -> list[dict]:
        """Index pas encore prêt : on donne le début du CV tel quel (la notation n'attend jamais)."""
        cv = settings.profile_dir / "cv.md"
        text = cv.read_text(encoding="utf-8")[:2500] if cv.exists() else ""
        return [{"text": text, "source": "cv.md", "score": 0.0}] if text else []

    async def asearch(self, query: str, k: int = 3) -> list[dict]:
        if self._hash is None or not self._vectors_ready():
            self.build_in_background()
            return self.fallback()
        try:
            return await asyncio.to_thread(self.search, query, k)
        except Exception as exc:  # noqa: BLE001
            log.warning("Recherche profil échouée : %s", exc)
            return self.fallback()

    def _vectors_ready(self) -> bool:
        return self._vectors is not None


profile_index = ProfileIndex()

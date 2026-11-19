"""Embeddings locaux (fastembed / ONNX, multilingue, sans torch ni API payante)."""
import asyncio
import threading
import time

import numpy as np

from ..config import settings

_model = None
_lock = threading.Lock()
_failed_at = 0.0
RETRY_AFTER_S = 300


def _get_model():
    """Charge le modèle une seule fois, sans jamais faire attendre un appel pendant le chargement :
    si un autre fil le télécharge déjà, on échoue tout de suite (l'appelant a une solution de repli).
    Après un échec (pas de réseau), on ne réessaie pas avant 5 minutes."""
    global _model, _failed_at
    if _model is not None:
        return _model
    if _failed_at and time.monotonic() - _failed_at < RETRY_AFTER_S:
        raise RuntimeError("Modèle d'embeddings indisponible (nouvel essai plus tard)")
    if not _lock.acquire(blocking=False):
        raise RuntimeError("Modèle d'embeddings en cours de chargement")
    try:
        if _model is None:
            from fastembed import TextEmbedding
            _model = TextEmbedding(model_name=settings.embedding_model, cache_dir=str(settings.models_dir))
    except Exception:
        _failed_at = time.monotonic()
        raise
    finally:
        _lock.release()
    return _model


def is_ready() -> bool:
    return _model is not None


def embed(texts: list[str]) -> np.ndarray:
    """Vecteurs normalisés : le produit scalaire donne directement la similarité cosinus."""
    vectors = np.array(list(_get_model().embed(texts)), dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.clip(norms, 1e-9, None)


async def aembed(texts: list[str]) -> np.ndarray:
    return await asyncio.to_thread(embed, texts)

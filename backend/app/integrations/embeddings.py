"""Embedding service backing the pgvector columns.

Two providers, selected by ``EMBEDDING_PROVIDER``:

``hash`` (default)
    A deterministic, dependency-free hashed bag-of-ngrams projection with light
    stemming. Zero network calls, zero model download, identical vectors on every
    machine - which is what a reproducible demo seed needs.

    It is lexical, not semantic: it matches shared vocabulary, so it ranks well
    *within* a filtered topic (how the agent uses it) but will not connect
    unrelated wordings. For genuine semantic search, switch to ``fastembed``.

``fastembed``
    A real local ONNX sentence-transformer (BAAI/bge-small-en-v1.5 by default).
    No API key, no external service; the model is downloaded once.

Both return unit-norm vectors of ``EMBEDDING_DIMENSIONS`` floats, so the provider
can be swapped through configuration without touching the schema.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import re
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "to",
        "of",
        "in",
        "on",
        "at",
        "for",
        "with",
        "it",
        "this",
        "that",
        "i",
        "we",
        "my",
        "our",
        "you",
        "your",
        "they",
        "he",
        "she",
        "as",
        "so",
        "very",
        "too",
    }
)


#: Order matters - longest suffix first, so "waiting" -> "wait" not "waitin".
_SUFFIXES = ("ingly", "edly", "ing", "ied", "ies", "ed", "es", "ly", "s")


def stem(token: str) -> str:
    """Crude suffix stripper.

    Not linguistically correct, and does not need to be: its only job is to make
    "waited", "waiting" and "waits" collide on one feature so a search for
    "waiting too long" retrieves a review that says "waited 20 minutes".
    """
    for suffix in _SUFFIXES:
        if len(token) > len(suffix) + 2 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def tokenize(text: str) -> list[str]:
    return [stem(t) for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]


def char_ngrams(token: str, n: int = 4) -> list[str]:
    """Sub-word features so near-miss vocabulary still shares signal."""
    if len(token) <= n:
        return [token]
    padded = f"^{token}$"
    return [padded[i : i + n] for i in range(len(padded) - n + 1)]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class EmbeddingService:
    def __init__(self) -> None:
        self._model: Any = None
        self._initialised = False

    @property
    def dimensions(self) -> int:
        return settings.embedding_dimensions

    @property
    def provider(self) -> str:
        return settings.embedding_provider

    # ------------------------------------------------------------------ hashing
    def _hash_embed(self, text: str) -> list[float]:
        """Hash stemmed words, word bigrams and character 4-grams into a fixed vector.

        Signs are hashed as well as positions so collisions cancel instead of always
        reinforcing, which keeps unrelated documents near-orthogonal.
        """
        dims = self.dimensions
        vector = [0.0] * dims
        tokens = tokenize(text)
        if not tokens:
            return vector

        # (feature, weight) - word features dominate, sub-word features add recall.
        features: list[tuple[str, float]] = [(t, 1.0) for t in tokens]
        features.extend((f"{a}_{b}", 1.4) for a, b in itertools.pairwise(tokens))
        # Sub-word features only help for longer words, and are deliberately
        # low-weight: at higher weight they swamp the word-level signal.
        for token in tokens:
            if len(token) >= 6:
                features.extend((f"#{g}", 0.22) for g in char_ngrams(token))

        for feature, weight in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % dims
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign * weight

        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            return vector
        return [v / norm for v in vector]

    # ------------------------------------------------------------------ fastembed
    def _ensure_model(self) -> Any:
        if self._initialised:
            return self._model
        self._initialised = True
        if settings.embedding_provider != "fastembed":
            return None
        try:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=settings.embedding_model)
            log.info("embeddings_ready", provider="fastembed", model=settings.embedding_model)
        except Exception as exc:
            self._model = None
            log.warning(
                "fastembed_unavailable",
                detail=str(exc)[:200],
                fallback="hash",
            )
        return self._model

    # ------------------------------------------------------------------ public
    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._ensure_model()
        if model is None:
            return [self._hash_embed(t) for t in texts]
        try:
            vectors = [list(map(float, v)) for v in model.embed(texts)]
            # Keep the stored width honest even if the model differs from config.
            return [self._fit(v) for v in vectors]
        except Exception as exc:
            log.warning("embedding_failed", detail=str(exc)[:200], fallback="hash")
            return [self._hash_embed(t) for t in texts]

    def _fit(self, vector: list[float]) -> list[float]:
        dims = self.dimensions
        if len(vector) == dims:
            return vector
        if len(vector) > dims:
            return vector[:dims]
        return vector + [0.0] * (dims - len(vector))

    def similarity(self, a: str, b: str) -> float:
        va, vb = self.embed_batch([a, b])
        return cosine_similarity(va, vb)


embedding_service = EmbeddingService()

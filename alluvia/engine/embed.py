from __future__ import annotations
import hashlib
import math
from typing import Protocol


class Embedder(Protocol):
    dim: int
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FastEmbedEmbedder:
    """Local ONNX embeddings; no data leaves the machine. Model loads lazily on first
    embed() so building an engine is cheap (read-only commands never load it)."""
    def __init__(self, model: str = "BAAI/bge-small-en-v1.5"):
        self._model_name = model
        self._model = None
        self.dim = 384

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            from fastembed import TextEmbedding
            self._model = TextEmbedding(model_name=self._model_name)
        return [list(map(float, v)) for v in self._model.embed(texts)]


class FakeEmbedder:
    """Deterministic hash-based vectors for tests."""
    def __init__(self, dim: int = 8):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            vec = []
            for j in range(self.dim):
                h = hashlib.sha256(f"{j}:{t}".encode("utf-8")).digest()
                vec.append((int.from_bytes(h[:4], "big") / 2**32) - 0.5)
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / norm for x in vec])
        return out

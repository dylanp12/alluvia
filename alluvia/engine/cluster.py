from __future__ import annotations


def cluster(vectors: list[list[float]], min_cluster_size: int = 2) -> list[int]:
    """Return a cluster label per vector; -1 = noise."""
    n = len(vectors)
    if n < min_cluster_size:
        return [-1] * n
    import numpy as np
    import hdbscan
    X = np.asarray(vectors, dtype="float64")
    X = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)  # cosine ~ euclidean on unit vecs
    labels = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size, min_samples=1, metric="euclidean"
    ).fit_predict(X)
    return [int(x) for x in labels]

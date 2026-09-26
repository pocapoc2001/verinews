import os
import sys
import zlib

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def fake_embed(texts, dims=512):
    """Deterministic bag-of-words embedder: cosine similarity reflects word
    overlap, which is all the TVS tests need. No model download, no torch."""
    vectors = []
    for text in texts:
        vec = np.zeros(dims)
        for word in str(text).lower().split():
            token = word.strip(".,;:!?()\"'")
            if token:
                vec[zlib.crc32(token.encode()) % dims] += 1.0
        norm = np.linalg.norm(vec)
        vectors.append(vec / norm if norm else vec)
    return np.array(vectors)


@pytest.fixture
def pipeline(monkeypatch):
    """The Alex1 module with the SBERT encoder replaced by the fake embedder."""
    import Alex1

    monkeypatch.setattr(Alex1, "encode_texts_cached", fake_embed)
    monkeypatch.setattr(Alex1, "get_embedding_model", lambda: (_ for _ in ()).throw(AssertionError("model must not load in tests")))
    return Alex1

from sentence_transformers import SentenceTransformer, util

MODEL_NAME = "all-MiniLM-L6-v2"

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def cosine_similarity(text_a: str, text_b: str) -> float:
    """Embed two texts and return their cosine similarity, clipped to [0, 1]."""
    model = _get_model()
    embeddings = model.encode([text_a, text_b])
    similarity = float(util.cos_sim(embeddings[0], embeddings[1])[0][0])
    return max(0.0, min(1.0, similarity))

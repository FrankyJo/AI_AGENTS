"""
Етап 2, крок 2: той самий контракт (retrieve/as_context), що й
domain/knowledge.py, але зверху реального індексу — усього тексту ПДР і
Закону «Про Національну поліцію», зібраного в ingest.py.

Перед першим використанням:  python ingest.py

    python knowledge_qdrant.py "твоє питання"
"""

import pathlib
import sys

from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

ROOT = pathlib.Path(__file__).parent
QDRANT_PATH = str(ROOT / "qdrant_data")
COLLECTION = "laws"
MODEL_NAME = "intfloat/multilingual-e5-small"
# той самий поріг, що в knowledge_vec.py з module2 — для e5 косинуси
# зсунуті вгору; тюнити на власних запитах, не переносити між моделями
THRESHOLD = 0.78

_model = None
_client = None


def _encode(text: str, kind: str) -> list[float]:
    """kind: 'query' | 'passage' — префікс потрібен моделям e5."""
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model.encode([f"{kind}: {text}"], normalize_embeddings=True)[0].tolist()


def _client_() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(path=QDRANT_PATH)
        if not _client.collection_exists(COLLECTION):
            raise SystemExit(f"Індекс не знайдено ({QDRANT_PATH}). Спершу:  python ingest.py")
    return _client


def retrieve(query: str, k: int = 6) -> list:
    """Той самий контракт, що в domain/knowledge.py — fail-closed за рахунок
    score_threshold на рівні БД. Кожен рядок — цитата + текст + посилання
    на точний абзац (реконструйовані з metadata, а не вирізані регексом
    із суцільного тексту, як було на PDF-етапі).

    k=6, не 3: корпус виріс із 2 документів до 40 (десятки тисяч чанків),
    і k=3 почав систематично пропускати найбільш релевантну статтю серед
    багатьох схожих — реальні випадки під час індексації партії 3 (ЦКУ,
    НАБУ). Якщо корпус ще зросте — наступний крок не "ще більший k", а
    hybrid search / reranker (README, розділ «Нюанси»)."""
    hits = _client_().query_points(
        COLLECTION, query=_encode(query, "query"), limit=k, score_threshold=THRESHOLD,
    ).points
    return [f"{h.payload['cite']}: {h.payload['text']} ({h.payload['source_url']})"
            for h in hits]


def as_context(query: str, k: int = 6) -> str:
    hits = retrieve(query, k)
    if not hits:
        return ""
    return "\n\nВитяг з бази знань:\n" + "\n---\n".join(hits)


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "При яких обставинах поліція має право зупинити мене на блокпосту?"
    print(f"Запит: «{q}»\n" + "─" * 70)
    hits = retrieve(q, 6)
    if not hits:
        print("— нічого понад поріг (fail-closed)")
    for t in hits:
        print("\n·", t[:400].replace("\n", " "))

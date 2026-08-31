"""
Індексація: crawler.py (живий текст з офіційного OpenData API) → db.py
(SQLite, нормалізовані documents/clauses) → Qdrant (векторний пошук,
payload з повними метаданими для точної цитати).

    python ingest.py            # проіндексувати всі TRACKED документи (один раз)
    python ingest.py --reset    # перебудувати повністю (усі документи разом —
                                 # див. README про точкове оновлення одного джерела)

Джерело тексту — офіційний OpenData API Верховної Ради (data.rada.gov.ua),
не локальні PDF: PDF старіють (реальний приклад із цього проєкту —
локальний ПДР відставав на ~5 років правок від чинної редакції).
Резервний варіант на випадок недоступності API — pdf_source.py (не
використовується зараз, README пояснює, як переключитися).

Пауза між запитами (5-7с, за рекомендацією порталу) вже вбудована в
crawler._get() — тут спеціально чекати не треба.
"""

import sys
import pathlib

from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer

import db
from crawler import TRACKED, cite, fetch_card, fetch_clauses, group_for_embedding

ROOT = pathlib.Path(__file__).parent
QDRANT_PATH = str(ROOT / "qdrant_data")
COLLECTION = "laws"
MODEL_NAME = "intfloat/multilingual-e5-small"
STATUS_CHYNNYI = 5


def main():
    reset = "--reset" in sys.argv
    client = QdrantClient(path=QDRANT_PATH)
    conn = db.get_conn()

    if client.collection_exists(COLLECTION):
        if not reset:
            n = client.count(COLLECTION).count
            print(f"Колекція «{COLLECTION}» вже існує ({n} точок) — індексацію пропущено.")
            print("Перебудувати:  python ingest.py --reset")
            return
        client.delete_collection(COLLECTION)
        # --reset скидає й SQLite: інакше документ, прибраний із TRACKED
        # (напр. виявився втратив чинність), лишається "осиротілим" рядком —
        # видно тільки в БД, не в живому пошуку, і це вводить в оману.
        conn.execute("DELETE FROM clauses")
        conn.execute("DELETE FROM documents")
        conn.commit()

    print("Завантажую документи з офіційного OpenData API (пауза ~6с між запитами)...")
    docs_data = []      # (doc, card, clauses)
    for doc in TRACKED:
        card = fetch_card(doc)
        # 5 = чинний (перевірено емпірично на реальних документах). Інший код —
        # ознака "втратив чинність" чи щось нетипове: реальний випадок із цього
        # проєкту — Господарський кодекс (status=1) насправді втратив чинність
        # 28.08.2025, а індексувався б як звичайний чинний акт, якби не ця
        # перевірка. Індексувати скасований закон — саме той ризик, заради
        # уникнення якого існує весь цей проєкт.
        if card["status_code"] != STATUS_CHYNNYI:
            print(f"  ⚠ ПРОПУЩЕНО: {doc['title']} — status_code={card['status_code']} "
                 f"(очікували {STATUS_CHYNNYI}, «чинний»). Перевір вручну на "
                 f"zakon.rada.gov.ua/laws/show/{doc['id']} перш ніж додавати.")
            continue
        clauses = fetch_clauses(doc)
        docs_data.append((doc, card, clauses))
        print(f"  {doc['title']}: {len(clauses)} клауз, редакція від {card['revision_date']}")

    # SQLite отримує повний, дрібний список (нижче) — для точних якорів/аудиту.
    # Qdrant — згрупований: пункти однієї частини/статті чи розділу разом,
    # інакше перелік підстав розсипається на випадкові окремі чанки.
    flat = [(c, doc["title"], card["source_url"])
            for doc, card, clauses in docs_data
            for c in group_for_embedding(clauses, doc["structure"])]
    for i, (c, _, _) in enumerate(flat):
        c["qdrant_id"] = i

    print(f"\nУсього клауз: {len(flat)}")
    print("Завантажую модель ембедингів (перший раз — довше, ~120 МБ)...")
    model = SentenceTransformer(MODEL_NAME)

    print("Рахую ембединги...")
    # у текст для ембедингу додаємо цитату (стаття/частина/пункт) — саме
    # вона дає модель контекст, якого немає в самому тексті пункту
    texts = [f"passage: {cite(c, title)}. {c['text']}" for c, title, _ in flat]
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=True)

    client.create_collection(
        COLLECTION,
        vectors_config=models.VectorParams(size=vectors.shape[1], distance=models.Distance.COSINE),
    )

    print("Заливаю в Qdrant...")
    points = [
        models.PointStruct(
            id=c["qdrant_id"], vector=vec.tolist(),
            payload={"text": c["text"], "cite": cite(c, title), "document_id": c["document_id"],
                     "title": title, "source_url": url + (c["anchor"] or "")},
        )
        for vec, (c, title, url) in zip(vectors, flat)
    ]
    client.upsert(COLLECTION, points=points)

    for doc, card, clauses in docs_data:
        db.upsert_document(conn, card)
        db.replace_clauses(conn, doc["id"], clauses)

    print(f"Готово: {QDRANT_PATH}/ ({COLLECTION}, {len(flat)} точок), SQLite: {db.DB_PATH}")


if __name__ == "__main__":
    main()

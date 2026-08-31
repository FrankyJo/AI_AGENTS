"""
РЕЗЕРВНИЙ джерело тексту — локальні PDF у pdf/, замість OpenData API.

Зараз НЕ використовується (ingest.py тягне живий текст із
data.rada.gov.ua). Залишений про запас: якщо офіційний API колись стане
недоступний, тут — робочий шлях назад до PDF, витягнутих pypdf і
розрізаних по межах статей/пунктів регексом (без анкорів на конкретний
абзац і без розділення на частину/пункт так тонко, як дає HTML API —
PDF-текст суцільний, посилання можна дати лише на весь документ).

Щоб ним скористатися:
  1. Покладіть актуальний PDF у pdf/
  2. Замініть у ingest.py `from crawler import fetch_clauses`
     на `from pdf_source import fetch_clauses`
  3. python ingest.py --reset

    python pdf_source.py    # демо: скільки чанків витягнеться з pdf/
"""

import pathlib
import re

from pypdf import PdfReader

ROOT = pathlib.Path(__file__).parent
PDF_DIR = ROOT / "pdf"

# ключовий фрагмент назви файлу → відповідний запис у crawler.TRACKED
SOURCES = {
    "Правила дорожнього руху": "1306-2001-п",
    "Національну поліцію": "580-19",
}

CLAUSE_RE = re.compile(r"(?=\n\s*(?:Стаття\s+\d+[¹²³\d]*\.|\d{1,3}\.\d{1,3}\.\s))")
MAX_CHUNK_TOKENS = 350
OVERLAP_TOKENS = 60


def _tokens(text: str) -> int:
    return int(len(text.split()) * 1.3)


def _extract_text(pdf_path: pathlib.Path) -> str:
    reader = PdfReader(str(pdf_path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _word_window(text: str, size: int, overlap: int) -> list[str]:
    words = text.split()
    per_chunk = max(1, int(size / 1.3))
    step = max(1, int((size - overlap) / 1.3))
    out = []
    for start in range(0, len(words), step):
        piece = words[start:start + per_chunk]
        if not piece:
            break
        out.append(" ".join(piece))
        if start + per_chunk >= len(words):
            break
    return out


def _document_id(filename: str) -> str | None:
    for key, doc_id in SOURCES.items():
        if key in filename:
            return doc_id
    return None


def fetch_clauses(doc: dict) -> list[dict]:
    """Той самий контракт, що crawler.fetch_clauses(), але з PDF.
    Без anchor (PDF не дає точних якорів) і без section/part/point —
    лише межа статті/пункту через CLAUSE_RE."""
    pdf_path = next((p for p in PDF_DIR.glob("*.pdf") if _document_id(p.name) == doc["id"]), None)
    if not pdf_path:
        raise SystemExit(f"Не знайдено PDF для {doc['id']} у {PDF_DIR}/")

    text = _extract_text(pdf_path)
    raw_chunks = [c.strip() for c in CLAUSE_RE.split(text) if c.strip()]

    clauses = []
    for raw in raw_chunks:
        pieces = ([raw] if _tokens(raw) <= MAX_CHUNK_TOKENS
                 else _word_window(raw, MAX_CHUNK_TOKENS, OVERLAP_TOKENS))
        for piece in pieces:
            clauses.append({
                "document_id": doc["id"], "section": None, "chapter": None, "article": None,
                "part": None, "point": None, "subpoint": None,
                "text": piece, "anchor": None, "qdrant_id": None,
            })
    return clauses


if __name__ == "__main__":
    from crawler import TRACKED
    for doc in TRACKED:
        try:
            clauses = fetch_clauses(doc)
            print(f"{doc['title']}: {len(clauses)} чанків (з PDF)")
        except SystemExit as e:
            print(f"{doc['title']}: {e}")

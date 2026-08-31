"""
Нормалізована БД — SQLite (не Postgres: кілька документів не виправдовують
сервер; схема сумісна за духом, апгрейд пізніше — це заміна connection
string, якщо колись знадобиться).

  documents — один рядок на акт: номер, дати, статус, підстава редакції, URL
  clauses   — один рядок на абзац (розділ/глава/стаття/частина/пункт),
              з посиланням на конкретну точку в Qdrant

    from db import get_conn, upsert_document, replace_clauses
"""

import pathlib
import sqlite3

ROOT = pathlib.Path(__file__).parent
DB_PATH = ROOT / "laws.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id              TEXT PRIMARY KEY,      -- системний номер (nreg), напр. "580-19"
    title           TEXT NOT NULL,
    doc_type        TEXT NOT NULL,         -- "Закон" | "Кодекс" | "Постанова" | "Конституція" | ...
    structure       TEXT NOT NULL,         -- профіль парсера: "law" | "pdr" | "code"
    act_number      TEXT,                  -- офіційний номер акта, напр. "580-VIII"
    status_code     INTEGER,               -- код статусу з card.json (5 = чинний — перевірено emпірично)
    adopted_date    TEXT,                  -- дата прийняття, "02.07.2015"
    revision_date   TEXT,                  -- дата поточної редакції, "12.04.2026"
    revision_basis  TEXT,                  -- номер акта, яким внесено поточну редакцію
    source_url      TEXT NOT NULL,
    last_checked_at TEXT                   -- коли востаннє перевіряли на оновлення
);

CREATE TABLE IF NOT EXISTS clauses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id   TEXT NOT NULL REFERENCES documents(id),
    section       TEXT,     -- розділ (ПДР: арабська; code: римська)
    chapter       TEXT,     -- глава (лише в code, не завжди є)
    article       TEXT,     -- стаття (law, code) / без аналога в ПДР
    part          TEXT,     -- частина ("1", "2"...)
    point         TEXT,     -- пункт (ПДР "12.4" чи "1)")
    subpoint      TEXT,     -- підпункт ("а)", "б)"...)
    text          TEXT NOT NULL,
    anchor        TEXT,     -- #nXXX на сторінці zakon.rada.gov.ua — точний абзац
    qdrant_id     INTEGER   -- id відповідної точки в Qdrant
);

CREATE INDEX IF NOT EXISTS idx_clauses_document ON clauses(document_id);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert_document(conn: sqlite3.Connection, doc: dict) -> None:
    conn.execute(
        """INSERT INTO documents (id, title, doc_type, structure, act_number, status_code,
                                  adopted_date, revision_date, revision_basis, source_url,
                                  last_checked_at)
           VALUES (:id, :title, :doc_type, :structure, :act_number, :status_code,
                   :adopted_date, :revision_date, :revision_basis, :source_url,
                   :last_checked_at)
           ON CONFLICT(id) DO UPDATE SET
               title=excluded.title, doc_type=excluded.doc_type, structure=excluded.structure,
               act_number=excluded.act_number, status_code=excluded.status_code,
               adopted_date=excluded.adopted_date, revision_date=excluded.revision_date,
               revision_basis=excluded.revision_basis, source_url=excluded.source_url,
               last_checked_at=excluded.last_checked_at""",
        doc,
    )
    conn.commit()


def replace_clauses(conn: sqlite3.Connection, document_id: str, clauses: list[dict]) -> None:
    """Повна заміна пунктів документа (простіше й надійніше за diff по рядках)."""
    conn.execute("DELETE FROM clauses WHERE document_id = ?", (document_id,))
    conn.executemany(
        """INSERT INTO clauses (document_id, section, chapter, article, part, point, subpoint,
                                text, anchor, qdrant_id)
           VALUES (:document_id, :section, :chapter, :article, :part, :point, :subpoint,
                   :text, :anchor, :qdrant_id)""",
        clauses,
    )
    conn.commit()


def get_document(conn: sqlite3.Connection, document_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()


def all_documents(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM documents").fetchall()

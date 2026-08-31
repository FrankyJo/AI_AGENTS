"""
Щоденна перевірка нових редакцій відслідковуваних документів.

Порівнює revision_date з картки документа (crawler.fetch_card, офіційний
OpenData API) із тим, що востаннє збережено в SQLite (db.py). Лише
повідомляє про зміну — автоматично не переіндексовує: юридичний текст
вартий перегляду людиною перед тим, як замінювати базу знань агента.

    python watch.py               # разова перевірка, друк у консоль
"""

import db
from crawler import TRACKED, fetch_card


def check_for_updates() -> list[dict]:
    """Повертає список документів, у яких дата редакції змінилася відтоді,
    як ми востаннє індексували. Кожен запис — {title, old, new, url}."""
    conn = db.get_conn()
    changed = []

    for doc in TRACKED:
        known = db.get_document(conn, doc["id"])
        card = fetch_card(doc)

        if known and known["revision_date"] != card["revision_date"]:
            changed.append({
                "title": doc["title"], "old": known["revision_date"],
                "new": card["revision_date"], "url": card["source_url"],
            })

        # оновлюємо тільки last_checked_at — revision_date лишаємо старим
        # (тим, що реально проіндексовано), поки хтось не запустить ingest --reset
        conn.execute("UPDATE documents SET last_checked_at = ? WHERE id = ?",
                     (card["last_checked_at"], doc["id"]))
        conn.commit()

    return changed


if __name__ == "__main__":
    updates = check_for_updates()
    if not updates:
        print("Змін немає — усі відслідковувані документи в тій редакції, що й у індексі.")
    for u in updates:
        print(f"Нова редакція: «{u['title']}» — {u['old']} → {u['new']}\n  {u['url']}")

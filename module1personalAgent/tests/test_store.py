"""
Тести storage/store.py (SQLite-бекенд) — round-trip load/save/delete/list_chat_ids.
Підміняє store.DB_PATH на тимчасовий файл, щоб не чіпати реальну storage/data/app.db.

    python -m unittest tests.test_store -v
"""

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from storage import store


class TestStore(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig_db_path = store.DB_PATH
        store.DB_PATH = pathlib.Path(self.tmp.name) / "test.db"
        store._init_db()

    def tearDown(self):
        store.DB_PATH = self._orig_db_path
        self.tmp.cleanup()

    def test_load_missing_chat_id_returns_default(self):
        data = store.load("nobody")
        self.assertEqual(data, store.DEFAULT)
        self.assertIsNot(data, store.DEFAULT)              # deepcopy — не той самий об'єкт

    def test_save_then_load_roundtrips(self):
        data = store.load("u1")
        data["profile"]["name"] = "Тест"
        store.save("u1", data)
        self.assertEqual(store.load("u1")["profile"]["name"], "Тест")

    def test_save_overwrites_existing_row(self):
        store.save("u1", {"profile": {"name": "A"}})
        store.save("u1", {"profile": {"name": "B"}})
        self.assertEqual(store.load("u1")["profile"]["name"], "B")

    def test_delete_removes_user(self):
        store.save("u1", {"profile": {"name": "A"}})
        store.delete("u1")
        self.assertEqual(store.load("u1"), store.DEFAULT)

    def test_delete_missing_user_is_a_noop(self):
        store.delete("nobody")

    def test_list_chat_ids_reflects_saved_users(self):
        store.save("u1", {"profile": {}})
        store.save("u2", {"profile": {}})
        self.assertEqual(set(store.list_chat_ids()), {"u1", "u2"})

    def test_list_chat_ids_empty_by_default(self):
        self.assertEqual(store.list_chat_ids(), [])


if __name__ == "__main__":
    unittest.main()

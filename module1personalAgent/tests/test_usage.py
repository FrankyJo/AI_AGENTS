"""
Тести логу витрат API: storage/usage_log.py + core/cost.aggregate. Пишуть у
тимчасовий файл, не в справжній storage/data/usage_log.jsonl.

    python -m unittest tests.test_usage -v
"""

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from core import cost
from storage import usage_log


class TestUsageLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tmp.name) / "usage_log.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_and_read_all_roundtrip(self):
        usage_log.append("111", {"claude-sonnet-4-6": {"calls": 1, "in": 100, "out": 50}}, path=self.path)
        usage_log.append("222", {"claude-sonnet-4-6": {"calls": 2, "in": 200, "out": 80}}, path=self.path)

        records = usage_log.read_all(path=self.path)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["chat_id"], "111")
        self.assertEqual(records[1]["by_model"]["claude-sonnet-4-6"]["in"], 200)

    def test_append_skips_empty_usage(self):
        """Прогін без жодного виклику API (напр. миттєвий api_error) -> нема що логувати."""
        usage_log.append("111", {}, path=self.path)
        self.assertEqual(usage_log.read_all(path=self.path), [])

    def test_for_chat_returns_only_that_chats_records(self):
        """Кілька чатів пишуть у спільний лог -> for_chat бачить лише свій chat_id, не чужі витрати."""
        usage_log.append("111", {"claude-sonnet-4-6": {"calls": 1, "in": 100, "out": 50}}, path=self.path)
        usage_log.append("222", {"claude-sonnet-4-6": {"calls": 5, "in": 900, "out": 300}}, path=self.path)
        usage_log.append("111", {"claude-sonnet-4-6": {"calls": 1, "in": 20, "out": 10}}, path=self.path)

        records = usage_log.for_chat("111", path=self.path)

        self.assertEqual(len(records), 2)
        self.assertTrue(all(r["chat_id"] == "111" for r in records))

    def test_read_all_on_missing_file_returns_empty_list(self):
        missing = self.path.parent / "does-not-exist.jsonl"
        self.assertEqual(usage_log.read_all(path=missing), [])

    def test_aggregate_sums_across_records_and_models(self):
        records = [
            {"by_model": {"claude-sonnet-4-6": {"calls": 1, "in": 100, "out": 50}}},
            {"by_model": {"claude-sonnet-4-6": {"calls": 1, "in": 200, "out": 40},
                           "claude-haiku-4-5-20251001": {"calls": 1, "in": 30, "out": 10}}},
        ]

        total = cost.aggregate(records)

        self.assertEqual(total["claude-sonnet-4-6"],
                          {"calls": 2, "in": 300, "out": 90, "cache_write": 0, "cache_read": 0})
        self.assertEqual(total["claude-haiku-4-5-20251001"],
                          {"calls": 1, "in": 30, "out": 10, "cache_write": 0, "cache_read": 0})

    def test_aggregate_then_usd_matches_known_price(self):
        """1M вхідних + 1M вихідних токенів sonnet -> $3.00 + $15.00 за прайсом з core/cost.py."""
        records = [{"by_model": {"claude-sonnet-4-6": {"calls": 1, "in": 1_000_000, "out": 1_000_000}}}]
        total = cost.aggregate(records)
        self.assertAlmostEqual(cost.usd(total), 3.00 + 15.00)

    def test_cache_write_costs_more_than_plain_input(self):
        """Запис у кеш дорожчий за звичайний input (1.25x) — інакше немає сенсу
        відрізняти його від звичайного in."""
        plain = cost.usd({"claude-sonnet-4-6": {"in": 1_000_000, "out": 0}})
        cache_write = cost.usd({"claude-sonnet-4-6": {"in": 0, "out": 0, "cache_write": 1_000_000}})
        self.assertAlmostEqual(cache_write, plain * 1.25)

    def test_cache_read_costs_a_tenth_of_plain_input(self):
        """Читання з кешу — головна економія від prompt caching: ~10% ціни звичайного input."""
        plain = cost.usd({"claude-sonnet-4-6": {"in": 1_000_000, "out": 0}})
        cache_read = cost.usd({"claude-sonnet-4-6": {"in": 0, "out": 0, "cache_read": 1_000_000}})
        self.assertAlmostEqual(cache_read, plain * 0.1)


if __name__ == "__main__":
    unittest.main()

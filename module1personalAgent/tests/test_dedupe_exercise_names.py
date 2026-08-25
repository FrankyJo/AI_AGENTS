"""
Тести scripts/dedupe_exercise_names.py — кластеризація схожих назв вправ і
вибір канонічної форми, без storage/store.py (чисті функції на словниках).

    python -m unittest tests.test_dedupe_exercise_names -v
"""

import collections
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from scripts import dedupe_exercise_names as dedupe


class TestClusterNames(unittest.TestCase):

    def test_groups_similar_names_together(self):
        names = ["Горизонтальна тяга", "Горизонтальная тяга", "Присідання"]
        groups = dedupe.cluster_names(names)
        self.assertEqual(len(groups), 1)
        self.assertEqual(set(groups[0]), {"Горизонтальна тяга", "Горизонтальная тяга"})

    def test_dissimilar_names_stay_separate(self):
        names = ["Присідання", "Жим лежачи", "Тяга"]
        self.assertEqual(dedupe.cluster_names(names), [])

    def test_transitively_groups_a_chain_of_similar_names(self):
        """A схожий на B, B схожий на C -> усі три в одному кластері, навіть якщо A і C самі по собі не дуже схожі."""
        names = ["Гіперекстензія", "Гиперэкстензія", "Гиперэкстензии"]
        groups = dedupe.cluster_names(names)
        self.assertEqual(len(groups), 1)
        self.assertEqual(set(groups[0]), set(names))


class TestPickCanonical(unittest.TestCase):

    def test_prefers_catalog_exact_match(self):
        catalog_name = next(iter(dedupe.CATALOG_NAMES))
        group = [catalog_name, catalog_name + "!"]
        canonical = dedupe.pick_canonical(group, collections.Counter(), {})
        self.assertEqual(canonical, catalog_name)

    def test_prefers_the_variant_seen_earliest_in_history(self):
        group = ["Горизонтальна тяга", "Горизонтальная тяга"]
        first_seen = {"Горизонтальна тяга": "2026-08-19", "Горизонтальная тяга": "2026-08-24"}
        canonical = dedupe.pick_canonical(group, collections.Counter(), first_seen)
        self.assertEqual(canonical, "Горизонтальна тяга")

    def test_falls_back_to_most_frequent_when_no_history_dates(self):
        group = ["Присідання А", "Присідання Б"]
        counts = collections.Counter({"Присідання А": 1, "Присідання Б": 3})
        canonical = dedupe.pick_canonical(group, counts, {})
        self.assertEqual(canonical, "Присідання Б")


class TestApplyRename(unittest.TestCase):

    def test_renames_in_program_and_history_and_dedupes_program_day(self):
        data = {
            "program": {"days": [{"day": "День 1", "exercises": [
                {"name": "Горизонтальна тяга"}, {"name": "Горизонтальная тяга"}]}]},
            "history": [{"date": "2026-08-24", "exercises": [{"name": "Горизонтальная тяга"}]}],
        }
        rename_map = {"Горизонтальная тяга": "Горизонтальна тяга"}

        renamed = dedupe.apply_rename(data, rename_map)

        self.assertEqual(renamed, 2)
        self.assertEqual([e["name"] for e in data["program"]["days"][0]["exercises"]],
                          ["Горизонтальна тяга"])
        self.assertEqual(data["history"][0]["exercises"][0]["name"], "Горизонтальна тяга")

    def test_does_not_touch_names_outside_rename_map(self):
        data = {"program": {"days": [{"day": "День 1", "exercises": [{"name": "Присідання"}]}]},
                "history": []}
        dedupe.apply_rename(data, {"Горизонтальная тяга": "Горизонтальна тяга"})
        self.assertEqual(data["program"]["days"][0]["exercises"][0]["name"], "Присідання")


class TestRemoveHistoryDates(unittest.TestCase):

    def test_removes_only_matching_dates(self):
        data = {"history": [
            {"date": "2024-08-19", "exercises": []},
            {"date": "2026-08-19", "exercises": []},
            {"date": "2026-08-21", "exercises": []},
        ]}
        removed = dedupe.remove_history_dates(data, {"2024-08-19"})
        self.assertEqual(removed, 1)
        self.assertEqual([e["date"] for e in data["history"]], ["2026-08-19", "2026-08-21"])

    def test_returns_zero_when_no_dates_match(self):
        data = {"history": [{"date": "2026-08-19", "exercises": []}]}
        self.assertEqual(dedupe.remove_history_dates(data, {"1999-01-01"}), 0)


class TestManualTranslations(unittest.TestCase):

    def test_no_translation_maps_to_itself(self):
        """Кожен ручний переклад має реально щось міняти, а не бути записаним даремно."""
        no_ops = [k for k, v in dedupe.MANUAL_TRANSLATIONS.items() if k == v]
        self.assertEqual(no_ops, [])

    def test_translation_targets_do_not_need_further_translation(self):
        """Ціль перекладу сама не повинна бути ключем іншого перекладу (інакше ланцюжок недороблений)."""
        chained = [k for k in dedupe.MANUAL_TRANSLATIONS.values() if k in dedupe.MANUAL_TRANSLATIONS]
        self.assertEqual(chained, [])


if __name__ == "__main__":
    unittest.main()

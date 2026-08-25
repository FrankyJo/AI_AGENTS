"""
Тести domain/progress.py — чисті функції обчислення тоннажу та прогресії ваги,
без storage і без LLM.

    python -m unittest tests.test_progress -v
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from domain import progress


class TestParseNumber(unittest.TestCase):

    def test_parses_plain_integer_string(self):
        self.assertEqual(progress.parse_number("12"), 12.0)

    def test_parses_number_with_unit_suffix(self):
        self.assertEqual(progress.parse_number("12кг"), 12.0)

    def test_parses_number_with_comma_decimal(self):
        self.assertEqual(progress.parse_number("12,5 кг"), 12.5)

    def test_takes_first_number_from_range(self):
        self.assertEqual(progress.parse_number("8-10"), 8.0)

    def test_returns_none_for_unparseable_text(self):
        self.assertIsNone(progress.parse_number("власна вага"))

    def test_returns_none_for_none(self):
        self.assertIsNone(progress.parse_number(None))


class TestNormalizeSets(unittest.TestCase):

    def test_prefers_sets_detail_when_present(self):
        ex = {"name": "X", "sets_detail": [{"weight": "10кг", "reps": "12"}]}
        self.assertEqual(progress.normalize_sets(ex), [{"weight": "10кг", "reps": "12"}])

    def test_falls_back_to_flat_weight_reps(self):
        ex = {"name": "X", "sets": 3, "reps": "10", "weight": "50кг"}
        self.assertEqual(progress.normalize_sets(ex), [{"weight": "50кг", "reps": "10"}])

    def test_returns_empty_for_bodyweight_exercise_without_weight(self):
        ex = {"name": "Планка", "sets": 3, "reps": "60с"}
        self.assertEqual(progress.normalize_sets(ex), [{"weight": "", "reps": "60с"}])

    def test_returns_empty_list_when_nothing_recorded(self):
        self.assertEqual(progress.normalize_sets({"name": "X"}), [])


class TestVolumeCalculations(unittest.TestCase):

    def test_workout_volume_kg_sums_weight_times_reps_across_sets(self):
        entry = {"date": "2026-08-01", "exercises": [
            {"name": "Присідання", "sets_detail": [
                {"weight": "10кг", "reps": "12"}, {"weight": "12кг", "reps": "10"}]},
        ]}
        # 10*12 + 12*10 = 120 + 120 = 240
        self.assertEqual(progress.workout_volume_kg(entry), 240.0)

    def test_workout_volume_kg_ignores_unparseable_sets(self):
        entry = {"date": "2026-08-01", "exercises": [
            {"name": "Планка", "sets": 3, "reps": "60с"},
            {"name": "Присідання", "sets_detail": [{"weight": "10кг", "reps": "12"}]},
        ]}
        self.assertEqual(progress.workout_volume_kg(entry), 120.0)

    def test_volume_series_preserves_order_and_dates(self):
        history = [
            {"date": "2026-08-01", "exercises": [{"name": "A", "sets_detail": [{"weight": "10", "reps": "10"}]}]},
            {"date": "2026-08-03", "exercises": [{"name": "A", "sets_detail": [{"weight": "20", "reps": "10"}]}]},
        ]
        self.assertEqual(progress.volume_series(history),
                          [{"date": "2026-08-01", "volume_kg": 100.0},
                           {"date": "2026-08-03", "volume_kg": 200.0}])

    def test_exercise_progression_tracks_top_weight_and_volume_per_occurrence(self):
        history = [
            {"date": "2026-08-01", "exercises": [
                {"name": "Присідання", "sets_detail": [
                    {"weight": "10кг", "reps": "12"}, {"weight": "12кг", "reps": "10"}]}]},
            {"date": "2026-08-08", "exercises": [
                {"name": "Присідання", "sets_detail": [{"weight": "14кг", "reps": "10"}]}]},
            {"date": "2026-08-08", "exercises": [{"name": "Інша вправа", "sets_detail": []}]},
        ]

        rows = progress.exercise_progression(history, "Присідання")

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], {"date": "2026-08-01", "top_weight_kg": 12.0, "volume_kg": 240.0})
        self.assertEqual(rows[1], {"date": "2026-08-08", "top_weight_kg": 14.0, "volume_kg": 140.0})

    def test_exercise_progression_handles_missing_weight_gracefully(self):
        history = [{"date": "2026-08-01", "exercises": [{"name": "Планка", "sets": 3, "reps": "60с"}]}]
        rows = progress.exercise_progression(history, "Планка")
        self.assertEqual(rows, [{"date": "2026-08-01", "top_weight_kg": None, "volume_kg": 0.0}])


if __name__ == "__main__":
    unittest.main()

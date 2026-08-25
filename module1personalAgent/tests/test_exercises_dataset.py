"""
Тести завантаження бази вправ (domain/exercises.py): евристика
_infer_contraindications і форма даних, вивантажених з exercises-dataset.

    python -m unittest tests.test_exercises_dataset -v
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from domain import exercises


class TestInferContraindications(unittest.TestCase):

    def test_chest_exercise_tags_shoulder(self):
        ex = {"body_part": "груди", "target": "pectorals", "secondary_muscles": [], "equipment": "штанга"}
        self.assertEqual(exercises._infer_contraindications(ex), ["shoulder"])

    def test_calf_exercise_tags_ankle(self):
        ex = {"body_part": "гомілки", "target": "calves", "secondary_muscles": [], "equipment": "тренажер"}
        self.assertEqual(exercises._infer_contraindications(ex), ["ankle"])

    def test_thigh_glute_target_tags_hip_not_knee(self):
        ex = {"body_part": "стегна", "target": "glutes", "secondary_muscles": [], "equipment": "власна вага"}
        self.assertEqual(exercises._infer_contraindications(ex), ["hip"])

    def test_thigh_quad_target_tags_knee(self):
        ex = {"body_part": "стегна", "target": "quads", "secondary_muscles": [], "equipment": "тренажер"}
        self.assertEqual(exercises._infer_contraindications(ex), ["knee"])

    def test_secondary_lower_back_muscle_adds_lower_back_tag(self):
        """Тяга на прямих ногах: body_part стегна/hamstrings, але через secondary
        (поперек) додається ще й lower_back — інакше небезпечний для спини рух
        пройшов би повз фільтр lower_back."""
        ex = {"body_part": "стегна", "target": "hamstrings", "secondary_muscles": ["поперек"], "equipment": "штанга"}
        self.assertEqual(exercises._infer_contraindications(ex), ["knee", "lower_back"])

    def test_rowing_cardio_tags_lower_back_not_knee(self):
        ex = {"body_part": "кардіо", "target": "cardiovascular system", "secondary_muscles": [],
              "equipment": "гребний тренажер"}
        self.assertEqual(exercises._infer_contraindications(ex), ["lower_back"])

    def test_treadmill_cardio_tags_knee(self):
        ex = {"body_part": "кардіо", "target": "cardiovascular system", "secondary_muscles": [],
              "equipment": "доріжка"}
        self.assertEqual(exercises._infer_contraindications(ex), ["knee"])

    def test_neck_exercise_tags_neck(self):
        ex = {"body_part": "шия", "target": "neck", "secondary_muscles": [], "equipment": "власна вага"}
        self.assertEqual(exercises._infer_contraindications(ex), ["neck"])


class TestLoadedDataset(unittest.TestCase):

    def test_dataset_loads_all_records(self):
        self.assertEqual(len(exercises.EXERCISES), 1324)

    def test_every_exercise_has_a_gif_path(self):
        missing = [e["name"] for e in exercises.EXERCISES if not e["gif_path"]]
        self.assertEqual(missing, [])

    def test_sampled_gif_paths_exist_on_disk(self):
        sample = exercises.EXERCISES[:20] + exercises.EXERCISES[-20:]
        for e in sample:
            self.assertTrue(pathlib.Path(e["gif_path"]).exists(), e["name"])

    def test_muscle_group_buckets_are_known_values(self):
        known = {"ноги", "спина", "груди", "плечі", "руки", "кор", "кардіо", "шия"}
        buckets = {e["muscle_group"] for e in exercises.EXERCISES}
        self.assertTrue(buckets.issubset(known), buckets - known)

    def test_every_exercise_has_at_least_one_contraindication_tag(self):
        """Евристика консервативна за задумом (кожен body_part -> хоча б один
        тег) — краще зайве виключити з видачі, ніж пропустити ризиковану вправу."""
        untagged = [e["name"] for e in exercises.EXERCISES if not e["contraindications"]]
        self.assertEqual(untagged, [])


if __name__ == "__main__":
    unittest.main()

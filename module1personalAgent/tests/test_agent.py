"""
Тести логіки agent loop БЕЗ реального виклику LLM — мокаємо core.agent._call.
domain/backend.py лишається справжнім — він пише/читає JSON через storage/store.py,
тому тести ізолюють файл за CHAT_ID і прибирають його в tearDown.

    python -m unittest tests.test_agent -v
"""

import sys
import pathlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from core import agent
from domain import backend
from storage import store

CHAT_ID = "test-chat"


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_use_block(name, input_, id_="tu_1"):
    return SimpleNamespace(type="tool_use", name=name, input=input_, id=id_)


def fake_resp(content, stop_reason, in_tok=500, out_tok=200):
    return SimpleNamespace(
        content=content, stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok),
    )


class TestAgentLoop(unittest.TestCase):

    def setUp(self):
        backend.set_chat_id(CHAT_ID)

    def tearDown(self):
        store.delete(CHAT_ID)

    def test_ok_happy_path_logs_workout(self):
        """Модель викликає log_workout, потім відповідає текстом -> outcome ok, запис збережено."""
        responses = [
            fake_resp([tool_use_block("log_workout", {
                "date": "2026-08-20",
                "exercises": [{"name": "Присідання", "sets": 3, "reps": "10"}],
            })], "tool_use"),
            fake_resp([text_block("Записав тренування.")], "end_turn"),
        ]
        with patch.object(agent, "_call", side_effect=responses):
            result = agent.run_agent(system="test", tools=backend.tools(), query="test")

        self.assertEqual(result["outcome"], "ok")
        self.assertEqual(len(result["trace"]), 1)
        self.assertFalse(result["failures"])
        self.assertEqual(store.load(CHAT_ID)["history"][0]["exercises"][0]["name"], "Присідання")

    def test_add_constraint_filters_list_exercises(self):
        """Записане обмеження одразу виключає небезпечні вправи з list_exercises."""
        backend.add_constraint("lower_back", "тягне при нахилах")
        result = backend.list_exercises(muscle_group="ноги")
        names = [e["name"] for e in result["exercises"]]
        self.assertNotIn("Присідання зі штангою", names)
        self.assertIn("Присідання зі штангою", result["excluded_due_to_constraints"])

    def test_swap_exercise_unknown_day_is_tracked_not_swallowed(self):
        """Інструмент повернув {'error': ...} на неіснуючий день -> крок позначено failed."""
        backend.set_program("Спліт", [{"day": "День 1", "exercises": [{"name": "Присідання", "sets": 3, "reps": "10"}]}])
        responses = [
            fake_resp([tool_use_block("swap_exercise", {
                "day": "День 5", "old_exercise": "Присідання", "new_exercise": "Гоблет-присід",
            })], "tool_use"),
            fake_resp([text_block("Не знайшов такий день.")], "end_turn"),
        ]
        with patch.object(agent, "_call", side_effect=responses):
            result = agent.run_agent(system="test", tools=backend.tools(), query="test")

        self.assertEqual(len(result["failures"]), 1)
        self.assertEqual(result["failures"][0]["tool"], "swap_exercise")
        self.assertTrue(result["trace"][0]["failed"])

    def test_turns_exhausted_not_infinite_loop(self):
        """Модель нескінченно просить інструмент -> чесний turns_exhausted, а не зависання."""
        responses = [fake_resp([tool_use_block("get_profile", {})], "tool_use")] * agent.MAX_TURNS
        with patch.object(agent, "_call", side_effect=responses):
            result = agent.run_agent(system="test", tools=backend.tools(), query="test")

        self.assertEqual(result["outcome"], "turns_exhausted")
        self.assertEqual(result["turns"], agent.MAX_TURNS)

    def test_api_error_returns_structured_outcome_not_traceback(self):
        """Виняток з API -> структурований outcome, exception не спливає назовні."""
        with patch.object(agent, "_call", side_effect=RuntimeError("connection reset")):
            result = agent.run_agent(system="test", tools=[], query="test")

        self.assertEqual(result["outcome"], "api_error")
        self.assertIn("connection reset", result["error"])

    def test_budget_exceeded_stops_before_overspending(self):
        """Дорогі виклики поспіль -> зупинка за бюджетом, а не мовчазне продовження."""
        expensive = fake_resp([tool_use_block("get_profile", {})], "tool_use",
                               in_tok=50000, out_tok=5000)
        with patch.object(agent, "_call", side_effect=[expensive] * agent.MAX_TURNS):
            result = agent.run_agent(system="test", tools=backend.tools(), query="test")

        self.assertEqual(result["outcome"], "budget_exceeded")
        self.assertLess(result["turns"], agent.MAX_TURNS)


if __name__ == "__main__":
    unittest.main()

"""
Тести логіки agent loop БЕЗ реального виклику LLM — мок client.messages.create
(підміняємо core.agent._call). Мережа не потрібна, гроші не витрачаються.
domain/backend.py (фейковий бекенд) лишається справжнім — це не мок, а вже
детерміновані дані, на яких і без LLM є що перевіряти.

    python -m unittest tests.test_agent -v
"""

import sys
import pathlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from core import agent


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

    def test_ok_happy_path(self):
        """Модель просить інструмент, потім відповідає текстом -> outcome ok."""
        responses = [
            fake_resp([tool_use_block("get_order_status", {"tracking": "EE123456789UA"})], "tool_use"),
            fake_resp([text_block("Посилка прострочена на 10 днів.")], "end_turn"),
        ]
        with patch.object(agent, "_call", side_effect=responses):
            result = agent.run_agent(system="test", tools=[{"name": "get_order_status"}], query="test")

        self.assertEqual(result["outcome"], "ok")
        self.assertEqual(len(result["trace"]), 1)
        self.assertFalse(result["failures"])

    def test_tool_error_is_tracked_not_swallowed(self):
        """Інструмент повернув {'error': ...} -> крок позначений failed, є у failures."""
        responses = [
            fake_resp([tool_use_block("get_order_status", {"tracking": "EE000000000UA"})], "tool_use"),
            fake_resp([text_block("Не знайдено, зверніться до оператора.")], "end_turn"),
        ]
        with patch.object(agent, "_call", side_effect=responses):
            result = agent.run_agent(system="test", tools=[{"name": "get_order_status"}], query="test")

        self.assertEqual(len(result["failures"]), 1)
        self.assertEqual(result["failures"][0]["tool"], "get_order_status")
        self.assertTrue(result["trace"][0]["failed"])

    def test_turns_exhausted_not_infinite_loop(self):
        """Модель нескінченно просить інструмент -> чесний turns_exhausted, а не зависання."""
        responses = [fake_resp([tool_use_block("get_order_status",
                     {"tracking": "EE123456789UA"})], "tool_use")] * agent.MAX_TURNS
        with patch.object(agent, "_call", side_effect=responses):
            result = agent.run_agent(system="test", tools=[{"name": "get_order_status"}], query="test")

        self.assertEqual(result["outcome"], "turns_exhausted")
        self.assertEqual(result["turns"], agent.MAX_TURNS)

    def test_api_error_returns_structured_outcome_not_traceback(self):
        """Виняток з API -> структурований outcome, exception не спливає назовні."""
        with patch.object(agent, "_call", side_effect=RuntimeError("connection reset")):
            result = agent.run_agent(system="test", tools=[], query="test")

        self.assertEqual(result["outcome"], "api_error")
        self.assertIn("connection reset", result["error"])

    def test_budget_exceeded_stops_before_overspending(self):
        """Дорогі виклики поспіль -> зупинка по бюджету, а не мовчазне продовження."""
        expensive = fake_resp([tool_use_block("get_order_status", {"tracking": "EE123456789UA"})],
                               "tool_use", in_tok=50000, out_tok=5000)
        with patch.object(agent, "_call", side_effect=[expensive] * agent.MAX_TURNS):
            result = agent.run_agent(system="test", tools=[{"name": "get_order_status"}], query="test")

        self.assertEqual(result["outcome"], "budget_exceeded")
        self.assertLess(result["turns"], agent.MAX_TURNS)


if __name__ == "__main__":
    unittest.main()

"""
Тести логіки agent loop БЕЗ реального виклику LLM — мокаємо core.agent._call.
domain/backend.py лишається справжнім — він пише/читає JSON через storage/store.py,
тому тести ізолюють файл за CHAT_ID і прибирають його в tearDown.

    python -m unittest tests.test_agent -v
"""

import datetime
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

    def test_update_profile_saves_name(self):
        """update_profile(name=...) зберігає ім'я, з яким потім бот звертається до користувача."""
        profile = backend.update_profile(name="Денис")
        self.assertEqual(profile["name"], "Денис")
        self.assertEqual(backend.get_profile()["name"], "Денис")

    def test_run_agent_injects_todays_date_into_system_prompt(self):
        """Модель має знати, яке сьогодні число — інакше вгадує рік у log_workout/log_set."""
        responses = [fake_resp([text_block("ok")], "end_turn")]
        with patch.object(agent, "_call", side_effect=responses) as mock_call:
            agent.run_agent(system="базовий промпт", tools=[], query="test")

        sent_system = mock_call.call_args.kwargs["system"]
        self.assertIn(datetime.date.today().isoformat(), sent_system)
        self.assertIn("базовий промпт", sent_system)

    def test_run_agent_seeds_messages_with_prior_history(self):
        """Без цього репліка «так, вона» на другому повідомленні не має контексту,
        про яку вправу йшлося — модель бачить лише поточний query."""
        prior = [{"role": "user", "content": "А згинання ніг лежа?"},
                 {"role": "assistant", "content": "Є вправа «Згинання ніг лежа в тренажері»."}]
        responses = [fake_resp([text_block("ok")], "end_turn")]

        with patch.object(agent, "_call", side_effect=responses) as mock_call:
            agent.run_agent(system="base", tools=[], query="Так, вона", history=prior)

        sent_messages = mock_call.call_args.kwargs["messages"]
        self.assertEqual(sent_messages[0], prior[0])
        self.assertEqual(sent_messages[1], prior[1])
        self.assertEqual(sent_messages[2], {"role": "user", "content": "Так, вона"})

    def test_run_agent_without_history_starts_fresh(self):
        responses = [fake_resp([text_block("ok")], "end_turn")]
        with patch.object(agent, "_call", side_effect=responses) as mock_call:
            agent.run_agent(system="base", tools=[], query="test")
        self.assertEqual(mock_call.call_args.kwargs["messages"], [{"role": "user", "content": "test"}])

    def test_summarize_into_notes_noop_when_nothing_dropped(self):
        """Немає що сумаризувати -> старі нотатки повертаються без зайвого виклику API."""
        with patch.object(agent, "_call") as mock_call:
            result = agent.summarize_into_notes("стара нотатка", [])
        self.assertEqual(result, "стара нотатка")
        mock_call.assert_not_called()

    def test_summarize_into_notes_uses_fast_model(self):
        resp = fake_resp([text_block("нова нотатка")], "end_turn")
        dropped = [{"role": "user", "content": "Хочу схуднути"},
                   {"role": "assistant", "content": "Записав мету."}]
        with patch.object(agent, "_call", return_value=resp) as mock_call:
            result = agent.summarize_into_notes("", dropped)

        self.assertEqual(result, "нова нотатка")
        self.assertEqual(mock_call.call_args.kwargs["model"], agent.MODEL_FAST)

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
        fixture = [
            {"name": "Присідання зі штангою", "muscle_group": "ноги",
             "equipment": ["штанга"], "contraindications": ["lower_back", "knee"]},
            {"name": "Розгинання ніг у тренажері", "muscle_group": "ноги",
             "equipment": ["тренажер"], "contraindications": ["knee"]},
        ]
        with patch.object(backend, "EXERCISES", fixture):
            backend.add_constraint("lower_back", "тягне при нахилах")
            result = backend.list_exercises(muscle_group="ноги")

        names = [e["name"] for e in result["exercises"]]
        self.assertNotIn("Присідання зі штангою", names)
        self.assertIn("Розгинання ніг у тренажері", names)
        self.assertIn("Присідання зі штангою", result["excluded_due_to_constraints"])

    def test_list_exercises_respects_limit_and_reports_total(self):
        """Датасет великий -> список обрізається лімітом, але total_matching каже скільки насправді підходить."""
        fixture = [{"name": f"Вправа {i}", "muscle_group": "ноги", "equipment": ["штанга"],
                    "contraindications": []} for i in range(5)]
        with patch.object(backend, "EXERCISES", fixture):
            result = backend.list_exercises(muscle_group="ноги", limit=2)
        self.assertEqual(len(result["exercises"]), 2)
        self.assertEqual(result["total_matching"], 5)

    def test_list_exercises_caps_limit_at_max(self):
        """Модель попросила limit=999 -> все одно не більше LIST_EXERCISES_MAX_LIMIT, щоб не роздути контекст."""
        fixture = [{"name": f"Вправа {i}", "muscle_group": "ноги", "equipment": [],
                    "contraindications": []} for i in range(50)]
        with patch.object(backend, "EXERCISES", fixture):
            result = backend.list_exercises(muscle_group="ноги", limit=999)
        self.assertEqual(len(result["exercises"]), backend.LIST_EXERCISES_MAX_LIMIT)

    def test_get_exercise_details_returns_description_and_gif_path(self):
        fixture = [{"name": "Присідання зі штангою", "muscle_group": "ноги", "target": "quads",
                    "equipment": ["штанга"], "contraindications": ["knee"],
                    "description": "текст", "steps": ["крок 1"],
                    "gif_path": "/tmp/fake.gif", "image_path": "/tmp/fake.jpg"}]
        with patch.object(backend, "EXERCISES", fixture):
            result = backend.get_exercise_details("Присідання зі штангою")
        self.assertEqual(result["gif_path"], "/tmp/fake.gif")
        self.assertEqual(result["steps"], ["крок 1"])

    def test_get_exercise_details_unknown_name_returns_error(self):
        result = backend.get_exercise_details("Вигадана вправа, якої нема")
        self.assertEqual(result, {"error": "exercise_not_found", "name": "Вигадана вправа, якої нема"})

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

    def test_log_set_uses_expected_sets_from_program(self):
        """Кількість підходів у програмі -> log_set підказує remaining саме за нею."""
        backend.set_program("Спліт", [{"day": "День 1", "exercises": [
            {"name": "Присідання зі штангою", "sets": 3, "reps": "10"}]}])

        r1 = backend.log_set(exercise="Присідання зі штангою", weight="10кг", reps="12", day="День 1")
        r2 = backend.log_set(exercise="Присідання зі штангою", weight="12кг", reps="10", day="День 1")
        r3 = backend.log_set(exercise="Присідання зі штангою", weight="12кг", reps="8", day="День 1")

        self.assertEqual([r1["logged_sets"], r2["logged_sets"], r3["logged_sets"]], [1, 2, 3])
        self.assertEqual(r1["expected_sets"], 3)
        self.assertEqual([r1["remaining"], r2["remaining"], r3["remaining"]], [2, 1, 0])

    def test_log_set_without_program_defaults_expected_sets(self):
        """Вправи немає в збереженій програмі -> дефолтні 4 очікувані підходи."""
        r = backend.log_set(exercise="Молотки з гантелями", weight="12кг", reps="10")
        self.assertEqual(r["expected_sets"], backend.DEFAULT_EXPECTED_SETS)

    def test_finish_exercise_set_log_writes_history_and_clears_active(self):
        """Завершення підрахунку -> запис у history з деталями підходів, active_set_log очищено."""
        backend.log_set(exercise="Присідання зі штангою", weight="10кг", reps="12")
        backend.log_set(exercise="Присідання зі штангою", weight="12кг", reps="10")

        result = backend.finish_exercise_set_log()

        self.assertTrue(result["ok"])
        self.assertEqual(result["total_sets"], 2)
        self.assertFalse(result["early_stop"])
        saved = store.load(CHAT_ID)
        self.assertIsNone(saved["active_set_log"])
        self.assertEqual(saved["history"][-1]["exercises"][0]["sets_detail"],
                          [{"weight": "10кг", "reps": "12"}, {"weight": "12кг", "reps": "10"}])

    def test_finish_exercise_set_log_early_stop_keeps_partial_sets(self):
        """Користувач зупинився на 3 з 4 -> early_stop=true, зафіксовано лише зроблене."""
        for weight, reps in [("10кг", "12"), ("12кг", "10"), ("12кг", "8")]:
            backend.log_set(exercise="Молотки з гантелями", weight=weight, reps=reps)

        result = backend.finish_exercise_set_log(early_stop=True)

        self.assertEqual(result["total_sets"], 3)
        self.assertTrue(result["early_stop"])

    def test_finish_exercise_set_log_without_active_session_is_reported(self):
        """Немає активного підрахунку -> явна помилка, а не тихе NoneType."""
        result = backend.finish_exercise_set_log()
        self.assertEqual(result, {"error": "no_active_exercise"})

    def test_log_set_different_exercise_starts_fresh_count(self):
        """Прийшла інша вправа посеред підрахунку -> починається новий підрахунок з нуля."""
        backend.log_set(exercise="Присідання зі штангою", weight="10кг", reps="12")
        backend.log_set(exercise="Присідання зі штангою", weight="12кг", reps="10")

        r = backend.log_set(exercise="Молотки з гантелями", weight="12кг", reps="10")

        self.assertEqual(r["logged_sets"], 1)

    def test_update_body_metrics_merges_measurements(self):
        """Повторні виклики update_body_metrics домержують заміри, а не перезаписують усе."""
        backend.update_body_metrics(weight_kg=80, measurements={"талія": "82"})
        backend.update_body_metrics(measurements={"стегно": "58"})

        profile = backend.get_profile()

        self.assertEqual(profile["body_metrics"]["weight_kg"], 80)
        self.assertEqual(profile["body_metrics"]["measurements"], {"талія": "82", "стегно": "58"})

    def test_set_program_stores_type_and_updated_at(self):
        """set_program зберігає тип програми і дату оновлення для подальших рекомендацій."""
        program = backend.set_program(
            "Фулбаді", [{"day": "День 1", "exercises": []}], program_type="full_body")

        self.assertEqual(program["type"], "full_body")
        self.assertIsNotNone(program["updated_at"])

    def test_get_exercise_history_merges_both_logging_flows(self):
        """log_workout (одним рядком) і log_set+finish (подетально) -> обидва потрапляють в історію вправи, найновіші першими."""
        backend.log_workout(date="2026-08-01", exercises=[
            {"name": "Присідання зі штангою", "sets": 3, "reps": "10", "weight": "50кг"}])
        backend.log_set(exercise="Присідання зі штангою", weight="55кг", reps="10")
        backend.log_set(exercise="Присідання зі штангою", weight="55кг", reps="8")
        backend.finish_exercise_set_log()

        result = backend.get_exercise_history(exercise="Присідання зі штангою")

        self.assertEqual(len(result["occurrences"]), 2)
        self.assertEqual(result["occurrences"][0]["sets"],
                          [{"weight": "55кг", "reps": "10"}, {"weight": "55кг", "reps": "8"}])
        self.assertEqual(result["occurrences"][1]["sets"], [{"weight": "50кг", "reps": "10"}])

    def test_update_body_metrics_schedules_next_check_in(self):
        """Дані введено вручну -> наступне нагадування заплановане на майбутнє, не due сьогодні."""
        backend.update_body_metrics(weight_kg=80)
        self.assertFalse(backend.is_check_in_due())

    def test_get_conversation_starts_empty(self):
        self.assertEqual(backend.get_conversation(), [])

    def test_append_conversation_stores_user_and_assistant_pair(self):
        backend.append_conversation("А згинання ніг лежа?", "Є вправа «Згинання ніг лежа в тренажері».")
        conv = backend.get_conversation()
        self.assertEqual(conv, [
            {"role": "user", "content": "А згинання ніг лежа?"},
            {"role": "assistant", "content": "Є вправа «Згинання ніг лежа в тренажері»."},
        ])

    def test_append_conversation_trims_to_max_history_turns(self):
        """Довга розмова -> зберігаються лише останні MAX_HISTORY_TURNS пар, щоб контекст не ріс безмежно."""
        for i in range(backend.MAX_HISTORY_TURNS + 3):
            backend.append_conversation(f"питання {i}", f"відповідь {i}")

        conv = backend.get_conversation()

        self.assertEqual(len(conv), backend.MAX_HISTORY_TURNS * 2)
        self.assertEqual(conv[0]["content"], "питання 3")           # найстаріші 3 пари відкинуто
        self.assertEqual(conv[-1]["content"], f"відповідь {backend.MAX_HISTORY_TURNS + 2}")

    def test_append_conversation_returns_empty_when_under_limit(self):
        self.assertEqual(backend.append_conversation("q", "a"), [])

    def test_append_conversation_returns_dropped_pair_when_over_limit(self):
        """Найстаріша пара, що випадає з вікна, має повернутись — інакше нема що сумаризувати в memory_notes."""
        for i in range(backend.MAX_HISTORY_TURNS):
            backend.append_conversation(f"q{i}", f"a{i}")

        dropped = backend.append_conversation("qN", "aN")

        self.assertEqual(dropped, [{"role": "user", "content": "q0"},
                                    {"role": "assistant", "content": "a0"}])

    def test_memory_notes_roundtrip(self):
        self.assertEqual(backend.get_memory_notes(), "")
        backend.update_memory_notes("Юзер хоче схуднути з 95 до 90 кг.")
        self.assertEqual(backend.get_memory_notes(), "Юзер хоче схуднути з 95 до 90 кг.")

    def test_check_in_due_by_default_for_new_user(self):
        """Ще жодного разу не питали -> нагадування вважається due (щоб не пропустити нового користувача)."""
        self.assertTrue(backend.is_check_in_due())

    def test_mark_check_in_sent_pushes_due_date_into_future(self):
        """Після надсилання нагадування -> is_check_in_due стає false до наступного разу."""
        self.assertTrue(backend.is_check_in_due())
        backend.mark_check_in_sent()
        self.assertFalse(backend.is_check_in_due())

    def test_list_known_chat_ids_includes_users_with_saved_data(self):
        """Файл користувача вже існує (з setUp) -> він у списку відомих chat_id."""
        backend.get_profile()                          # гарантує, що файл точно збережений
        store.save(CHAT_ID, store.load(CHAT_ID))
        self.assertIn(CHAT_ID, store.list_chat_ids())

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

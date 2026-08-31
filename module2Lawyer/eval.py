"""
Ragas: як агент відпрацьовує з РІЗНИМИ конфігураціями RAG.

Один датасет (6 юридичних питань з еталонами), чотири конфігурації:

  lexical   — static RAG, лексичний retriever (domain/knowledge.py, 11 ручних пунктів)
  vector    — static RAG, векторний retriever (knowledge_qdrant.py, увесь текст)
  gate      — vector + self-RAG ворота (self_rag.py): grade → rewrite → ескалація
  agentic   — retrieval як інструмент search_kb (rag_agentic.py)

Ragas міряє:
  faithfulness      — чи відповідь спирається на видані витяги
  answer_relevancy  — чи відповідає на питання
  context_recall    — чи retriever взагалі дістав потрібну норму
                      (головна метрика порівняння retriever'ів)

Суддя — дешева модель з нашого каскаду (MODEL_FAST), ембединги — та сама
локальна multilingual-e5-small, що й у пошуку.

    pip install -r requirements-eval.txt
    python ingest.py                  # якщо ще не індексували
    python eval.py
    python eval.py lexical vector     # тільки вибрані конфігурації
"""

import sys
import warnings

warnings.filterwarnings("ignore")

try:
    from datasets import Dataset
    from ragas import evaluate
    from ragas.llms import LangchainLLMWrapper
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.run_config import RunConfig
    from ragas.metrics import answer_relevancy, context_recall, faithfulness
    from langchain_anthropic import ChatAnthropic
    from langchain_huggingface import HuggingFaceEmbeddings
except ImportError as e:
    raise SystemExit(f"Бракує пакета ({e.name}):\n  pip install -r requirements-eval.txt")

from config import BASE_PROMPT, MODEL_FAST
from core.agent import ask
import domain.knowledge as lex
import knowledge_qdrant as vec
from self_rag import answer_with_gate
from rag_agentic import run_agentic

# ── датасет: 6 питань з еталонами, звіреними з реального тексту законів ─
CASES = [
    {"question": "Яка дозволена швидкість руху у населеному пункті?",
     "ground_truth": "У населених пунктах дозволена швидкість — не більше 50 км/год "
                     "(п. 12.4 ПДР), у житлових і пішохідних зонах — не більше 20 км/год (п. 12.5)."},
    {"question": "Чи можна керувати автомобілем у стані алкогольного сп'яніння?",
     "ground_truth": "Ні, заборонено. Пункт 2.9(а) ПДР забороняє керування транспортним "
                     "засобом у стані алкогольного, наркотичного чи іншого сп'яніння."},
    {"question": "Чи обов'язково пасажирам пристібатися ременем безпеки?",
     "ground_truth": "Так, згідно з п. 5.2(б) ПДР пасажири повинні користуватися ременями "
                     "безпеки там, де їх установка передбачена конструкцією, крім осіб з "
                     "інвалідністю, яким це фізіологічно неможливо."},
    {"question": "З якого віку дитину можна перевозити без спеціального автокрісла?",
     "ground_truth": "Дітей до 12 років або зростом менше 145 см заборонено перевозити без "
                     "спеціальних утримувальних засобів (п. 21.11(б) ПДР)."},
    {"question": "Хто має перевагу в русі на перехресті рівнозначних доріг?",
     "ground_truth": "За п. 16.12 ПДР водій зобов'язаний дати дорогу транспортному засобу, "
                     "що наближається праворуч, крім перехресть з круговим рухом."},
    {"question": "Чи зобов'язаний поліцейський пояснити причину зупинки автомобіля?",
     "ground_truth": "Так, за ч. 3 ст. 35 Закону «Про Національну поліцію» поліцейський "
                     "зобов'язаний повідомити водію конкретну причину зупинення."},
]

EMPTY = "(база знань нічого не повернула)"


def run_lexical(question: str) -> tuple[str, list]:
    contexts = lex.retrieve(question, 3)
    result = ask(BASE_PROMPT + lex.as_context(question), question)
    return result["answer"], contexts


def run_vector(question: str) -> tuple[str, list]:
    contexts = vec.retrieve(question, 6)
    result = ask(BASE_PROMPT + vec.as_context(question), question)
    return result["answer"], contexts


def run_gate(question: str) -> tuple[str, list]:
    r = answer_with_gate(question)
    return r["answer"], r.get("contexts", [])


def run_agentic_(question: str) -> tuple[str, list]:
    r = run_agentic(question)
    contexts = [c for t in r["trace"] if t["tool"] == "search_kb"
                for c in t["output"].get("laws", [])]
    return r["answer"], contexts


VARIANTS = {"lexical": run_lexical, "vector": run_vector,
            "gate": run_gate, "agentic": run_agentic_}


def collect(runner) -> Dataset:
    rows = {"question": [], "answer": [], "contexts": [], "ground_truth": []}
    for case in CASES:
        answer, contexts = runner(case["question"])
        rows["question"].append(case["question"])
        rows["answer"].append(answer)
        rows["contexts"].append(list(dict.fromkeys(contexts)) or [EMPTY])
        rows["ground_truth"].append(case["ground_truth"])
        print(f"    · {case['question'][:55]}…  ({len(contexts)} витягів у контексті)")
    return Dataset.from_dict(rows)


if __name__ == "__main__":
    wanted = [v for v in sys.argv[1:] if v in VARIANTS] or list(VARIANTS)

    judge = LangchainLLMWrapper(ChatAnthropic(model=MODEL_FAST))
    emb = LangchainEmbeddingsWrapper(HuggingFaceEmbeddings(model_name="intfloat/multilingual-e5-small"))
    metrics = [faithfulness, answer_relevancy, context_recall]
    # низька конкурентність + великий timeout: суддя (MODEL_FAST через
    # langchain_anthropic) інколи відповідає до ~2 хв на складену метрику;
    # при max_workers=4/timeout=180 частина завдань падала по таймауту
    run_cfg = RunConfig(max_workers=2, timeout=300)

    results = {}
    for name in wanted:
        print(f"\n=== Конфігурація: {name} ===")
        ds = collect(VARIANTS[name])
        print("  Ragas оцінює…")
        results[name] = evaluate(ds, metrics=metrics, llm=judge, embeddings=emb,
                                 run_config=run_cfg, show_progress=False).to_pandas()

    print("\n" + "═" * 66)
    print(f"{'конфігурація':<12} {'faithful.':>10} {'relevancy':>10} {'ctx_recall':>11}")
    for name, df in results.items():
        print(f"{name:<12} {df['faithfulness'].mean():>10.2f} "
              f"{df['answer_relevancy'].mean():>10.2f} "
              f"{df['context_recall'].mean():>11.2f}")

    print("\ncontext_recall по питаннях:")
    print("  " + "".join(f"{n:>12}" for n in results))
    for i, case in enumerate(CASES):
        cells = "".join(f"{df['context_recall'][i]:>12.2f}" for df in results.values())
        print(f"  {cells}   {case['question'][:45]}…")

    print("\n6 питань — не вибірка: різниці менші за ~0.1 можуть бути шумом.")

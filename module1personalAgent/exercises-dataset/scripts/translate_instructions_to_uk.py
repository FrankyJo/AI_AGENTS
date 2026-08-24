#!/usr/bin/env python3
"""
Translate exercise instructions from English to Ukrainian via a local Ollama model.

The script translates unique instruction steps, caches completed translations, then
rewrites both "instructions" and "instruction_steps" so they contain only "uk".
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable


FIELDS_TO_TRANSLATE = ("instructions", "instruction_steps")
DEFAULT_MODEL = "gemma4:latest"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
DEFAULT_CACHE = Path("/private/tmp/exercise_instruction_steps_uk_cache.json")

SYSTEM_PROMPT = """You are a professional English-to-Ukrainian translator and editor for fitness exercise instructions. Translate into natural Ukrainian only, using clear polite imperative instructions. Return valid JSON only.
Rules:
- Return an object exactly like {"translations": [ ... ]}.
- The translations array must have the same length and order as input.
- No English text unless it is an unavoidable brand/equipment name.
- Preserve numbers, angles, seconds, reps, left/right, body parts, and equipment meaning.
- Use consistent Ukrainian fitness terminology: core = мʼязи кора; abs = прес; starting position = початкове положення; repetitions = повторення; dumbbell = гантель; dumbbells = гантелі; barbell = штанга; cable machine = блочний тренажер; shoulder-width apart = на ширині плечей; ground/floor = підлога; upper arms = верхня частина рук; curl the weights = згинайте руки з обтяженням; squeeze = напружте/стисніть мʼязи; glutes = сідниці; knee = коліно; elbow = лікоть; ankle = щиколотка; heel = пʼята.
- Avoid literal mistranslations like ядро for core, земля for floor/ground, ваги for weights when it means exercise weights, or верхні руки.
"""


class TranslationError(RuntimeError):
    pass


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_cache(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data = load_json(path)
    if not isinstance(data, dict):
        raise TranslationError(f"Cache must be a JSON object: {path}")
    return {str(k): str(v) for k, v in data.items()}


def save_cache(path: Path, cache: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, dict(sorted(cache.items())))


def chunked(items: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def parse_translations(content: str) -> list[str]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    candidates = [text]
    object_match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    array_match = re.search(r"\[.*\]", text, flags=re.DOTALL)
    if object_match:
        candidates.append(object_match.group(0))
    if array_match:
        candidates.append(array_match.group(0))

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception as exc:  # noqa: BLE001 - keep retry context compact
            last_error = exc
            continue
        if isinstance(parsed, dict):
            parsed = parsed.get("translations", parsed.get("translation"))
        if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
            return [cleanup_translation(item) for item in parsed]

    raise TranslationError(f"Could not parse Ollama JSON response: {last_error}\n{text[:1000]}")


def cleanup_translation(text: str) -> str:
    cleaned = " ".join(text.split())
    replacements = {
        "м'язи": "мʼязи",
        "м’язи": "мʼязи",
        "форму «Y»": "форму літери «ігрек»",
        "пласко на підлогу": "пласко на підлозі",
        "стопами пласко на підлогу": "стопами пласко на підлозі",
        "ногами пласко на підлогу": "ногами пласко на підлозі",
        "Зхопіть": "Візьміться за",
        "зхопіть": "візьміться за",
        "опустите": "опустіть",
        "плавальному русі": "русі педалювання",
        "ядро": "мʼязи кора",
        "Ядро": "Мʼязи кора",
        "землю": "підлогу",
        "землі": "підлозі",
        "верхні руки": "верхню частину рук",
        "верхніх рук": "верхньої частини рук",
        "D-ручки": "одинарні рукоятки",
        "D-ручку": "одинарну рукоятку",
        "D-ручка": "одинарна рукоятка",
        "V-подібний пристрій": "трикутну рукоятку",
        "V-подібного пристрою": "трикутної рукоятки",
        "V-подібну рукоятку": "трикутну рукоятку",
        "V-подібний": "трикутний",
        "V-подібна": "трикутна",
        "V-образний": "трикутний",
        "у формі V": "трикутної форми",
        "формі V": "трикутній формі",
        "BOSU-м'яч": "балансувальну напівсферу",
        "BOSU-мʼяч": "балансувальну напівсферу",
        "BOSU-м'яча": "балансувальної напівсфери",
        "BOSU-мʼяча": "балансувальної напівсфери",
        "EZ штангу": "вигнуту штангу",
        "EZ штанги": "вигнутої штанги",
        "EZ штанзі": "вигнутій штанзі",
        "EZ-штангу": "вигнуту штангу",
        "EZ-штанги": "вигнутої штанги",
        "EZ-штанзі": "вигнутій штанзі",
        "EZ штанга": "вигнута штанга",
        "EZ-штанга": "вигнута штанга",
        "ви facing блочний тренажер": "обличчям до блочного тренажера",
        "facing блочний тренажер": "обличчям до блочного тренажера",
        "зі straight спиною": "з прямою спиною",
        "м'GetObject('calf muscles')": "литкові мʼязи",
        "мʼGetObject('calf muscles')": "литкові мʼязи",
        "м'GetObject('calves')": "литкові мʼязи",
        "мʼGetObject('calves')": "литкові мʼязи",
        "Покладіть мʼGetObject": "Покладіть балансувальну напівсферу",
        "позицію на мʼGetObject": "позицію на балансувальній напівсфері",
        "мʼGetObject": "балансувальну напівсферу",
        "тренажер «пастка»": "трап-гриф",
        "тренажера «пастка»": "трап-грифа",
        "тренажеру «пастка»": "трап-грифу",
        "арматор": "фіксатор для рук",
        "приsquat-положення": "положення присідання",
        "положення приsquat": "положення присідання",
        "вихідне положення присідання": "початкове положення присідання",
        "дна приsquat": "нижньої точки присідання",
        "низу приsquat": "нижньої точки присідання",
        "приsquat": "присідання",
        "приlunge": "випаду",
        "припідлозіться": "приземліться",
        "передп'ястя": "подушечки стоп",
        "передпʼястя": "подушечки стоп",
    }
    for source, target in replacements.items():
        cleaned = cleaned.replace(source, target)
    cleaned = re.sub(r"\s*\([^)]*[A-Za-z][^)]*\)", "", cleaned)
    cleaned = cleaned.replace("«V»", "«ві»")
    cleaned = cleaned.replace("літери V", "літери «ві»")
    cleaned = cleaned.replace("літеру V", "літеру «ві»")
    cleaned = re.sub(r"\bY\b", "ігрек", cleaned)
    return cleaned


def call_ollama(
    steps: list[str],
    *,
    model: str,
    ollama_url: str,
    timeout: int,
    num_ctx: int,
) -> list[str]:
    prompt = "Translate this JSON array from English to Ukrainian:\n" + json.dumps(
        steps, ensure_ascii=False
    )
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0, "num_ctx": num_ctx},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        ollama_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise TranslationError(f"Ollama request failed: {exc}") from exc

    content = payload.get("message", {}).get("content")
    if not isinstance(content, str):
        raise TranslationError(f"Unexpected Ollama payload: {payload!r}")

    translations = parse_translations(content)
    if len(translations) != len(steps):
        raise TranslationError(
            f"Expected {len(steps)} translations, got {len(translations)}"
        )
    return translations


def translate_batch_with_fallback(
    steps: list[str],
    *,
    model: str,
    ollama_url: str,
    timeout: int,
    num_ctx: int,
) -> list[str]:
    try:
        return call_ollama(
            steps,
            model=model,
            ollama_url=ollama_url,
            timeout=timeout,
            num_ctx=num_ctx,
        )
    except TranslationError:
        if len(steps) <= 1:
            raise
        midpoint = len(steps) // 2
        left = translate_batch_with_fallback(
            steps[:midpoint],
            model=model,
            ollama_url=ollama_url,
            timeout=timeout,
            num_ctx=num_ctx,
        )
        right = translate_batch_with_fallback(
            steps[midpoint:],
            model=model,
            ollama_url=ollama_url,
            timeout=timeout,
            num_ctx=num_ctx,
        )
        return left + right


def unique_english_steps(data: list[dict]) -> list[str]:
    seen: set[str] = set()
    steps: list[str] = []
    for item in data:
        instruction_steps = item.get("instruction_steps")
        if not isinstance(instruction_steps, dict) or "en" not in instruction_steps:
            continue
        for step in instruction_steps["en"]:
            if isinstance(step, str) and step not in seen:
                seen.add(step)
                steps.append(step)
    return steps


def apply_ukrainian_translations(data: list[dict], cache: dict[str, str]) -> None:
    for index, item in enumerate(data):
        instruction_steps = item.get("instruction_steps")
        if not isinstance(instruction_steps, dict) or "en" not in instruction_steps:
            raise TranslationError(f"Missing instruction_steps.en at record {index}")

        source_steps = instruction_steps["en"]
        translated_steps = [cache[step] for step in source_steps]
        item["instruction_steps"] = {"uk": translated_steps}
        item["instructions"] = {"uk": " ".join(translated_steps)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "json_path",
        nargs="?",
        default=str(Path(__file__).resolve().parent.parent / "data" / "exercises.json"),
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--num-ctx", type=int, default=16384)
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    json_path = Path(args.json_path)
    data = load_json(json_path)
    if not isinstance(data, list):
        raise TranslationError("Expected top-level JSON array.")

    all_steps = unique_english_steps(data)
    if not all_steps:
        print("No instruction_steps.en values found; nothing to translate.")
        return 0

    cache = load_cache(args.cache)
    pending = [step for step in all_steps if step not in cache]
    print(f"Records: {len(data)}")
    print(f"Unique steps: {len(all_steps)}")
    print(f"Cached steps: {len(all_steps) - len(pending)}")
    print(f"Pending steps: {len(pending)}")

    translated = 0
    started_at = time.time()
    for batch in chunked(pending, args.batch_size):
        batch_start = time.time()
        translations = translate_batch_with_fallback(
            batch,
            model=args.model,
            ollama_url=args.ollama_url,
            timeout=args.timeout,
            num_ctx=args.num_ctx,
        )
        cache.update(zip(batch, translations, strict=True))
        save_cache(args.cache, cache)
        translated += len(batch)
        elapsed = time.time() - started_at
        print(
            f"Translated {translated}/{len(pending)} pending "
            f"({len(cache)}/{len(all_steps)} total) in {elapsed:.1f}s; "
            f"last batch {time.time() - batch_start:.1f}s",
            flush=True,
        )

    missing = [step for step in all_steps if step not in cache]
    if missing:
        raise TranslationError(f"Missing translations after run: {len(missing)}")

    if not args.no_backup:
        backup_path = json_path.with_suffix(".before-uk.json")
        if not backup_path.exists():
            shutil.copy2(json_path, backup_path)
            print(f"Backup saved: {backup_path}")

    apply_ukrainian_translations(data, cache)
    write_json(json_path, data)
    print(f"Updated: {json_path}")
    print(f"Fields rewritten: {', '.join(FIELDS_TO_TRANSLATE)} -> uk only")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - command-line script should show one clear error
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

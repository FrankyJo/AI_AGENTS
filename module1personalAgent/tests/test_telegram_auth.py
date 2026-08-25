"""
Тести webapp/telegram_auth.py — перевірка HMAC-підпису Telegram WebApp
initData. Будуємо initData вручну тим самим алгоритмом, що й Telegram (та сам
клас під тестом), щоб перевірити прийняття валідних даних і відхилення
підроблених/протермінованих/без підпису.

    python -m unittest tests.test_telegram_auth -v
"""

import hashlib
import hmac
import json
import pathlib
import sys
import time
import unittest
from urllib.parse import parse_qsl, urlencode

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from webapp.telegram_auth import InvalidInitData, validate_init_data

BOT_TOKEN = "123456:test-token"


def _signed_fields(bot_token: str, fields: dict) -> dict:
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    signed = dict(fields)
    signed["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return signed


def _build_init_data(bot_token: str, user: dict, auth_date: int = None) -> str:
    fields = {
        "query_id": "AAEXAMPLE",
        "user": json.dumps(user, separators=(",", ":")),
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
    }
    return urlencode(_signed_fields(bot_token, fields))


class TestValidateInitData(unittest.TestCase):

    def test_valid_init_data_returns_user(self):
        init_data = _build_init_data(BOT_TOKEN, {"id": 366320939, "first_name": "Denys"})
        user = validate_init_data(init_data, BOT_TOKEN)
        self.assertEqual(user["id"], 366320939)

    def test_tampered_user_field_is_rejected(self):
        """Хтось підмінив chat_id у payload, лишивши старий hash -> підпис більше не збігається."""
        init_data = _build_init_data(BOT_TOKEN, {"id": 111, "first_name": "A"})
        pairs = dict(parse_qsl(init_data))
        pairs["user"] = json.dumps({"id": 999, "first_name": "A"})
        tampered = urlencode(pairs)

        with self.assertRaises(InvalidInitData):
            validate_init_data(tampered, BOT_TOKEN)

    def test_wrong_bot_token_is_rejected(self):
        init_data = _build_init_data(BOT_TOKEN, {"id": 111, "first_name": "A"})
        with self.assertRaises(InvalidInitData):
            validate_init_data(init_data, "other-token")

    def test_expired_init_data_is_rejected(self):
        old_auth_date = int(time.time()) - 999_999
        init_data = _build_init_data(BOT_TOKEN, {"id": 111, "first_name": "A"}, auth_date=old_auth_date)
        with self.assertRaises(InvalidInitData):
            validate_init_data(init_data, BOT_TOKEN, max_age_seconds=86400)

    def test_fresh_init_data_within_max_age_is_accepted(self):
        recent = int(time.time()) - 60
        init_data = _build_init_data(BOT_TOKEN, {"id": 111, "first_name": "A"}, auth_date=recent)
        validate_init_data(init_data, BOT_TOKEN, max_age_seconds=86400)   # не кидає

    def test_missing_hash_is_rejected(self):
        with self.assertRaises(InvalidInitData):
            validate_init_data("auth_date=123&user=%7B%7D", BOT_TOKEN)

    def test_empty_init_data_is_rejected(self):
        with self.assertRaises(InvalidInitData):
            validate_init_data("", BOT_TOKEN)


if __name__ == "__main__":
    unittest.main()

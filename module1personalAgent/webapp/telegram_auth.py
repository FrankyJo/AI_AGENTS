"""
Перевірка Telegram WebApp initData: підпис, який Mini App передає з кожним
запитом, щоб бекенд міг довести, що дані дійсно прийшли від Telegram для
конкретного chat_id — без цього хтось міг би підставити чужий id у запит і
побачити чужий профіль/прогрес.

Офіційний алгоритм: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


class InvalidInitData(Exception):
    pass


def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int = 86400) -> dict:
    """Повертає розпарсений словник user (id, first_name тощо) або кидає InvalidInitData."""
    if not init_data:
        raise InvalidInitData("empty init_data")
    if not bot_token:
        raise InvalidInitData("bot token not configured on server")

    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError as e:
        raise InvalidInitData(f"malformed init_data: {e}")

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise InvalidInitData("missing hash")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        raise InvalidInitData("bad signature")

    try:
        auth_date = int(pairs.get("auth_date", 0))
    except ValueError:
        raise InvalidInitData("bad auth_date")
    if time.time() - auth_date > max_age_seconds:
        raise InvalidInitData("init_data expired")

    user_raw = pairs.get("user")
    if not user_raw:
        raise InvalidInitData("missing user")
    try:
        return json.loads(user_raw)
    except json.JSONDecodeError:
        raise InvalidInitData("bad user payload")

"""
carnaval/auth.py — HMAC-SHA256 сессионные токены.

Токен = base64url(user_id:issued_ts) + "." + HMAC-SHA256(payload, SECRET)
Не хранит состояние: валидация без БД.
Срок жизни: 4 часа (14 400 сек).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Optional

logger = logging.getLogger("Carnaval.Auth")

_SECRET: bytes = b""  # заполняется при запуске сервера через init(secret)
_TTL: int = 14_400    # 4 часа по спецификации

_INIT_DATA_TTL: int = 86_400  # 24 ч — макс. допустимый возраст Telegram initData


def init(secret: str = "") -> None:
    """
    Инициализировать модуль секретом.
    Если не задан — читает или безопасно генерирует ключ в storage/cache/carnaval_secret.key.
    Ключ сохраняется с правами доступа 0600 (только для владельца процесса).
    """
    global _SECRET
    if not secret:
        cache_file = "storage/cache/carnaval_secret.key"
        try:
            if os.path.exists(cache_file):
                with open(cache_file, "r", encoding="utf-8") as f:
                    secret = f.read().strip()
            if not secret:
                secret = secrets.token_hex(32)
                os.makedirs(os.path.dirname(cache_file), exist_ok=True)
                with open(cache_file, "w", encoding="utf-8") as f:
                    f.write(secret)
                try:
                    os.chmod(cache_file, 0o600)
                except OSError:
                    pass
                logger.info("Carnaval: сгенерирован новый секретный ключ подписи и сохранён в storage/cache/carnaval_secret.key")
        except Exception as e:
            logger.warning(f"Carnaval: не удалось сохранить ключ на диск: {e}, используется in-memory ключ")
            secret = secrets.token_hex(32)

    _SECRET = secret.encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    pad = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + "=" * (pad % 4))


def create_token(user_id: int) -> str:
    """Создать сессионный токен для указанного Telegram user_id."""
    payload = _b64(json.dumps({"uid": int(user_id), "iat": int(time.time())}).encode())
    sig = _b64(hmac.new(_SECRET, payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify_token(token: str) -> Optional[int]:
    """
    Проверить токен. Возвращает user_id или None при ошибке/истечении.
    Константное время сравнения — защита от timing attack.
    """
    if not token or not isinstance(token, str):
        return None

    try:
        payload, sig = token.rsplit(".", 1)
    except ValueError:
        return None

    expected_sig = _b64(hmac.new(_SECRET, payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected_sig):
        return None

    try:
        data = json.loads(_unb64(payload))
    except Exception:
        return None

    if time.time() - data.get("iat", 0) > _TTL:
        return None

    return int(data["uid"])


def verify_init_data(raw_init_data: str, bot_token: str) -> Optional[dict]:
    """
    Проверить Telegram Mini App initData (HMAC-SHA256).
    Возвращает словарь полей initData или None если невалидно / просрочено.

    Spec: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    from urllib.parse import parse_qsl

    params = dict(parse_qsl(raw_init_data, keep_blank_values=True))
    hash_value = params.pop("hash", None)
    if not hash_value:
        return None

    # Строка для проверки: отсортированные "key=value" через \n
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))

    # secret_key = HMAC-SHA256("WebAppData", bot_token)
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed, hash_value):
        return None

    # Проверка свежести по полю auth_date
    try:
        auth_date = int(params.get("auth_date", 0))
    except (ValueError, TypeError):
        return None

    if time.time() - auth_date > _INIT_DATA_TTL:
        return None

    # Распаковать user JSON если есть
    result = dict(params)
    if "user" in result:
        try:
            result["user"] = json.loads(result["user"])
        except Exception:
            pass

    return result

"""
carnaval/routers/auth.py — авторизация через Telegram Mini App initData.

POST /api/auth
  Body: { "initData": "<raw string from Telegram.WebApp.initData>" }
  Returns: { "token": "...", "user": { "id": ..., "username": "..." } }

Лимит: не более 10 попыток с одного IP за 60 секунд (простой in-memory rate limit).
"""

from __future__ import annotations

import time
import logging
from collections import defaultdict

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse

from carnaval import auth
from carnaval.deps import get_cardinal

router = APIRouter()
logger = logging.getLogger("Carnaval.Auth")

# --- простой rate limiter (не требует redis) ---
_rate: dict[str, list[float]] = defaultdict(list)
_RATE_WINDOW = 60
_RATE_MAX = 10


def _is_rate_limited(ip: str) -> bool:
    now = time.time()
    hits = [t for t in _rate[ip] if now - t < _RATE_WINDOW]
    _rate[ip] = hits
    if len(hits) >= _RATE_MAX:
        return True
    _rate[ip].append(now)
    return False


@router.post("/auth")
async def login(request: Request) -> JSONResponse:
    """
    Принимает Telegram initData, проверяет HMAC, возвращает JWT-подобный токен.
    """
    ip = request.client.host if request.client else "unknown"
    if _is_rate_limited(ip):
        return JSONResponse({"error": "rate_limited"}, status_code=429)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "bad_json"}, status_code=400)

    raw_init_data = body.get("initData", "")
    if not raw_init_data:
        return JSONResponse({"error": "missing_init_data"}, status_code=400)

    cardinal = get_cardinal()
    bot_token = cardinal.MAIN_CFG["Telegram"]["token"]

    init_data = auth.verify_init_data(raw_init_data, bot_token)
    if init_data is None:
        logger.warning(f"Carnaval: отклонён initData с IP {ip}")
        return JSONResponse({"error": "invalid_init_data"}, status_code=401)

    user = init_data.get("user", {})
    user_id = user.get("id") if isinstance(user, dict) else None
    if user_id is None:
        return JSONResponse({"error": "no_user_in_init_data"}, status_code=401)

    # Проверить, что user_id в списке авторизованных пользователей Cardinal
    if cardinal.telegram and int(user_id) not in cardinal.telegram.authorized_users:
        logger.warning(f"Carnaval: user {user_id} не в authorized_users")
        return JSONResponse({"error": "not_authorized"}, status_code=403)

    token = auth.create_token(int(user_id))
    logger.info(f"Carnaval: выдан токен для user_id={user_id}")

    return JSONResponse({
        "token": token,
        "user": {
            "id": user_id,
            "username": user.get("username"),
            "first_name": user.get("first_name"),
        }
    })


from carnaval.deps import get_cardinal, require_user, extract_token

# Для обратной совместимости внутри роутера
_extract_token = extract_token


@router.get("/me")
async def me(request: Request, user_id: int = Depends(require_user)) -> JSONResponse:
    """Проверить текущий токен и вернуть данные пользователя."""
    cardinal = get_cardinal()
    return JSONResponse({
        "user_id": user_id,
        "fp_username": cardinal.account.username if cardinal.account else None,
        "fp_user_id": cardinal.account.id if cardinal.account else None,
        "version": cardinal.VERSION,
    })


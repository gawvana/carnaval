"""
carnaval/deps.py — общие зависимости и инъекции (FastAPI).

- get_cardinal / set_cardinal: доступ к экземпляру бота.
- extract_token: извлечение Bearer токена из заголовка Authorization.
- require_user: зависимость FastAPI, проверяющая токен И наличие пользователя
  в списке cardinal.telegram.authorized_users на КАЖДОМ запросе.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from fastapi import HTTPException, Request

if TYPE_CHECKING:
    from cardinal import Cardinal

logger = logging.getLogger("Carnaval.Deps")

_cardinal: "Cardinal | None" = None


def set_cardinal(c: "Cardinal") -> None:
    global _cardinal
    _cardinal = c


def get_cardinal() -> "Cardinal":
    if _cardinal is None:
        raise RuntimeError("Carnaval: Cardinal not set")
    return _cardinal


def extract_token(request: Request) -> Optional[str]:
    """Извлекает Bearer токен из заголовка Authorization."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        return token if token else None
    return None


def require_user(request: Request) -> int:
    """
    FastAPI зависимость:
    1. Извлекает Bearer токен из Authorization.
    2. Проверяет криптографическую подпись и срок жизни (4 часа).
    3. Проверяет, что user_id входит в cardinal.telegram.authorized_users.
       Если доступ был отозван — немедленный отказ 403 Forbidden.
    """
    token = extract_token(request)
    if not token:
        raise HTTPException(
            status_code=401,
            detail={"error": "unauthorized", "message": "Токен авторизации отсутствует"}
        )

    from carnaval import auth
    user_id = auth.verify_token(token)
    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid_token", "message": "Токен недействителен или истёк"}
        )

    if isinstance(user_id, dict):
        user_id = user_id.get("uid") or user_id.get("id") or user_id.get("user_id") or 777000
    try:
        user_id = int(user_id)
    except (ValueError, TypeError):
        user_id = 777000

    cardinal = get_cardinal()
    tg = getattr(cardinal, "telegram", None)
    if tg and hasattr(tg, "authorized_users") and tg.authorized_users is not None:
        auth_users = tg.authorized_users
        if len(auth_users) > 0:
            is_present = (user_id in auth_users) or (str(user_id) in auth_users)
            if not is_present:
                logger.warning(f"Carnaval: доступ отклонён — user_id {user_id} удалён из authorized_users")
                raise HTTPException(
                    status_code=403,
                    detail={"error": "access_revoked", "message": "Доступ отозван администратором"}
                )

    return int(user_id)

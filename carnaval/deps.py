"""
carnaval/deps.py — внедрение зависимостей FastAPI для многоуровневой авторизации.

Уровни доступа:
1. Public — не требует авторизации (/api/health, /api/meta, /api/auth/telegram)
2. require_telegram_auth — требует валидной сессии Telegram Mini App (кука carnaval_session или Bearer токен)
3. require_owner — требует, чтобы пользователь имел роль 'owner' (владелец)
4. require_panel_unlocked — требует, чтобы панель была разблокирована паролем (panel_unlocked == 1)
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Optional

from fastapi import Depends, HTTPException, Request

from carnaval import auth
from carnaval.db import get_state

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


def extract_session_token(request: Request) -> Optional[str]:
    """Извлекает токен сессии из заголовка Authorization (приоритет) или HttpOnly куки."""
    # 1. Приоритет: Bearer заголовок (предпочтителен в SPA/WebView)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token:
            return token

    # 2. Fallback: HttpOnly cookie (для браузерных сессий)
    cookie_token = request.cookies.get("carnaval_session")
    if cookie_token:
        return cookie_token.strip()

    return None


def require_telegram_auth(request: Request) -> dict:
    """
    Зависимость 1-го уровня: валидирует активную сессию Telegram Mini App.
    """
    token = extract_session_token(request)
    if not token:
        raise HTTPException(
            status_code=401,
            detail={"error": "unauthorized", "message": "Сессия отсутствует"}
        )

    session = auth.get_session(token)
    if not session:
        raise HTTPException(
            status_code=401,
            detail={"error": "unauthorized", "message": "Сессия недействительна или истекла"}
        )

    # Проверка CSRF для куки-запросов на мутирующие методы
    has_bearer = request.headers.get("Authorization", "").startswith("Bearer ")
    if request.cookies.get("carnaval_session") and not has_bearer and request.method in ("POST", "PUT", "PATCH", "DELETE"):
        # Если эндпоинт не в списке исключений
        if not request.url.path.startswith("/api/auth/"):
            csrf_token = request.headers.get("X-CSRF-Token")
            # Токен CSRF должен соответствовать токену сессии
            if not csrf_token or csrf_token != token:
                raise HTTPException(
                    status_code=403,
                    detail={"error": "csrf_detected", "message": "Недействительный CSRF токен"}
                )

    # Проверка отзыва доступа через authorized_users Cardinal
    try:
        cardinal = get_cardinal()
        owner_id = get_state("owner_telegram_id")
        uid = session["telegram_user_id"]
        if owner_id and int(owner_id) == uid:
            pass
        elif hasattr(cardinal, "telegram") and cardinal.telegram and hasattr(cardinal.telegram, "authorized_users") and cardinal.telegram.authorized_users:
            auth_users = cardinal.telegram.authorized_users
            if uid not in auth_users and str(uid) not in auth_users:
                raise HTTPException(
                    status_code=403,
                    detail={"error": "access_revoked", "message": "Доступ отозван"}
                )
    except HTTPException:
        raise
    except Exception:
        pass

    request.state.session = session
    request.state.session_token = token
    return session


def require_owner(request: Request, session: dict = Depends(require_telegram_auth)) -> dict:
    """
    Зависимость: проверяет, что пользователь является владельцем системы или авторизованным администратором.
    """
    if session.get("role") in ("owner", "admin"):
        return session

    owner_id_str = get_state("owner_telegram_id")
    current_uid = session["telegram_user_id"]

    # Во время первого запуска до claim владельца разрешаем доступ
    state = get_state("state", "UNINITIALIZED")
    if state == "UNINITIALIZED" or not owner_id_str:
        return session

    env_owner = os.getenv("TG_OWNER_ID", "").strip() or os.getenv("OWNER_TELEGRAM_ID", "").strip()
    if env_owner and str(current_uid) == env_owner:
        return session

    if owner_id_str and int(owner_id_str) == current_uid:
        return session

    # Разрешаем доступ администраторам из authorized_users Cardinal
    try:
        cardinal = get_cardinal()
        tg = getattr(cardinal, "telegram", None)
        if tg and hasattr(tg, "authorized_users") and tg.authorized_users:
            if current_uid in tg.authorized_users or str(current_uid) in tg.authorized_users:
                return session
    except Exception:
        pass

    raise HTTPException(
        status_code=403,
        detail={"error": "forbidden", "message": "Действие доступно только владельцу системы или администратору"}
    )


def require_panel_unlocked(request: Request, session: dict = Depends(require_owner)) -> dict:
    """
    Зависимость 2-го уровня: требует разблокировки панели управления паролем.
    """
    state = get_state("state", "UNINITIALIZED")
    if state != "INITIALIZED":
        # На этапе onboarding панель еще не заблокирована
        return session

    has_pwd = bool(get_state("password_hash"))
    if not has_pwd:
        return session

    if not session.get("panel_unlocked"):
        raise HTTPException(
            status_code=403,
            detail={"error": "panel_locked", "message": "Панель управления заблокирована. Введите пароль."}
        )

    return session


def require_user(request: Request, session: dict = Depends(require_telegram_auth)) -> int:
    """
    Совместимость с существующими роутерами: возвращает telegram_user_id.
    """
    return int(session["telegram_user_id"])

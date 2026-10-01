"""
carnaval/routers/auth.py — эндпоинты аутентификации Telegram Mini App и сессий.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from carnaval import auth
from carnaval.db import get_state, set_state, log_audit
from carnaval.deps import (
    extract_session_token,
    get_cardinal,
    require_owner,
    require_panel_unlocked,
    require_telegram_auth,
)
from carnaval.security_utils import hash_password, verify_password
from carnaval.services import setup as setup_svc

logger = logging.getLogger("Carnaval.Routers.Auth")
router = APIRouter()


class TelegramAuthRequest(BaseModel):
    init_data: Optional[str] = Field(None, max_length=8192)
    initData: Optional[str] = Field(None, max_length=8192)

    def get_raw_init_data(self) -> str:
        return (self.init_data or self.initData or "").strip()


class PanelUnlockRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=6, max_length=128)


def _get_bot_token() -> str:
    """Получает токен Telegram бота из окружения или Cardinal."""
    env_token = os.getenv("TG_BOT_TOKEN", "").strip()
    if env_token:
        return env_token

    try:
        cardinal = get_cardinal()
        if cardinal and hasattr(cardinal, "MAIN_CFG") and "Telegram" in cardinal.MAIN_CFG:
            cfg_token = cardinal.MAIN_CFG["Telegram"].get("token", "").strip()
            if cfg_token:
                return cfg_token
    except Exception:
        pass

    return ""


@router.post("/auth")
@router.post("/auth/telegram")
async def telegram_auth(req: TelegramAuthRequest, request: Request, response: Response) -> JSONResponse:
    """
    Первичный вход в Mini App:
    1. Проверяет криптографическую подпись Telegram initData (HMAC-SHA256).
    2. Проверяет защиту от Replay Attack (auth_date).
    3. Создает защищенную серверную сессию в SQLite.
    4. Устанавливает HttpOnly secure cookie.
    """
    bot_token = _get_bot_token()
    if not bot_token:
        logger.error("Carnaval.Auth: TG_BOT_TOKEN не задан!")
        return JSONResponse({"error": "server_misconfiguration", "message": "TG_BOT_TOKEN не настроен"}, status_code=500)

    raw_init = req.get_raw_init_data()
    if not raw_init or len(raw_init) < 10:
        raise HTTPException(
            status_code=400,
            detail={"error": "missing_init_data", "message": "Параметр init_data обязателен"}
        )

    user_data = auth.verify_telegram_init_data(raw_init, bot_token)
    if not user_data:
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid_init_data", "message": "Telegram initData не прошла криптографическую проверку"}
        )

    telegram_user_id = int(user_data["id"])
    first_name = user_data.get("first_name", "")
    username = user_data.get("username", "")

    ip = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")

    # Проверяем состояние системы
    state = get_state("state", "UNINITIALIZED")
    owner_id_str = get_state("owner_telegram_id")

    env_owner = os.getenv("TG_OWNER_ID", "").strip() or os.getenv("OWNER_TELEGRAM_ID", "").strip()
    if env_owner and str(telegram_user_id) == env_owner:
        owner_id_str = env_owner
        set_state("owner_telegram_id", env_owner)

    # Если система уже настроена и пользователь не владелец и не в списке авторизованных
    if state == "INITIALIZED" and owner_id_str and int(owner_id_str) != telegram_user_id:
        # Проверяем, есть ли пользователь в authorized_users Cardinal
        is_allowed = False
        try:
            cardinal = get_cardinal()
            tg = getattr(cardinal, "telegram", None)
            if tg and hasattr(tg, "authorized_users") and tg.authorized_users:
                if telegram_user_id in tg.authorized_users or str(telegram_user_id) in tg.authorized_users:
                    is_allowed = True
        except Exception:
            pass

        if not is_allowed:
            logger.warning(f"Carnaval.Auth: доступ отклонен для Telegram ID {telegram_user_id} (не владелец)")
            return JSONResponse(
                {"error": "access_denied", "message": "Доступ разрешен только владельцу системы"},
                status_code=403
            )

    # Создаем серверную сессию
    session_token = auth.create_session(telegram_user_id, ip, user_agent)

    # Устанавливаем HttpOnly cookie
    is_secure = request.url.scheme == "https" or os.getenv("CARNAVAL_TRUST_PROXY", "0") == "1" or request.headers.get("x-forwarded-proto") == "https"
    res = JSONResponse({
        "status": "ok",
        "token": session_token,
        "csrf_token": session_token,
        "telegram_user_id": telegram_user_id,
        "first_name": first_name,
        "username": username,
        "system_state": state,
    })
    res.set_cookie(
        key="carnaval_session",
        value=session_token,
        max_age=auth.SESSION_TTL,
        httponly=True,
        secure=is_secure,
        samesite="lax",
        path="/",
    )
    return res


@router.post("/auth/panel-unlock")
async def panel_unlock(req: PanelUnlockRequest, request: Request, session: dict = Depends(require_telegram_auth)) -> JSONResponse:
    """
    Разблокировка чувствительных функций панели паролем.
    Включает защиту от брутфорса (rate limit + lockout).
    """
    telegram_user_id = session["telegram_user_id"]
    ip = request.client.host if request.client else ""
    rate_key = f"unlock:{telegram_user_id}:{ip}"

    # 1. Проверяем блокировку по числу попыток
    allowed, remaining = auth.check_login_rate_limit(rate_key)
    if not allowed:
        return JSONResponse(
            {"error": "rate_limited", "message": f"Слишком много попыток. Попробуйте через {remaining} сек."},
            status_code=429
        )

    # 2. Проверяем пароль
    stored_hash = get_state("panel_password_hash")
    if not stored_hash:
        return JSONResponse({"error": "not_configured", "message": "Пароль панели еще не настроен"}, status_code=400)

    if not verify_password(req.password, stored_hash):
        is_blocked, blocked_for = auth.record_failed_attempt(rate_key)
        log_audit("panel_unlock_failed", telegram_user_id, ip, "Неверный пароль панели")
        if is_blocked:
            return JSONResponse(
                {"error": "rate_limited", "message": f"Слишком много неверных попыток. Заблокировано на {blocked_for} сек."},
                status_code=429
            )
        return JSONResponse({"error": "invalid_password", "message": "Неверный пароль панели"}, status_code=400)

    # 3. Успех: сбрасываем счетчик ошибок и активируем сессию
    auth.reset_rate_limit(rate_key)
    session_token = request.state.session_token
    auth.unlock_panel_session(session_token)
    log_audit("panel_unlocked", telegram_user_id, ip, "Панель управления успешно разблокирована")

    return JSONResponse({"status": "ok", "panel_unlocked": True})


@router.post("/auth/panel-lock")
async def lock_panel(request: Request, session: dict = Depends(require_telegram_auth)) -> JSONResponse:
    """Блокировка панели управления (Lock Panel)."""
    token = getattr(request.state, "session_token", None) or extract_session_token(request)
    if token:
        auth.lock_panel_session(token)
    telegram_user_id = session["telegram_user_id"]
    ip = request.client.host if request.client else ""
    log_audit("panel_locked", telegram_user_id, ip, "Панель управления заблокирована")
    return JSONResponse({"status": "ok", "panel_unlocked": False})


@router.get("/me")
@router.get("/auth/me")
async def get_current_user_info(request: Request, session: dict = Depends(require_telegram_auth)) -> JSONResponse:
    """Возвращает безопасную информацию о текущем пользователе и состоянии панели."""
    telegram_user_id = session["telegram_user_id"]
    sys_status = setup_svc.get_system_status()

    fp_username = ""
    try:
        cardinal = get_cardinal()
        if hasattr(cardinal, "account") and cardinal.account:
            fp_username = getattr(cardinal.account, "username", "") or ""
    except Exception:
        pass

    return JSONResponse({
        "authenticated": True,
        "user_id": telegram_user_id,
        "telegram_user_id": telegram_user_id,
        "fp_username": fp_username,
        "role": session.get("role", "user"),
        "panel_unlocked": bool(session.get("panel_unlocked", False)),
        "system_state": sys_status["state"],
        "has_owner": sys_status["has_owner"],
        "has_golden_key": sys_status["has_golden_key"],
        "has_password": sys_status["has_password"],
    })


@router.post("/auth/logout")
async def logout(request: Request, response: Response, session: dict = Depends(require_telegram_auth)) -> JSONResponse:
    """Завершение текущей сессии."""
    token = getattr(request.state, "session_token", None) or extract_session_token(request)
    if token:
        auth.revoke_session(token)
    log_audit("logout", session["telegram_user_id"], request.client.host if request.client else "")
    res = JSONResponse({"status": "ok", "message": "Сессия завершена"})
    res.delete_cookie("carnaval_session", path="/")
    return res


@router.post("/auth/logout-all")
async def logout_all(request: Request, response: Response, session: dict = Depends(require_panel_unlocked)) -> JSONResponse:
    """Завершение всех сессий на всех устройствах."""
    uid = session["telegram_user_id"]
    count = auth.revoke_all_user_sessions(uid)
    log_audit("logout_all", uid, request.client.host if request.client else "", f"Отозвано сессий: {count}")
    res = JSONResponse({"status": "ok", "revoked_count": count})
    res.delete_cookie("carnaval_session", path="/")
    return res


@router.get("/auth/sessions")
async def get_active_sessions(session: dict = Depends(require_panel_unlocked)) -> JSONResponse:
    """Возвращает список активных сессий пользователя для экрана Безопасности."""
    uid = session["telegram_user_id"]
    return JSONResponse({"sessions": auth.list_user_sessions(uid)})


@router.post("/auth/change-password")
async def change_panel_password(req: ChangePasswordRequest, request: Request, session: dict = Depends(require_panel_unlocked)) -> JSONResponse:
    """Смена пароля панели управления."""
    uid = session["telegram_user_id"]
    stored_hash = get_state("panel_password_hash")

    if not stored_hash or not verify_password(req.old_password, stored_hash):
        log_audit("change_password_failed", uid, request.client.host if request.client else "", "Неверный старый пароль")
        return JSONResponse({"error": "invalid_password", "message": "Старый пароль указан неверно"}, status_code=400)

    new_hash = hash_password(req.new_password)
    set_state("panel_password_hash", new_hash)

    # Отзываем все остальные сессии кроме текущей
    current_hash = session["session_id_hash"]
    auth.revoke_all_user_sessions(uid, keep_token_hash=current_hash)

    log_audit("change_password_success", uid, request.client.host if request.client else "", "Пароль панели успешно изменен")
    return JSONResponse({"status": "ok", "message": "Пароль панели успешно обновлен"})

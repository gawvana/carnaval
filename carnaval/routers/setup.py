"""
carnaval/routers/setup.py — API эндпоинты пошаговой первоначальной настройки и захвата владения.
"""

from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from carnaval.deps import require_owner, require_telegram_auth
from carnaval.services import setup as setup_svc
from carnaval import auth

logger = logging.getLogger("Carnaval.Routers.Setup")
router = APIRouter()


class PasswordSetupRequest(BaseModel):
    password: str = Field(..., min_length=6, max_length=128)


class GoldenKeySetupRequest(BaseModel):
    golden_key: str = Field(..., min_length=32, max_length=32)


class FunPaySetupRequest(BaseModel):
    login: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=128)


class ProxySetupRequest(BaseModel):
    host: str = Field(..., min_length=1, max_length=255)
    port: int = Field(..., ge=1, le=65535)
    username: str | None = Field(None, max_length=128)
    password: str | None = Field(None, max_length=128)


@router.get("/setup/status")
async def get_setup_status() -> JSONResponse:
    """Возвращает текущее состояние первоначальной настройки."""
    return JSONResponse(setup_svc.get_system_status())


@router.post("/setup/claim")
async def claim_system_owner(request: Request, session: dict = Depends(require_telegram_auth)) -> JSONResponse:
    """
    Первичная регистрация владельца.
    Одноразовая, защищена от состояния гонки.
    """
    uid = session["telegram_user_id"]
    ip = request.client.host if request.client else ""

    ok, err = setup_svc.claim_ownership(uid, ip=ip)
    if not ok:
        raise HTTPException(status_code=409, detail={"error": "claim_rejected", "message": err})

    return JSONResponse({"status": "ok", "state": "OWNER_CLAIM"})


@router.post("/setup/password")
async def setup_initial_password(
    req: PasswordSetupRequest,
    request: Request,
    session: dict = Depends(require_owner),
) -> JSONResponse:
    """Установка пароля панели на этапе первичной настройки."""
    uid = session["telegram_user_id"]
    ip = request.client.host if request.client else ""

    ok, err = setup_svc.set_panel_password(uid, req.password, ip=ip)
    if not ok:
        raise HTTPException(status_code=400, detail={"error": "bad_request", "message": err})

    return JSONResponse({"status": "ok", "message": "Пароль панели успешно сохранен"})


@router.post("/setup/golden-key")
async def setup_initial_golden_key(
    req: GoldenKeySetupRequest,
    request: Request,
    session: dict = Depends(require_owner),
) -> JSONResponse:
    """Шифрование и сохранение Golden Key на этапе первичной настройки."""
    uid = session["telegram_user_id"]
    ip = request.client.host if request.client else ""

    ok, err = setup_svc.configure_golden_key(uid, req.golden_key, ip=ip)
    if not ok:
        raise HTTPException(status_code=400, detail={"error": "bad_request", "message": err})

    # Frontend получает ТОЛЬКО флаг успеха, реальный ключ никогда не возвращается
    return JSONResponse({"status": "ok", "configured": True, "message": "Golden Key успешно зашифрован"})


@router.post("/setup/finalize")
async def finalize_initial_setup(
    request: Request,
    session: dict = Depends(require_owner),
) -> JSONResponse:
    """
    Завершение первоначальной настройки.
    Навсегда закрывает OWNER_CLAIM и переводит систему в INITIALIZED.
    """
    uid = session["telegram_user_id"]
    ip = request.client.host if request.client else ""

    ok, err = setup_svc.finalize_setup(uid, ip=ip)
    if not ok:
        raise HTTPException(status_code=400, detail={"error": "bad_request", "message": err})

    # Разблокируем текущую сессию владельца для прямого перехода в Dashboard
    token = request.state.session_token
    auth.unlock_panel_session(token)

    return JSONResponse({"status": "ok", "state": "INITIALIZED", "panel_unlocked": True})


@router.post("/setup/funpay")
async def setup_initial_funpay(
    req: FunPaySetupRequest,
    request: Request,
    session: dict = Depends(require_owner),
) -> JSONResponse:
    """Сохранение логина и пароля FunPay на этапе первичной настройки."""
    uid = session["telegram_user_id"]
    ip = request.client.host if request.client else ""

    ok, err = setup_svc.configure_funpay_credentials(uid, req.login, req.password, ip=ip)
    if not ok:
        raise HTTPException(status_code=400, detail={"error": "bad_request", "message": err})

    return JSONResponse({"status": "ok", "configured": True, "message": "Учетные данные FunPay успешно зашифрованы"})


@router.post("/setup/funpay/test")
async def test_funpay_route(
    req: FunPaySetupRequest,
    session: dict = Depends(require_owner),
) -> JSONResponse:
    """Проверка подключения к FunPay."""
    ok, msg = setup_svc.test_funpay_connection(req.login, req.password)
    return JSONResponse({"status": "ok" if ok else "error", "message": msg})


@router.post("/setup/proxy")
async def setup_initial_proxy(
    req: ProxySetupRequest,
    request: Request,
    session: dict = Depends(require_owner),
) -> JSONResponse:
    """Сохранение прокси на этапе первичной настройки."""
    uid = session["telegram_user_id"]
    ip = request.client.host if request.client else ""

    ok, err = setup_svc.configure_proxy(uid, req.host, req.port, req.username or "", req.password or "", ip=ip)
    if not ok:
        raise HTTPException(status_code=400, detail={"error": "bad_request", "message": err})

    return JSONResponse({"status": "ok", "configured": True, "message": "Прокси успешно настроен"})


@router.post("/setup/proxy/test")
async def test_proxy_route(
    req: ProxySetupRequest,
    session: dict = Depends(require_owner),
) -> JSONResponse:
    """Тестирование прокси-соединения."""
    ok, msg = setup_svc.test_proxy_connection(req.host, req.port, req.username or "", req.password or "")
    if not ok:
        raise HTTPException(status_code=400, detail={"error": "bad_request", "message": msg})
    return JSONResponse({"status": "ok", "message": msg})


@router.get("/secrets/{secret_name}")
async def check_secret_status(
    secret_name: str,
    session: dict = Depends(require_telegram_auth),
) -> JSONResponse:
    """
    Section 61: Проверка настройки секрета.
    Никогда не возвращает реальное значение секрета, только факт его наличия!
    """
    from carnaval.secrets_manager import SecretManager
    allowed_map = {
        "golden-key": "golden_key",
        "golden_key": "golden_key",
        "funpay": "funpay_password",
        "proxy": "proxy_password",
    }
    target = allowed_map.get(secret_name, secret_name.replace("-", "_"))
    configured = SecretManager.has_secret(target)
    return JSONResponse({"configured": configured})

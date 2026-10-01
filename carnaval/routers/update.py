"""
carnaval/routers/update.py — API эндпоинты системы обновлений и управления системными режимами:
- /api/updates/current
- /api/updates/manifest
- /api/updates/check
- /api/updates/download
- /api/updates/install (Защищен: require_panel_unlocked, require_user)
- /api/updates/rollback (Защищен: require_panel_unlocked)
- /api/updates/status
- /api/system/mode
- /api/system/maintenance (Защищен: require_panel_unlocked)
- /api/system/safe-mode (Защищен: require_panel_unlocked)
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from carnaval.deps import require_panel_unlocked, require_user
from carnaval.services import system_mode
from carnaval.services import update as update_svc

logger = logging.getLogger("Carnaval.Routers.Update")

router = APIRouter()


# ---------------------------------------------------------------------------
# Модели запросов
# ---------------------------------------------------------------------------

class CheckUpdatesRequest(BaseModel):
    channel: Optional[str] = None
    force: bool = False


class DownloadUpdateRequest(BaseModel):
    manifest: Optional[dict[str, Any]] = None
    artifact_bytes_b64: Optional[str] = None


class InstallUpdateRequest(BaseModel):
    manifest_id: Optional[str] = None
    version: Optional[str] = None
    manifest: Optional[dict[str, Any]] = None
    artifact_bytes_b64: Optional[str] = None
    fail_on_migration: bool = False
    fail_on_health: bool = False


class RollbackUpdateRequest(BaseModel):
    backup_id: Optional[str] = None


class MaintenanceModeRequest(BaseModel):
    enabled: bool
    reason: str = ""


class SafeModeRequest(BaseModel):
    enabled: bool


# ---------------------------------------------------------------------------
# Эндпоинты обновлений
# ---------------------------------------------------------------------------

@router.get("/updates/current")
@router.get("/api/updates/current")
async def get_current_versions(request: Request) -> JSONResponse:
    """Возвращает информацию о текущих версиях компонентов, активном канале и системных режимах."""
    versions = update_svc.get_current_versions()
    return JSONResponse(versions)


@router.get("/updates/manifest")
@router.get("/api/updates/manifest")
async def get_update_manifest(
    request: Request,
    channel: Optional[str] = Query(None, description="Канал обновления (stable, beta, nightly)"),
) -> JSONResponse:
    """Возвращает манифест обновления для указанного или активного канала."""
    ch = channel or update_svc.get_active_channel()
    check_result = update_svc.check_for_updates(channel=ch)
    return JSONResponse(check_result["manifest"])


@router.post("/updates/check")
@router.post("/api/updates/check")
async def check_updates(
    request: Request,
    body: Optional[CheckUpdatesRequest] = None,
) -> JSONResponse:
    """
    Проверяет наличие доступных обновлений и возвращает унифицированную схему:
    {"ok": true, "current_version": str, "latest_version": str, "update_available": bool,
     "channel": str, "manifest": dict, "status": str, "progress": int, "error_code": Optional[str]}
    """
    channel = body.channel if body else None
    result = await asyncio.get_event_loop().run_in_executor(
        None, update_svc.check_for_updates, channel
    )
    return JSONResponse(result)


@router.post("/updates/download")
@router.post("/api/updates/download")
async def download_update(
    request: Request,
    body: Optional[DownloadUpdateRequest] = None,
) -> JSONResponse:
    """Загружает/стадирует пакет обновления (DOWNLOADING -> VERIFYING -> READY)."""
    manifest = body.manifest if body else None
    artifact_bytes = None
    if body and body.artifact_bytes_b64:
        try:
            artifact_bytes = base64.b64decode(body.artifact_bytes_b64)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid base64 in artifact_bytes_b64")

    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, update_svc.stage_update, manifest, artifact_bytes
        )
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"Carnaval.Routers.Update: Ошибка при скачивании: {e}")
        return JSONResponse({"status": "failed", "error": str(e)}, status_code=400)


@router.post("/updates/install")
@router.post("/api/updates/install")
async def install_update(
    request: Request,
    body: Optional[InstallUpdateRequest] = None,
    user_id: int = Depends(require_user),
    session: dict = Depends(require_panel_unlocked),
) -> JSONResponse:
    """
    Устанавливает обновление атомарно:
    1. Pre-update бэкап
    2. Проверка SHA-256 хэша и размера
    3. Распаковка в staging и валидация архива
    4. Выполнение миграций схемы (V1 -> V2 -> V3)
    5. Атомарная замена файлов приложения
    6. Перезапуск рантайма
    7. Health check и автоматический откат при ошибках
    8. Очистка временных файлов стадирования
    Защищено: require_panel_unlocked и require_user.
    """
    manifest = body.manifest if body else None
    version = body.version if body else None
    fail_on_mig = body.fail_on_migration if body else False
    fail_on_health = body.fail_on_health if body else False
    artifact_bytes = None

    if body and body.artifact_bytes_b64:
        try:
            artifact_bytes = base64.b64decode(body.artifact_bytes_b64)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid base64 in artifact_bytes_b64")


    success, message, details = await asyncio.get_event_loop().run_in_executor(
        None,
        update_svc.install_update,
        manifest,
        artifact_bytes,
        fail_on_mig,
        fail_on_health,
        version,
    )

    if not success:
        return JSONResponse({
            "ok": False,
            "success": False,
            "error": message,
            "details": details,
        }, status_code=400)

    return JSONResponse({
        "ok": True,
        "success": True,
        "message": message,
        "details": details,
    })


@router.post("/updates/rollback")
@router.post("/api/updates/rollback")
async def rollback_update(
    request: Request,
    body: Optional[RollbackUpdateRequest] = None,
    session: dict = Depends(require_panel_unlocked),
) -> JSONResponse:
    """
    Откатывает систему к предыдущему сохраненному бэкапу.
    Защищено: require_panel_unlocked.
    """
    backup_id = body.backup_id if body else None
    ok, err = await asyncio.get_event_loop().run_in_executor(
        None, update_svc.rollback_update, backup_id
    )
    if not ok:
        return JSONResponse({"ok": False, "success": False, "error": err}, status_code=400)
    return JSONResponse({"ok": True, "success": True, "message": "Rollback completed successfully"})


@router.get("/updates/status")
@router.get("/api/updates/status")
async def get_update_status(request: Request) -> JSONResponse:
    """Возвращает текущее состояние и прогресс процесса обновления."""
    return JSONResponse(update_svc.get_update_status())


# ---------------------------------------------------------------------------
# Эндпоинты системных режимов
# ---------------------------------------------------------------------------

@router.get("/system/mode")
@router.get("/api/system/mode")
async def get_system_mode(request: Request) -> JSONResponse:
    """Возвращает текущие статусы safe mode и maintenance mode."""
    return JSONResponse({
        "safe_mode": system_mode.is_safe_mode(),
        "maintenance_mode": system_mode.is_maintenance_mode(),
        "maintenance_reason": system_mode.get_maintenance_reason(),
    })


@router.post("/system/maintenance")
@router.post("/api/system/maintenance")
async def toggle_maintenance_mode(
    request: Request,
    body: MaintenanceModeRequest,
    session: dict = Depends(require_panel_unlocked),
) -> JSONResponse:
    """
    Включает или отключает режим обслуживания (Maintenance Mode).
    Защищено: require_panel_unlocked.
    """
    system_mode.set_maintenance_mode(body.enabled, reason=body.reason)
    return JSONResponse({
        "success": True,
        "maintenance_mode": system_mode.is_maintenance_mode(),
        "reason": system_mode.get_maintenance_reason(),
    })


@router.post("/system/safe-mode")
@router.post("/api/system/safe-mode")
async def toggle_safe_mode(
    request: Request,
    body: SafeModeRequest,
    session: dict = Depends(require_panel_unlocked),
) -> JSONResponse:
    """
    Включает или отключает безопасный режим (Safe Mode).
    Защищено: require_panel_unlocked.
    """
    system_mode.set_safe_mode(body.enabled)
    return JSONResponse({
        "success": True,
        "safe_mode": system_mode.is_safe_mode(),
    })

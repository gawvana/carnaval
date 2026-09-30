"""
carnaval/routers/settings.py — управление настройками бота (_main.cfg).

GET /api/settings — получить все настройки (с замаскированными секретами).
PATCH /api/settings/{section}/{key} — обновить настройку.
"""

from __future__ import annotations

import logging
from pydantic import BaseModel
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from carnaval.deps import require_user
from carnaval.services import config as cfg_service

router = APIRouter()
logger = logging.getLogger("Carnaval.Settings")


class SettingUpdateRequest(BaseModel):
    value: str
    confirm: bool = False


@router.get("/settings")
async def get_settings(request: Request, user_id: int = Depends(require_user)) -> JSONResponse:
    """Получить все секции настроек _main.cfg с маскированными секретами."""
    settings = cfg_service.get_masked_settings()
    return JSONResponse(settings)


@router.patch("/settings/{section}/{key}")
async def patch_setting(
    section: str,
    key: str,
    req: SettingUpdateRequest,
    request: Request,
    user_id: int = Depends(require_user),
) -> JSONResponse:
    """Обновить одну настройку в _main.cfg с валидацией схемы."""
    ok, err = cfg_service.update_setting(section, key, req.value, confirm=req.confirm)
    if not ok:
        logger.warning(f"Carnaval: отклонено изменение {section}.{key} пользователем {user_id}: {err}")
        return JSONResponse({"error": "invalid_setting", "message": err}, status_code=400)

    logger.info(f"AUDIT: user_id={user_id} обновил параметр {section}.{key}")
    return JSONResponse({"success": True, "section": section, "key": key})

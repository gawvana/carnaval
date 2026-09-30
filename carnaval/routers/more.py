"""
carnaval/routers/more.py — REST-эндпоинты для вкладки «Ещё».
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from carnaval.deps import require_user
from carnaval.services import more as more_svc

router = APIRouter()
logger = logging.getLogger("Carnaval.More")


# ── Вспомогательная проверка подтверждения ────────────────────

async def _check_confirmation(request: Request, query_or_arg_confirm: bool = False) -> bool:
    """Проверяет confirm через параметр, query string или JSON body."""
    if query_or_arg_confirm:
        return True
    if request.query_params.get("confirm", "").lower() in ("true", "1"):
        return True
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            body = await request.json()
            if isinstance(body, dict) and body.get("confirm"):
                return True
        except Exception:
            pass
    return False


# ── Pydantic-модели ──────────────────────────────────────────

class NotificationUpdate(BaseModel):
    section: str
    key: str
    enabled: bool


class GreetingUpdate(BaseModel):
    section: str
    key: str
    value: str


class BlacklistAdd(BaseModel):
    username: str


class ProxyAdd(BaseModel):
    proxy: str


class ProxyEnabled(BaseModel):
    enabled: bool


class GoldenKeyChange(BaseModel):
    new_key: str
    confirm: bool = False


class SystemAction(BaseModel):
    confirm: bool = False


# ─────────────────────────────────────────────────────────────
# 1. Уведомления
# ─────────────────────────────────────────────────────────────

@router.get("/more/notifications")
async def get_notifications(request: Request, user_id: int = Depends(require_user)):
    return JSONResponse(await asyncio.get_event_loop().run_in_executor(None, more_svc.get_notifications))


@router.patch("/more/notifications")
async def update_notification(request: Request, body: NotificationUpdate, user_id: int = Depends(require_user)):
    ok, err = await asyncio.get_event_loop().run_in_executor(
        None, more_svc.update_notification, body.section, body.key, body.enabled
    )
    if not ok:
        raise HTTPException(400, err)
    logger.info(f"AUDIT: user_id={user_id} изменил уведомление {body.section}.{body.key} -> {body.enabled}")
    return JSONResponse({"ok": True})


# ─────────────────────────────────────────────────────────────
# 2. Приветствие / OrderConfirm / ReviewReply
# ─────────────────────────────────────────────────────────────

@router.get("/more/greetings")
async def get_greetings(request: Request, user_id: int = Depends(require_user)):
    return JSONResponse(await asyncio.get_event_loop().run_in_executor(None, more_svc.get_greetings))


@router.patch("/more/greetings")
async def update_greeting(request: Request, body: GreetingUpdate, user_id: int = Depends(require_user)):
    ok, err = await asyncio.get_event_loop().run_in_executor(
        None, more_svc.update_greeting, body.section, body.key, body.value
    )
    if not ok:
        raise HTTPException(400, err)
    logger.info(f"AUDIT: user_id={user_id} обновил текст/настройку {body.section}.{body.key}")
    return JSONResponse({"ok": True})


# ─────────────────────────────────────────────────────────────
# 3. Чёрный список
# ─────────────────────────────────────────────────────────────

@router.get("/more/blacklist")
async def get_blacklist(request: Request, user_id: int = Depends(require_user)):
    return JSONResponse({"blacklist": await asyncio.get_event_loop().run_in_executor(None, more_svc.get_blacklist)})


@router.post("/more/blacklist")
async def add_to_blacklist(request: Request, body: BlacklistAdd, user_id: int = Depends(require_user)):
    ok, err = await asyncio.get_event_loop().run_in_executor(None, more_svc.add_to_blacklist, body.username)
    if not ok:
        raise HTTPException(400, err)
    logger.info(f"AUDIT: user_id={user_id} добавил в ЧС @{body.username}")
    return JSONResponse({"ok": True})


@router.delete("/more/blacklist/{username}")
async def remove_from_blacklist(request: Request, username: str, user_id: int = Depends(require_user)):
    ok, err = await asyncio.get_event_loop().run_in_executor(None, more_svc.remove_from_blacklist, username)
    if not ok:
        raise HTTPException(400, err)
    logger.info(f"AUDIT: user_id={user_id} удалил из ЧС @{username}")
    return JSONResponse({"ok": True})


# ─────────────────────────────────────────────────────────────
# 4. Плагины
# ─────────────────────────────────────────────────────────────

@router.get("/more/plugins")
async def list_plugins(request: Request, user_id: int = Depends(require_user)):
    return JSONResponse({"plugins": await asyncio.get_event_loop().run_in_executor(None, more_svc.list_plugins)})


@router.post("/more/plugins/{uuid}/toggle")
async def toggle_plugin(request: Request, uuid: str, user_id: int = Depends(require_user)):
    ok, err = await asyncio.get_event_loop().run_in_executor(None, more_svc.toggle_plugin, uuid)
    if not ok:
        raise HTTPException(400, err)
    logger.info(f"AUDIT: user_id={user_id} переключил статус плагина {uuid}")
    return JSONResponse({"ok": True})


@router.post("/more/plugins/upload")
async def upload_plugin(
    request: Request,
    user_id: int = Depends(require_user),
    file: UploadFile = File(...),
    confirm: bool = Form(False),
):
    """Загрузка плагина. Требует confirm=true (плагин исполняет произвольный код)."""
    if not confirm and not await _check_confirmation(request):
        return JSONResponse(
            {"error": "confirm_required", "message": "Загрузка плагина требует confirm=true. Плагин исполняет произвольный код!"},
            status_code=400,
        )

    content = await file.read()
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(413, "Файл слишком большой (макс. 2 МБ)")

    ok, err = await asyncio.get_event_loop().run_in_executor(
        None, more_svc.upload_plugin, file.filename or "plugin.py", content
    )
    if not ok:
        raise HTTPException(400, err)
    logger.warning(f"AUDIT: user_id={user_id} загрузил плагин '{file.filename}'")
    return JSONResponse({"ok": True})


@router.delete("/more/plugins/{uuid}")
async def delete_plugin(
    uuid: str,
    request: Request,
    user_id: int = Depends(require_user),
    confirm: bool = Query(False),
):
    """Удаление плагина. Требует confirm=true."""
    if not await _check_confirmation(request, confirm):
        return JSONResponse(
            {"error": "confirm_required", "message": "Удаление плагина требует confirm=true"},
            status_code=400,
        )

    ok, err = await asyncio.get_event_loop().run_in_executor(None, more_svc.delete_plugin, uuid)
    if not ok:
        raise HTTPException(400, err)
    logger.warning(f"AUDIT: user_id={user_id} удалил плагин {uuid}")
    return JSONResponse({"ok": True})


# ─────────────────────────────────────────────────────────────
# 5. Прокси
# ─────────────────────────────────────────────────────────────

@router.get("/more/proxy")
async def get_proxy(request: Request, user_id: int = Depends(require_user)):
    return JSONResponse(await asyncio.get_event_loop().run_in_executor(None, more_svc.get_proxy_info))


@router.post("/more/proxy")
async def add_proxy(request: Request, body: ProxyAdd, user_id: int = Depends(require_user)):
    ok, err = await asyncio.get_event_loop().run_in_executor(None, more_svc.add_proxy, body.proxy)
    if not ok:
        raise HTTPException(400, err)
    logger.info(f"AUDIT: user_id={user_id} добавил новый прокси")
    return JSONResponse({"ok": True})


@router.delete("/more/proxy/{proxy_id}")
async def delete_proxy(proxy_id: int, request: Request, user_id: int = Depends(require_user)):
    ok, err = await asyncio.get_event_loop().run_in_executor(None, more_svc.delete_proxy, proxy_id)
    if not ok:
        raise HTTPException(400, err)
    logger.info(f"AUDIT: user_id={user_id} удалил прокси #{proxy_id}")
    return JSONResponse({"ok": True})


@router.post("/more/proxy/{proxy_id}/activate")
async def activate_proxy(proxy_id: int, request: Request, user_id: int = Depends(require_user)):
    ok, err = await asyncio.get_event_loop().run_in_executor(None, more_svc.set_active_proxy, proxy_id)
    if not ok:
        raise HTTPException(400, err)
    logger.info(f"AUDIT: user_id={user_id} активировал прокси #{proxy_id}")
    return JSONResponse({"ok": True})


@router.patch("/more/proxy/enabled")
async def set_proxy_enabled(request: Request, body: ProxyEnabled, user_id: int = Depends(require_user)):
    ok, err = await asyncio.get_event_loop().run_in_executor(None, more_svc.set_proxy_enabled, body.enabled)
    if not ok:
        raise HTTPException(400, err)
    logger.info(f"AUDIT: user_id={user_id} изменил статус использования прокси: {body.enabled}")
    return JSONResponse({"ok": True})


# ─────────────────────────────────────────────────────────────
# 6. Авторизованные пользователи (ТОЛЬКО просмотр и удаление)
# ─────────────────────────────────────────────────────────────

@router.get("/more/authorized-users")
async def get_authorized_users(request: Request, user_id: int = Depends(require_user)):
    return JSONResponse({"users": await asyncio.get_event_loop().run_in_executor(None, more_svc.get_authorized_users)})


@router.delete("/more/authorized-users/{target_user_id}")
async def remove_authorized_user(
    target_user_id: int,
    request: Request,
    user_id: int = Depends(require_user),
    confirm: bool = Query(False),
):
    """
    Удаление администратора.
    Защита: нельзя удалить самого себя, нельзя удалить последнего администратора,
    требуется явное подтверждение confirm=true.
    """
    if target_user_id == user_id:
        return JSONResponse(
            {"error": "self_deletion_forbidden", "message": "Нельзя удалить самого себя из администраторов"},
            status_code=400,
        )

    if not await _check_confirmation(request, confirm):
        return JSONResponse(
            {"error": "confirm_required", "message": "Удаление администратора требует confirm=true"},
            status_code=400,
        )

    ok, err = await asyncio.get_event_loop().run_in_executor(None, more_svc.remove_authorized_user, target_user_id)
    if not ok:
        raise HTTPException(400, err)

    logger.warning(f"AUDIT: user_id={user_id} удалил администратора {target_user_id}")
    return JSONResponse({"ok": True})


# ─────────────────────────────────────────────────────────────
# 7. Аккаунт FunPay
# ─────────────────────────────────────────────────────────────

@router.get("/more/account")
async def get_account_info(request: Request, user_id: int = Depends(require_user)):
    return JSONResponse(await asyncio.get_event_loop().run_in_executor(None, more_svc.get_account_info))


@router.post("/more/account/golden-key")
async def change_golden_key(request: Request, body: GoldenKeyChange, user_id: int = Depends(require_user)):
    if not body.confirm:
        return JSONResponse(
            {"error": "confirm_required", "message": "Смена golden_key требует confirm=true"},
            status_code=400,
        )
    ok, err = await asyncio.get_event_loop().run_in_executor(
        None, more_svc.change_golden_key, body.new_key, body.confirm
    )
    if not ok:
        raise HTTPException(400, err)
    logger.warning(f"AUDIT: user_id={user_id} изменил golden_key аккаунта")
    return JSONResponse({"ok": True})


@router.delete("/more/account/golden-key")
async def delete_golden_key_route(request: Request, user_id: int = Depends(require_user), confirm: bool = Query(False)):
    if not await _check_confirmation(request, confirm):
        return JSONResponse(
            {"error": "confirm_required", "message": "Удаление golden_key требует confirm=true"},
            status_code=400,
        )
    ok, err = await asyncio.get_event_loop().run_in_executor(None, more_svc.delete_golden_key, True)
    if not ok:
        raise HTTPException(400, err)
    logger.warning(f"AUDIT: user_id={user_id} удалил golden_key аккаунта")
    return JSONResponse({"ok": True})


# ─────────────────────────────────────────────────────────────
# 8. Логи и аудит
# ─────────────────────────────────────────────────────────────

@router.get("/more/audit-logs")
async def get_audit_logs_route(request: Request, user_id: int = Depends(require_user), limit: int = 100):
    """Возвращает историю событий безопасности и аудита."""
    from carnaval.db import get_db_connection
    conn = get_db_connection()
    try:
        limit_clean = min(max(1, limit), 200)
        rows = conn.execute(
            "SELECT id, action, telegram_user_id, ip, details, created_at FROM audit_logs ORDER BY id DESC LIMIT ?",
            (limit_clean,)
        ).fetchall()
        logs = [
            {
                "id": r["id"],
                "action": r["action"],
                "telegram_user_id": r["telegram_user_id"],
                "ip": r["ip"],
                "details": r["details"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
        return JSONResponse({"logs": logs})
    finally:
        conn.close()


@router.get("/more/logs")
async def get_logs(request: Request, n: int = 150, user_id: int = Depends(require_user)):
    lines = await asyncio.get_event_loop().run_in_executor(None, more_svc.get_logs, n)
    return JSONResponse({"lines": lines})


@router.delete("/more/logs")
async def clear_logs(request: Request, user_id: int = Depends(require_user), confirm: bool = Query(False)):
    """Очистка логов. Требует confirm=true."""
    if not await _check_confirmation(request, confirm):
        return JSONResponse(
            {"error": "confirm_required", "message": "Очистка логов требует confirm=true"},
            status_code=400,
        )
    ok, err = await asyncio.get_event_loop().run_in_executor(None, more_svc.clear_logs)
    if not ok:
        raise HTTPException(400, err)
    logger.warning(f"AUDIT: user_id={user_id} очистил историю логов")
    return JSONResponse({"ok": True})


# ─────────────────────────────────────────────────────────────
# 9. Бэкап конфигов
# ─────────────────────────────────────────────────────────────

@router.get("/more/backup")
async def download_backup(request: Request, user_id: int = Depends(require_user)):
    data = await asyncio.get_event_loop().run_in_executor(None, more_svc.create_configs_backup)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info(f"AUDIT: user_id={user_id} скачал резервную копию конфигурации")
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="carnaval_backup_{ts}.zip"',
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )


@router.post("/more/backup/restore")
async def restore_backup(
    request: Request,
    user_id: int = Depends(require_user),
    file: UploadFile = File(...),
    confirm: bool = Form(False),
):
    """Восстановление конфигурации из бэкапа. Требует confirm=true."""
    if not confirm and not await _check_confirmation(request):
        return JSONResponse(
            {"error": "confirm_required", "message": "Восстановление бэкапа требует confirm=true"},
            status_code=400,
        )
    if file.size and file.size > 25 * 1024 * 1024:
        raise HTTPException(413, "Файл бэкапа превышает лимит 25 МБ")
    content = await file.read()
    ok, err = await asyncio.get_event_loop().run_in_executor(None, more_svc.restore_backup, content)
    if not ok:
        raise HTTPException(400, err)
    logger.warning(f"AUDIT: user_id={user_id} восстановил конфигурацию из архива '{file.filename}'")
    return JSONResponse({"ok": True})


# ─────────────────────────────────────────────────────────────
# 10. Системные команды
# ─────────────────────────────────────────────────────────────

@router.post("/more/system/restart")
async def restart(request: Request, body: SystemAction, user_id: int = Depends(require_user)):
    if not body.confirm:
        return JSONResponse(
            {"error": "confirm_required", "message": "Перезапуск требует confirm=true"},
            status_code=400,
        )
    ok, err = await asyncio.get_event_loop().run_in_executor(None, more_svc.restart_cardinal, body.confirm)
    if not ok:
        raise HTTPException(400, err)
    logger.warning(f"AUDIT: user_id={user_id} инициировал перезапуск бота")
    return JSONResponse({"ok": True, "message": "Перезапуск инициирован"})


@router.post("/more/system/shutdown")
async def shutdown(request: Request, body: SystemAction, user_id: int = Depends(require_user)):
    if not body.confirm:
        return JSONResponse(
            {"error": "confirm_required", "message": "Выключение требует confirm=true"},
            status_code=400,
        )
    ok, err = await asyncio.get_event_loop().run_in_executor(None, more_svc.shutdown_cardinal, body.confirm)
    if not ok:
        raise HTTPException(400, err)
    logger.warning(f"AUDIT: user_id={user_id} инициировал выключение бота")
    return JSONResponse({"ok": True, "message": "Выключение инициировано"})

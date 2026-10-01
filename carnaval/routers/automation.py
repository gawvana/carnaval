"""
carnaval/routers/automation.py — API для вкладки «Авто» (автовыдача, склад, автоответчик, шаблоны).
"""

from __future__ import annotations

import logging
from typing import Optional, List
from pydantic import BaseModel
from fastapi import APIRouter, Depends, Request, UploadFile, File, Query
from fastapi.responses import JSONResponse, PlainTextResponse

from carnaval.deps import require_user
from carnaval.services import automation as auto_svc

router = APIRouter()
logger = logging.getLogger("Carnaval.Automation")


# ── Схемы данных ─────────────────────────────────────────────

class DeliveryLotCreate(BaseModel):
    name: str
    response: str
    productsFileName: Optional[str] = None
    disable: bool = False


class DeliveryLotUpdate(BaseModel):
    response: Optional[str] = None
    productsFileName: Optional[str] = None
    disable: Optional[bool] = None


class GoodsAddRequest(BaseModel):
    goods: List[str]
    at_zero_position: bool = False


class AutoResponseCreate(BaseModel):
    command: str
    response: str
    telegramNotification: bool = False
    enabled: bool = True
    notificationText: Optional[str] = None


class AutoResponseUpdate(BaseModel):
    command: Optional[str] = None
    response: Optional[str] = None
    telegramNotification: Optional[bool] = None
    enabled: Optional[bool] = None
    notificationText: Optional[str] = None


class TemplateRequest(BaseModel):
    text: str


class TemplateSendRequest(BaseModel):
    chat_id: int
    username: Optional[str] = None


class TemplateRenderRequest(BaseModel):
    username: Optional[str] = None



async def _check_confirmation(request: Request, query_confirm: bool = False) -> bool:
    """Проверяет confirm через query-параметр или JSON body."""
    if query_confirm:
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


# ─────────────────────────────────────────────────────────────
# 1. Автовыдача
# ─────────────────────────────────────────────────────────────

@router.get("/delivery/lots")
async def get_delivery_lots(request: Request, user_id: int = Depends(require_user)) -> JSONResponse:
    return JSONResponse({"lots": auto_svc.list_delivery_lots()})


@router.get("/delivery/lots/{i}")
async def get_delivery_lot_item(i: int, request: Request, user_id: int = Depends(require_user)) -> JSONResponse:
    lot = auto_svc.get_delivery_lot(i)
    if not lot:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return JSONResponse(lot)


@router.post("/delivery/lots")
async def create_delivery_lot_route(req: DeliveryLotCreate, request: Request, user_id: int = Depends(require_user)) -> JSONResponse:
    try:
        lot = auto_svc.create_delivery_lot(req.name, req.response, req.productsFileName, req.disable)
        logger.info(f"AUDIT: user_id={user_id} создал лот автовыдачи '{req.name}'")
        return JSONResponse(lot)
    except Exception as e:
        return JSONResponse({"error": "bad_request", "message": str(e)}, status_code=400)


@router.patch("/delivery/lots/{i}")
async def update_delivery_lot_route(i: int, req: DeliveryLotUpdate, request: Request, user_id: int = Depends(require_user)) -> JSONResponse:
    try:
        lot = auto_svc.update_delivery_lot(i, req.response, req.productsFileName, req.disable)
        logger.info(f"AUDIT: user_id={user_id} обновил лот автовыдачи #{i}")
        return JSONResponse(lot)
    except Exception as e:
        return JSONResponse({"error": "bad_request", "message": str(e)}, status_code=400)


@router.delete("/delivery/lots/{i}")
async def delete_delivery_lot_route(
    i: int,
    request: Request,
    user_id: int = Depends(require_user),
    confirm: bool = Query(False),
) -> JSONResponse:
    if not await _check_confirmation(request, confirm):
        return JSONResponse({"error": "confirm_required", "message": "Удаление лота требует confirm=true"}, status_code=400)
    try:
        auto_svc.delete_delivery_lot(i)
        logger.warning(f"AUDIT: user_id={user_id} удалил лот автовыдачи #{i}")
        return JSONResponse({"success": True})
    except Exception as e:
        return JSONResponse({"error": "bad_request", "message": str(e)}, status_code=400)


@router.post("/delivery/lots/{i}/test")
async def create_delivery_lot_test(i: int, request: Request, user_id: int = Depends(require_user)) -> JSONResponse:
    try:
        test_info = auto_svc.create_delivery_test(i)
        return JSONResponse(test_info)
    except Exception as e:
        return JSONResponse({"error": "bad_request", "message": str(e)}, status_code=400)


# ─────────────────────────────────────────────────────────────
# 2. Файлы товаров
# ─────────────────────────────────────────────────────────────

@router.get("/delivery/files")
async def get_products_files(request: Request, user_id: int = Depends(require_user)) -> JSONResponse:
    return JSONResponse({"files": auto_svc.list_products_files()})


@router.get("/delivery/files/{name}")
async def get_products_file(name: str, request: Request, user_id: int = Depends(require_user)) -> JSONResponse:
    try:
        goods = auto_svc.get_products_file_goods(name)
        return JSONResponse({"name": name, "goods": goods})
    except Exception as e:
        return JSONResponse({"error": "not_found", "message": str(e)}, status_code=404)


@router.post("/delivery/files")
async def create_products_file_route(
    request: Request,
    user_id: int = Depends(require_user),
) -> JSONResponse:
    try:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            body = await request.json()
            filename = body.get("name")
            if not filename:
                return JSONResponse({"error": "bad_request", "message": "Missing file name"}, status_code=400)
            goods = body.get("goods", [])
            res = auto_svc.create_products_file(filename, goods)
        else:
            form = await request.form()
            file = form.get("file")
            name = form.get("name")
            goods = []
            if file and hasattr(file, "read"):
                filename = name or getattr(file, "filename", "products.txt") or "products.txt"
                content = await file.read()
                if isinstance(content, bytes):
                    lines = content.decode("utf-8", errors="ignore").splitlines()
                else:
                    lines = str(content).splitlines()
                goods = [line.strip() for line in lines if line.strip()]
            else:
                if not name:
                    return JSONResponse({"error": "bad_request", "message": "Missing file or name"}, status_code=400)
                filename = str(name)
            res = auto_svc.create_products_file(filename, goods)
        logger.info(f"AUDIT: user_id={user_id} создал файл товаров '{res.get('name')}'")
        return JSONResponse(res)
    except Exception as e:
        return JSONResponse({"error": "bad_request", "message": str(e)}, status_code=400)


@router.delete("/delivery/files/{name}")
async def delete_products_file_route(
    name: str,
    request: Request,
    user_id: int = Depends(require_user),
    confirm: bool = Query(False),
) -> JSONResponse:
    if not await _check_confirmation(request, confirm):
        return JSONResponse({"error": "confirm_required", "message": "Удаление файла товаров требует confirm=true"}, status_code=400)
    try:
        ok = auto_svc.delete_products_file(name)
        logger.warning(f"AUDIT: user_id={user_id} удалил файл товаров '{name}'")
        return JSONResponse({"success": ok})
    except Exception as e:
        return JSONResponse({"error": "bad_request", "message": str(e)}, status_code=400)


@router.post("/delivery/files/{name}/goods")
async def add_goods_route(name: str, req: GoodsAddRequest, request: Request, user_id: int = Depends(require_user)) -> JSONResponse:
    try:
        new_count = auto_svc.add_goods_to_file(name, req.goods, req.at_zero_position)
        logger.info(f"AUDIT: user_id={user_id} добавил {len(req.goods)} товаров в файл '{name}'")
        return JSONResponse({"success": True, "count": new_count})
    except Exception as e:
        return JSONResponse({"error": "bad_request", "message": str(e)}, status_code=400)


@router.get("/delivery/files/{name}/download")
async def download_products_file_route(name: str, request: Request, user_id: int = Depends(require_user)):
    try:
        goods = auto_svc.get_products_file_goods(name, limit=100000)
        content = "\n".join(goods)
        return PlainTextResponse(
            content,
            headers={
                "Content-Disposition": f'attachment; filename="{name}"',
                "Content-Type": "text/plain; charset=utf-8",
            }
        )
    except Exception as e:
        return JSONResponse({"error": "not_found", "message": str(e)}, status_code=404)


# ─────────────────────────────────────────────────────────────
# 3. Автоответчик
# ─────────────────────────────────────────────────────────────

@router.get("/autoresponse/commands")
async def get_commands(request: Request, user_id: int = Depends(require_user)) -> JSONResponse:
    return JSONResponse({"commands": auto_svc.list_auto_response_commands()})


@router.post("/autoresponse/commands")
async def create_command_route(req: AutoResponseCreate, request: Request, user_id: int = Depends(require_user)) -> JSONResponse:
    try:
        cmd = auto_svc.create_auto_response_command(
            req.command, req.response, req.telegramNotification, req.enabled, req.notificationText or ""
        )
        logger.info(f"AUDIT: user_id={user_id} создал команду автоответчика '{req.command}'")
        return JSONResponse(cmd)
    except Exception as e:
        return JSONResponse({"error": "bad_request", "message": str(e)}, status_code=400)


@router.patch("/autoresponse/commands/{i}")
async def update_command_route(i: int, req: AutoResponseUpdate, request: Request, user_id: int = Depends(require_user)) -> JSONResponse:
    try:
        cmd = auto_svc.update_auto_response_command(
            i, req.command, req.response, req.telegramNotification, req.enabled, req.notificationText
        )
        logger.info(f"AUDIT: user_id={user_id} обновил команду автоответчика #{i}")
        return JSONResponse(cmd)
    except Exception as e:
        return JSONResponse({"error": "bad_request", "message": str(e)}, status_code=400)


@router.delete("/autoresponse/commands/{i}")
async def delete_command_route(
    i: int,
    request: Request,
    user_id: int = Depends(require_user),
    confirm: bool = Query(False),
) -> JSONResponse:
    if not await _check_confirmation(request, confirm):
        return JSONResponse({"error": "confirm_required", "message": "Удаление команды требует confirm=true"}, status_code=400)
    try:
        auto_svc.delete_auto_response_command(i)
        logger.warning(f"AUDIT: user_id={user_id} удалил команду автоответчика #{i}")
        return JSONResponse({"success": True})
    except Exception as e:
        return JSONResponse({"error": "bad_request", "message": str(e)}, status_code=400)


# ─────────────────────────────────────────────────────────────
# 4. Шаблоны ответов
# ─────────────────────────────────────────────────────────────

@router.get("/templates")
async def get_templates_route(request: Request, user_id: int = Depends(require_user)) -> JSONResponse:
    return JSONResponse({"templates": auto_svc.list_templates()})


@router.post("/templates")
async def create_template_route(req: TemplateRequest, request: Request, user_id: int = Depends(require_user)) -> JSONResponse:
    try:
        res = auto_svc.create_template(req.text)
        logger.info(f"AUDIT: user_id={user_id} создал шаблон быстрого ответа")
        return JSONResponse(res)
    except Exception as e:
        return JSONResponse({"error": "bad_request", "message": str(e)}, status_code=400)


@router.patch("/templates/{i}")
async def update_template_route(i: int, req: TemplateRequest, request: Request, user_id: int = Depends(require_user)) -> JSONResponse:
    try:
        res = auto_svc.update_template(i, req.text)
        logger.info(f"AUDIT: user_id={user_id} обновил шаблон быстрого ответа #{i}")
        return JSONResponse(res)
    except Exception as e:
        return JSONResponse({"error": "bad_request", "message": str(e)}, status_code=400)


@router.delete("/templates/{i}")
async def delete_template_route(
    i: int,
    request: Request,
    user_id: int = Depends(require_user),
    confirm: bool = Query(False),
) -> JSONResponse:
    if not await _check_confirmation(request, confirm):
        return JSONResponse({"error": "confirm_required", "message": "Удаление шаблона требует confirm=true"}, status_code=400)
    try:
        auto_svc.delete_template(i)
        logger.warning(f"AUDIT: user_id={user_id} удалил шаблон #{i}")
        return JSONResponse({"success": True})
    except Exception as e:
        return JSONResponse({"error": "bad_request", "message": str(e)}, status_code=400)


@router.get("/templates/answer-mode")
async def get_templates_answer_mode(request: Request, username: Optional[str] = None, user_id: int = Depends(require_user)) -> JSONResponse:
    """Список шаблонов в режиме ответа с подстановкой переменной username."""
    items = auto_svc.list_templates_answer_mode(username)
    return JSONResponse({"templates": items})


@router.post("/templates/{i}/render")
async def render_template_route(i: int, req: TemplateRenderRequest, request: Request, user_id: int = Depends(require_user)) -> JSONResponse:
    """Предпросмотр рендеринга шаблона с подстановкой $username."""
    try:
        rendered = auto_svc.render_template(i, req.username)
        return JSONResponse({"index": i, "rendered": rendered})
    except IndexError:
        return JSONResponse({"error": "not_found", "message": f"Template #{i} not found"}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": "bad_request", "message": str(e)}, status_code=400)


@router.post("/templates/{i}/send")
async def send_template_route(i: int, req: TemplateSendRequest, request: Request, user_id: int = Depends(require_user)) -> JSONResponse:
    """Отправить шаблон ответа в чат FunPay."""
    try:
        ok = await auto_svc.send_template_to_chat(i, req.chat_id, req.username)
        if not ok:
            return JSONResponse({"error": "send_failed", "message": "Failed to send message via template"}, status_code=500)
        logger.info(f"AUDIT: user_id={user_id} отправил шаблон #{i} в чат #{req.chat_id}")
        return JSONResponse({"success": True, "index": i, "chat_id": req.chat_id})
    except IndexError:
        return JSONResponse({"error": "not_found", "message": f"Template #{i} not found"}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": "bad_request", "message": str(e)}, status_code=400)



# ─────────────────────────────────────────────────────────────
# 5. Лоты FunPay
# ─────────────────────────────────────────────────────────────

@router.get("/funpay/lots")
async def get_funpay_lots_route(request: Request, user_id: int = Depends(require_user), refresh: bool = False) -> JSONResponse:
    try:
        lots = await auto_svc.get_funpay_lots(refresh=refresh)
        return JSONResponse({"lots": lots})
    except Exception as e:
        return JSONResponse({"error": "failed_to_fetch_lots", "message": str(e)}, status_code=500)

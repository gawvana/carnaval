"""
carnaval/routers/chats.py — API переписок и сообщений FunPay.
"""

from __future__ import annotations

import logging
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, Request, UploadFile, File
from fastapi.responses import JSONResponse

from carnaval.deps import require_user
from carnaval.services import chats as chats_svc

router = APIRouter()
logger = logging.getLogger("Carnaval.Chats")


class MessageSendRequest(BaseModel):
    text: str
    chat_name: Optional[str] = None


@router.get("/chats")
async def list_chats(
    request: Request,
    user_id: int = Depends(require_user),
    update: bool = False,
) -> JSONResponse:
    """Получить список чатов."""
    try:
        chats = await chats_svc.get_chats(update=update)
        return JSONResponse({"chats": chats})
    except Exception as e:
        logger.error(f"Failed to fetch chats: {e}")
        return JSONResponse({"error": "chats_fetch_failed", "message": str(e)}, status_code=500)


@router.get("/chats/{chat_id}/history")
async def chat_history(
    chat_id: int,
    request: Request,
    user_id: int = Depends(require_user),
    before: Optional[int] = None,
) -> JSONResponse:
    """Получить историю сообщений в чате."""
    try:
        messages = await chats_svc.get_chat_history(chat_id, last_message_id=before)
        return JSONResponse({"messages": messages})
    except Exception as e:
        logger.error(f"Failed to fetch chat history for {chat_id}: {e}")
        return JSONResponse({"error": "history_fetch_failed", "message": str(e)}, status_code=500)


@router.post("/chats/{chat_id}/messages")
async def send_chat_message(
    chat_id: int,
    req: MessageSendRequest,
    request: Request,
    user_id: int = Depends(require_user),
) -> JSONResponse:
    """Отправить текстовое сообщение в чат."""
    if not req.text.strip():
        return JSONResponse({"error": "empty_message", "message": "Message text cannot be empty"}, status_code=400)

    try:
        ok = await chats_svc.send_message(chat_id, req.text, chat_name=req.chat_name)
        if not ok:
            return JSONResponse({"error": "send_failed", "message": "Failed to deliver message"}, status_code=500)
        logger.info(f"AUDIT: user_id={user_id} отправил сообщение в чат #{chat_id}")
        return JSONResponse({"success": True})
    except Exception as e:
        logger.error(f"Failed to send message to {chat_id}: {e}")
        return JSONResponse({"error": "send_failed", "message": str(e)}, status_code=500)


@router.post("/chats/{chat_id}/images")
async def send_chat_image(
    chat_id: int,
    request: Request,
    user_id: int = Depends(require_user),
    file: UploadFile = File(...),
    chat_name: Optional[str] = None,
) -> JSONResponse:
    """Загрузить и отправить изображение в чат."""
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # лимит 10 МБ
        return JSONResponse({"error": "file_too_large", "message": "Image size exceeds 10MB"}, status_code=400)

    try:
        ok = await chats_svc.send_image(chat_id, content, filename=file.filename or "image.png", chat_name=chat_name)
        if not ok:
            return JSONResponse({"error": "image_send_failed", "message": "Failed to upload or send image"}, status_code=500)
        logger.info(f"AUDIT: user_id={user_id} отправил картинку в чат #{chat_id}")
        return JSONResponse({"success": True})
    except Exception as e:
        logger.error(f"Failed to send image to {chat_id}: {e}")
        return JSONResponse({"error": "image_send_failed", "message": str(e)}, status_code=500)


@router.get("/chats/{chat_id}/viewing")
async def buyer_viewing(
    chat_id: int,
    buyer_id: int,
    request: Request,
    user_id: int = Depends(require_user),
) -> JSONResponse:
    """Получить информацию 'Покупатель смотрит'."""
    try:
        viewing = await chats_svc.get_buyer_viewing(buyer_id)
        return JSONResponse({"viewing": viewing})
    except Exception as e:
        logger.error(f"Failed to fetch buyer viewing for {buyer_id}: {e}")
        return JSONResponse({"error": "viewing_fetch_failed", "message": str(e)}, status_code=500)

"""
carnaval/services/chats.py — сервис работы с чатами и переписками FunPay.
"""

from __future__ import annotations

import io
import asyncio
from typing import Any, Optional

from carnaval.deps import get_cardinal


def _chat_to_dict(c: Any) -> dict[str, Any]:
    return {
        "id": getattr(c, "id", 0),
        "name": getattr(c, "name", "") or "Чат",
        "last_message_text": getattr(c, "last_message_text", "") or "",
        "unread": bool(getattr(c, "unread", False)),
        "node_msg_id": getattr(c, "node_msg_id", 0),
        "user_msg_id": getattr(c, "user_msg_id", 0),
        "last_by_bot": getattr(c, "last_by_bot", None),
    }


def _message_to_dict(m: Any) -> dict[str, Any]:
    return {
        "id": getattr(m, "id", 0),
        "text": getattr(m, "text", "") or "",
        "chat_id": getattr(m, "chat_id", 0),
        "chat_name": getattr(m, "chat_name", ""),
        "author": getattr(m, "author", ""),
        "author_id": getattr(m, "author_id", 0),
        "image_link": getattr(m, "image_link", None),
        "image_name": getattr(m, "image_name", None),
        "badge_text": getattr(m, "badge_text", None),
    }


class ChatsServiceError(Exception):
    """Базовое исключение сервиса чатов."""
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.message = message


class FunPayAccountNotInitializedError(ChatsServiceError):
    def __init__(self, message: str = "Аккаунт FunPay не инициализирован или не подключен"):
        super().__init__("FUNPAY_ACCOUNT_NOT_INITIALIZED", message)


class FunPayNetworkError(ChatsServiceError):
    def __init__(self, message: str = "Ошибка сети при обращении к FunPay"):
        super().__init__("NETWORK_ERROR", message)


async def _ensure_account_initiated():
    cardinal = get_cardinal()
    acc = cardinal.account
    if not acc or not getattr(acc, "is_initiated", False):
        from carnaval.services.account_lifecycle import lifecycle_manager
        status = lifecycle_manager.get_status()
        if status.get("has_key"):
            try:
                await lifecycle_manager.reconnect_account()
            except Exception:
                pass
        acc = cardinal.account
        if not acc or not getattr(acc, "is_initiated", False):
            raise FunPayAccountNotInitializedError()
    return acc


async def get_chats(update: bool = False) -> list[dict[str, Any]]:
    """Получить список последних переписок продавца."""
    acc = await _ensure_account_initiated()

    def _fetch():
        chats_dict = acc.get_chats(update=update)
        return list(chats_dict.values()) if isinstance(chats_dict, dict) else list(chats_dict)

    try:
        chats = await asyncio.to_thread(_fetch)
        return [_chat_to_dict(c) for c in (chats or [])]
    except Exception as e:
        if isinstance(e, ChatsServiceError):
            raise
        raise FunPayNetworkError(f"Ошибка при получении списка чатов: {e}") from e


async def get_chat_history(chat_id: int | str, last_message_id: Optional[int] = None) -> list[dict[str, Any]]:
    """Получить историю сообщений в чате."""
    acc = await _ensure_account_initiated()

    def _fetch():
        return acc.get_chat_history(chat_id, last_message_id=last_message_id)

    try:
        messages = await asyncio.to_thread(_fetch)
        return [_message_to_dict(m) for m in (messages or [])]
    except Exception as e:
        if isinstance(e, ChatsServiceError):
            raise
        raise FunPayNetworkError(f"Ошибка при получении истории сообщений: {e}") from e


async def send_message(chat_id: int | str, text: str, chat_name: Optional[str] = None) -> bool:
    """
    Отправить текстовое сообщение в чат FunPay через Cardinal.
    Поддерживает подстановки, $photo=ID, $sleep= и водяной знак.
    """
    await _ensure_account_initiated()
    cardinal = get_cardinal()

    def _send():
        res = cardinal.send_message(chat_id, text, chat_name=chat_name)
        return bool(res)

    try:
        return await asyncio.to_thread(_send)
    except Exception as e:
        if isinstance(e, ChatsServiceError):
            raise
        raise FunPayNetworkError(f"Ошибка при отправке сообщения: {e}") from e


async def send_image(chat_id: int | str, file_bytes: bytes, filename: str = "image.png", chat_name: Optional[str] = None) -> bool:
    """
    Загрузить и отправить изображение в чат FunPay.
    """
    acc = await _ensure_account_initiated()

    def _upload_and_send():
        bio = io.BytesIO(file_bytes)
        bio.name = filename
        img_id = acc.upload_image(bio, type_="chat")
        if not img_id:
            return False
        res = acc.send_image(int(chat_id), img_id, chat_name=chat_name)
        return bool(res)

    try:
        return await asyncio.to_thread(_upload_and_send)
    except Exception as e:
        if isinstance(e, ChatsServiceError):
            raise
        raise FunPayNetworkError(f"Ошибка при отправке изображения: {e}") from e


async def get_buyer_viewing(buyer_id: int) -> Optional[dict[str, Any]]:
    """Получить данные 'Покупатель смотрит'."""
    cardinal = get_cardinal()
    acc = cardinal.account
    if not acc:
        return None

    def _fetch():
        bv = acc.get_buyer_viewing(buyer_id)
        if not bv:
            return None
        return {
            "buyer_id": getattr(bv, "buyer_id", buyer_id),
            "text": getattr(bv, "text", ""),
            "link": getattr(bv, "link", ""),
            "tag": getattr(bv, "tag", ""),
        }

    return await asyncio.to_thread(_fetch)

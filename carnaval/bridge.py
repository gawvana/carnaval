"""
carnaval/bridge.py — SSE-мост между Cardinal (sync потоки) и FastAPI (asyncio).

Особенности:
- Потокобезопасная отправка через emit().
- Кольцевой буфер последних 200 событий с монотонными ID.
- Поддержка Last-Event-ID для досылки пропущенных при разрыве связи событий.
- Keepalive ping каждые 15 секунд.
"""

from __future__ import annotations

import asyncio
import collections
import json
import logging
import time
from typing import AsyncGenerator, Optional

logger = logging.getLogger("Carnaval.Bridge")

# Глобальный event loop FastAPI
_loop: asyncio.AbstractEventLoop | None = None

# Активные подписчики SSE
_subscribers: list[asyncio.Queue] = []
_QUEUE_MAX = 64

# Кольцевой буфер истории событий для Last-Event-ID (до 200 событий)
_EVENT_HISTORY_MAX = 200
_history: collections.deque[tuple[int, str]] = collections.deque(maxlen=_EVENT_HISTORY_MAX)
_event_counter: int = 0


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Вызывается из lifespan FastAPI при старте."""
    global _loop
    _loop = loop


def get_queue_size() -> int:
    """Возвращает суммарное количество подписчиков для /api/health."""
    return len(_subscribers)


def emit(event_type: str, data: dict) -> None:
    """
    Отправить событие всем подписчикам SSE и сохранить в кольцевой буфер.
    Потокобезопасно: вызывается из любых потоков Cardinal.
    """
    global _event_counter
    _event_counter += 1
    eid = _event_counter

    payload = {"type": event_type, "ts": int(time.time()), "data": data}
    json_str = json.dumps(payload, ensure_ascii=False)
    raw_event = f"id: {eid}\nevent: {event_type}\ndata: {json_str}\n\n"

    # Сохраняем в кольцевой буфер
    _history.append((eid, raw_event))

    if _loop is None or _loop.is_closed():
        return

    def _put():
        dead = []
        for q in _subscribers:
            try:
                q.put_nowait(raw_event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            try:
                _subscribers.remove(q)
            except ValueError:
                pass

    _loop.call_soon_threadsafe(_put)


async def stream(last_event_id: Optional[int] = None) -> AsyncGenerator[str, None]:
    """
    Async generator для SSE-стрима.
    1. Если указан last_event_id — досылает пропущенные события из кольцевого буфера.
    2. Отправляет ': ping\\n\\n' при старте и каждые 15 сек при отсутствии активности.
    """
    q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX)
    _subscribers.append(q)

    # Первый ping
    yield ": ping\n\n"

    # Восстановление пропущенных событий
    if last_event_id is not None and last_event_id > 0:
        for eid, raw in list(_history):
            if eid > last_event_id:
                yield raw

    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=15)
                yield msg
            except asyncio.TimeoutError:
                yield ": ping\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        try:
            _subscribers.remove(q)
        except ValueError:
            pass


# ─────────────────────────────────────────────────────────────
# Обработчики событий Cardinal для регистрации в BIND_TO_*
# ─────────────────────────────────────────────────────────────

def bridge_new_order_handler(c, e, *args):
    """Слушатель нового заказа."""
    try:
        emit("order.new", {
            "order_id": getattr(e.order, "id", ""),
            "description": getattr(e.order, "description", ""),
            "price": getattr(e.order, "price", 0.0),
            "currency": str(getattr(e.order, "currency", "")),
            "buyer_username": getattr(e.order, "buyer_username", ""),
            "buyer_id": getattr(e.order, "buyer_id", 0),
            "chat_id": getattr(e.order, "chat_id", 0),
            "status": str(getattr(e.order, "status", "")),
        })
    except Exception as ex:
        logger.debug(f"Carnaval bridge on_new_order error: {ex}")


def bridge_order_status_changed_handler(c, e, *args):
    """Слушатель изменения статуса заказа."""
    try:
        emit("order.status", {
            "order_id": getattr(e.order, "id", ""),
            "status": str(getattr(e.order, "status", "")),
            "buyer_username": getattr(e.order, "buyer_username", ""),
        })
    except Exception as ex:
        logger.debug(f"Carnaval bridge on_order_status_changed error: {ex}")


def bridge_new_message_handler(c, e, *args):
    """Слушатель нового сообщения."""
    try:
        emit("message.new", {
            "id": getattr(e.message, "id", 0),
            "chat_id": getattr(e.message, "chat_id", 0),
            "chat_name": getattr(e.message, "chat_name", ""),
            "text": getattr(e.message, "text", ""),
            "author": getattr(e.message, "author", ""),
            "author_id": getattr(e.message, "author_id", 0),
            "image_link": getattr(e.message, "image_link", None),
        })
    except Exception as ex:
        logger.debug(f"Carnaval bridge on_new_message error: {ex}")


def bridge_post_delivery_handler(c, e, *args):
    """Слушатель выдачи товара."""
    try:
        emit("delivery.done", {
            "order_id": getattr(e.order, "id", ""),
            "delivered": getattr(e, "delivered", False),
            "delivery_text": getattr(e, "delivery_text", ""),
            "goods_left": getattr(e, "goods_left", None),
        })
    except Exception as ex:
        logger.debug(f"Carnaval bridge on_post_delivery error: {ex}")


def bridge_post_lots_raise_handler(c, cat, error_text=""):
    """Слушатель поднятия лотов."""
    try:
        emit("lots.raised", {
            "category_name": getattr(cat, "name", str(cat)),
            "error_text": error_text,
        })
    except Exception as ex:
        logger.debug(f"Carnaval bridge on_post_lots_raise error: {ex}")

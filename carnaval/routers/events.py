"""
carnaval/routers/events.py — SSE стрим GET /api/events

Клиент подключается и получает push-события от Cardinal:
  id: 12
  event: order.new
  data: {"type": "order.new", "ts": 1234567890, "data": {...}}

  : ping  ← keepalive каждые 15 секунд

Требует Authorization: Bearer <token>.
Поддерживает заголовок Last-Event-ID для восстановления потока.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse

from carnaval import bridge
from carnaval.deps import require_user

router = APIRouter()
logger = logging.getLogger("Carnaval.Events")


@router.get("/events")
async def sse_events(
    request: Request,
    user_id: int = Depends(require_user),
    last_event_id: Optional[str] = Header(None, alias="Last-Event-ID"),
    query_last_id: Optional[int] = Query(None, alias="last_event_id"),
):
    """
    Полноценный SSE-стрим для Mini App.
    Авторизация: Bearer токен через require_user.
    Поддерживает заголовок Last-Event-ID для досылки пропущенных событий.
    """
    parsed_last_id: Optional[int] = None
    if last_event_id and last_event_id.isdigit():
        parsed_last_id = int(last_event_id)
    elif query_last_id is not None:
        parsed_last_id = query_last_id

    return StreamingResponse(
        bridge.stream(last_event_id=parsed_last_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",   # отключение буферизации в nginx/reverse-proxy
            "Connection": "keep-alive",
        },
    )

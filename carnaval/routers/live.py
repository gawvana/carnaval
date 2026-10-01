"""
carnaval/routers/live.py — REST API эндпоинты Live Control Center:
- GET  /api/live/metrics
- GET  /api/live/topology
- GET  /api/live/timeline
- POST /api/live/replay-event
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from carnaval import auth
from carnaval.deps import extract_session_token
from carnaval.services import live as live_svc

router = APIRouter(prefix="/live")
logger = logging.getLogger("Carnaval.LiveRouter")


class ReplayEventRequest(BaseModel):
    event_id: Optional[str] = Field(None, description="ID события из ленты активности для повтора")
    category: Optional[str] = Field(None, description="Категория события: 'chat' или 'order'")
    payload: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Параметры события для симуляции")


def _check_optional_auth(request: Request) -> Optional[int]:
    """
    Проверяет токен авторизации, если он передан в заголовках или cookie.
    Если передан некорректный токен — выбрасывает 401.
    Если токен не передан — разрешает доступ (для мониторинга и тестов).
    """
    token = extract_session_token(request)
    if token:
        session = auth.get_session(token)
        if not session:
            raise HTTPException(
                status_code=401,
                detail={"error": "unauthorized", "message": "Сессия недействительна или истекла"},
            )
        request.state.session = session
        return int(session.get("telegram_user_id", 0))
    return None


@router.get("/metrics")
async def get_metrics(request: Request) -> JSONResponse:
    """
    GET /api/live/metrics
    Возвращает авторитетную телеметрию FunPay, Runner, системных ресурсов и операций.
    """
    _check_optional_auth(request)
    try:
        telemetry = live_svc.get_live_telemetry()
        return JSONResponse(telemetry)
    except Exception as e:
        logger.error(f"LiveCenter: ошибка сбора телеметрии: {e}", exc_info=True)
        return JSONResponse(
            {
                "ok": False,
                "error": "telemetry_error",
                "message": str(e),
            },
            status_code=500,
        )


@router.get("/topology")
async def get_topology(request: Request) -> JSONResponse:
    """
    GET /api/live/topology
    Возвращает граф топологии компонентов (DAG) с их актуальным состоянием,
    причинами статусов и кнопками восстановления.
    """
    _check_optional_auth(request)
    try:
        topo = live_svc.get_live_topology()
        return JSONResponse(topo)
    except Exception as e:
        logger.error(f"LiveCenter: ошибка построения топологии: {e}", exc_info=True)
        return JSONResponse(
            {
                "ok": False,
                "error": "topology_error",
                "message": str(e),
            },
            status_code=500,
        )


@router.get("/timeline")
async def get_timeline(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    category: Optional[str] = Query(None),
) -> JSONResponse:
    """
    GET /api/live/timeline
    Возвращает список последних событий из кольцевого буфера активности.
    """
    _check_optional_auth(request)
    try:
        events = live_svc.timeline.get_events(limit=limit, category=category)
        return JSONResponse({
            "ok": True,
            "events": events,
            "total": len(events),
            "limit": limit,
            "category": category,
        })
    except Exception as e:
        logger.error(f"LiveCenter: ошибка чтения ленты активности: {e}", exc_info=True)
        return JSONResponse(
            {
                "ok": False,
                "error": "timeline_error",
                "message": str(e),
            },
            status_code=500,
        )


@router.post("/replay-event")
async def replay_event_endpoint(
    req: ReplayEventRequest,
    request: Request,
) -> JSONResponse:
    """
    POST /api/live/replay-event
    Запускает безопасную симуляцию (Dry Run) прохождения события через правила
    автоответа или автовыдачи без реальных побочных эффектов.
    """
    _check_optional_auth(request)
    try:
        result = live_svc.replay_event(
            event_id=req.event_id,
            category=req.category,
            payload=req.payload,
        )
        return JSONResponse(result)
    except ValueError as ve:
        return JSONResponse(
            {
                "ok": False,
                "error": "invalid_event",
                "message": str(ve),
            },
            status_code=400,
        )
    except Exception as e:
        logger.error(f"LiveCenter: ошибка выполнения replay-event: {e}", exc_info=True)
        return JSONResponse(
            {
                "ok": False,
                "error": "replay_error",
                "message": str(e),
            },
            status_code=500,
        )

"""
carnaval/routers/search.py — API для единого глобального поиска Carnaval.
"""

from __future__ import annotations

import logging
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from carnaval.deps import require_user
from carnaval.services import search as search_svc

router = APIRouter()
logger = logging.getLogger("Carnaval.SearchRouter")


@router.get("/search")
async def search_endpoint(
    request: Request,
    user_id: int = Depends(require_user),
    q: Optional[str] = Query(None, description="Строка поискового запроса"),
    query: Optional[str] = Query(None, description="Строка поискового запроса (алиас)"),
    limit_per_category: int = Query(5, ge=1, le=50, description="Максимум результатов на категорию"),
) -> JSONResponse:
    """
    Сквозной глобальный поиск по 8 доменам Carnaval (требует авторизации).
    """
    search_q = q if q is not None else (query or "")
    results = search_svc.global_search(search_q, limit_per_category=limit_per_category)
    return JSONResponse(results)

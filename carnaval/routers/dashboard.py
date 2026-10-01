"""
carnaval/routers/dashboard.py — GET /api/dashboard (основная информация).

Возвращает всё нужное для дашборда одним запросом:
- данные аккаунта FunPay
- баланс (из кэша, обновляется не чаще 1 раза в 60 сек)
- глобальные переключатели
- аптайм бота
"""

from __future__ import annotations

import time
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from carnaval.deps import get_cardinal, require_user

router = APIRouter()
logger = logging.getLogger("Carnaval.Dashboard")

# Простой in-process кэш баланса (избегаем HTTP к FunPay на каждый запрос)
_balance_cache: dict | None = None
_balance_ts: float = 0
_BALANCE_TTL = 60  # секунд


def reset_balance_cache() -> None:
    """Сброс кэша баланса (для тестов и принудительного обновления)."""
    global _balance_cache, _balance_ts
    _balance_cache = None
    _balance_ts = 0


@router.get("/dashboard")
async def dashboard(request: Request, user_id: int = Depends(require_user)) -> JSONResponse:


    cardinal = get_cardinal()
    account = cardinal.account

    # --- Баланс с кэшем ---
    global _balance_cache, _balance_ts
    balance_data = None
    if _balance_cache and time.time() - _balance_ts < _BALANCE_TTL:
        balance_data = _balance_cache
    else:
        if cardinal.balance:
            b = cardinal.balance
            balance_data = {
                "total_rub": b.total_rub,
                "available_rub": b.available_rub,
                "total_usd": b.total_usd,
                "available_usd": b.available_usd,
                "total_eur": b.total_eur,
                "available_eur": b.available_eur,
            }
            _balance_cache = balance_data
            _balance_ts = time.time()

    # --- Аптайм ---
    uptime_sec = int(time.time()) - cardinal.start_time if getattr(cardinal, "start_time", None) and isinstance(cardinal.start_time, (int, float)) else 0

    # --- Безопасные времена поднятия ---
    r_time = getattr(cardinal, "raise_time", None)
    if isinstance(r_time, dict) and r_time:
        now = time.time()
        future_times = [v for v in r_time.values() if isinstance(v, (int, float)) and v > now]
        safe_raise_time = int(min(future_times)) if future_times else None
    elif isinstance(r_time, (int, float)):
        safe_raise_time = int(r_time)
    else:
        safe_raise_time = None

    rs_time = getattr(cardinal, "raised_time", None)
    if isinstance(rs_time, dict) and rs_time:
        now = time.time()
        past_times = [v for v in rs_time.values() if isinstance(v, (int, float)) and v <= now]
        safe_raised_time = int(max(past_times)) if past_times else None
    elif isinstance(rs_time, (int, float)):
        safe_raised_time = int(rs_time)
    else:
        safe_raised_time = None

    # --- Переключатели (FunPay секция) ---
    fp = cardinal.MAIN_CFG["FunPay"]
    toggles = {
        "autoRaise": fp.getboolean("autoRaise"),
        "autoResponse": fp.getboolean("autoResponse"),
        "autoDelivery": fp.getboolean("autoDelivery"),
        "multiDelivery": fp.getboolean("multiDelivery"),
        "autoRestore": fp.getboolean("autoRestore"),
        "autoDisable": fp.getboolean("autoDisable"),
        "oldMsgGetMode": fp.getboolean("oldMsgGetMode"),
        "keepSentMessagesUnread": fp.getboolean("keepSentMessagesUnread"),
    }

    return JSONResponse({
        "account": {
            "id": getattr(account, "id", None) if isinstance(getattr(account, "id", None), (int, str)) else None,
            "username": getattr(account, "username", None) if isinstance(getattr(account, "username", None), str) else None,
            "active_sales": getattr(account, "active_sales", None) if isinstance(getattr(account, "active_sales", None), int) else None,
            "active_purchases": getattr(account, "active_purchases", None) if isinstance(getattr(account, "active_purchases", None), int) else None,
        },
        "balance": balance_data,
        "toggles": toggles,
        "uptime_sec": uptime_sec,
        "raise_time": safe_raise_time,
        "raised_time": safe_raised_time,
        "version": getattr(cardinal, "VERSION", "0.1.17.15"),
        "running": bool(getattr(cardinal, "running", False)),
    })

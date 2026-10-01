"""
carnaval/services/orders.py — сервис работы с заказами FunPay.
Вызовы к блокирующему FunPayAPI выполняются безопасно.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from carnaval.deps import get_cardinal
from FunPayAPI.common.enums import OrderStatuses


def _order_to_dict(o: Any) -> dict[str, Any]:
    """Преобразование объекта OrderShortcut в JSON-сериализуемый словарь."""
    return {
        "id": getattr(o, "id", ""),
        "description": getattr(o, "description", ""),
        "price": getattr(o, "price", 0.0),
        "currency": str(getattr(o, "currency", "")),
        "buyer_username": getattr(o, "buyer_username", ""),
        "buyer_id": getattr(o, "buyer_id", 0),
        "chat_id": getattr(o, "chat_id", 0),
        "status": getattr(o.status, "name", str(getattr(o, "status", ""))),
        "date": getattr(o.date, "isoformat", lambda: str(getattr(o, "date", "")))() if getattr(o, "date", None) else None,
        "subcategory_name": getattr(o, "subcategory_name", ""),
        "amount": getattr(o, "amount", 1),
    }


def _order_detail_to_dict(o: Any) -> dict[str, Any]:
    """Преобразование детального объекта Order в JSON-сериализуемый словарь."""
    review_obj = getattr(o, "review", None)
    review_data = None
    if review_obj:
        review_data = {
            "stars": getattr(review_obj, "stars", None),
            "text": getattr(review_obj, "text", None),
            "reply": getattr(review_obj, "reply", None),
            "anonymous": getattr(review_obj, "anonymous", False),
        }

    fields_dict = {}
    raw_fields = getattr(o, "fields", {}) or {}
    for k, f in raw_fields.items():
        fields_dict[k] = {
            "name": getattr(f, "name", k),
            "value": getattr(f, "value", str(f)),
        }

    return {
        "id": getattr(o, "id", ""),
        "status": getattr(o.status, "name", str(getattr(o, "status", ""))),
        "subcategory": getattr(o.subcategory, "name", None) if getattr(o, "subcategory", None) else None,
        "sum": getattr(o, "sum", getattr(o, "price", 0.0)),
        "currency": str(getattr(o, "currency", "")),
        "amount": getattr(o, "amount", 1),
        "buyer_id": getattr(o, "buyer_id", 0),
        "buyer_username": getattr(o, "buyer_username", ""),
        "chat_id": getattr(o, "chat_id", 0),
        "fields": fields_dict,
        "review": review_data,
        "order_secrets": getattr(o, "order_secrets", []) or [],
    }


async def get_orders(status: Optional[str] = None, start_from: Optional[str] = None, limit: int = 25) -> dict[str, Any]:
    """
    Получить список заказов продавца.
    status: 'paid', 'closed', 'refunded' или None (все)
    """
    cardinal = get_cardinal()
    acc = cardinal.account
    if not acc or not getattr(acc, "is_initiated", False):
        from carnaval.services.account_lifecycle import lifecycle_manager
        curr_status = lifecycle_manager.get_status()
        if curr_status.get("has_key"):
            try:
                await lifecycle_manager.reconnect_account()
            except Exception:
                pass
        if not acc or not getattr(acc, "is_initiated", False):
            return {"orders": [], "next_order_id": None, "funpay_connected": False}

    include_paid = True
    include_closed = True
    include_refunded = True

    if status == "paid":
        include_closed = False
        include_refunded = False
    elif status == "closed":
        include_paid = False
        include_refunded = False
    elif status == "refunded":
        include_paid = False
        include_closed = False

    def _fetch():
        next_id, orders_list, locale, _ = acc.get_sales(
            start_from=start_from,
            include_paid=include_paid,
            include_closed=include_closed,
            include_refunded=include_refunded,
        )
        return next_id, orders_list[:limit]

    try:
        next_order_id, orders = await asyncio.to_thread(_fetch)
        return {
            "orders": [_order_to_dict(o) for o in orders],
            "next_order_id": next_order_id,
            "funpay_connected": True,
        }
    except Exception as e:
        return {"orders": [], "next_order_id": None, "funpay_connected": False, "error": str(e)}


async def get_order(order_id: str) -> Optional[dict[str, Any]]:
    """Получить детальную информацию о заказе."""
    cardinal = get_cardinal()
    acc = cardinal.account
    if not acc or not getattr(acc, "is_initiated", False):
        return None

    def _fetch():
        return acc.get_order(order_id)

    try:
        order = await asyncio.to_thread(_fetch)
        if not order:
            return None
        return _order_detail_to_dict(order)
    except Exception:
        return None


async def refund_order(order_id: str, confirm: bool = False) -> tuple[bool, str]:
    """
    Оформить возврат средств покупателю за заказ.
    Требует confirm=True в соответствии со спецификацией опасных действий.
    """
    if not confirm:
        return False, "Refund requires confirm=true"

    cardinal = get_cardinal()
    acc = cardinal.account
    if not acc or not getattr(acc, "is_initiated", False):
        return False, "FunPay account not connected"

    def _exec():
        acc.refund(order_id)

    try:
        await asyncio.to_thread(_exec)
        return True, ""
    except Exception as e:
        return False, str(e)


async def send_review_reply(order_id: str, text: str, rating: int = 5) -> tuple[bool, str]:
    """Отправить ответ на отзыв к заказу."""
    cardinal = get_cardinal()
    acc = cardinal.account
    if not acc or not getattr(acc, "id", None):
        return False, "FunPay account not connected"

    def _exec():
        return acc.send_review(order_id, text, rating)

    try:
        res = await asyncio.to_thread(_exec)
        return True, res or "ok"
    except Exception as e:
        return False, str(e)


async def delete_review_reply(order_id: str) -> tuple[bool, str]:
    """Удалить ответ на отзыв к заказу."""
    cardinal = get_cardinal()
    acc = cardinal.account
    if not acc or not getattr(acc, "id", None):
        return False, "FunPay account not connected"

    def _exec():
        return acc.delete_review(order_id)

    try:
        res = await asyncio.to_thread(_exec)
        return True, res or "deleted"
    except Exception as e:
        return False, str(e)

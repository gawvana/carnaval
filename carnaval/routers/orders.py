"""
carnaval/routers/orders.py — API работы с заказами FunPay.
"""

from __future__ import annotations

import logging
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from carnaval.deps import require_user
from carnaval.services import orders as orders_svc

router = APIRouter()
logger = logging.getLogger("Carnaval.Orders")


class RefundRequest(BaseModel):
    confirm: bool = False


class ReviewReplyRequest(BaseModel):
    text: str
    rating: int = 5


@router.get("/orders")
async def list_orders(
    request: Request,
    user_id: int = Depends(require_user),
    status: Optional[str] = None,
    offset: Optional[str] = None,
    limit: int = 25,
) -> JSONResponse:
    """Получить список заказов."""
    try:
        data = await orders_svc.get_orders(status=status, start_from=offset, limit=limit)
        return JSONResponse(data)
    except Exception as e:
        logger.warning(f"Failed to fetch orders: {e}")
        return JSONResponse({"orders": [], "next_order_id": None, "funpay_connected": False, "error": "orders_fetch_failed", "message": str(e)}, status_code=200)


@router.get("/orders/{order_id}")
async def get_order_details(
    order_id: str,
    request: Request,
    user_id: int = Depends(require_user),
) -> JSONResponse:
    """Получить детальную информацию о заказе."""
    try:
        order = await orders_svc.get_order(order_id)
        if not order:
            return JSONResponse({"error": "not_found", "message": "Order not found"}, status_code=404)
        return JSONResponse(order)
    except Exception as e:
        logger.warning(f"Failed to fetch order {order_id}: {e}")
        return JSONResponse({"error": "order_fetch_failed", "message": str(e)}, status_code=400)


@router.post("/orders/{order_id}/refund")
async def refund_order_route(
    order_id: str,
    req: RefundRequest,
    request: Request,
    user_id: int = Depends(require_user),
) -> JSONResponse:
    """Оформить возврат средств (требует confirm: true)."""
    if not req.confirm:
        return JSONResponse({"error": "confirm_required", "message": "Refund requires confirm=true"}, status_code=400)

    ok, err = await orders_svc.refund_order(order_id, confirm=True)
    if not ok:
        return JSONResponse({"error": "refund_failed", "message": err}, status_code=400)

    logger.warning(f"AUDIT: user_id={user_id} оформил возврат по заказу #{order_id}")
    return JSONResponse({"success": True, "order_id": order_id})


@router.post("/orders/{order_id}/review-reply")
async def reply_review_route(
    order_id: str,
    req: ReviewReplyRequest,
    request: Request,
    user_id: int = Depends(require_user),
) -> JSONResponse:
    """Отправить ответ на отзыв."""
    ok, msg = await orders_svc.send_review_reply(order_id, req.text, req.rating)
    if not ok:
        return JSONResponse({"error": "review_reply_failed", "message": msg}, status_code=400)

    logger.info(f"AUDIT: user_id={user_id} ответил на отзыв к заказу #{order_id}")
    return JSONResponse({"success": True, "order_id": order_id})


@router.delete("/orders/{order_id}/review-reply")
async def delete_review_route(
    order_id: str,
    request: Request,
    user_id: int = Depends(require_user),
) -> JSONResponse:
    """Удалить ответ на отзыв."""
    ok, msg = await orders_svc.delete_review_reply(order_id)
    if not ok:
        return JSONResponse({"error": "review_delete_failed", "message": msg}, status_code=400)

    logger.info(f"AUDIT: user_id={user_id} удалил ответ на отзыв к заказу #{order_id}")
    return JSONResponse({"success": True, "order_id": order_id})

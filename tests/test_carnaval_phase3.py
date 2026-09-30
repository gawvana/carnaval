"""
Тесты для Этапа 3 Carnaval:
- Заказы (список, детализация, возврат с confirm: true, ответы на отзывы)
- Чаты (список диалогов, история сообщений, отправка сообщений, просмотр лота)
- SSE-мост (bridge_new_order_handler, bridge_new_message_handler и т.д.)
"""

import time
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from carnaval.server import build_app
from carnaval.deps import set_cardinal
from carnaval import auth
from carnaval import bridge


@pytest.fixture
def mock_cardinal_p3():
    import configparser
    c = MagicMock()
    c.VERSION = "0.1.17.15"
    c.running = True

    cfg = configparser.ConfigParser(delimiters=(":",), interpolation=None)
    cfg.optionxform = str
    cfg.add_section("FunPay")
    cfg.set("FunPay", "golden_key", "abcdef1234567890abcdef1234567890")
    cfg.set("FunPay", "autoRaise", "1")
    cfg.set("FunPay", "autoResponse", "1")
    cfg.set("FunPay", "autoDelivery", "1")
    cfg.set("FunPay", "multiDelivery", "0")
    cfg.set("FunPay", "autoRestore", "1")
    cfg.set("FunPay", "autoDisable", "0")
    cfg.set("FunPay", "oldMsgGetMode", "0")
    cfg.set("FunPay", "keepSentMessagesUnread", "0")
    cfg.set("FunPay", "locale", "ru")

    cfg.add_section("Telegram")
    cfg.set("Telegram", "enabled", "1")
    cfg.set("Telegram", "token", "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
    cfg.set("Telegram", "secretKeyHash", "$2b$12$SomeHashedSecretKeyString")
    cfg.set("Telegram", "proxy", "")
    cfg.set("Telegram", "blockLogin", "0")

    cfg.add_section("Carnaval")
    cfg.set("Carnaval", "enabled", "1")
    cfg.set("Carnaval", "host", "127.0.0.1")
    cfg.set("Carnaval", "port", "8765")
    cfg.set("Carnaval", "secretKey", "test_secret_p3")

    c.MAIN_CFG = cfg

    # Мок аккаунта FunPay
    acc = MagicMock()
    acc.id = 778899
    acc.username = "FastSeller"

    # Мок заказа
    mock_order_sc = MagicMock()
    mock_order_sc.id = "ORD12345"
    mock_order_sc.description = "1000 Золота WOW"
    mock_order_sc.price = 500.0
    mock_order_sc.currency = "RUB"
    mock_order_sc.buyer_username = "PlayerOne"
    mock_order_sc.buyer_id = 998877
    mock_order_sc.chat_id = 123456
    mock_order_sc.status = "PAID"
    mock_order_sc.date = MagicMock()
    mock_order_sc.date.isoformat = MagicMock(return_value="2026-09-29T12:00:00")
    mock_order_sc.subcategory_name = "World of Warcraft"
    mock_order_sc.amount = 1

    acc.get_sales.return_value = ("NEXT_ID_999", [mock_order_sc], "ru", {})

    mock_detail = MagicMock()
    mock_detail.id = "ORD12345"
    mock_detail.status = "PAID"
    mock_detail.sum = 500.0
    mock_detail.price = 500.0
    mock_detail.currency = "RUB"
    mock_detail.amount = 1
    mock_detail.buyer_id = 998877
    mock_detail.buyer_username = "PlayerOne"
    mock_detail.chat_id = 123456
    mock_detail.fields = {}
    mock_detail.review = None
    mock_detail.order_secrets = ["login:password123"]
    mock_detail.subcategory = MagicMock()
    mock_detail.subcategory.name = "WOW Золото"

    acc.get_order.return_value = mock_detail
    acc.refund.return_value = None
    acc.send_review.return_value = "<div>Отзыв отправлен</div>"
    acc.delete_review.return_value = "<div>Отзыв удален</div>"

    # Мок чатов
    mock_chat = MagicMock()
    mock_chat.id = 123456
    mock_chat.name = "PlayerOne"
    mock_chat.last_message_text = "Привет, товар получен!"
    mock_chat.unread = True
    mock_chat.node_msg_id = 555
    mock_chat.user_msg_id = 554
    mock_chat.last_by_bot = False

    acc.get_chats.return_value = {123456: mock_chat}

    mock_msg = MagicMock()
    mock_msg.id = 999
    mock_msg.text = "Привет, товар получен!"
    mock_msg.chat_id = 123456
    mock_msg.chat_name = "PlayerOne"
    mock_msg.author = "PlayerOne"
    mock_msg.author_id = 998877
    mock_msg.image_link = None
    mock_msg.image_name = None
    mock_msg.badge_text = None

    acc.get_chat_history.return_value = [mock_msg]

    mock_bv = MagicMock()
    mock_bv.buyer_id = 998877
    mock_bv.text = "Золото 1000 шт."
    mock_bv.link = "https://funpay.com/lots/123/"
    mock_bv.tag = "lot"
    acc.get_buyer_viewing.return_value = mock_bv

    c.account = acc
    c.send_message.return_value = [mock_msg]
    c.telegram = MagicMock()
    c.telegram.authorized_users = {555666777: {}}

    from carnaval.routers.dashboard import reset_balance_cache
    reset_balance_cache()

    set_cardinal(c)
    auth.init("test_secret_p3")
    return c


def test_orders_api_flow(mock_cardinal_p3):
    app = build_app()
    client = TestClient(app)
    token = auth.create_token(555666777)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Список заказов
    res = client.get("/api/orders", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data["orders"]) == 1
    assert data["orders"][0]["id"] == "ORD12345"
    assert data["next_order_id"] == "NEXT_ID_999"

    # 2. Детали заказа
    detail_res = client.get("/api/orders/ORD12345", headers=headers)
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["id"] == "ORD12345"
    assert detail["order_secrets"] == ["login:password123"]

    # 3. Возврат без confirm=true -> отказ 400
    ref_fail = client.post("/api/orders/ORD12345/refund", json={"confirm": False}, headers=headers)
    assert ref_fail.status_code == 400
    assert "confirm_required" in ref_fail.json()["error"]

    # 4. Возврат с confirm=true -> успех 200
    ref_ok = client.post("/api/orders/ORD12345/refund", json={"confirm": True}, headers=headers)
    assert ref_ok.status_code == 200
    assert ref_ok.json()["success"] is True

    # 5. Ответ на отзыв
    rev_ok = client.post("/api/orders/ORD12345/review-reply", json={"text": "Спасибо за покупку!", "rating": 5}, headers=headers)
    assert rev_ok.status_code == 200
    assert rev_ok.json()["success"] is True

    # 6. Удаление ответа на отзыв
    del_ok = client.delete("/api/orders/ORD12345/review-reply", headers=headers)
    assert del_ok.status_code == 200
    assert del_ok.json()["success"] is True


def test_chats_api_flow(mock_cardinal_p3):
    app = build_app()
    client = TestClient(app)
    token = auth.create_token(555666777)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Список диалогов
    chats_res = client.get("/api/chats", headers=headers)
    assert chats_res.status_code == 200
    chats = chats_res.json()["chats"]
    assert len(chats) == 1
    assert chats[0]["name"] == "PlayerOne"
    assert chats[0]["unread"] is True

    # 2. История сообщений в диалоге
    hist_res = client.get("/api/chats/123456/history", headers=headers)
    assert hist_res.status_code == 200
    msgs = hist_res.json()["messages"]
    assert len(msgs) == 1
    assert msgs[0]["text"] == "Привет, товар получен!"

    # 3. Отправка пустого сообщения -> отказ 400
    empty_send = client.post("/api/chats/123456/messages", json={"text": "   "}, headers=headers)
    assert empty_send.status_code == 400

    # 4. Отправка валидного сообщения -> 200
    send_res = client.post("/api/chats/123456/messages", json={"text": "Обращайтесь еще!"}, headers=headers)
    assert send_res.status_code == 200
    assert send_res.json()["success"] is True

    # 5. Покупатель смотрит
    view_res = client.get("/api/chats/123456/viewing?buyer_id=998877", headers=headers)
    assert view_res.status_code == 200
    assert "Золото" in view_res.json()["viewing"]["text"]


def test_sse_bridge_handlers(mock_cardinal_p3):
    mock_order = MagicMock()
    mock_order.id = "ORD999"
    mock_order.description = "Test item"
    mock_order.price = 100.0
    mock_order.currency = "RUB"
    mock_order.buyer_username = "TestBuyer"
    mock_order.buyer_id = 123
    mock_order.chat_id = 456
    mock_order.status = "PAID"

    event_order = MagicMock()
    event_order.order = mock_order

    # Проверка, что хэндлеры моста не бросают исключений
    bridge.bridge_new_order_handler(mock_cardinal_p3, event_order)
    bridge.bridge_order_status_changed_handler(mock_cardinal_p3, event_order)

    mock_msg = MagicMock()
    mock_msg.id = 1
    mock_msg.chat_id = 456
    mock_msg.chat_name = "TestBuyer"
    mock_msg.text = "Hello!"
    mock_msg.author = "TestBuyer"
    mock_msg.author_id = 123
    mock_msg.image_link = None

    event_msg = MagicMock()
    event_msg.message = mock_msg
    bridge.bridge_new_message_handler(mock_cardinal_p3, event_msg)
    bridge.bridge_post_delivery_handler(mock_cardinal_p3, event_order)
    bridge.bridge_post_lots_raise_handler(mock_cardinal_p3, MagicMock(name="Cat"))


def test_orders_and_chats_frontend_assets(mock_cardinal_p3):
    app = build_app()
    client = TestClient(app)

    # Проверка раздачи скриптов экранов
    r1 = client.get("/js/pages/orders.js")
    assert r1.status_code == 200
    assert "renderOrders" in r1.text

    r2 = client.get("/js/pages/chats.js")
    assert r2.status_code == 200
    assert "renderChats" in r2.text

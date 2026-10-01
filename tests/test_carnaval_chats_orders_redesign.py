"""
tests/test_carnaval_chats_orders_redesign.py
Тесты для доработок по чатам, заказам, удалению FAB и мобильному чату.
"""

from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from carnaval.server import build_app
from carnaval.deps import set_cardinal
from carnaval import auth
from carnaval.services import chats as chats_svc
from carnaval.services import orders as orders_svc


@pytest.fixture
def mock_cardinal():
    c = MagicMock()
    c.VERSION = "0.1.17.15"
    c.running = True
    c.MAIN_CFG = MagicMock()

    acc = MagicMock()
    acc.id = 112233
    acc.username = "TestUser"
    acc.is_initiated = True

    c.account = acc
    c.telegram = MagicMock()
    c.telegram.authorized_users = {123456789: {}}

    set_cardinal(c)
    auth.init("test_secret_redesign")
    return c


def test_chats_success_zero_chats(mock_cardinal):
    """При успешном ответе без чатов возвращается ok: True и пустой список."""
    mock_cardinal.account.get_chats.return_value = {}

    app = build_app()
    client = TestClient(app)
    token = auth.create_token(123456789)
    headers = {"Authorization": f"Bearer {token}"}

    res = client.get("/api/chats", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["chats"] == []
    assert data["funpay_connected"] is True


def test_chats_account_not_initialized(mock_cardinal):
    """Если аккаунт не инициализирован, возвращается структурированная ошибка."""
    mock_cardinal.account.is_initiated = False

    app = build_app()
    client = TestClient(app)
    token = auth.create_token(123456789)
    headers = {"Authorization": f"Bearer {token}"}

    res = client.get("/api/chats", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False
    assert data["error_code"] == "FUNPAY_ACCOUNT_NOT_INITIALIZED"
    assert data["funpay_connected"] is False


def test_chats_network_error(mock_cardinal):
    """При ошибке сети get_chats не проглатывает исключение, а возвращает NETWORK_ERROR."""
    mock_cardinal.account.get_chats.side_effect = ConnectionResetError("FunPay connection lost")

    app = build_app()
    client = TestClient(app)
    token = auth.create_token(123456789)
    headers = {"Authorization": f"Bearer {token}"}

    res = client.get("/api/chats", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False
    assert data["error_code"] == "NETWORK_ERROR"
    assert "FunPay connection lost" in data["message"]


def test_chat_history_error_handling(mock_cardinal):
    """При ошибке истории сообщений не возвращается молча пустой список."""
    mock_cardinal.account.get_chat_history.side_effect = RuntimeError("Failed to parse history")

    app = build_app()
    client = TestClient(app)
    token = auth.create_token(123456789)
    headers = {"Authorization": f"Bearer {token}"}

    res = client.get("/api/chats/999/history", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False
    assert data["error_code"] == "NETWORK_ERROR"
    assert data["messages"] == []


def test_orders_success_zero_orders(mock_cardinal):
    """При успешном ответе без заказов возвращается ok: True и orders: []."""
    mock_cardinal.account.get_sales.return_value = (None, [], "ru", {})

    app = build_app()
    client = TestClient(app)
    token = auth.create_token(123456789)
    headers = {"Authorization": f"Bearer {token}"}

    res = client.get("/api/orders", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["orders"] == []
    assert data["funpay_connected"] is True


def test_orders_account_not_initialized(mock_cardinal):
    """Если аккаунт не инициализирован, заказы возвращают FUNPAY_ACCOUNT_NOT_INITIALIZED."""
    mock_cardinal.account.is_initiated = False

    app = build_app()
    client = TestClient(app)
    token = auth.create_token(123456789)
    headers = {"Authorization": f"Bearer {token}"}

    res = client.get("/api/orders", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False
    assert data["error_code"] == "FUNPAY_ACCOUNT_NOT_INITIALIZED"
    assert data["funpay_connected"] is False


def test_orders_network_error(mock_cardinal):
    """При ошибке сети заказы возвращают NETWORK_ERROR."""
    mock_cardinal.account.get_sales.side_effect = TimeoutError("FunPay timed out")

    app = build_app()
    client = TestClient(app)
    token = auth.create_token(123456789)
    headers = {"Authorization": f"Bearer {token}"}

    res = client.get("/api/orders", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False
    assert data["error_code"] == "NETWORK_ERROR"
    assert data["orders"] == []


def test_fab_removed_from_dock_js():
    """Проверка, что FAB полностью удален из dock.js."""
    with open("carnaval/web/js/ui/dock.js", "r", encoding="utf-8") as f:
        content = f.read()

    assert "fab" not in content.lower() or "fab" not in content
    assert "createElement('button')" not in content or "class=\"fab\"" not in content
    assert "openCreateSheet" not in content
    assert "action-create-lot" not in content


def test_fab_disabled_in_css():
    """Проверка, что в app.css и components.css .fab отключен."""
    with open("carnaval/web/css/app.css", "r", encoding="utf-8") as f:
        app_css = f.read()
    assert ".fab" in app_css
    assert "display: none !important" in app_css

    with open("carnaval/web/css/components.css", "r", encoding="utf-8") as f:
        comp_css = f.read()
    assert ".fab" in comp_css
    assert "display: none !important" in comp_css


def test_mobile_chat_styles_and_dock_hiding():
    """Проверка CSS-классов мобильного чата и скрытия дока."""
    with open("carnaval/web/css/app.css", "r", encoding="utf-8") as f:
        css = f.read()

    assert "body.in-chat-thread .chrome" in css
    assert "transform: translate(-50%, 150%)" in css
    assert ".mobile-chat-thread" in css
    assert ".mobile-chat-header" in css
    assert ".mobile-chat-messages" in css
    assert ".mobile-chat-composer" in css
    assert "safe-area-inset-bottom" in css

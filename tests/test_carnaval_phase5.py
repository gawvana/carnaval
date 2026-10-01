"""
tests/test_carnaval_phase5.py — тесты для вкладки «Ещё».

Покрывает:
1. Сервисы чёрного списка (add / remove)
2. Сервисы уведомлений (get / update)
3. REST-эндпоинты /api/more/* (GET/POST blacklist, GET notifications, GET logs,
   GET plugins, toggle, system restart/shutdown без confirm)
"""

from __future__ import annotations

import os
import sys
import types
import threading
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Minimal stub setup (без реального Cardinal)
# ---------------------------------------------------------------------------

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_stub_cardinal(tmp_path, blacklist=None):
    """Создаёт минимальный заглушечный Cardinal для тестов."""
    import configparser

    cfg = configparser.ConfigParser()
    cfg.read_string("""
[FunPay]
golden_key = testkey1234abcdefghij
user_agent =
autoRaise = 0
autoResponse = 0
autoDelivery = 0
multiDelivery = 0
autoRestore = 0
autoDisable = 0
oldMsgGetMode = 0
keepSentMessagesUnread = 0
locale = ru

[Telegram]
enabled = 0
token =
secretKeyHash =
proxy =
blockLogin = 0

[BlockList]
blockDelivery = 0
blockResponse = 0
blockNewMessageNotification = 1
blockNewOrderNotification = 0
blockCommandNotification = 0

[NewMessageView]
includeMyMessages = 1
includeFPMessages = 0
includeBotMessages = 0
notifyOnlyMyMessages = 0
notifyOnlyFPMessages = 0
notifyOnlyBotMessages = 0
showImageName = 0

[Greetings]
ignoreSystemMessages = 0
onlyNewChats = 0
sendGreetings = 0
greetingsText = Привет!
greetingsCooldown = 86400

[OrderConfirm]
watermark = 0
sendReply = 0
replyText = Спасибо за заказ!

[ReviewReply]
star1Reply = 0
star1ReplyText =
star2Reply = 0
star2ReplyText =
star3Reply = 0
star3ReplyText =
star4Reply = 0
star4ReplyText =
star5Reply = 0
star5ReplyText =

[Proxy]
enable = 0
proxy =
check = 0

[Other]
watermark =
requestsDelay = 2
language = ru

[Carnaval]
enabled = 1
host = 127.0.0.1
port = 8765
secretKey =
""")

    class StubAccount:
        username = "testuser"
        id = 123456
        golden_key = "testkey1234abcdefghij"
        proxy = {}

    _bl = list(blacklist or [])

    class StubCardinal:
        MAIN_CFG = cfg
        plugins: dict[str, Any] = {}
        proxy_dict: dict[int, str] = {}
        telegram = None
        account = StubAccount()

        def __init__(self):
            self.blacklist = list(_bl)

        @staticmethod
        def save_config(config, path):
            pass

    return StubCardinal()


# ---------------------------------------------------------------------------
# Фикстура: подменяем deps.get_cardinal
# ---------------------------------------------------------------------------

@pytest.fixture
def stub_cardinal(tmp_path, monkeypatch):
    cardinal = _make_stub_cardinal(tmp_path)

    # Патчим get_cardinal в модуле carnaval.services.more
    from carnaval import deps
    monkeypatch.setattr(deps, "_cardinal", cardinal, raising=False)

    import carnaval.services.more as svc_more
    monkeypatch.setattr(svc_more, "get_cardinal", lambda: cardinal)

    return cardinal


# ---------------------------------------------------------------------------
# Тест 1: Сервис чёрного списка
# ---------------------------------------------------------------------------

def test_blacklist_service(stub_cardinal, monkeypatch):
    """Добавление и удаление из ЧС работает корректно."""
    import carnaval.services.more as svc

    # Патчим cache_blacklist — не пишем на диск
    monkeypatch.setattr(svc, "cache_blacklist", lambda bl: None)

    assert svc.get_blacklist() == []

    ok, err = svc.add_to_blacklist("@baduser")
    assert ok, err
    assert "baduser" in svc.get_blacklist()

    # Дубль → ошибка
    ok2, _ = svc.add_to_blacklist("baduser")
    assert not ok2

    ok3, err3 = svc.remove_from_blacklist("baduser")
    assert ok3, err3
    assert "baduser" not in svc.get_blacklist()

    # Удаление несуществующего
    ok4, _ = svc.remove_from_blacklist("ghost")
    assert not ok4


# ---------------------------------------------------------------------------
# Тест 2: Сервис уведомлений
# ---------------------------------------------------------------------------

def test_notifications_service(stub_cardinal):
    """get_notifications возвращает все ожидаемые ключи с правильными типами."""
    import carnaval.services.more as svc

    data = svc.get_notifications()
    assert isinstance(data, dict)
    assert len(data) > 0

    # Проверяем известный ключ
    assert "BlockList.blockNewMessageNotification" in data
    entry = data["BlockList.blockNewMessageNotification"]
    assert "label" in entry
    assert "enabled" in entry
    assert isinstance(entry["enabled"], bool)
    # Из конфига blockNewMessageNotification = 1
    assert entry["enabled"] is True

    # Обновление
    ok, err = svc.update_notification("BlockList", "blockDelivery", True)
    assert ok, err


# ---------------------------------------------------------------------------
# Тест 3: REST-эндпоинты /api/more/*
# ---------------------------------------------------------------------------

@pytest.fixture
def client(stub_cardinal, monkeypatch):
    """TestClient для FastAPI с подменённым кардиналом."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from carnaval.routers.more import router as more_router
    from carnaval import auth as auth_mod

    # Патчим get_session — всегда авторизован
    monkeypatch.setattr(auth_mod, "get_session", lambda tok: {
        "telegram_user_id": 12345,
        "role": "user",
        "panel_unlocked": 1,
        "session_id_hash": "mock",
    })

    # Патчим cache_blacklist в сервисе
    import carnaval.services.more as svc
    monkeypatch.setattr(svc, "cache_blacklist", lambda bl: None)

    app = FastAPI()
    app.include_router(more_router)

    return TestClient(app, raise_server_exceptions=False)


AUTH_HDR = {"Authorization": "Bearer fake-test-token"}


def test_rest_blacklist(client):
    """GET /api/more/blacklist и POST /api/more/blacklist работают."""
    r = client.get("/more/blacklist", headers=AUTH_HDR)
    assert r.status_code == 200
    data = r.json()
    assert "blacklist" in data
    assert isinstance(data["blacklist"], list)

    r2 = client.post("/more/blacklist", json={"username": "newbad"}, headers=AUTH_HDR)
    assert r2.status_code == 200
    assert r2.json()["ok"] is True

    r3 = client.get("/more/blacklist", headers=AUTH_HDR)
    assert "newbad" in r3.json()["blacklist"]

    r4 = client.delete("/more/blacklist/newbad", headers=AUTH_HDR)
    assert r4.status_code == 200


def test_rest_notifications(client):
    """GET /api/more/notifications и PATCH возвращают корректные данные."""
    r = client.get("/more/notifications", headers=AUTH_HDR)
    assert r.status_code == 200
    data = r.json()
    assert "BlockList.blockDelivery" in data

    r2 = client.patch("/more/notifications",
                      json={"section": "BlockList", "key": "blockDelivery", "enabled": True},
                      headers=AUTH_HDR)
    assert r2.status_code == 200
    assert r2.json()["ok"] is True


def test_rest_logs_and_plugins(client):
    """GET /api/more/logs и GET /api/more/plugins работают без ошибок."""
    r = client.get("/more/logs?n=10", headers=AUTH_HDR)
    assert r.status_code == 200
    data = r.json()
    assert "lines" in data
    assert isinstance(data["lines"], list)

    r2 = client.get("/more/plugins", headers=AUTH_HDR)
    assert r2.status_code == 200
    data2 = r2.json()
    assert "plugins" in data2
    assert isinstance(data2["plugins"], list)


def test_rest_system_requires_confirm(client):
    """Рестарт и выключение без confirm=True возвращают 400."""
    r = client.post("/more/system/restart", json={"confirm": False}, headers=AUTH_HDR)
    assert r.status_code == 400

    r2 = client.post("/more/system/shutdown", json={"confirm": False}, headers=AUTH_HDR)
    assert r2.status_code == 400


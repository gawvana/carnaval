"""
tests/test_carnaval_bot_parity.py — тесты паритета функций Telegram-бота и Carnaval API:
1. Greetings text & cooldown (EDIT_GREETINGS_TEXT, EDIT_GREETINGS_COOLDOWN)
2. Watermark setting (EDIT_WATERMARK)
3. Order confirmation reply text (EDIT_ORDER_CONFIRM_REPLY_TEXT)
4. Review reply text & star settings (EDIT_REVIEW_REPLY_TEXT, SEND_REVIEW_REPLY_TEXT)
5. Proxy management: select, check toggle, test (PROXY, ADD_PROXY, CHOOSE_PROXY, DELETE_PROXY)
6. Blacklist ban/unban with reason (BAN, UNBAN)
7. Plugins: pin & commands (PIN_PLUGIN, PLUGIN_COMMANDS)
8. Authorized users: detail (AUTHORIZED_USERS, AUTHORIZED_USER_SETTINGS)
9. Config loader: list, download, upload with RBAC (DOWNLOAD_CFG, CONFIG_LOADER)
10. Template answer modes, render & send (TMPLT_LIST_ANS_MODE, SEND_TMPLT)
11. Refund workflow: request, confirm, cancel (REQUEST_REFUND, REFUND_CONFIRMED, REFUND_CANCELLED)
"""

from __future__ import annotations

import configparser
import os
import sys
from typing import Any
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class MockPlugin:
    def __init__(self, uuid="test-uuid", name="Test Plugin"):
        self.uuid = uuid
        self.name = name
        self.version = "1.0.0"
        self.description = "Test description"
        self.credits = "Author"
        self.path = f"plugins/{uuid}.py"
        self.enabled = True
        self.pinned = False
        self.settings_page = False
        self.commands = {"ping": "gl_ping", "help": "gl_help"}


class MockTelegram:
    def __init__(self):
        self.authorized_users = {
            12345: {"username": "admin", "full_name": "Admin User"},
            67890: {"username": "moderator", "full_name": "Mod User"},
        }
        self.answer_templates = ["Привет, $username! Чем могу помочь?", "Спасибо за покупку, $username!"]

    def is_alive(self):
        return True


class MockAccount:
    def __init__(self):
        self.username = "seller"
        self.id = 999
        self.golden_key = "test_golden_key_1234567890"
        self.proxy = {}
        self.is_initiated = True

    def refund(self, order_id: str):
        return True

    def send_review(self, order_id: str, text: str, rating: int = 5):
        return "review_sent"

    def get_order(self, order_id: str):
        class OrderDetail:
            id = order_id
            status = "PAID"
            subcategory = None
            sum = 150.0
            currency = "RUB"
            amount = 1
            buyer_id = 555
            buyer_username = "buyer1"
            chat_id = 777
            fields = {}
            review = None
            order_secrets = []
        return OrderDetail()


class MockCardinal:
    VERSION = "3.13.1"
    start_time = 1000.0
    running = True

    def __init__(self):
        cfg = configparser.ConfigParser()
        cfg.read_string("""
[FunPay]
golden_key = test_key_12345678901234567890
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
enabled = 1
token = 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
secretKeyHash = hash123
proxy =
blockLogin = 0

[BlockList]
blockDelivery = 0
blockResponse = 0
blockNewMessageNotification = 0
blockNewOrderNotification = 0
blockCommandNotification = 0

[NewMessageView]
includeMyMessages = 0
includeFPMessages = 0
includeBotMessages = 0
notifyOnlyMyMessages = 0
notifyOnlyFPMessages = 0
notifyOnlyBotMessages = 0
showImageName = 0

[Greetings]
ignoreSystemMessages = 0
onlyNewChats = 0
sendGreetings = 1
greetingsText = Добро пожаловать!
greetingsCooldown = 7200

[OrderConfirm]
watermark = 1
sendReply = 1
replyText = Спасибо за оформление заказа!

[ReviewReply]
star1Reply = 1
star1ReplyText = Извините за неудобства!
star2Reply = 0
star2ReplyText =
star3Reply = 0
star3ReplyText =
star4Reply = 1
star4ReplyText = Спасибо за 4 звезды!
star5Reply = 1
star5ReplyText = Спасибо за отличный отзыв!

[Proxy]
enable = 1
proxy = http://user:pass@127.0.0.1:8080
check = 1

[Other]
watermark = Carnaval Bot
requestsDelay = 2
language = ru

[Carnaval]
enabled = 1
host = 127.0.0.1
port = 8765
secretKey =
allowedOrigins = *
""")
        self.MAIN_CFG = cfg
        self.RAW_AR_CFG = configparser.ConfigParser()
        self.AR_CFG = {}
        self.AD_CFG = configparser.ConfigParser()
        self.blacklist = ["scammer1"]
        self.plugins = {"test-uuid": MockPlugin("test-uuid")}
        self.proxy_dict = {0: "http://user:pass@127.0.0.1:8080", 1: "http://127.0.0.1:9090"}
        self.telegram = MockTelegram()
        self.account = MockAccount()

    def save_config(self, config, path):
        pass

    def pin_plugin(self, uuid: str):
        if uuid in self.plugins:
            self.plugins[uuid].pinned = not self.plugins[uuid].pinned


@pytest.fixture
def mock_cardinal_env(tmp_path, monkeypatch):
    cardinal = MockCardinal()
    from carnaval import deps
    deps.set_cardinal(cardinal)

    import carnaval.services.more as svc_more
    monkeypatch.setattr(svc_more, "get_cardinal", lambda: cardinal)
    monkeypatch.setattr(svc_more, "cache_blacklist", lambda bl: None)
    monkeypatch.setattr(svc_more, "cache_proxy_dict", lambda pd: None)

    import carnaval.services.automation as svc_auto
    monkeypatch.setattr(svc_auto, "get_cardinal", lambda: cardinal)

    import carnaval.services.chats as svc_chats
    monkeypatch.setattr(svc_chats, "get_cardinal", lambda: cardinal)
    async def mock_send_msg(chat_id, text, chat_name=None):
        return True
    monkeypatch.setattr(svc_chats, "send_message", mock_send_msg)

    import carnaval.services.orders as svc_orders
    monkeypatch.setattr(svc_orders, "get_cardinal", lambda: cardinal)

    yield cardinal
    deps.set_cardinal(None)
    from carnaval.services.account_lifecycle import lifecycle_manager
    lifecycle_manager._init_state()



@pytest.fixture
def test_client(mock_cardinal_env, monkeypatch):
    from carnaval import auth as auth_mod
    monkeypatch.setattr(auth_mod, "get_session", lambda tok: {
        "telegram_user_id": 12345,
        "role": "owner",
        "panel_unlocked": 1,
        "session_id_hash": "mock",
    })

    from carnaval.routers.more import router as more_router
    from carnaval.routers.automation import router as auto_router
    from carnaval.routers.chats import router as chats_router
    from carnaval.routers.orders import router as orders_router

    app = FastAPI()
    app.include_router(more_router)
    app.include_router(auto_router)
    app.include_router(chats_router)
    app.include_router(orders_router)

    return TestClient(app, raise_server_exceptions=False)


AUTH = {"Authorization": "Bearer test-token"}


def test_greetings_endpoints(test_client, mock_cardinal_env):
    """Проверка endpoints для текста и кулдауна приветствия."""
    # 1. Текст приветствия
    r = test_client.get("/more/greetings/text", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["text"] == "Добро пожаловать!"

    r_patch = test_client.patch("/more/greetings/text", json={"text": "Приветствуем в магазине!"}, headers=AUTH)
    assert r_patch.status_code == 200
    assert mock_cardinal_env.MAIN_CFG["Greetings"]["greetingsText"] == "Приветствуем в магазине!"

    # 2. Кулдаун приветствия
    r_cd = test_client.get("/more/greetings/cooldown", headers=AUTH)
    assert r_cd.status_code == 200
    assert r_cd.json()["cooldown"] == 7200.0

    r_patch_cd = test_client.patch("/more/greetings/cooldown", json={"cooldown": 3600.0}, headers=AUTH)
    assert r_patch_cd.status_code == 200
    assert mock_cardinal_env.MAIN_CFG["Greetings"]["greetingsCooldown"] == "3600.0"

    # Невалидный отрицательный кулдаун
    r_err = test_client.patch("/more/greetings/cooldown", json={"cooldown": -50.0}, headers=AUTH)
    assert r_err.status_code == 400


def test_watermark_endpoints(test_client, mock_cardinal_env):
    """Проверка endpoints для водяного знака."""
    r = test_client.get("/more/watermark", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["watermark"] == "Carnaval Bot"

    # Обновление
    r_patch = test_client.patch("/more/watermark", json={"watermark": "My Brand"}, headers=AUTH)
    assert r_patch.status_code == 200
    assert mock_cardinal_env.MAIN_CFG["Other"]["watermark"] == "My Brand"

    # Очистка через "-"
    r_clear = test_client.patch("/more/watermark", json={"watermark": "-"}, headers=AUTH)
    assert r_clear.status_code == 200
    assert mock_cardinal_env.MAIN_CFG["Other"]["watermark"] == ""

    # Запрещенный формат [tag]
    r_bad = test_client.patch("/more/watermark", json={"watermark": "[admin]"}, headers=AUTH)
    assert r_bad.status_code == 400


def test_order_confirm_endpoints(test_client, mock_cardinal_env):
    """Проверка endpoints подтверждения заказа."""
    r = test_client.get("/more/order-confirm", headers=AUTH)
    assert r.status_code == 200
    data = r.json()
    assert data["sendReply"] is True
    assert data["watermark"] is True
    assert data["replyText"] == "Спасибо за оформление заказа!"

    r_txt = test_client.get("/more/order-confirm/reply-text", headers=AUTH)
    assert r_txt.status_code == 200
    assert r_txt.json()["text"] == "Спасибо за оформление заказа!"

    r_patch = test_client.patch("/more/order-confirm/reply-text", json={"text": "Заказ выдан успешно!"}, headers=AUTH)
    assert r_patch.status_code == 200
    assert mock_cardinal_env.MAIN_CFG["OrderConfirm"]["replyText"] == "Заказ выдан успешно!"


def test_review_reply_endpoints(test_client, mock_cardinal_env):
    """Проверка endpoints автоответов на отзывы по звездам."""
    r = test_client.get("/more/review-reply", headers=AUTH)
    assert r.status_code == 200
    stars = r.json()["stars"]
    assert "5" in stars
    assert stars["5"]["enabled"] is True
    assert stars["5"]["text"] == "Спасибо за отличный отзыв!"

    r_5 = test_client.get("/more/review-reply/5", headers=AUTH)
    assert r_5.status_code == 200
    assert r_5.json()["star"] == 5

    r_patch = test_client.patch(
        "/more/review-reply/5",
        json={"enabled": True, "text": "Благодарим за 5 звёзд!"},
        headers=AUTH,
    )
    assert r_patch.status_code == 200
    assert mock_cardinal_env.MAIN_CFG["ReviewReply"]["star5ReplyText"] == "Благодарим за 5 звёзд!"

    # Некорректная звезда
    r_bad = test_client.get("/more/review-reply/10", headers=AUTH)
    assert r_bad.status_code == 400


def test_proxy_endpoints(test_client, mock_cardinal_env, monkeypatch):
    """Проверка управления прокси (активация, проверка, тестирование)."""
    # 1. Переключение проверки
    r_check = test_client.patch("/more/proxy/check", json={"check": True}, headers=AUTH)
    assert r_check.status_code == 200
    assert mock_cardinal_env.MAIN_CFG["Proxy"]["check"] == "1"

    # 2. Выбор активного прокси через POST /select
    r_sel = test_client.post("/more/proxy/select", json={"proxy_id": 1}, headers=AUTH)
    assert r_sel.status_code == 200
    assert "127.0.0.1:9090" in mock_cardinal_env.MAIN_CFG["Proxy"]["proxy"]

    # 3. Тест прокси
    from Utils import cardinal_tools
    monkeypatch.setattr(cardinal_tools, "check_proxy", lambda p: True)
    r_test = test_client.post("/more/proxy/1/test", headers=AUTH)
    assert r_test.status_code == 200
    assert r_test.json()["ok"] is True


def test_blacklist_ban_unban_with_reason(test_client, mock_cardinal_env):
    """Проверка BAN/UNBAN с причиной и сохранением метаданных."""
    # 1. Блокировка с причиной
    r_ban = test_client.post(
        "/more/blacklist/ban",
        json={"username": "cheater99", "reason": "Попытка обмана продавца"},
        headers=AUTH,
    )
    assert r_ban.status_code == 200
    assert "cheater99" in mock_cardinal_env.blacklist

    # 2. Получение ЧС с причиной
    r_list = test_client.get("/more/blacklist", headers=AUTH)
    assert r_list.status_code == 200
    data = r_list.json()
    assert "cheater99" in data["blacklist"]
    item = next((i for i in data["items"] if i["username"] == "cheater99"), None)
    assert item is not None
    assert item["reason"] == "Попытка обмана продавца"

    # 3. Разблокировка через /unban
    r_unban = test_client.post("/more/blacklist/unban", json={"username": "cheater99"}, headers=AUTH)
    assert r_unban.status_code == 200
    assert "cheater99" not in mock_cardinal_env.blacklist


def test_plugin_pin_and_commands(test_client, mock_cardinal_env):
    """Проверка закрепления плагина и получения его команд."""
    r_pin = test_client.post("/more/plugins/test-uuid/pin", headers=AUTH)
    assert r_pin.status_code == 200
    assert mock_cardinal_env.plugins["test-uuid"].pinned is True

    r_cmds = test_client.get("/more/plugins/test-uuid/commands", headers=AUTH)
    assert r_cmds.status_code == 200
    assert "ping" in r_cmds.json()["commands"]


def test_authorized_user_detail(test_client, mock_cardinal_env):
    """Проверка получения детальной информации об авторизованном пользователе."""
    r = test_client.get("/more/authorized-users/12345", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["user_id"] == 12345
    assert r.json()["data"]["username"] == "admin"

    r_none = test_client.get("/more/authorized-users/99999", headers=AUTH)
    assert r_none.status_code == 404


def test_config_loader_endpoints(test_client, mock_cardinal_env, tmp_path, monkeypatch):
    """Проверка Config Loader: список, скачивание и загрузка."""
    import carnaval.services.more as svc_more

    # Мокаем пути конфигов во временную папку
    main_cfg_file = tmp_path / "_main.cfg"
    main_cfg_file.write_text("[FunPay]\ngolden_key = test\n", encoding="utf-8")
    monkeypatch.setattr(svc_more, "list_available_configs", lambda: [
        {"type": "main", "filename": "_main.cfg", "path": str(main_cfg_file), "exists": True, "size": 100, "description": "Main"}
    ])
    monkeypatch.setattr(svc_more, "get_config_content", lambda t: ("[FunPay]\ngolden_key = test\n", "_main.cfg", None))
    monkeypatch.setattr(svc_more, "save_config_file", lambda t, c: (True, ""))

    r_list = test_client.get("/more/configs", headers=AUTH)
    assert r_list.status_code == 200
    assert len(r_list.json()["configs"]) == 1

    r_dl = test_client.get("/more/configs/main/download", headers=AUTH)
    assert r_dl.status_code == 200
    assert "[FunPay]" in r_dl.text

    # Загрузка без confirm -> 400
    r_bad_up = test_client.post("/more/configs/main", json={"content": "[FunPay]\n", "confirm": False}, headers=AUTH)
    assert r_bad_up.status_code == 400

    # Загрузка с confirm=True
    r_ok_up = test_client.post("/more/configs/main", json={"content": "[FunPay]\n", "confirm": True}, headers=AUTH)
    assert r_ok_up.status_code == 200


def test_template_answer_mode_and_send(test_client, mock_cardinal_env):
    """Проверка режима ответа шаблонами и отправки в чат."""
    from Utils import cardinal_tools
    # 1. Answer mode с подстановкой $username
    r_ans = test_client.get("/templates/answer-mode?username=Alex", headers=AUTH)
    assert r_ans.status_code == 200
    templates = r_ans.json()["templates"]
    assert len(templates) == 2
    assert cardinal_tools.safe_text("Alex") in templates[0]["rendered"]

    # 2. Render
    r_ren = test_client.post("/templates/0/render", json={"username": "Maria"}, headers=AUTH)
    assert r_ren.status_code == 200
    assert cardinal_tools.safe_text("Maria") in r_ren.json()["rendered"]

    # 3. Send template через /templates/{i}/send
    r_send = test_client.post("/templates/0/send", json={"chat_id": 777, "username": "John"}, headers=AUTH)
    assert r_send.status_code == 200

    # 4. Send template через /chats/{chat_id}/templates
    r_chat_send = test_client.post("/chats/777/templates", json={"template_index": 1, "username": "John"}, headers=AUTH)
    assert r_chat_send.status_code == 200



def test_order_refund_and_review_reply(test_client, mock_cardinal_env):
    """Проверка процесса возврата средств и ответа на отзыв."""
    # 1. Запрос на возврат (request)
    r_req = test_client.post("/orders/ORDER-1/refund/request", headers=AUTH)
    assert r_req.status_code == 200
    assert r_req.json()["refundable"] is True
    assert r_req.json()["buyer_username"] == "buyer1"

    # 2. Отмена возврата (cancel)
    r_canc = test_client.post("/orders/ORDER-1/refund/cancel", headers=AUTH)
    assert r_canc.status_code == 200
    assert r_canc.json()["cancelled"] is True

    # 3. Подтверждение возврата (confirm)
    r_conf = test_client.post("/orders/ORDER-1/refund/confirm", headers=AUTH)
    assert r_conf.status_code == 200
    assert r_conf.json()["success"] is True

    # 4. Ответ на отзыв с авто-шаблоном для 5 звезд
    r_rev = test_client.post("/orders/ORDER-1/review-reply", json={"rating": 5}, headers=AUTH)
    assert r_rev.status_code == 200

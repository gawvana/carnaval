"""
Тесты для Carnaval:
1. Эмуляция автоматизации (simulate_automation) без сетевых запросов и мутаций:
   - Проверка правил auto_delivery, auto_response, greetings.
   - Проверка условий pass/fail, action_preview, duration_ms.
   - Проверка отсутствия списания товаров и отсутствия сетевых запросов.
2. Кольцевой буфер трассировок (debug-traces):
   - Добавление трассировок при симуляции.
   - Лимит и порядок (newest first).
   - Защита от переполнения.
3. Единый глобальный поиск (global_search & GET /api/search):
   - Поиск по 8 доменам: chats, orders, templates, plugins, automations, blacklist, logs, settings.
   - Валидация структуры ответа: title, description, category, route, action.
   - Авторизация и пагинация limit_per_category.
"""

import os
import time
import configparser
import logging
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from carnaval.server import build_app
from carnaval.deps import set_cardinal
from carnaval import auth
from carnaval.services import automation as auto_svc
from carnaval.services import search as search_svc
from carnaval.services import more as more_svc


@pytest.fixture
def mock_cardinal_env(tmp_path, monkeypatch):
    """Изолированная среда Cardinal для тестирования эмуляции и поиска."""
    monkeypatch.chdir(tmp_path)

    c = MagicMock()
    c.VERSION = "0.1.18.0"
    c.delivery_tests = {}
    c.blacklist = ["banned_user", "cheater99"]
    c.old_users = {55555: time.time() - 100}  # в кулдауне
    c.greeting_chat_id_threshold = 1000
    c.greeting_threshold_chat_ids = {1001, 1002}
    c.autodelivery_enabled = True
    c.autoresponse_enabled = True
    c.bl_delivery_enabled = True
    c.bl_response_enabled = True

    # 1. Папка товаров и тестовый файл
    products_dir = tmp_path / "storage" / "products"
    products_dir.mkdir(parents=True, exist_ok=True)
    goods_file = products_dir / "keys.txt"
    goods_file.write_text("KEY-AAA-111\nKEY-BBB-222\nKEY-CCC-333\n", encoding="utf-8")

    cache_dir = tmp_path / "storage" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Причины блокировки в ЧС
    reasons_file = cache_dir / "blacklist_reasons.json"
    reasons_file.write_text('{"banned_user": "Мошенничество", "cheater99": "Спам"}', encoding="utf-8")

    # 2. ConfigParser'ы
    main_cfg = configparser.ConfigParser(delimiters=(":",), interpolation=None)
    main_cfg.optionxform = str
    main_cfg.add_section("Carnaval")
    main_cfg.set("Carnaval", "enabled", "1")
    main_cfg.set("Carnaval", "secretKey", "secret_auto_search_test")

    main_cfg.add_section("FunPay")
    main_cfg.set("FunPay", "golden_key", "mock_golden_key_1234567890abcdef")
    main_cfg.set("FunPay", "autoDelivery", "1")
    main_cfg.set("FunPay", "autoResponse", "1")

    main_cfg.add_section("BlockList")
    main_cfg.set("BlockList", "blockDelivery", "1")
    main_cfg.set("BlockList", "blockResponse", "1")

    main_cfg.add_section("Greetings")
    main_cfg.set("Greetings", "sendGreetings", "1")
    main_cfg.set("Greetings", "greetingsText", "Добро пожаловать в магазин, $username!")
    main_cfg.set("Greetings", "greetingsCooldown", "1.0")
    main_cfg.set("Greetings", "onlyNewChats", "1")
    main_cfg.set("Greetings", "ignoreSystemMessages", "1")

    main_cfg.add_section("Proxy")
    main_cfg.set("Proxy", "enable", "0")
    main_cfg.set("Proxy", "proxy", "http://user:pass@proxy.example.com:8080")

    ad_cfg = configparser.ConfigParser(delimiters=(":",), interpolation=None)
    ad_cfg.optionxform = str
    ad_cfg.add_section("Steam Random Key")
    ad_cfg.set("Steam Random Key", "response", "Привет $buyer, вот твой ключ: $product! Заказ $order_id.")
    ad_cfg.set("Steam Random Key", "productsFileName", "keys.txt")
    ad_cfg.set("Steam Random Key", "disable", "0")

    ad_cfg.add_section("Disabled Key Lot")
    ad_cfg.set("Disabled Key Lot", "response", "Товар: $product")
    ad_cfg.set("Disabled Key Lot", "productsFileName", "keys.txt")
    ad_cfg.set("Disabled Key Lot", "disable", "1")

    raw_ar_cfg = configparser.ConfigParser(delimiters=(":",), interpolation=None)
    raw_ar_cfg.optionxform = str
    raw_ar_cfg.add_section("!help|!помощь")
    raw_ar_cfg.set("!help|!помощь", "response", "Здравствуйте, $username! Мы работаем круглосуточно.")
    raw_ar_cfg.set("!help|!помощь", "telegramNotification", "1")
    raw_ar_cfg.set("!help|!помощь", "notificationText", "Команда помощи от $username")
    raw_ar_cfg.set("!help|!помощь", "enabled", "1")

    raw_ar_cfg.add_section("!disabled_cmd")
    raw_ar_cfg.set("!disabled_cmd", "response", "Отключено")
    raw_ar_cfg.set("!disabled_cmd", "telegramNotification", "0")
    raw_ar_cfg.set("!disabled_cmd", "enabled", "0")

    ar_cfg = configparser.ConfigParser(delimiters=(":",), interpolation=None)
    ar_cfg.optionxform = str
    ar_cfg.add_section("!help")
    ar_cfg.set("!help", "response", "Здравствуйте, $username! Мы работаем круглосуточно.")
    ar_cfg.set("!help", "enabled", "1")
    ar_cfg.add_section("!помощь")
    ar_cfg.set("!помощь", "response", "Здравствуйте, $username! Мы работаем круглосуточно.")
    ar_cfg.set("!помощь", "enabled", "1")
    ar_cfg.add_section("!disabled_cmd")
    ar_cfg.set("!disabled_cmd", "response", "Отключено")
    ar_cfg.set("!disabled_cmd", "enabled", "0")

    c.MAIN_CFG = main_cfg
    c.AD_CFG = ad_cfg
    c.RAW_AR_CFG = raw_ar_cfg
    c.AR_CFG = ar_cfg

    # 3. Плагины
    mock_plugin = MagicMock()
    mock_plugin.name = "AutoDeliveryTurbo"
    mock_plugin.description = "Плагин ускоренной доставки товаров"
    mock_plugin.credits = "Carnaval Team"
    mock_plugin.version = "2.5.0"
    mock_plugin.enabled = True
    c.plugins = {"uuid-turbo-001": mock_plugin}

    # 4. Шаблоны ответов
    c.telegram = MagicMock()
    c.telegram.authorized_users = {12345: {}}
    c.telegram.answer_templates = [
        "Благодарим за покупку!",
        "Оставьте, пожалуйста, положительный отзыв.",
    ]

    # 5. Аккаунт и чаты/заказы
    c.account = MagicMock()
    c.account.id = 777
    c.account.is_initiated = True

    mock_chat = MagicMock()
    mock_chat.id = 98765
    mock_chat.name = "AlexGamer"
    mock_chat.last_message_text = "Куплю золото в World of Warcraft"
    c.account.chats = {98765: mock_chat}

    mock_order = MagicMock()
    mock_order.id = "ORD-998877"
    mock_order.description = "1000 Gold WoW EU Horde"
    mock_order.buyer_username = "AlexGamer"
    mock_order.price = 450.0
    mock_order.currency = "RUB"
    mock_order.subcategory_name = "WoW Золото"
    c.orders = {"ORD-998877": mock_order}

    # Подмена вызова отправки FunPay сообщений
    c.send_message = MagicMock(return_value=True)

    set_cardinal(c)
    auth.init("secret_auto_search_test")

    # Добавим запись в лог для проверки поиска логов
    c.logs = ["Carnaval test runner engine is running smoothly"]
    more_svc._memory_handler._lines.append("Carnaval test runner engine is running smoothly")

    auto_svc.clear_execution_traces()
    return c


# ─────────────────────────────────────────────────────────────
# 1. Тесты эмуляции без мутаций
# ─────────────────────────────────────────────────────────────

def test_simulation_delivery_success_and_immutability(mock_cardinal_env):
    """Проверка успешной симуляции автовыдачи без списания товаров и без отправки сообщений."""
    products_file_path = os.path.abspath(os.path.join("storage", "products", "keys.txt"))
    with open(products_file_path, "r", encoding="utf-8") as f:
        initial_lines = f.readlines()
    assert len(initial_lines) == 3

    payload = {
        "description": "Steam Random Key (Global)",
        "buyer_username": "LegitBuyer",
        "amount": 2,
        "order_id": "ORD-12345",
    }

    result = auto_svc.simulate_automation("auto_delivery", payload)

    assert result["success"] is True
    assert result["matched_rule"] == "Steam Random Key"
    assert result["duration_ms"] >= 0.0

    conditions_dict = {c["name"]: c["passed"] for c in result["conditions"]}
    assert conditions_dict["global_auto_delivery"] is True
    assert conditions_dict["buyer_not_blacklisted"] is True
    assert conditions_dict["lot_rule_matched"] is True
    assert conditions_dict["rule_not_disabled"] is True
    assert conditions_dict["goods_availability"] is True

    preview = result["action_preview"]
    assert preview is not None
    assert preview["action"] == "deliver_product"
    assert preview["recipient"] == "LegitBuyer"
    assert "KEY-AAA-111" in preview["delivery_text"]
    assert "KEY-BBB-222" in preview["delivery_text"]
    assert "ORD-12345" in preview["delivery_text"]
    assert preview["goods_delivered_count"] == 2
    assert preview["goods_left_estimate"] == 1

    # ВАЖНО: Проверяем, что файл НЕ изменился (мутации нет)
    with open(products_file_path, "r", encoding="utf-8") as f:
        after_lines = f.readlines()
    assert len(after_lines) == 3
    assert initial_lines == after_lines

    # ВАЖНО: Cardinal.send_message не вызывался
    assert mock_cardinal_env.send_message.call_count == 0


def test_simulation_delivery_blacklisted_user(mock_cardinal_env):
    """Проверка отказа в автовыдаче для пользователя из ЧС."""
    payload = {
        "description": "Steam Random Key",
        "buyer_username": "banned_user",
        "amount": 1,
    }
    result = auto_svc.simulate_automation("auto_delivery", payload)

    assert result["success"] is False
    assert result["matched_rule"] == "Steam Random Key"
    conditions = {c["name"]: c for c in result["conditions"]}
    assert conditions["buyer_not_blacklisted"]["passed"] is False
    assert "blacklisted" in conditions["buyer_not_blacklisted"]["details"].lower()


def test_simulation_delivery_disabled_lot(mock_cardinal_env):
    """Проверка симуляции для отключённого лота."""
    payload = {
        "description": "Disabled Key Lot",
        "buyer_username": "GoodBuyer",
        "amount": 1,
    }
    result = auto_svc.simulate_automation("auto_delivery", payload)
    assert result["success"] is False
    assert result["matched_rule"] == "Disabled Key Lot"
    conditions = {c["name"]: c for c in result["conditions"]}
    assert conditions["rule_not_disabled"]["passed"] is False


def test_simulation_delivery_out_of_stock(mock_cardinal_env):
    """Проверка симуляции при нехватке товара."""
    payload = {
        "description": "Steam Random Key",
        "buyer_username": "GoodBuyer",
        "amount": 50,  # В файле только 3
    }
    result = auto_svc.simulate_automation("auto_delivery", payload)
    assert result["success"] is False
    conditions = {c["name"]: c for c in result["conditions"]}
    assert conditions["goods_availability"]["passed"] is False


def test_simulation_delivery_not_matched(mock_cardinal_env):
    """Проверка симуляции для лота, отсутствующего в конфиге."""
    payload = {
        "description": "Non-existent item",
        "buyer_username": "GoodBuyer",
    }
    result = auto_svc.simulate_automation("auto_delivery", payload)
    assert result["success"] is False
    assert result["matched_rule"] is None
    conditions = {c["name"]: c for c in result["conditions"]}
    assert conditions["lot_rule_matched"]["passed"] is False


def test_simulation_auto_response(mock_cardinal_env):
    """Проверка симуляции правил автоответчика."""
    # 1. Успешное срабатывание команды
    payload = {
        "message": "!help",
        "author": "Alice",
        "chat_id": 11111,
    }
    res = auto_svc.simulate_automation("auto_response", payload)
    assert res["success"] is True
    assert res["matched_rule"] in ("!help", "!help|!помощь")
    assert res["action_preview"]["response_text"] == "Здравствуйте, Alice! Мы работаем круглосуточно."
    assert res["action_preview"]["telegram_notification"] is True

    # 2. Алиас команды (!помощь)
    payload_alias = {"message": "!помощь", "author": "Bob"}
    res_alias = auto_svc.simulate_automation("auto_response", payload_alias)
    assert res_alias["success"] is True

    # 3. Отключенная команда
    res_dis = auto_svc.simulate_automation("auto_response", {"message": "!disabled_cmd", "author": "Alice"})
    assert res_dis["success"] is False
    conditions_dis = {c["name"]: c["passed"] for c in res_dis["conditions"]}
    assert conditions_dis["command_enabled"] is False

    # 4. Заблокированный пользователь
    res_bl = auto_svc.simulate_automation("auto_response", {"message": "!help", "author": "banned_user"})
    assert res_bl["success"] is False
    conditions_bl = {c["name"]: c["passed"] for c in res_bl["conditions"]}
    assert conditions_bl["user_not_blacklisted"] is False


def test_simulation_greetings(mock_cardinal_env):
    """Проверка симуляции приветственного сообщения."""
    # 1. Новый чат (> порога threshold 1000)
    payload_new = {
        "username": "Charlie",
        "chat_id": 99999,
        "is_new_chat": True,
    }
    res = auto_svc.simulate_automation("greetings", payload_new)
    assert res["success"] is True
    assert res["matched_rule"] == "Greetings"
    assert res["action_preview"]["greeting_text"] == "Добро пожаловать в магазин, Charlie!"

    # 2. Старый чат при onlyNewChats=1
    payload_old = {
        "username": "Charlie",
        "chat_id": 500,  # <= 1000
    }
    res_old = auto_svc.simulate_automation("greetings", payload_old)
    assert res_old["success"] is False
    conditions_old = {c["name"]: c["passed"] for c in res_old["conditions"]}
    assert conditions_old["only_new_chats_check"] is False


def test_simulation_message_event_dispatch(mock_cardinal_env):
    """Проверка диспетчеризации обобщенного события 'message'."""
    # Команда -> уходит в автоответчик
    res_cmd = auto_svc.simulate_automation("message", {"message": "!help", "author": "User1"})
    assert res_cmd["category"] == "auto_response"
    assert res_cmd["success"] is True

    # Обычный текст -> уходит в приветствие
    res_msg = auto_svc.simulate_automation("message", {"message": "Привет!", "username": "User2", "chat_id": 88888})
    assert res_msg["category"] == "greetings"
    assert res_msg["success"] is True


# ─────────────────────────────────────────────────────────────
# 2. Тесты кольцевого буфера трассировок
# ─────────────────────────────────────────────────────────────

def test_debug_traces_ring_buffer(mock_cardinal_env):
    """Проверка сохранения трассировок, лимитов и порядка (newest first)."""
    auto_svc.clear_execution_traces()
    assert len(auto_svc.get_execution_traces()) == 0

    # Выполняем 3 симуляции
    auto_svc.simulate_automation("auto_response", {"message": "!help", "author": "U1"})
    auto_svc.simulate_automation("greetings", {"username": "U2", "chat_id": 77777})
    auto_svc.simulate_automation("auto_delivery", {"description": "Steam Random Key", "buyer_username": "U3"})

    traces = auto_svc.get_execution_traces(limit=10)
    assert len(traces) == 3

    # Самая последняя симуляция должна быть первой
    assert traces[0]["category"] == "auto_delivery"
    assert traces[0]["matched_rule"] == "Steam Random Key"
    assert traces[1]["category"] == "greetings"
    assert traces[2]["category"] == "auto_response"

    # Проверка фильтрации по limit
    limited_traces = auto_svc.get_execution_traces(limit=2)
    assert len(limited_traces) == 2
    assert limited_traces[0]["category"] == "auto_delivery"
    assert limited_traces[1]["category"] == "greetings"

    # Проверка емкости кольцевого буфера (не превышает maxlen=200)
    for i in range(250):
        auto_svc.simulate_automation("auto_response", {"message": f"!cmd_{i}"})

    all_traces = auto_svc.get_execution_traces(limit=300)
    assert len(all_traces) <= 200


# ─────────────────────────────────────────────────────────────
# 3. HTTP Endpoints автоматизации (POST /simulate, GET /debug-traces)
# ─────────────────────────────────────────────────────────────

def test_automation_api_endpoints(mock_cardinal_env):
    """Проверка HTTP API эмуляции и получения трассировок."""
    app = build_app()
    client = TestClient(app)

    # 1. Проверка требования авторизации
    res_unauth = client.post("/api/automation/simulate", json={"event_type": "auto_delivery"})
    assert res_unauth.status_code == 401

    res_traces_unauth = client.get("/api/automation/debug-traces")
    assert res_traces_unauth.status_code == 401

    # 2. Авторизованный запрос симуляции
    token = auth.create_token(12345)
    headers = {"Authorization": f"Bearer {token}"}

    sim_payload = {
        "event_type": "auto_delivery",
        "test_payload": {
            "description": "Steam Random Key",
            "buyer_username": "HttpBuyer",
            "amount": 1,
        }
    }
    res_sim = client.post("/api/automation/simulate", json=sim_payload, headers=headers)
    assert res_sim.status_code == 200
    data = res_sim.json()
    assert data["success"] is True
    assert data["matched_rule"] == "Steam Random Key"
    assert "KEY-AAA-111" in data["action_preview"]["delivery_text"]

    # 3. Авторизованный запрос получения трассировок
    res_traces = client.get("/api/automation/debug-traces?limit=5", headers=headers)
    assert res_traces.status_code == 200
    traces = res_traces.json().get("traces", [])
    assert len(traces) >= 1
    assert traces[0]["matched_rule"] == "Steam Random Key"


# ─────────────────────────────────────────────────────────────
# 4. Тесты единого глобального поиска (Service & API)
# ─────────────────────────────────────────────────────────────

def test_global_search_service_domains(mock_cardinal_env):
    """Проверка поиска по всем 8 доменам через search_svc.global_search."""
    # 1. Пустой запрос
    empty_res = search_svc.global_search("")
    assert empty_res["total"] == 0
    assert len(empty_res["items"]) == 0
    for cat in ["chats", "orders", "templates", "plugins", "automations", "blacklist", "logs", "settings"]:
        assert cat in empty_res["results"]
        assert len(empty_res["results"][cat]) == 0

    # 2. Поиск по чатам ("AlexGamer" / "золото")
    res_chat = search_svc.global_search("AlexGamer")
    assert len(res_chat["chats"]) >= 1
    chat_item = res_chat["chats"][0]
    assert chat_item["category"] == "chats"
    assert "AlexGamer" in chat_item["title"]
    assert chat_item["route"] == f"/chats/{mock_cardinal_env.account.chats[98765].id}"
    assert "action" in chat_item

    # 3. Поиск по заказам ("WoW" / "ORD-998877")
    res_order = search_svc.global_search("ORD-998877")
    assert len(res_order["orders"]) >= 1
    order_item = res_order["orders"][0]
    assert order_item["category"] == "orders"
    assert "ORD-998877" in order_item["title"]
    assert order_item["route"] == "/orders/ORD-998877"

    # 4. Поиск по шаблонам ("покупку")
    res_tmpl = search_svc.global_search("покупку")
    assert len(res_tmpl["templates"]) >= 1
    tmpl_item = res_tmpl["templates"][0]
    assert tmpl_item["category"] == "templates"
    assert "покупку" in tmpl_item["description"]
    assert "/automation#template" in tmpl_item["route"]

    # 5. Поиск по плагинам ("AutoDeliveryTurbo" / "ускоренной")
    res_pl = search_svc.global_search("Turbo")
    assert len(res_pl["plugins"]) >= 1
    pl_item = res_pl["plugins"][0]
    assert pl_item["category"] == "plugins"
    assert "AutoDeliveryTurbo" in pl_item["title"]
    assert "/more#plugin-uuid-turbo-001" in pl_item["route"]

    # 6. Поиск по автоматизациям ("Steam" / "!help")
    res_auto = search_svc.global_search("Steam")
    assert len(res_auto["automations"]) >= 1
    auto_item = res_auto["automations"][0]
    assert auto_item["category"] == "automations"
    assert "Steam Random Key" in auto_item["title"]

    res_cmd = search_svc.global_search("help")
    assert len(res_cmd["automations"]) >= 1

    # 7. Поиск по чёрному списку ("banned_user" / "Мошенничество")
    res_bl = search_svc.global_search("banned_user")
    assert len(res_bl["blacklist"]) >= 1
    bl_item = res_bl["blacklist"][0]
    assert bl_item["category"] == "blacklist"
    assert "@banned_user" in bl_item["title"]
    assert "Мошенничество" in bl_item["description"]

    # 8. Поиск по логам ("Carnaval test runner")
    res_logs = search_svc.global_search("test runner engine")
    assert len(res_logs["logs"]) >= 1
    log_item = res_logs["logs"][0]
    assert log_item["category"] == "logs"
    assert "runner engine" in log_item["description"]

    # 9. Поиск по настройкам ("golden_key" / "Greetings")
    res_settings = search_svc.global_search("greetings")
    assert len(res_settings["settings"]) >= 1
    setting_item = res_settings["settings"][0]
    assert setting_item["category"] == "settings"
    assert "Greetings" in setting_item["title"] or "greetings" in setting_item["description"].lower()


def test_search_api_endpoint(mock_cardinal_env):
    """Проверка эндпоинта GET /api/search с авторизацией и параметрами."""
    app = build_app()
    client = TestClient(app)

    # 1. 401 Unauthorized
    res_unauth = client.get("/api/search?q=Steam")
    assert res_unauth.status_code == 401

    # 2. 200 OK
    token = auth.create_token(12345)
    headers = {"Authorization": f"Bearer {token}"}

    res_auth = client.get("/api/search?q=Steam&limit_per_category=2", headers=headers)
    assert res_auth.status_code == 200
    data = res_auth.json()

    assert data["query"] == "Steam"
    assert data["total"] >= 1
    assert "results" in data
    assert len(data["results"]["automations"]) >= 1
    assert len(data["results"]["automations"]) <= 2

    # Проверка alias-параметра query
    res_alias = client.get("/api/search?query=Gold", headers=headers)
    assert res_alias.status_code == 200
    assert res_alias.json()["query"] == "Gold"

"""
tests/test_carnaval_live_center.py
Полный набор тестов для Live Control Center:
1. Сбор живой авторитетной телеметрии (FunPay, Runner, System, Operational).
2. Провайдер топологии системы (DAG из 8 узлов, статусы, причины, кнопки восстановления, ребра).
3. Кольцевой буфер ленты активности (потокобезопасность, лимит 100, структура событий, фильтрация).
4. Сервис симуляции повтора событий (Event Replay: chat & order, dry-run, правила, предотвращение side-effects).
5. REST API эндпоинты (/api/live/metrics, /api/live/topology, /api/live/timeline, /api/live/replay-event).
"""

from __future__ import annotations

import configparser
import datetime
import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from carnaval import auth, bridge
from carnaval.deps import set_cardinal
from carnaval.routers import api_router
from carnaval.routers.live import router as live_router
from carnaval.server import build_app
from carnaval.services import live as live_svc


@pytest.fixture(autouse=True)
def reset_timeline():
    """Сбрасывает буфер ленты активности перед каждым тестом."""
    live_svc.timeline.clear()
    live_svc.timeline.record_event(
        category="system",
        title="Live Control Center Initialized",
        description="Тестовая инициализация",
        details={"env": "test"},
        replay_supported=False,
        broadcast_sse=False,
        node_id="backend",
    )
    yield
    live_svc.timeline.clear()


@pytest.fixture
def mock_cardinal():
    """Создает мок Cardinal с реалистичными подсистемами."""
    c = MagicMock()
    c.VERSION = "0.1.18.0"
    c.running = True
    c.start_time = time.time() - 3600  # Uptime 1 час

    # Конфигурации
    main_cfg = configparser.ConfigParser()
    main_cfg.read_string("""
[FunPay]
golden_key = test_golden_key_32_characters_1234
autoRaise = 1
autoResponse = 1
autoDelivery = 1

[Telegram]
enabled = 1
token = test_token

[Other]
adExactMatch = 0
""")
    c.MAIN_CFG = main_cfg

    ad_cfg = configparser.ConfigParser()
    ad_cfg.read_string("""
[Premium VIP]
response = Ваш VIP ключ: $product! Приятной игры, $username!
productsFileName = vip_keys.txt
disable = 0

[Disabled Lot]
response = Этот лот отключен
productsFileName =
disable = 1
""")
    c.AD_CFG = ad_cfg

    ar_cfg = configparser.ConfigParser()
    ar_cfg.read_string("""
[!help]
response = Здравствуйте, $username! Доступные команды: !help, !stock
enabled = 1
telegramNotification = 1
notificationText = Вызвана справка !help

[!disabled]
response = Отключенная команда
enabled = 0
telegramNotification = 0
""")
    c.AR_CFG = ar_cfg
    c.RAW_AR_CFG = ar_cfg

    # Аккаунт FunPay
    acc = MagicMock()
    acc.id = 778899
    acc.username = "TopSeller"
    acc.is_initiated = True
    acc.total_balance = 12500.50
    curr_mock = MagicMock()
    curr_mock.name = "RUB"
    acc.currency = curr_mock
    acc.last_update = time.time() - 10

    # Сохраненные чаты
    c1 = MagicMock()
    c1.unread = True
    c2 = MagicMock()
    c2.unread = False
    acc._Account__saved_chats = {1: c1, 2: c2}
    c.account = acc

    # Баланс
    bal = MagicMock()
    bal.total_rub = 12500.50
    bal.available_rub = 12000.00
    c.balance = bal

    # Runner
    runner = MagicMock()
    runner.payload_queue = {"req1": {}, "req2": {}}
    runner.saved_orders = {
        "ord1": MagicMock(
            id="ord1",
            date=datetime.datetime.now(),
            description="Premium VIP 30 days",
            buyer_username="HappyBuyer",
            price=500.0,
            currency=curr_mock,
        ),
        "ord2": MagicMock(
            id="ord2",
            date=datetime.datetime.now() - datetime.timedelta(days=2),
            description="Old order",
            buyer_username="OldBuyer",
            price=200.0,
            currency=curr_mock,
        ),
    }
    c.runner = runner

    # Telegram
    tg = MagicMock()
    tg.is_alive.return_value = True
    tg.authorized_users = {987654321: {}}
    c.telegram = tg

    # Плагины
    p1 = MagicMock()
    p1.enabled = True
    p2 = MagicMock()
    p2.enabled = False
    c.plugins = {"plugin_auto_review": p1, "plugin_inactive": p2}
    c.disabled_plugins = ["plugin_inactive"]

    set_cardinal(c)
    auth.init("test_secret_live_control")
    return c


@pytest.fixture
def auth_headers():
    token = auth.create_token(987654321)
    return {"Authorization": f"Bearer {token}"}


# ─────────────────────────────────────────────────────────────
# 1. Тесты сбора живой телеметрии
# ─────────────────────────────────────────────────────────────

def test_telemetry_gathering_disconnected(monkeypatch):
    """Проверка сбора телеметрии при отключенном Cardinal."""
    monkeypatch.setattr(live_svc, "_safe_get_cardinal", lambda: None)
    telemetry = live_svc.get_live_telemetry()

    assert telemetry["ok"] is True
    assert isinstance(telemetry["timestamp"], float)

    # FunPay
    assert telemetry["funpay"]["connection_state"] in ("disconnected", "no_key")
    assert telemetry["funpay"]["user"]["id"] is None
    assert telemetry["funpay"]["user"]["username"] is None
    assert telemetry["funpay"]["balance"] == 0.0

    # Runner
    assert telemetry["runner"]["loop_status"] in ("stopped", "inactive")
    assert telemetry["runner"]["queue_size"] == 0
    assert telemetry["runner"]["attempts"] == 0

    # System
    assert "cpu_percent" in telemetry["system"]
    assert "memory_mb" in telemetry["system"]
    assert telemetry["system"]["uptime_seconds"] >= 0
    assert "database_size_bytes" in telemetry["system"]
    assert "database_size_formatted" in telemetry["system"]
    assert telemetry["system"]["sse_connected_clients"] >= 0

    # Operational
    assert telemetry["operational"]["unread_chats"] == 0
    assert telemetry["operational"]["today_orders_count"] == 0
    assert telemetry["operational"]["active_automations"] >= 0
    assert telemetry["operational"]["running_plugins_count"] == 0


def test_telemetry_gathering_connected(mock_cardinal, monkeypatch):
    """Проверка сбора полной авторитетной телеметрии при активном Cardinal."""
    monkeypatch.setattr(live_svc, "_safe_get_cardinal", lambda: mock_cardinal)

    telemetry = live_svc.get_live_telemetry()

    assert telemetry["ok"] is True
    # FunPay
    assert telemetry["funpay"]["connection_state"] == "ready"
    assert telemetry["funpay"]["user"]["id"] == 778899
    assert telemetry["funpay"]["user"]["username"] == "TopSeller"
    assert telemetry["funpay"]["balance"] == 12500.50
    assert telemetry["funpay"]["currency"] == "RUB"
    assert telemetry["funpay"]["last_ping"] > 0

    # Runner
    assert telemetry["runner"]["loop_status"] == "running"
    assert telemetry["runner"]["queue_size"] == 2

    # Operational
    assert telemetry["operational"]["unread_chats"] == 1
    assert telemetry["operational"]["today_orders_count"] == 1  # 1 сегодня, 1 2 дня назад
    assert telemetry["operational"]["running_plugins_count"] == 1
    assert telemetry["operational"]["active_automations"] >= 2  # 1 лот + 1 команда включены


def test_system_metrics_calculation():
    """Проверка расчета системных метрик CPU, памяти и БД."""
    cpu, mem = live_svc._get_system_cpu_memory()
    assert isinstance(cpu, float)
    assert isinstance(mem, float)
    assert mem > 0  # Тестовый процесс Python занимает память

    size_b, formatted = live_svc._get_database_size()
    assert isinstance(size_b, int)
    assert isinstance(formatted, str)
    assert any(unit in formatted for unit in ("B", "KB", "MB"))


# ─────────────────────────────────────────────────────────────
# 2. Тесты провайдера топологии (DAG)
# ─────────────────────────────────────────────────────────────

def test_topology_structure(mock_cardinal, monkeypatch):
    """Проверка формирования всех 8 узлов топологии и DAG ребер."""
    monkeypatch.setattr(live_svc, "_safe_get_cardinal", lambda: mock_cardinal)

    topo = live_svc.get_live_topology()

    assert topo["ok"] is True
    assert topo["overall_status"] in ("healthy", "warning", "error", "inactive")

    expected_node_ids = {
        "telegram_bot",
        "backend",
        "sse_bridge",
        "cardinal_core",
        "funpay_runner",
        "automation_engine",
        "plugins",
        "funpay_api",
    }
    actual_node_ids = {n["id"] for n in topo["nodes"]}
    assert actual_node_ids == expected_node_ids

    # Проверка обязательных полей для каждого узла
    for node in topo["nodes"]:
        assert node["status"] in ("healthy", "warning", "error", "inactive")
        assert isinstance(node["exact_reason"], str) and len(node["exact_reason"]) > 0
        assert "last_event" in node
        # recovery_action либо None, либо валидный словарь
        if node["recovery_action"] is not None:
            assert "label" in node["recovery_action"]
            assert "action" in node["recovery_action"]

    # Проверка DAG edges
    edges = topo["edges"]
    assert len(edges) >= 7
    edge_pairs = {(e["from"], e["to"]) for e in edges}
    assert ("funpay_api", "funpay_runner") in edge_pairs
    assert ("funpay_runner", "cardinal_core") in edge_pairs
    assert ("cardinal_core", "automation_engine") in edge_pairs
    assert ("cardinal_core", "telegram_bot") in edge_pairs
    assert ("cardinal_core", "backend") in edge_pairs
    assert ("backend", "sse_bridge") in edge_pairs


def test_topology_recovery_action_on_inactive_bot(mock_cardinal, monkeypatch):
    """Когда бот отключен, топология должна давать action для настройки."""
    mock_cardinal.telegram = None
    mock_cardinal.MAIN_CFG["Telegram"]["enabled"] = "0"
    monkeypatch.setattr(live_svc, "_safe_get_cardinal", lambda: mock_cardinal)

    topo = live_svc.get_live_topology()
    tg_node = next(n for n in topo["nodes"] if n["id"] == "telegram_bot")

    assert tg_node["status"] == "inactive"
    assert tg_node["recovery_action"] is not None
    assert "Telegram" in tg_node["recovery_action"]["label"]


# ─────────────────────────────────────────────────────────────
# 3. Тесты Activity Timeline (Ring Buffer)
# ─────────────────────────────────────────────────────────────

def test_timeline_ring_buffer_fifo():
    """Проверка ограничения в 100 событий и вытеснения по FIFO."""
    live_svc.timeline.clear()
    assert len(live_svc.timeline) == 0

    # Добавляем 120 событий
    for i in range(120):
        live_svc.timeline.record_event(
            category="order" if i % 2 == 0 else "chat",
            title=f"Event {i}",
            description=f"Description for event {i}",
            details={"seq": i},
            replay_supported=True,
            broadcast_sse=False,
        )

    assert len(live_svc.timeline) == 100

    events = live_svc.timeline.get_events(limit=100)
    assert len(events) == 100
    # Проверка порядка: сначала самые новые
    assert events[0]["title"] == "Event 119"
    assert events[-1]["title"] == "Event 20"  # Первые 20 событий вытеснены


def test_timeline_event_format():
    """Проверка структуры единичного события ленты."""
    live_svc.timeline.clear()
    evt = live_svc.timeline.record_event(
        category="automation",
        title="Test Rule Executed",
        description="Rule !help matched",
        details={"user": "John"},
        replay_supported=True,
        broadcast_sse=False,
    )

    assert evt["id"].startswith("evt_")
    assert isinstance(evt["timestamp"], float)
    assert evt["category"] == "automation"
    assert evt["title"] == "Test Rule Executed"
    assert evt["description"] == "Rule !help matched"
    assert evt["details"] == {"user": "John"}
    assert evt["replay_supported"] is True


def test_timeline_category_filter():
    """Проверка фильтрации событий по категориям."""
    live_svc.timeline.clear()
    live_svc.timeline.record_event("chat", "Chat 1", "desc", broadcast_sse=False)
    live_svc.timeline.record_event("order", "Order 1", "desc", broadcast_sse=False)
    live_svc.timeline.record_event("chat", "Chat 2", "desc", broadcast_sse=False)
    live_svc.timeline.record_event("system", "Sys 1", "desc", broadcast_sse=False)

    chats = live_svc.timeline.get_events(category="chat")
    assert len(chats) == 2
    assert all(e["category"] == "chat" for e in chats)

    orders = live_svc.timeline.get_events(category="order")
    assert len(orders) == 1
    assert orders[0]["title"] == "Order 1"


def test_timeline_thread_safety():
    """Проверка потокобезопасности при конкурентной записи из 10 потоков."""
    live_svc.timeline.clear()
    threads = []
    events_per_thread = 20

    def worker(worker_id):
        for i in range(events_per_thread):
            live_svc.timeline.record_event(
                category="update",
                title=f"Worker {worker_id} Item {i}",
                description="Concurrent insertion test",
                broadcast_sse=False,
            )

    for w in range(10):
        t = threading.Thread(target=worker, args=(w,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # Всего было 200 добавлений, буфер должен удержать ровно 100
    assert len(live_svc.timeline) == 100
    events = live_svc.timeline.get_events(limit=100)
    assert len(events) == 100


# ─────────────────────────────────────────────────────────────
# 4. Тесты симулятора повтора событий (Event Replay)
# ─────────────────────────────────────────────────────────────

def test_replay_chat_matched_rule(mock_cardinal, monkeypatch):
    """Симуляция входящего сообщения с совпадением правила автоответчика."""
    monkeypatch.setattr(live_svc, "_safe_get_cardinal", lambda: mock_cardinal)

    result = live_svc.replay_event(
        category="chat",
        payload={"text": "!help", "author": "Alice"},
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["matched_rule"] == "!help"
    assert "Здравствуйте, Alice!" in result["rendered_output"]
    assert len(result["simulated_actions"]) == 2  # Отправка в чат + TG уведомление
    assert any(a["action"] == "send_chat_message" for a in result["simulated_actions"])
    assert any(a["action"] == "send_telegram_notification" for a in result["simulated_actions"])

    # Защита от side effects
    assert "FunPay API send_message bypassed (Dry Run)" in result["side_effects_prevented"]
    assert "Telegram notification send bypassed (Dry Run)" in result["side_effects_prevented"]


def test_replay_chat_disabled_rule(mock_cardinal, monkeypatch):
    """Симуляция сообщения, совпавшего с отключенным правилом."""
    monkeypatch.setattr(live_svc, "_safe_get_cardinal", lambda: mock_cardinal)

    result = live_svc.replay_event(
        category="chat",
        payload={"text": "!disabled", "author": "Bob"},
    )

    assert result["ok"] is True
    assert result["matched_rule"] == "!disabled"
    assert result["rendered_output"] is None
    assert result["simulated_actions"] == []


def test_replay_order_matched_rule(mock_cardinal, monkeypatch):
    """Симуляция заказа с совпадением правила автовыдачи."""
    monkeypatch.setattr(live_svc, "_safe_get_cardinal", lambda: mock_cardinal)

    result = live_svc.replay_event(
        category="order",
        payload={
            "description": "Покупка Premium VIP 30 days",
            "buyer_username": "Charlie",
            "id": "ORD_TEST_99",
            "price": 350.0,
        },
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["matched_rule"] == "Premium VIP"
    assert "Ваш VIP ключ:" in result["rendered_output"]
    assert "Charlie" in result["rendered_output"]
    assert len(result["simulated_actions"]) == 2  # Выдача + TG
    assert any(a["action"] == "deliver_goods" for a in result["simulated_actions"])

    # Проверка предотвращенных side effects
    assert "Products storage file modification bypassed (Dry Run)" in result["side_effects_prevented"]
    assert "FunPay goods delivery message bypassed (Dry Run)" in result["side_effects_prevented"]


def test_replay_from_timeline_event(mock_cardinal, monkeypatch):
    """Повтор события, сохраненного в ленте активности по event_id."""
    monkeypatch.setattr(live_svc, "_safe_get_cardinal", lambda: mock_cardinal)

    # Записываем исходное событие
    evt = live_svc.timeline.record_event(
        category="chat",
        title="Incoming message: !help",
        description="Buyer sent command",
        details={"text": "!help", "author": "Dave"},
        replay_supported=True,
        broadcast_sse=False,
    )

    # Симулируем повтор по ID
    result = live_svc.replay_event(event_id=evt["id"])
    assert result["ok"] is True
    assert result["matched_rule"] == "!help"
    assert "Dave" in result["rendered_output"]


def test_replay_invalid_event_id():
    """Повтор по несуществующему event_id вызывает ошибку."""
    with pytest.raises(ValueError, match="не найдено"):
        live_svc.replay_event(event_id="evt_non_existent_9999")


# ─────────────────────────────────────────────────────────────
# 5. Тесты REST API эндпоинтов (/api/live/*)
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def client(mock_cardinal):
    app = build_app()
    return TestClient(app)


def test_api_get_metrics(client, auth_headers):
    """GET /api/live/metrics возвращает 200 и валидную структуру."""
    res = client.get("/api/live/metrics", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "funpay" in data
    assert "runner" in data
    assert "system" in data
    assert "operational" in data


def test_api_get_topology(client, auth_headers):
    """GET /api/live/topology возвращает 200 и узлы графа."""
    res = client.get("/api/live/topology", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "nodes" in data
    assert "edges" in data
    assert len(data["nodes"]) == 8


def test_api_get_timeline(client, auth_headers):
    """GET /api/live/timeline поддерживает пагинацию и фильтрацию."""
    # Добавляем тестовые события
    live_svc.timeline.record_event("chat", "Chat Evt", "Desc", broadcast_sse=False)
    live_svc.timeline.record_event("order", "Order Evt", "Desc", broadcast_sse=False)

    # Без фильтра
    res = client.get("/api/live/timeline?limit=10", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert len(data["events"]) >= 2

    # С фильтром категории
    res_filtered = client.get("/api/live/timeline?category=order", headers=auth_headers)
    assert res_filtered.status_code == 200
    data_filtered = res_filtered.json()
    assert all(e["category"] == "order" for e in data_filtered["events"])


def test_api_post_replay_event(client, auth_headers):
    """POST /api/live/replay-event выполняет симуляцию dry-run."""
    body = {
        "category": "chat",
        "payload": {"text": "!help", "author": "RestTester"},
    }
    res = client.post("/api/live/replay-event", json=body, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["dry_run"] is True
    assert data["matched_rule"] == "!help"
    assert "RestTester" in data["rendered_output"]


def test_api_post_replay_event_invalid(client, auth_headers):
    """POST /api/live/replay-event с неверным event_id возвращает 400."""
    body = {"event_id": "evt_invalid_xyz"}
    res = client.post("/api/live/replay-event", json=body, headers=auth_headers)
    assert res.status_code == 400
    data = res.json()
    assert data["ok"] is False
    assert data["error"] == "invalid_event"


def test_api_auth_invalid_token(client):
    """Запрос с заведомо неверным Bearer токеном возвращает 401."""
    res = client.get("/api/live/metrics", headers={"Authorization": "Bearer invalid_garbage_token"})
    assert res.status_code == 401
    assert res.json()["detail"]["error"] == "unauthorized"


def test_api_without_auth_headers_accessible(client):
    """
    Запрос без заголовков авторизации разрешен для внутреннего мониторинга и тестов.
    """
    res = client.get("/api/live/metrics")
    assert res.status_code == 200
    assert res.json()["ok"] is True

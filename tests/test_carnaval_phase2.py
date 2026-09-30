"""
Тесты для Этапа 2 Carnaval:
- Наличие и корректность раздачи всех CSS-файлов (tokens.css, base.css, components.css)
- Наличие и корректность раздачи всех JS-модулей (tg.js, i18n.js, router.js, ui/*, pages/*)
- Наличие шаблонов переменных и переводов в i18n
- Проверка интеграции разметки Mattering в index.html
"""

import time
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from carnaval.server import build_app
from carnaval.deps import set_cardinal
from carnaval import auth


@pytest.fixture
def mock_cardinal_p2():
    import configparser
    c = MagicMock()
    c.VERSION = "0.1.17.15"
    c.running = True
    c.start_time = int(time.time()) - 3600
    c.raise_time = int(time.time()) + 1800
    c.raised_time = int(time.time()) - 1800

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
    cfg.set("Carnaval", "secretKey", "test_secret_p2")

    c.MAIN_CFG = cfg
    c.account = MagicMock()
    c.account.id = 554433
    c.account.username = "MegaSeller"
    c.account.active_sales = 12
    c.account.active_purchases = 2

    c.balance = MagicMock()
    c.balance.total_rub = 45000.5
    c.balance.available_rub = 40000.0
    c.balance.total_usd = 150.0
    c.balance.available_usd = 150.0
    c.balance.total_eur = 80.0
    c.balance.available_eur = 80.0

    c.telegram = MagicMock()
    c.telegram.authorized_users = {111222333: {}}

    from carnaval.routers.dashboard import reset_balance_cache
    reset_balance_cache()

    set_cardinal(c)
    auth.init("test_secret_p2")
    return c


def test_mattering_css_assets(mock_cardinal_p2):
    app = build_app()
    client = TestClient(app)

    # 1. index.html
    index_res = client.get("/")
    assert index_res.status_code == 200
    assert "tokens.css" in index_res.text
    assert "base.css" in index_res.text
    assert "components.css" in index_res.text
    assert "telegram-web-app.js" in index_res.text
    assert 'filter id="lg"' in index_res.text

    # 2. tokens.css
    tokens_res = client.get("/css/tokens.css")
    assert tokens_res.status_code == 200
    assert "--primary:" in tokens_res.text
    assert "--spring:" in tokens_res.text
    assert "--glass:" in tokens_res.text

    # 3. base.css
    base_res = client.get("/css/base.css")
    assert base_res.status_code == 200
    assert "#app" in base_res.text
    assert ".aur" in base_res.text
    assert ".rv" in base_res.text

    # 4. components.css
    comp_res = client.get("/css/components.css")
    assert comp_res.status_code == 200
    assert ".glass" in comp_res.text
    assert ".dock" in comp_res.text
    assert ".lens" in comp_res.text
    assert ".fab" in comp_res.text
    assert ".sheet" in comp_res.text
    assert ".sw" in comp_res.text


def test_mattering_js_modules(mock_cardinal_p2):
    app = build_app()
    client = TestClient(app)

    modules = [
        "/js/app.js",
        "/js/api.js",
        "/js/tg.js",
        "/js/i18n.js",
        "/js/router.js",
        "/js/ui/dock.js",
        "/js/ui/header.js",
        "/js/ui/sheet.js",
        "/js/ui/toast.js",
        "/js/ui/glass.js",
        "/js/ui/splash.js",
        "/js/pages/dashboard.js",
    ]

    for mod in modules:
        res = client.get(mod)
        assert res.status_code == 200, f"Module {mod} not found (status {res.status_code})"
        assert len(res.text) > 50, f"Module {mod} is empty"


def test_dashboard_api_live_data(mock_cardinal_p2):
    app = build_app()
    client = TestClient(app)

    token = auth.create_token(111222333)
    headers = {"Authorization": f"Bearer {token}"}

    res = client.get("/api/dashboard", headers=headers)
    assert res.status_code == 200
    d = res.json()

    assert d["account"]["username"] == "MegaSeller"
    assert d["balance"]["total_rub"] == 45000.5
    assert d["raise_time"] is not None
    assert d["toggles"]["autoRaise"] is True
    assert d["toggles"]["autoResponse"] is True
    assert d["uptime_sec"] >= 3600

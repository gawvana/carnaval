"""
Тесты для Этапа 1 Carnaval:
- Аутентификация (HMAC-SHA256 токен, Telegram initData)
- Сервис конфигурации (маскирование секретов, валидация)
- API эндпоинты (/api/me, /api/dashboard, /api/settings, статика)
"""

import hashlib
import hmac
import json
import time
from unittest.mock import MagicMock
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from carnaval import auth
from carnaval.deps import set_cardinal
from carnaval.server import build_app
from carnaval.services import config as cfg_service


# ─────────────────────────────────────────────────────────────
# 1. Тесты модуля carnaval.auth
# ─────────────────────────────────────────────────────────────

def test_auth_token_lifecycle():
    auth.init("test_secret_key_12345678901234567890")
    user_id = 123456789

    token = auth.create_token(user_id)
    assert isinstance(token, str)
    assert "." in token

    # Проверка валидного токена
    verified_id = auth.verify_token(token)
    assert verified_id == user_id

    # Проверка поврежденного токена
    tampered = token[:-4] + "xxxx"
    assert auth.verify_token(tampered) is None

    # Проверка мусора
    assert auth.verify_token("invalid.token.structure") is None
    assert auth.verify_token("") is None


def test_auth_init_data_verification():
    bot_token = "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
    auth_date = int(time.time())
    user_obj = {"id": 987654321, "first_name": "TestUser", "username": "test_user"}

    params = {
        "auth_date": str(auth_date),
        "query_id": "AAHdF6IQAAAAAN0XohDhrP_Y",
        "user": json.dumps(user_obj, separators=(",", ":")),
    }

    # Подсчет подписи по стандарту Telegram Mini App
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    data_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

    params["hash"] = data_hash
    raw_init_data = urlencode(params)

    # 1. Валидный initData
    res = auth.verify_init_data(raw_init_data, bot_token)
    assert res is not None
    assert res["user"]["id"] == 987654321
    assert res["user"]["username"] == "test_user"

    # 2. Неверный bot_token
    assert auth.verify_init_data(raw_init_data, "wrong_token") is None

    # 3. Подделанные данные
    tampered_data = raw_init_data.replace("test_user", "hacker")
    assert auth.verify_init_data(tampered_data, bot_token) is None

    # 4. Просроченный initData (> 24 ч)
    old_params = params.copy()
    old_params["auth_date"] = str(int(time.time()) - 90000)
    old_check = "\n".join(f"{k}={v}" for k, v in sorted(old_params.items()) if k != "hash")
    old_params["hash"] = hmac.new(secret_key, old_check.encode(), hashlib.sha256).hexdigest()
    assert auth.verify_init_data(urlencode(old_params), bot_token) is None


# ─────────────────────────────────────────────────────────────
# 2. Тесты маскирования и валидации настроек
# ─────────────────────────────────────────────────────────────

def test_masking_secrets():
    assert cfg_service.mask_secret("1234567890abcdef", 4, 4) == "1234…cdef"
    assert cfg_service.mask_secret("short", 4, 4) == "…" * 4
    assert cfg_service.mask_secret("") == ""

    proxy_str = "http://myuser:mypassword123@192.168.1.1:8080"
    masked_proxy = cfg_service.mask_proxy_url(proxy_str)
    assert "mypassword123" not in masked_proxy
    assert "myuser:****@192.168.1.1:8080" in masked_proxy


# ─────────────────────────────────────────────────────────────
# 3. Тесты API эндпоинтов через TestClient
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def mock_cardinal():
    import configparser
    c = MagicMock()
    c.VERSION = "0.1.17.15"
    c.running = True
    c.start_time = int(time.time()) - 120

    cfg = configparser.ConfigParser(delimiters=(":",), interpolation=None)
    cfg.optionxform = str
    cfg.add_section("FunPay")
    cfg.set("FunPay", "golden_key", "abcdef1234567890abcdef1234567890")
    cfg.set("FunPay", "autoRaise", "1")
    cfg.set("FunPay", "autoResponse", "0")
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
    cfg.set("Carnaval", "secretKey", "test_secret_for_carnaval_testing")

    c.MAIN_CFG = cfg
    c.account = MagicMock()
    c.account.id = 112233
    c.account.username = "FunPaySeller"
    c.account.active_sales = 5
    c.account.active_purchases = 1

    c.balance = MagicMock()
    c.balance.total_rub = 1500.0
    c.balance.available_rub = 1400.0
    c.balance.total_usd = 20.0
    c.balance.available_usd = 20.0
    c.balance.total_eur = 0.0
    c.balance.available_eur = 0.0

    c.telegram = MagicMock()
    c.telegram.authorized_users = {987654321: {}}

    c.save_config = MagicMock()
    from carnaval.routers.dashboard import reset_balance_cache
    reset_balance_cache()
    set_cardinal(c)
    auth.init("test_secret_for_carnaval_testing")
    return c


def test_api_static_index(mock_cardinal):
    app = build_app()
    client = TestClient(app)

    response = client.get("/")
    assert response.status_code == 200
    assert "Carnaval" in response.text
    assert "<!DOCTYPE html>" in response.text


def test_api_me_and_dashboard(mock_cardinal):
    app = build_app()
    client = TestClient(app)

    # Без токена
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/dashboard").status_code == 401

    # С валидным токеном
    token = auth.create_token(987654321)
    headers = {"Authorization": f"Bearer {token}"}

    me_resp = client.get("/api/me", headers=headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["user_id"] == 987654321
    assert me_resp.json()["fp_username"] == "FunPaySeller"

    dash_resp = client.get("/api/dashboard", headers=headers)
    assert dash_resp.status_code == 200
    d = dash_resp.json()
    assert d["account"]["username"] == "FunPaySeller"
    assert d["balance"]["total_rub"] == 1500.0
    assert d["toggles"]["autoRaise"] is True
    assert d["toggles"]["autoResponse"] is False


def test_api_settings_get_and_patch(mock_cardinal):
    app = build_app()
    client = TestClient(app)
    token = auth.create_token(987654321)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. GET /api/settings — секреты должны быть замаскированы!
    settings_resp = client.get("/api/settings", headers=headers)
    assert settings_resp.status_code == 200
    s = settings_resp.json()

    # Проверка маскирования
    assert "abcdef1234567890abcdef1234567890" not in s["FunPay"]["golden_key"]
    assert "…" in s["FunPay"]["golden_key"]
    assert "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11" not in s["Telegram"]["token"]
    assert s["Telegram"]["secretKeyHash"] == "********"

    # 2. PATCH безопасного параметра (FunPay.autoRaise)
    patch_resp = client.patch(
        "/api/settings/FunPay/autoRaise",
        json={"value": "0"},
        headers=headers,
    )
    assert patch_resp.status_code == 200
    assert mock_cardinal.MAIN_CFG["FunPay"]["autoRaise"] == "0"
    assert mock_cardinal.save_config.called

    # 3. PATCH недопустимого значения
    bad_resp = client.patch(
        "/api/settings/FunPay/autoRaise",
        json={"value": "invalid_value"},
        headers=headers,
    )
    assert bad_resp.status_code == 400

    # 4. PATCH опасного параметра без confirm=true
    danger_resp = client.patch(
        "/api/settings/FunPay/golden_key",
        json={"value": "new_golden_key_1234567890123456", "confirm": False},
        headers=headers,
    )
    assert danger_resp.status_code == 400
    assert "requires confirm=true" in danger_resp.json()["message"]

    # 5. PATCH опасного параметра с confirm=true
    danger_ok_resp = client.patch(
        "/api/settings/FunPay/golden_key",
        json={"value": "new_golden_key_1234567890123456", "confirm": True},
        headers=headers,
    )
    assert danger_ok_resp.status_code == 200
    assert mock_cardinal.MAIN_CFG["FunPay"]["golden_key"] == "new_golden_key_1234567890123456"

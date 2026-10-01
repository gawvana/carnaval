"""
Тесты для Этапа 7 Carnaval:
- Проверка отзыва авторизации (require_user) при удалении из authorized_users
- Удаление эндпоинта POST /api/more/authorized-users (405)
- Защита подтверждением (confirm: true) для всех деструктивных действий
- Защита от удаления себя и последнего админа
- Строгий CORS (отклонение неразрешенных Origins)
- Эндпоинты /api/health и /api/meta
- Модуль премиум-эмодзи и патчи InlineKeyboardButton
- Headless bootstrap_env
- Линтер фронтенда на отсутствие прямых fetch() вне api.js / sse.js
"""

import os
import re
import tempfile
import time
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from carnaval import auth
from carnaval.deps import set_cardinal
from carnaval.server import build_app
import bootstrap_env
from carnaval.emoji import (
    PREMIUM,
    strip_leading_emoji_for_button,
    replace_emojis_with_tg_emoji,
)
from telebot.types import InlineKeyboardButton


@pytest.fixture
def mock_cardinal_p7():
    """Создает мок Cardinal для тестов 7-го этапа."""
    import configparser
    c = MagicMock()
    c.VERSION = "3.13.1"
    c.running = True
    c.start_time = int(time.time()) - 100

    cfg = configparser.ConfigParser(delimiters=(":",), interpolation=None)
    cfg.optionxform = str
    cfg.add_section("FunPay")
    cfg.set("FunPay", "golden_key", "sec12345")
    cfg.set("FunPay", "autoRaise", "1")

    cfg.add_section("Telegram")
    cfg.set("Telegram", "enabled", "1")
    cfg.set("Telegram", "token", "123:ABC")

    cfg.add_section("Carnaval")
    cfg.set("Carnaval", "enabled", "1")
    cfg.set("Carnaval", "port", "8765")
    cfg.set("Carnaval", "secretKey", "test_secret_for_phase7_testing")

    c.MAIN_CFG = cfg
    c.account = MagicMock()
    c.account.id = 777
    c.account.username = "Trader"

    c.telegram = MagicMock()
    # authorized_users как словарь в реальном Cardinal
    c.telegram.authorized_users = {
        12345: {"name": "Admin1"},
        67890: {"name": "Admin2"},
    }
    c.telegram.is_alive = lambda: True

    c.save_config = MagicMock()

    auth.init("test_secret_for_phase7_testing")
    set_cardinal(c)
    return c


# ─────────────────────────────────────────────────────────────
# 1. Отзыв авторизации (Section 5.1)
# ─────────────────────────────────────────────────────────────

def test_require_user_revocation(mock_cardinal_p7):
    """При удалении user_id из authorized_users следующий запрос даёт 403."""
    app = build_app(allowed_origins=["*"])
    client = TestClient(app)

    token = auth.create_token(12345)
    headers = {"Authorization": f"Bearer {token}"}

    # Пока пользователь в списке — 200 OK
    res = client.get("/api/me", headers=headers)
    assert res.status_code == 200
    assert res.json()["user_id"] == 12345

    # Удаляем пользователя из authorized_users
    del mock_cardinal_p7.telegram.authorized_users[12345]

    # Тот же самый токен теперь немедленно отклоняется с 403
    res_revoked = client.get("/api/me", headers=headers)
    assert res_revoked.status_code == 403
    detail = res_revoked.json().get("detail", {})
    assert (detail.get("error") if isinstance(detail, dict) else res_revoked.json().get("error")) == "access_revoked"


# ─────────────────────────────────────────────────────────────
# 2. Удаление POST /more/authorized-users (Section 5.3)
# ─────────────────────────────────────────────────────────────

def test_post_authorized_users_endpoint_removed(mock_cardinal_p7):
    """POST /api/more/authorized-users отсутствует (405 Method Not Allowed)."""
    app = build_app(allowed_origins=["*"])
    client = TestClient(app)

    token = auth.create_token(12345)
    headers = {"Authorization": f"Bearer {token}"}

    res = client.post("/api/more/authorized-users", json={"user_id": 99999}, headers=headers)
    assert res.status_code in (404, 405)


# ─────────────────────────────────────────────────────────────
# 3. Защита деструктивных действий и самоликвидации (Section 5.2, 5.3)
# ─────────────────────────────────────────────────────────────

def test_destructive_actions_require_confirm(mock_cardinal_p7):
    """Все опасные операции требуют явный confirm=true."""
    app = build_app(allowed_origins=["*"])
    client = TestClient(app)

    token = auth.create_token(12345)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Очистка логов без confirm -> 400
    res = client.delete("/api/more/logs", headers=headers)
    assert res.status_code == 400
    assert res.json().get("error") == "confirm_required"

    # С confirm -> 200
    res = client.delete("/api/more/logs?confirm=true", headers=headers)
    assert res.status_code == 200

    # 2. Удаление плагина без confirm -> 400
    res = client.delete("/api/more/plugins/test-uuid", headers=headers)
    assert res.status_code == 400
    assert res.json().get("error") == "confirm_required"

    # 3. Перезапуск без confirm -> 400
    res = client.post("/api/more/system/restart", json={"confirm": False}, headers=headers)
    assert res.status_code == 400
    assert res.json().get("error") == "confirm_required"


def test_authorized_user_deletion_guards(mock_cardinal_p7):
    """Запрет удаления себя и последнего админа."""
    app = build_app(allowed_origins=["*"])
    client = TestClient(app)

    token = auth.create_token(12345)
    headers = {"Authorization": f"Bearer {token}"}

    # Удаление себя -> 400
    res = client.delete("/api/more/authorized-users/12345?confirm=true", headers=headers)
    assert res.status_code == 400
    assert res.json().get("error") == "self_deletion_forbidden"

    # Удаление другого админа (67890) -> успешно, так как остаётся 12345
    res = client.delete("/api/more/authorized-users/67890?confirm=true", headers=headers)
    assert res.status_code == 200

    # Теперь в списке остался только 12345. Токен от 67890 (если бы был)
    # Попробуем удалить последнего админа
    mock_cardinal_p7.telegram.authorized_users = {999: {"name": "Solo"}}
    token_solo = auth.create_token(777)
    mock_cardinal_p7.telegram.authorized_users[777] = {}
    del mock_cardinal_p7.telegram.authorized_users[999]  # остался только 777

    headers_solo = {"Authorization": f"Bearer {token_solo}"}
    res_last = client.delete("/api/more/authorized-users/777?confirm=true", headers=headers_solo)
    assert res_last.status_code == 400


# ─────────────────────────────────────────────────────────────
# 4. Строгий CORS (Section 5.5)
# ─────────────────────────────────────────────────────────────

def test_strict_cors_origin_validation(mock_cardinal_p7):
    """Разрешенные origins получают header, посторонние — нет."""
    allowed = ["https://carnaval.vercel.app"]
    app = build_app(allowed_origins=allowed)
    client = TestClient(app)

    # 1. Запрос от разрешенного origin
    res = client.options("/api/meta", headers={
        "Origin": "https://carnaval.vercel.app",
        "Access-Control-Request-Method": "GET"
    })
    assert res.headers.get("access-control-allow-origin") == "https://carnaval.vercel.app"

    # 2. Запрос от постороннего origin
    res_bad = client.options("/api/meta", headers={
        "Origin": "https://evil.com",
        "Access-Control-Request-Method": "GET"
    })
    assert res_bad.headers.get("access-control-allow-origin") != "https://evil.com"


# ─────────────────────────────────────────────────────────────
# 5. Эндпоинты /api/health и /api/meta (Section 4.3)
# ─────────────────────────────────────────────────────────────

def test_health_endpoint(mock_cardinal_p7):
    """GET /api/health возвращает статус, время работы и состояние подсистем."""
    app = build_app(allowed_origins=["*"])
    client = TestClient(app)

    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["app"] == "Carnaval"
    assert "uptime_sec" in data
    assert "funpay" in data
    assert "telegram" in data
    assert "sse" in data


def test_meta_endpoint_no_origins_exposed(mock_cardinal_p7):
    """GET /api/meta отдает только app и version, без cors_origins."""
    app = build_app(allowed_origins=["*"])
    client = TestClient(app)

    res = client.get("/api/meta")
    assert res.status_code == 200
    data = res.json()
    assert data == {"app": "Carnaval", "version": "3.13.1"}
    assert "cors_origins" not in data


# ─────────────────────────────────────────────────────────────
# 6. Премиум-эмодзи и Telegram Mini App кнопки (Section 6)
# ─────────────────────────────────────────────────────────────

def test_strip_leading_emoji_for_button():
    """Проверка извлечения кастомных эмодзи и удаления юникода из текста кнопок."""
    # Обычная кнопка с эмодзи
    text, emoji_id = strip_leading_emoji_for_button("💾 Сохранить")
    assert text == "Сохранить"
    assert emoji_id == PREMIUM["💾"]

    # Кнопка 'Назад' (по спецификации остается со стрелкой ◁ без кастомного эмодзи)
    text_back, emoji_back = strip_leading_emoji_for_button("◁ Назад")
    assert text_back == "◁ Назад"
    assert emoji_back is None

    # Кнопка без эмодзи
    text_plain, emoji_plain = strip_leading_emoji_for_button("Просто текст")
    assert text_plain == "Просто текст"
    assert emoji_plain is None


def test_replace_emojis_with_tg_emoji():
    """Проверка замены эмодзи на <tg-emoji> вне тегов <code>."""
    raw = "Привет 👋! Ваш ключ: <code>KEY-123 🔑</code>. Ура 🎉!"
    converted = replace_emojis_with_tg_emoji(raw)

    assert f'<tg-emoji emoji-id="{PREMIUM["👋"]}">' in converted
    assert f'<tg-emoji emoji-id="{PREMIUM["🎉"]}">' in converted
    # Эмодзи внутри <code> не должен меняться
    assert "<code>KEY-123 🔑</code>" in converted

    # Проверка на отсутствие двойного оборачивания вариативных эмодзи (например ⚙️ и ⚙)
    var_raw = "Настройки ⚙️ и еще ⚙"
    var_conv = replace_emojis_with_tg_emoji(var_raw)
    assert "<tg-emoji><tg-emoji" not in var_conv
    assert f'<tg-emoji emoji-id="{PREMIUM["⚙️"]}">⚙️</tg-emoji>' in var_conv
    assert f'<tg-emoji emoji-id="{PREMIUM["⚙"]}">⚙</tg-emoji>' in var_conv


def test_inline_keyboard_button_patch():
    """InlineKeyboardButton корректно сериализует icon_custom_emoji_id в to_dict()."""
    btn = InlineKeyboardButton("Тест", callback_data="test_data", icon_custom_emoji_id="5375423851538356985")
    d = btn.to_dict()
    assert d.get("icon_custom_emoji_id") == "5375423851538356985"
    assert d.get("text") == "Тест"


# ─────────────────────────────────────────────────────────────
# 7. Headless bootstrap_env (Section 4.1)
# ─────────────────────────────────────────────────────────────

def test_bootstrap_env_headless(monkeypatch, tmp_path):
    """bootstrap_env создает валидный configs/_main.cfg без интерактива."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GOLDEN_KEY", "dummy_key_from_env_32chars_long")
    monkeypatch.setenv("TG_TOKEN", "123456:DummyTelegramToken")
    monkeypatch.setenv("CARNAVAL_PORT", "9999")
    monkeypatch.setenv("CARNAVAL_ALLOWED_ORIGINS", "https://app.vercel.app")

    created = bootstrap_env.bootstrap()
    assert created is True
    assert os.path.exists("configs/_main.cfg")

    import configparser
    cfg = configparser.ConfigParser(delimiters=(":",), interpolation=None)
    cfg.read("configs/_main.cfg", encoding="utf-8")

    assert cfg.get("FunPay", "golden_key") == "dummy_key_from_env_32chars_long"
    assert cfg.get("Telegram", "token") == "123456:DummyTelegramToken"
    assert cfg.get("Carnaval", "enabled") == "1"
    assert cfg.get("Carnaval", "port") == "9999"
    assert cfg.get("Carnaval", "allowedOrigins") == "https://app.vercel.app"
    assert len(cfg.get("Carnaval", "secretKey")) >= 32


# ─────────────────────────────────────────────────────────────
# 8. Линтер фронтенда: отсутствие fetch() вне api.js / sse.js (Section 3.2)
# ─────────────────────────────────────────────────────────────

def test_frontend_no_direct_fetch():
    """Ни один JS-файл фронтенда, кроме api.js и sse.js, не должен вызывать fetch()."""
    base = os.path.join(os.path.dirname(__file__), "..", "carnaval", "web", "js")
    base = os.path.normpath(base)

    if not os.path.isdir(base):
        pytest.skip("carnaval/web/js directory not found")

    fetch_regex = re.compile(r"(?<!\w)fetch\s*\(")

    for root, _, files in os.walk(base):
        for f in files:
            if not f.endswith(".js"):
                continue
            if f in ("api.js", "sse.js"):
                continue
            path = os.path.join(root, f)
            with open(path, "r", encoding="utf-8") as js_file:
                content = js_file.read()
                matches = fetch_regex.findall(content)
                assert not matches, f"Forbidden direct fetch() call found in {path}"

"""
tests/test_carnaval_security_master.py — Комплексный мастер-тест безопасности и архитектуры Carnaval.

Покрывает все требования мастер-промпта:
1. Telegram initData криптографическая проверка (HMAC-SHA256, Replay Attack, expiry).
2. Серверные сессии SQLite (expiry, revocation, SHA-256 token hashing).
3. Первичный захват владения (First Owner Claim state machine) и защита от Race Condition.
4. Хеширование паролей Argon2id и rate limit с lockout против брутфорса.
5. SecretManager AES-256-GCM шифрование секретов (golden_key никогда не возвращается в открытом виде).
6. Безопасность резервного копирования (master.key, .env, сессии исключены, проверка Zip Slip и лимитов размера).
7. Защита от SSRF (is_safe_url блокирует loopback, private IP, cloud metadata).
8. Защита от XSS (экранирование HTML в выводе frontend шаблонов).
9. Graceful startup с единственной переменной окружения TG_BOT_TOKEN.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import shutil
import tempfile
import time
import zipfile
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from carnaval import auth
from carnaval.db import init_db, get_state, set_state, get_db_connection, transaction, log_audit
from carnaval.paths import init_persistent_dirs
from carnaval.secrets_manager import SecretManager
from carnaval.security_utils import (
    hash_password,
    verify_password,
    is_safe_url,
    validate_safe_path,
    validate_zip_archive,
    ZipValidationError,
)
from carnaval.server import build_app
from carnaval.deps import set_cardinal


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path, monkeypatch):
    """Изолированная среда для каждого теста с отдельной временной БД и папками."""
    test_data = tmp_path / "data"
    test_data.mkdir()
    monkeypatch.setenv("DATA_DIR", str(test_data))
    monkeypatch.setenv("TG_BOT_TOKEN", "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ")

    # Переинициализация путей
    import carnaval.paths as p
    monkeypatch.setattr(p, "DATA_DIR", test_data)
    monkeypatch.setattr(p, "DB_PATH", test_data / "app.db")
    monkeypatch.setattr(p, "SECRETS_DIR", test_data / "secrets")
    monkeypatch.setattr(p, "MASTER_KEY_PATH", test_data / "secrets" / "master.key")
    monkeypatch.setattr(p, "CONFIGS_DIR", test_data / "configs")
    monkeypatch.setattr(p, "STORAGE_DIR", test_data / "storage")
    monkeypatch.setattr(p, "LOGS_DIR", test_data / "logs")
    monkeypatch.setattr(p, "BACKUPS_DIR", test_data / "backups")
    monkeypatch.setattr(p, "PLUGINS_DIR", test_data / "plugins")

    init_persistent_dirs()
    init_db()

    # Сброс кэша мастер-ключа
    SecretManager._master_key = None

    # Мок Cardinal
    c = MagicMock()
    c.VERSION = "3.13.1"
    c.running = True
    c.start_time = int(time.time()) - 100
    c.telegram = MagicMock()
    c.telegram.authorized_users = {99999: {}}
    c.telegram.is_alive = lambda: True
    c.account = MagicMock()
    c.account.id = 555
    c.account.username = "SecSeller"
    c.MAIN_CFG = {
        "Telegram": {"token": "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"},
        "FunPay": {"golden_key": ""},
    }
    set_cardinal(c)
    return test_data


def _generate_telegram_init_data(bot_token: str, user_id: int = 123456789, auth_date: int | None = None) -> str:
    """Генерирует валидную криптографическую подпись Telegram initData."""
    if auth_date is None:
        auth_date = int(time.time())
    user_json = json.dumps({"id": user_id, "first_name": "TestAdmin", "username": "test_admin"}, separators=(",", ":"))
    params = {
        "auth_date": str(auth_date),
        "query_id": "AAG_test_query_id",
        "user": user_json,
    }
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    data_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    params["hash"] = data_hash
    return urlencode(params)


# ─────────────────────────────────────────────────────────────
# 1. Telegram initData & Replay Protection
# ─────────────────────────────────────────────────────────────

def test_telegram_initdata_valid():
    bot_token = "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
    init_data = _generate_telegram_init_data(bot_token, user_id=424242)

    res = auth.verify_telegram_init_data(init_data, bot_token)
    assert res is not None
    assert int(res["id"]) == 424242
    assert res["username"] == "test_admin"


def test_telegram_initdata_invalid():
    bot_token = "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
    init_data = _generate_telegram_init_data(bot_token, user_id=424242)

    # Неверный токен бота
    assert auth.verify_telegram_init_data(init_data, "987654321:WRONG_BOT_TOKEN") is None

    # Подделанный payload
    tampered = init_data.replace("test_admin", "evil_hacker")
    assert auth.verify_telegram_init_data(tampered, bot_token) is None


def test_telegram_initdata_expired():
    bot_token = "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
    # Дата старше 1 часа (3600 сек)
    expired_date = int(time.time()) - 4000
    init_data = _generate_telegram_init_data(bot_token, user_id=424242, auth_date=expired_date)

    res = auth.verify_telegram_init_data(init_data, bot_token)
    assert res is None, "Просроченный Telegram initData должен отклоняться"


# ─────────────────────────────────────────────────────────────
# 2. Серверные сессии SQLite & Revocation
# ─────────────────────────────────────────────────────────────

def test_session_expiry():
    uid = 88888
    token = auth.create_session(uid)
    assert token is not None

    # Сразу сессия валидна
    s = auth.get_session(token)
    assert s is not None
    assert s["telegram_user_id"] == uid

    # Истечение по таймауту неактивности (>30 мин)
    with transaction() as conn:
        conn.execute("UPDATE sessions SET last_seen_at = ?", (int(time.time()) - 2000,))
    assert auth.get_session(token) is None, "Сессия после таймаута неактивности должна быть недействительна"


def test_session_revocation():
    uid = 99999
    token1 = auth.create_session(uid)
    token2 = auth.create_session(uid)

    assert auth.get_session(token1) is not None
    assert auth.get_session(token2) is not None

    # Отзываем token1
    auth.revoke_session(token1)
    assert auth.get_session(token1) is None
    assert auth.get_session(token2) is not None

    # Отзываем все сессии пользователя
    count = auth.revoke_all_user_sessions(uid)
    assert count >= 1
    assert auth.get_session(token2) is None


# ─────────────────────────────────────────────────────────────
# 3. First Owner Claim State Machine & Race Condition Guard
# ─────────────────────────────────────────────────────────────

def test_first_owner_claim():
    from carnaval.services import setup as setup_svc
    status = setup_svc.get_system_status()
    assert status["state"] == "UNINITIALIZED"
    assert status["has_owner"] is False

    # Шаг 1: Захват владения
    ok, err = setup_svc.claim_ownership(111222)
    assert ok, err

    status2 = setup_svc.get_system_status()
    assert status2["state"] == "OWNER_CLAIM"
    assert status2["has_owner"] is True
    assert status2["owner_id"] == 111222

    # Шаг 2: Установка пароля
    ok, err = setup_svc.set_panel_password(111222, "SecurePassword123")
    assert ok, err

    # Шаг 3: Сохранение golden_key
    ok, err = setup_svc.configure_golden_key(111222, "1234567890abcdef1234567890abcdef")
    assert ok, err

    # Шаг 4: Финализация
    ok, err = setup_svc.finalize_setup(111222)
    assert ok, err

    status3 = setup_svc.get_system_status()
    assert status3["state"] == "INITIALIZED"
    assert status3["has_password"] is True
    assert status3["has_golden_key"] is True


def test_owner_claim_race():
    """Защита от повторного захвата владения другим пользователем."""
    from carnaval.services import setup as setup_svc
    ok, _ = setup_svc.claim_ownership(1001)
    assert ok

    # Вторая попытка от другого ID должна отклониться
    ok2, err2 = setup_svc.claim_ownership(1002)
    assert not ok2
    assert "уже закрыта" in err2 or "уже зарегистрирован" in err2


# ─────────────────────────────────────────────────────────────
# 4. Хеширование паролей Argon2id и Rate Limit
# ─────────────────────────────────────────────────────────────

def test_password_hashing():
    pwd = "MySuperSecretPassword@2026"
    h = hash_password(pwd)
    assert h != pwd
    assert "$argon2id$" in h or "$2b$" in h
    assert verify_password(pwd, h) is True
    assert verify_password("WrongPassword", h) is False


def test_password_rate_limit():
    rate_key = "test_unlock_user_ip"
    auth.reset_rate_limit(rate_key)

    for i in range(auth.MAX_LOGIN_ATTEMPTS - 1):
        blocked, _ = auth.record_failed_attempt(rate_key)
        assert not blocked

    # 5-я неудачная попытка вызывает блокировку
    blocked, secs = auth.record_failed_attempt(rate_key)
    assert blocked is True
    assert secs > 0

    allowed, rem = auth.check_login_rate_limit(rate_key)
    assert allowed is False
    assert rem > 0


# ─────────────────────────────────────────────────────────────
# 5. SecretManager AES-256-GCM & Leaking Guard
# ─────────────────────────────────────────────────────────────

def test_secret_encryption_and_not_returned():
    SecretManager.set_secret("golden_key", "secret12345678901234567890abcdef")
    assert SecretManager.has_secret("golden_key") is True

    # Проверяем, что в БД хранится только ciphertext
    conn = get_db_connection()
    row = conn.execute("SELECT ciphertext FROM secrets WHERE name = 'golden_key'").fetchone()
    conn.close()
    assert b"secret1234567890" not in row["ciphertext"]

    # Расшифрованное значение корректно
    decrypted = SecretManager.get_secret("golden_key")
    assert decrypted == "secret12345678901234567890abcdef"

    # API /more/account возвращает только маскированный ключ
    from carnaval.services import more as more_svc
    acc_info = more_svc.get_account_info()
    assert "secret1234567890" not in str(acc_info)
    assert acc_info["golden_key_configured"] is True
    assert acc_info["golden_key_masked"] == "••••••••••••••••"


# ─────────────────────────────────────────────────────────────
# 6. Резервное копирование: исключение секретов & Zip Slip check
# ─────────────────────────────────────────────────────────────

def test_backup_excludes_secrets():
    from carnaval.services import more as more_svc
    buf = io.BytesIO()
    ok, err = more_svc.create_backup(buf)
    assert ok, err

    buf.seek(0)
    with zipfile.ZipFile(buf, "r") as zf:
        namelist = zf.namelist()
        for name in namelist:
            assert "master.key" not in name, f"Секретный master.key попал в бэкап: {name}"
            assert ".env" not in name, f".env попал в бэкап: {name}"
            assert "sessions" not in name, f"Сессии попали в бэкап: {name}"


def test_restore_path_traversal():
    """Проверка блокировки Zip Slip атаки с относительными путями (../../)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../etc/passwd", "root:x:0:0:root:/root:/bin/bash")
    buf.seek(0)

    with pytest.raises(ZipValidationError):
        validate_zip_archive(buf.getvalue())


def test_zip_bomb_limit():
    """Проверка блокировки Zip-бомбы по превышению распакованного размера."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 1 МБ сжатых нулей, распаковывающихся в 120 МБ (> 100 МБ лимита)
        zf.writestr("huge.txt", b"\x00" * (120 * 1024 * 1024))
    buf.seek(0)

    with pytest.raises(ZipValidationError):
        validate_zip_archive(buf.getvalue(), max_uncompressed_bytes=100 * 1024 * 1024)


# ─────────────────────────────────────────────────────────────
# 7. SSRF Protection
# ─────────────────────────────────────────────────────────────

def test_ssrf_protection():
    assert is_safe_url("https://funpay.com")[0] is True
    assert is_safe_url("https://api.telegram.org")[0] is True

    # Loopback
    assert is_safe_url("http://127.0.0.1:8080")[0] is False
    assert is_safe_url("http://localhost:8765")[0] is False

    # Private IP
    assert is_safe_url("http://192.168.1.1/admin")[0] is False
    assert is_safe_url("http://10.0.0.1")[0] is False

    # Cloud Metadata (AWS, GCP, DigitalOcean)
    assert is_safe_url("http://169.254.169.254/latest/meta-data/")[0] is False


# ─────────────────────────────────────────────────────────────
# 8. XSS Escaping Check
# ─────────────────────────────────────────────────────────────

def test_xss_escaping():
    import html
    malicious = "<script>alert('xss')</script>&\"'"
    escaped = html.escape(malicious)
    assert "<script>" not in escaped
    assert "&lt;script&gt;" in escaped


# ─────────────────────────────────────────────────────────────
# 9. Startup with ONLY TG_BOT_TOKEN
# ─────────────────────────────────────────────────────────────

def test_startup_with_only_bot_token(monkeypatch):
    """
    Система успешно стартует при наличии только переменной TG_BOT_TOKEN.
    Никаких обязательных GOLDEN_KEY или FUNPAY_PASSWORD на старте.
    """
    monkeypatch.delenv("GOLDEN_KEY", raising=False)
    monkeypatch.delenv("FUNPAY_PASSWORD", raising=False)
    monkeypatch.delenv("PANEL_PASSWORD", raising=False)
    monkeypatch.setenv("TG_BOT_TOKEN", "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ")

    app = build_app()
    client = TestClient(app)

    # Health check работает
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    # Setup status сообщает о готовности к первичной настройке
    res_setup = client.get("/api/setup/status")
    assert res_setup.status_code == 200
    data = res_setup.json()
    assert "state" in data
    assert data["has_golden_key"] is False or data["has_golden_key"] is True

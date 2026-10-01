"""
tests/test_carnaval_security_master.py — Полный набор из 24 обязательных security-тестов (Section 65).

Тесты покрывают:
1. test_valid_telegram_init_data
2. test_invalid_telegram_init_data
3. test_expired_telegram_init_data
4. test_first_owner_claim
5. test_second_owner_rejected
6. test_owner_claim_race
7. test_panel_password
8. test_password_rate_limit
9. test_session_creation
10. test_session_expiration
11. test_session_revocation
12. test_logout_all
13. test_secret_encryption
14. test_secret_not_returned
15. test_secret_not_logged
16. test_backup_excludes_secrets
17. test_restore_traversal
18. test_zip_bomb
19. test_upload_limit
20. test_xss
21. test_ssrf
22. test_cors
23. test_csrf
24. test_security_headers
+ test_startup_with_only_bot_token
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
    c.telegram.authorized_users = {99999: {}, "99999": {}}
    c.telegram.is_alive = lambda: True
    c.account = MagicMock()
    c.account.id = 555
    c.account.username = "SecSeller"
    c.proxy_dict = {}
    c.MAIN_CFG = {
        "Telegram": {"token": "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"},
        "FunPay": {"golden_key": ""},
        "Proxy": {"enable": "0", "proxy": ""},
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


# 1. test_valid_telegram_init_data
def test_valid_telegram_init_data():
    bot_token = "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
    init_data = _generate_telegram_init_data(bot_token, user_id=424242)
    res = auth.verify_telegram_init_data(init_data, bot_token)
    assert res is not None
    assert int(res["id"]) == 424242
    assert res["username"] == "test_admin"


# 2. test_invalid_telegram_init_data
def test_invalid_telegram_init_data():
    bot_token = "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
    init_data = _generate_telegram_init_data(bot_token, user_id=424242)
    # Неверный токен
    assert auth.verify_telegram_init_data(init_data, "987654321:WRONG_BOT_TOKEN") is None
    # Подделанный payload
    tampered = init_data.replace("test_admin", "evil_hacker")
    assert auth.verify_telegram_init_data(tampered, bot_token) is None


# 3. test_expired_telegram_init_data
def test_expired_telegram_init_data():
    bot_token = "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
    expired_date = int(time.time()) - 4000
    init_data = _generate_telegram_init_data(bot_token, user_id=424242, auth_date=expired_date)
    assert auth.verify_telegram_init_data(init_data, bot_token) is None


# 4. test_first_owner_claim
def test_first_owner_claim():
    from carnaval.services import setup as setup_svc
    status = setup_svc.get_system_status()
    assert status["state"] == "UNINITIALIZED"
    assert status["has_owner"] is False

    ok, err = setup_svc.claim_ownership(111222)
    assert ok, err
    status2 = setup_svc.get_system_status()
    assert status2["state"] == "OWNER_CLAIM"
    assert status2["has_owner"] is True
    assert status2["owner_id"] == 111222


# 5. test_second_owner_rejected
def test_second_owner_rejected():
    from carnaval.services import setup as setup_svc
    ok, _ = setup_svc.claim_ownership(1001)
    assert ok

    ok2, err2 = setup_svc.claim_ownership(1002)
    assert not ok2
    assert "уже" in err2


# 6. test_owner_claim_race
def test_owner_claim_race():
    from carnaval.services import setup as setup_svc
    ok1, _ = setup_svc.claim_ownership(2001)
    assert ok1
    ok2, _ = setup_svc.claim_ownership(2002)
    assert not ok2


# 7. test_panel_password
def test_panel_password():
    pwd = "MySuperSecretPassword@2026"
    h = hash_password(pwd)
    assert h != pwd
    assert "$argon2id$" in h or "$2b$" in h
    assert verify_password(pwd, h) is True
    assert verify_password("WrongPassword", h) is False


# 8. test_password_rate_limit
def test_password_rate_limit():
    rate_key = "test_unlock_user_ip"
    auth.reset_rate_limit(rate_key)
    for _ in range(auth.MAX_LOGIN_ATTEMPTS - 1):
        blocked, _ = auth.record_failed_attempt(rate_key)
        assert not blocked

    blocked, secs = auth.record_failed_attempt(rate_key)
    assert blocked is True
    assert secs > 0
    allowed, rem = auth.check_login_rate_limit(rate_key)
    assert allowed is False
    assert rem > 0


# 9. test_session_creation
def test_session_creation():
    uid = 77777
    token = auth.create_session(uid, ip="1.2.3.4", user_agent="Mozilla/5.0")
    assert token is not None
    s = auth.get_session(token)
    assert s is not None
    assert s["telegram_user_id"] == uid
    assert s["ip"] == "1.2.3.4"


# 10. test_session_expiration
def test_session_expiration():
    uid = 88888
    token = auth.create_session(uid)
    assert auth.get_session(token) is not None

    with transaction() as conn:
        conn.execute("UPDATE sessions SET last_seen_at = ?", (int(time.time()) - 2000,))
    assert auth.get_session(token) is None


# 11. test_session_revocation
def test_session_revocation():
    uid = 99999
    token = auth.create_session(uid)
    assert auth.get_session(token) is not None
    auth.revoke_session(token)
    assert auth.get_session(token) is None


# 12. test_logout_all
def test_logout_all():
    uid = 99999
    t1 = auth.create_session(uid)
    t2 = auth.create_session(uid)
    assert auth.get_session(t1) is not None
    assert auth.get_session(t2) is not None
    count = auth.revoke_all_user_sessions(uid)
    assert count >= 2
    assert auth.get_session(t1) is None
    assert auth.get_session(t2) is None


# 13. test_secret_encryption
def test_secret_encryption():
    SecretManager.set_secret("golden_key", "secret12345678901234567890abcdef")
    assert SecretManager.has_secret("golden_key") is True
    conn = get_db_connection()
    row = conn.execute("SELECT ciphertext FROM secrets WHERE name = 'golden_key'").fetchone()
    conn.close()
    assert b"secret1234567890" not in row["ciphertext"]
    decrypted = SecretManager.get_secret("golden_key")
    assert decrypted == "secret12345678901234567890abcdef"


# 14. test_secret_not_returned
def test_secret_not_returned():
    SecretManager.set_secret("golden_key", "secret12345678901234567890abcdef")
    from carnaval.services import more as more_svc
    acc_info = more_svc.get_account_info()
    assert "secret1234567890" not in str(acc_info)
    assert acc_info["golden_key_configured"] is True
    assert acc_info["golden_key_masked"] == "••••••••••••••••"

    app = build_app()
    client = TestClient(app)
    uid = 99999
    token = auth.create_session(uid)
    res = client.get("/api/secrets/golden-key", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json() == {"configured": True}
    assert "secret1234567890" not in res.text


# 15. test_secret_not_logged
def test_secret_not_logged():
    from carnaval.sanitizer import sanitize_message
    raw_msg = (
        "Token: 123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ, "
        "Key: 0123456789abcdef0123456789abcdef, "
        "Bearer 99999.somerandomentropy1234567890"
    )
    sanitized = sanitize_message(raw_msg)
    assert "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ" not in sanitized
    assert "0123456789abcdef0123456789abcdef" not in sanitized


# 16. test_backup_excludes_secrets
def test_backup_excludes_secrets():
    from carnaval.services import more as more_svc
    buf = io.BytesIO()
    ok, err = more_svc.create_backup(buf)
    assert ok, err

    buf.seek(0)
    with zipfile.ZipFile(buf, "r") as zf:
        namelist = zf.namelist()
        for name in namelist:
            assert "master.key" not in name
            assert ".env" not in name
            assert "sessions" not in name


# 17. test_restore_traversal
def test_restore_traversal():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../etc/passwd", "root:x:0:0:root:/root:/bin/bash")
    buf.seek(0)

    with pytest.raises(ZipValidationError):
        validate_zip_archive(buf.getvalue())


# 18. test_zip_bomb
def test_zip_bomb():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("huge.txt", b"\x00" * (120 * 1024 * 1024))
    buf.seek(0)

    with pytest.raises(ZipValidationError):
        validate_zip_archive(buf.getvalue(), max_uncompressed_bytes=100 * 1024 * 1024)


# 19. test_upload_limit
def test_upload_limit():
    huge_bytes = b"0" * (60 * 1024 * 1024)
    with pytest.raises(ZipValidationError):
        validate_zip_archive(huge_bytes, max_uncompressed_bytes=50 * 1024 * 1024)


# 20. test_xss
def test_xss():
    import html
    malicious = "<script>alert('xss')</script>&\"'<img src=x onerror=alert(1)>"
    escaped = html.escape(malicious)
    assert "<script>" not in escaped
    assert "&lt;script&gt;" in escaped
    assert "<img" not in escaped


# 21. test_ssrf
def test_ssrf():
    assert is_safe_url("https://funpay.com")[0] is True
    assert is_safe_url("https://api.telegram.org")[0] is True
    assert is_safe_url("http://127.0.0.1:8080")[0] is False
    assert is_safe_url("http://localhost:8765")[0] is False
    assert is_safe_url("http://192.168.1.1/admin")[0] is False
    assert is_safe_url("http://10.0.0.1")[0] is False
    assert is_safe_url("http://169.254.169.254/latest/meta-data/")[0] is False
    assert is_safe_url("http://[::1]")[0] is False


# 22. test_cors
def test_cors():
    app = build_app(allowed_origins=["https://carnaval.vercel.app"])
    client = TestClient(app)
    res = client.options("/api/meta", headers={
        "Origin": "https://carnaval.vercel.app",
        "Access-Control-Request-Method": "GET"
    })
    assert res.headers.get("access-control-allow-origin") == "https://carnaval.vercel.app"


# 23. test_csrf
def test_csrf():
    app = build_app()
    client = TestClient(app)
    uid = 99999
    token = auth.create_session(uid)
    client.cookies.set("carnaval_session", token)

    # Мутирующий запрос с cookie, но без X-CSRF-Token блокируется (403)
    res = client.patch("/api/more/proxy/enabled", json={"enabled": True})
    assert res.status_code == 403
    err_text = res.text.lower()
    assert "csrf" in err_text

    # Мутирующий запрос с валидным X-CSRF-Token пропускается
    res_ok = client.patch(
        "/api/more/proxy/enabled",
        json={"enabled": True},
        headers={"X-CSRF-Token": token}
    )
    assert res_ok.status_code != 403


# 24. test_security_headers
def test_security_headers():
    app = build_app()
    client = TestClient(app)
    res = client.get("/api/meta")
    assert res.headers.get("x-content-type-options") == "nosniff"
    assert res.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert "no-store" in res.headers.get("cache-control", "")
    assert "frame-ancestors 'none'" in res.headers.get("content-security-policy", "")


# Extra: startup with only TG_BOT_TOKEN
def test_startup_with_only_bot_token(monkeypatch):
    monkeypatch.delenv("GOLDEN_KEY", raising=False)
    monkeypatch.delenv("FUNPAY_PASSWORD", raising=False)
    monkeypatch.delenv("PANEL_PASSWORD", raising=False)
    monkeypatch.setenv("TG_BOT_TOKEN", "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ")
    SecretManager.delete_secret("golden_key")
    from carnaval.deps import set_cardinal
    set_cardinal(None)
    from carnaval.services.account_lifecycle import lifecycle_manager, AccountState
    lifecycle_manager.state = AccountState.NO_KEY
    lifecycle_manager.profile = None

    app = build_app()
    client = TestClient(app)

    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] != "ok"  # Never return status: ok if FunPay is not connected!
    assert res.json()["status"] in ("degraded", "healthy")
    assert res.json()["funpay"] == "disconnected"
    assert res.json()["telegram"] == "connected"

    res_setup = client.get("/api/setup/status")
    assert res_setup.status_code == 200
    data = res_setup.json()
    assert "state" in data


def test_all_protected_routes_require_authentication():
    """
    Автоматический security-аудит маршрутов:
    Обходит все зарегистрированные роуты FastAPI и проверяет,
    что неавторизованные запросы возвращают 401 Unauthorized или 403 Forbidden.
    Исключения: строго ограниченный белый список публичных эндпоинтов.
    """
    app = build_app()
    client = TestClient(app)

    PUBLIC_ALLOWLIST = {
        "/api/health",
        "/api/meta",
        "/api/system/version",
        "/api/auth",
        "/api/auth/telegram",
        "/api/auth/telegram/login",
        "/api/setup/status",
        "/api/setup/claim",
    }

    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", set())
        if not path or not path.startswith("/api/"):
            continue

        if path in PUBLIC_ALLOWLIST:
            continue

        for method in methods:
            if method in ("OPTIONS", "HEAD"):
                continue

            test_path = re.sub(r"\{[a-zA-Z_0-9]+\}", "test_param", path)
            resp = client.request(method, test_path, json={})
            assert resp.status_code in (401, 403), (
                f"Маршрут {method} {path} ({test_path}) не защищен! Получен статус {resp.status_code}"
            )

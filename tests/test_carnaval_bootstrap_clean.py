"""
tests/test_carnaval_bootstrap_clean.py — Регрессионные тесты чистого старта и CORS allowlist.

Проверяет:
1. Запуск SecretManager на абсолютно чистой базе данных (пустая директория без app.db).
   SecretManager.get_secret("golden_key") никогда не падает с "no such table: secrets".
2. Идемпотентность схемы БД при многократных вызовах init_db().
3. Строгий список разрешённых CORS-origins по умолчанию (web.telegram.org, vercel apps, localhost:5000/8000).
4. Запрет wildcard '*' без явного указания CARNAVAL_ALLOW_ANY_ORIGIN=1.
5. Корректная обработка кастомных origins из CARNAVAL_ALLOWED_ORIGINS.
6. Интеграция CORS Middleware с FastAPI при проверке допустимых и недопустимых origins.
"""

from __future__ import annotations

import os
import configparser
import pytest
from fastapi.testclient import TestClient

from carnaval import paths
from carnaval.db import init_db, get_db_connection
from carnaval.secrets_manager import SecretManager, reset_master_key
from carnaval.server import (
    DEFAULT_ALLOWED_ORIGINS,
    build_app,
    set_allowed_origins,
    get_allowed_origins,
)
import bootstrap_env


@pytest.fixture
def clean_isolated_env(tmp_path, monkeypatch):
    """
    Создает изолированное окружение с пустой рабочей директорией и отсутствующей БД.
    """
    clean_data = str(tmp_path / "data")
    monkeypatch.setenv("DATA_DIR", clean_data)
    monkeypatch.delenv("CARNAVAL_ALLOW_ANY_ORIGIN", raising=False)
    monkeypatch.delenv("CARNAVAL_ALLOWED_ORIGINS", raising=False)

    # Перенаправляем пути
    monkeypatch.setattr(paths, "DATA_DIR", clean_data)
    monkeypatch.setattr(paths, "DB_PATH", os.path.join(clean_data, "app.db"))
    monkeypatch.setattr(paths, "SECRETS_DIR", os.path.join(clean_data, "secrets"))
    monkeypatch.setattr(paths, "MASTER_KEY_PATH", os.path.join(clean_data, "secrets", "master.key"))
    monkeypatch.setattr(paths, "CONFIGS_DIR", os.path.join(clean_data, "configs"))
    monkeypatch.setattr(paths, "STORAGE_DIR", os.path.join(clean_data, "storage"))
    monkeypatch.setattr(paths, "PRODUCTS_DIR", os.path.join(clean_data, "storage", "products"))
    monkeypatch.setattr(paths, "LOGS_DIR", os.path.join(clean_data, "logs"))
    monkeypatch.setattr(paths, "BACKUPS_DIR", os.path.join(clean_data, "backups"))
    monkeypatch.setattr(paths, "PLUGINS_DIR", os.path.join(clean_data, "plugins"))

    reset_master_key()
    set_allowed_origins()

    yield clean_data

    reset_master_key()
    set_allowed_origins()


def test_secret_manager_on_fresh_empty_database(clean_isolated_env):
    """
    Regression: SecretManager на пустой директории без предварительного init_db.
    Не должен выбрасывать 'no such table: secrets'.
    """
    db_file = paths.DB_PATH
    assert not os.path.exists(db_file), "База данных не должна существовать перед тестом"

    # Вызов get_secret на чистой БД
    val = SecretManager.get_secret("golden_key")
    assert val is None, "Несуществующий секрет должен возвращать None"

    # Проверяем, что БД была автоматически создана и таблица secrets создана
    assert os.path.exists(db_file), "БД должна быть автоматически создана"
    assert SecretManager.has_secret("golden_key") is False

    # Проверяем запись, чтение и удаление секрета
    SecretManager.set_secret("golden_key", "dummy_token_abcdef_123456")
    assert SecretManager.has_secret("golden_key") is True
    assert SecretManager.get_secret("golden_key") == "dummy_token_abcdef_123456"

    configured = SecretManager.list_configured_secrets()
    assert "golden_key" in configured

    assert SecretManager.delete_secret("golden_key") is True
    assert SecretManager.has_secret("golden_key") is False
    assert SecretManager.get_secret("golden_key") is None


def test_cardinal_init_account_sequence_clean_db(clean_isolated_env):
    """
    Имитация startup последовательности cardinal.__init_account():
    вызов SecretManager.get_secret('golden_key') до старта lifespan или сервера.
    """
    db_file = paths.DB_PATH
    assert not os.path.exists(db_file)

    # Имитация чтения ключа из cardinal.__init_account
    try:
        from carnaval.secrets_manager import SecretManager
        g_key = SecretManager.get_secret("golden_key")
    except Exception as e:
        pytest.fail(f"Cardinal startup sequence failed with exception: {e}")

    assert g_key is None


def test_db_init_idempotence(clean_isolated_env):
    """Многократный запуск init_db() должен быть полностью идемпотентным."""
    for _ in range(5):
        init_db()

    conn = get_db_connection()
    try:
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = {t["name"] for t in tables}
        required_tables = {"system_state", "users", "sessions", "secrets", "audit_logs", "rate_limits"}
        assert required_tables.issubset(table_names)

        state = conn.execute("SELECT value FROM system_state WHERE key = 'state'").fetchone()
        assert state is not None
        assert state["value"] == "UNINITIALIZED"
    finally:
        conn.close()


def test_cors_strict_allowlist_defaults(monkeypatch):
    """Строгий список разрешённых origins по умолчанию не содержит '*'."""
    monkeypatch.delenv("CARNAVAL_ALLOW_ANY_ORIGIN", raising=False)
    monkeypatch.delenv("CARNAVAL_ALLOWED_ORIGINS", raising=False)

    set_allowed_origins()
    origins = get_allowed_origins()

    assert "*" not in origins
    assert "https://web.telegram.org" in origins
    assert "https://carnaval-cardinal.vercel.app" in origins
    assert "https://amazing-babbage-tau.vercel.app" in origins
    assert "http://localhost:5000" in origins
    assert "http://127.0.0.1:5000" in origins
    assert "http://localhost:8000" in origins
    assert "http://127.0.0.1:8000" in origins


def test_cors_rejects_wildcard_without_flag(monkeypatch):
    """Wildcard '*' игнорируется, если CARNAVAL_ALLOW_ANY_ORIGIN != 1."""
    monkeypatch.delenv("CARNAVAL_ALLOW_ANY_ORIGIN", raising=False)

    # Передача '*' в set_allowed_origins
    set_allowed_origins("*")
    origins = get_allowed_origins()
    assert "*" not in origins
    assert "https://web.telegram.org" in origins

    # Передача '*' через CARNAVAL_ALLOWED_ORIGINS
    monkeypatch.setenv("CARNAVAL_ALLOWED_ORIGINS", "*")
    set_allowed_origins()
    origins = get_allowed_origins()
    assert "*" not in origins


def test_cors_allows_wildcard_with_flag(monkeypatch):
    """Wildcard '*' разрешён ТОЛЬКО при CARNAVAL_ALLOW_ANY_ORIGIN=1."""
    monkeypatch.setenv("CARNAVAL_ALLOW_ANY_ORIGIN", "1")

    set_allowed_origins("*")
    assert get_allowed_origins() == ["*"]

    # bootstrap_env также формирует '*'
    assert bootstrap_env.resolve_allowed_origins_string() == "*"


def test_cors_with_custom_origins(monkeypatch):
    """Кастомные origins из CARNAVAL_ALLOWED_ORIGINS добавляются к строгому списку."""
    monkeypatch.delenv("CARNAVAL_ALLOW_ANY_ORIGIN", raising=False)
    monkeypatch.setenv("CARNAVAL_ALLOWED_ORIGINS", "https://custom.app, https://another.domain")

    set_allowed_origins()
    origins = get_allowed_origins()

    assert "*" not in origins
    assert "https://custom.app" in origins
    assert "https://another.domain" in origins
    assert "https://web.telegram.org" in origins


def test_cors_middleware_enforcement(monkeypatch):
    """FastAPI CORSMiddleware разрешает доверенные origins и не выдает allow-origin для недоверенных."""
    monkeypatch.delenv("CARNAVAL_ALLOW_ANY_ORIGIN", raising=False)
    monkeypatch.delenv("CARNAVAL_ALLOWED_ORIGINS", raising=False)

    set_allowed_origins()
    app = build_app()
    client = TestClient(app)

    # 1. Запрос от доверенного Telegram WebApp
    res_tg = client.options("/api/meta", headers={
        "Origin": "https://web.telegram.org",
        "Access-Control-Request-Method": "GET"
    })
    assert res_tg.headers.get("access-control-allow-origin") == "https://web.telegram.org"

    # 2. Запрос от доверенного Vercel фронтенда
    res_vercel = client.options("/api/meta", headers={
        "Origin": "https://carnaval-cardinal.vercel.app",
        "Access-Control-Request-Method": "GET"
    })
    assert res_vercel.headers.get("access-control-allow-origin") == "https://carnaval-cardinal.vercel.app"

    # 3. Запрос от недоверенного домена
    res_malicious = client.options("/api/meta", headers={
        "Origin": "https://attacker.evil.com",
        "Access-Control-Request-Method": "GET"
    })
    assert res_malicious.headers.get("access-control-allow-origin") is None


def test_bootstrap_env_sync_replaces_insecure_wildcard(tmp_path, monkeypatch):
    """_sync_existing_config заменяет старый 'allowedOrigins = *' на строгий allowlist."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CARNAVAL_ALLOW_ANY_ORIGIN", raising=False)

    cfg_dir = tmp_path / "configs"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_file = cfg_dir / "_main.cfg"

    with open(cfg_file, "w", encoding="utf-8") as f:
        f.write("[Carnaval]\nallowedOrigins: *\nport: 5000\n")

    synced = bootstrap_env._sync_existing_config(str(cfg_file))
    assert synced is True

    cfg = configparser.ConfigParser(delimiters=(":",), interpolation=None)
    cfg.read(str(cfg_file), encoding="utf-8")

    allowed = cfg.get("Carnaval", "allowedOrigins")
    assert allowed != "*"
    assert "https://web.telegram.org" in allowed
    assert "https://carnaval-cardinal.vercel.app" in allowed

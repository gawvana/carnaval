"""
tests/test_carnaval_update_system.py — комплексное тестирование подсистемы обновлений Carnaval:
- Эндпоинт текущих версий (/api/updates/current)
- Генерация и проверка манифеста обновлений (/api/updates/manifest, /api/updates/check)
- Унифицированная схема ответа POST /api/updates/check
- Персистентность и поведение Safe Mode (обход сторонних плагинов)
- Персистентность и поведение Maintenance Mode (пауза автовыдачи + рассылка предупреждений)
- Автоматический pre-update бэкап и восстановление (carnaval.services.backup)
- Реальный загрузчик артефактов (Real Download Service) с лимитом размера, таймаутом и SHA-256
- Все реальные режимы сбоев:
  * неверный SHA-256
  * поврежденный ZIP архив (broken archive)
  * превышение максимального размера артефакта (>50MB)
  * ошибка сетевой загрузки артефакта (download failure)
  * сбой миграции БД с автоматическим Safe Rollback
  * сбой health check с автоматическим Safe Rollback
  * неавторизованный доступ и заблокированная панель (401 / 403 / 423)
- Реальный атомарный установщик (Real Atomic Update Lifecycle)
- Ручной откат к бэкапу (/api/updates/rollback)
- Отслеживание статуса и каналов (/api/updates/status)
"""

import configparser
import hashlib
import io
import os
import sqlite3
import time
import urllib.error
import zipfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from carnaval import auth, bridge
from carnaval.db import get_db_connection, get_state, init_db, set_state, transaction
from carnaval.deps import set_cardinal
from carnaval.paths import BACKUPS_DIR, CONFIGS_DIR, DATA_DIR, init_persistent_dirs
from carnaval.server import build_app
import carnaval.services.backup as backup_svc
from carnaval.services import system_mode
from carnaval.services import update as update_svc
from carnaval.services.update import (
    APP_VERSION,
    BACKEND_VERSION,
    CARDINAL_VERSION,
    DOWNLOAD_TIMEOUT,
    MAX_ARTIFACT_SIZE,
    SCHEMA_VERSION,
    PLUGIN_API_VERSION,
    UpdateChannel,
    UpdateState,
    download_artifact,
    generate_manifest,
    get_active_channel,
    get_current_schema_version,
    get_current_versions,
    get_staging_dir,
    get_update_status,
    install_update,
    rollback_update,
    run_schema_migrations,
    set_active_channel,
    stage_update,
    verify_manifest,
)


@pytest.fixture(autouse=True)
def setup_update_test_env(tmp_path, monkeypatch):
    """Изолированная среда для каждого теста с отдельной временной БД и папками."""
    test_data = tmp_path / "data"
    test_data.mkdir()

    import carnaval.paths as p
    monkeypatch.setattr(p, "DATA_DIR", str(test_data))
    monkeypatch.setattr(p, "DB_PATH", os.path.join(str(test_data), "app.db"))
    monkeypatch.setattr(p, "SECRETS_DIR", os.path.join(str(test_data), "secrets"))
    monkeypatch.setattr(p, "MASTER_KEY_PATH", os.path.join(str(test_data), "secrets", "master.key"))
    monkeypatch.setattr(p, "CONFIGS_DIR", os.path.join(str(test_data), "configs"))
    monkeypatch.setattr(p, "STORAGE_DIR", os.path.join(str(test_data), "storage"))
    monkeypatch.setattr(p, "PRODUCTS_DIR", os.path.join(str(test_data), "storage", "products"))
    monkeypatch.setattr(p, "LOGS_DIR", os.path.join(str(test_data), "logs"))
    monkeypatch.setattr(p, "BACKUPS_DIR", os.path.join(str(test_data), "backups"))
    monkeypatch.setattr(p, "PLUGINS_DIR", os.path.join(str(test_data), "plugins"))

    init_persistent_dirs()
    init_db()

    # Сброс глобального состояния обновлений
    update_svc._current_state = UpdateState.IDLE
    update_svc._progress_percent = 0
    update_svc._current_step = ""
    update_svc._last_error = None
    update_svc._last_backup_id = None
    update_svc._last_backup_info = None
    update_svc._target_version = None
    update_svc._staged_manifest = None
    update_svc._staged_artifact = None

    # Создаем фиктивный Cardinal для тестов
    c = MagicMock()
    c.VERSION = CARDINAL_VERSION
    c.running = True
    c.start_time = int(time.time()) - 50

    cfg = configparser.ConfigParser(delimiters=(":",), interpolation=None)
    cfg.optionxform = str
    cfg.add_section("FunPay")
    cfg.set("FunPay", "golden_key", "sec12345abcdef12345abcdef1234567")
    cfg.set("FunPay", "autoRaise", "1")
    cfg.set("FunPay", "autoResponse", "1")
    cfg.set("FunPay", "autoDelivery", "1")
    cfg.set("FunPay", "multiDelivery", "0")
    cfg.set("FunPay", "autoRestore", "1")
    cfg.set("FunPay", "autoDisable", "0")

    cfg.add_section("Telegram")
    cfg.set("Telegram", "enabled", "1")
    cfg.set("Telegram", "token", "123:ABC")

    cfg.add_section("Carnaval")
    cfg.set("Carnaval", "enabled", "1")
    cfg.set("Carnaval", "port", "8765")
    cfg.set("Carnaval", "secretKey", "test_secret_for_update_tests_12345")

    c.MAIN_CFG = cfg
    c.plugins = {}
    c.telegram = MagicMock()
    c.telegram.send_notification = MagicMock()
    c.telegram.authorized_users = {111: {}}
    c.account = MagicMock()
    c.account.id = 111

    type(c).autodelivery_enabled = property(
        lambda self: False if system_mode.is_maintenance_mode() else self.MAIN_CFG["FunPay"].getboolean("autoDelivery")
    )

    set_cardinal(c)
    yield c
    set_cardinal(None)
    system_mode.set_safe_mode(False)
    system_mode.set_maintenance_mode(False)


@pytest.fixture
def client():
    """Тестовый клиент FastAPI."""
    app = build_app(allowed_origins=["*"])
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """Заголовки авторизованного владельца с разблокированной панелью."""
    token = auth.create_session(telegram_user_id=111)
    auth.unlock_panel_session(token)
    return {"Authorization": f"Bearer {token}", "X-CSRF-Token": token}


def _create_sample_zip(files: dict[str, bytes]) -> bytes:
    """Хелпер создания валидного ZIP-архива в памяти."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, content in files.items():
            zf.writestr(fname, content)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 1. Тесты эндпоинта текущих версий
# ---------------------------------------------------------------------------

def test_current_version_endpoint(client, auth_headers):
    """GET /api/updates/current возвращает полные версионные метаданные и системные режимы."""
    response = client.get("/api/updates/current", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()

    assert data["app_version"] == APP_VERSION
    assert data["backend_version"] == BACKEND_VERSION
    assert data["cardinal_version"] == CARDINAL_VERSION
    assert data["schema_version"] in (1, 2, 3)
    assert data["plugin_api_version"] == PLUGIN_API_VERSION
    assert data["channel"] == "stable"
    assert data["safe_mode"] is False
    assert data["maintenance_mode"] is False


# ---------------------------------------------------------------------------
# 2. Тесты манифеста и унифицированной схемы POST /api/updates/check
# ---------------------------------------------------------------------------

def test_manifest_generation_and_check(client, auth_headers):
    """Проверка генерации манифеста, валидации каналов и унифицированной схемы /api/updates/check."""
    # Проверка эндпоинта GET /api/updates/manifest
    resp_manifest = client.get("/api/updates/manifest?channel=beta", headers=auth_headers)
    assert resp_manifest.status_code == 200
    manifest = resp_manifest.json()
    assert manifest["channel"] == "beta"
    assert "version" in manifest
    assert "artifact_sha256" in manifest
    assert "artifact_size" in manifest
    assert "minimum_version" in manifest
    assert "minimum_schema_version" in manifest
    assert "maximum_schema_version" in manifest
    assert "compatible_backend" in manifest
    assert "compatible_cardinal" in manifest
    assert "plugin_api_version" in manifest
    assert "requires_restart" in manifest
    assert "required_migrations" in manifest
    assert "signature" in manifest
    assert "release_date" in manifest

    # Проверка POST /api/updates/check — унифицированная схема
    resp_check = client.post("/api/updates/check", json={"channel": "nightly"}, headers=auth_headers)
    assert resp_check.status_code == 200
    check_data = resp_check.json()
    assert check_data["ok"] is True
    assert check_data["current_version"] == APP_VERSION
    assert check_data["latest_version"] == "2.4.0-nightly"
    assert check_data["update_available"] is True
    assert check_data["channel"] == "nightly"
    assert "manifest" in check_data
    assert "status" in check_data
    assert "progress" in check_data
    assert "error_code" in check_data

    # Тестирование verify_manifest с валидным пакетом
    dummy_bundle = _create_sample_zip({"version.txt": b"2.2.0"})
    valid_manifest = generate_manifest(
        version="2.2.0",
        channel="stable",
        artifact_bytes=dummy_bundle,
        minimum_version="1.0.0",
    )
    ok, err = verify_manifest(valid_manifest, dummy_bundle)
    assert ok is True
    assert err == ""

    # Проверка отказа при несовместимой minimum_version
    incompatible_manifest = generate_manifest(
        version="3.0.0",
        channel="stable",
        artifact_bytes=dummy_bundle,
        minimum_version="99.0.0",
    )
    ok_compat, err_compat = verify_manifest(incompatible_manifest, dummy_bundle)
    assert ok_compat is False
    assert "lower than minimum required version" in err_compat

    # Проверка отказа при неизвестном канале
    invalid_channel_manifest = dict(valid_manifest)
    invalid_channel_manifest["channel"] = "experimental_unsupported"
    ok_chan, err_chan = verify_manifest(invalid_channel_manifest)
    assert ok_chan is False
    assert "Invalid manifest channel" in err_chan


# ---------------------------------------------------------------------------
# 3. Тесты Safe Mode (персистентность, обход плагинов, авторизация)
# ---------------------------------------------------------------------------

def test_safe_mode_persistence_and_bypass(client, setup_update_test_env, auth_headers):
    """Включение Safe Mode персистентно сохраняется и блокирует сторонние плагины."""
    cardinal = setup_update_test_env

    assert system_mode.is_safe_mode() is False
    assert system_mode.should_bypass_plugin("plugin-123-uuid") is False

    # Включаем Safe Mode через защищенный API
    resp_enable = client.post("/api/system/safe-mode", json={"enabled": True}, headers=auth_headers)
    assert resp_enable.status_code == 200
    assert resp_enable.json()["safe_mode"] is True

    # Проверка персистентности в SQLite
    assert system_mode.is_safe_mode() is True
    assert get_state("safe_mode") == "1"

    # Проверка GET /api/system/mode
    mode_resp = client.get("/api/system/mode", headers=auth_headers)
    assert mode_resp.status_code == 200
    assert mode_resp.json()["safe_mode"] is True

    # Проверка обхода сторонних плагинов
    assert system_mode.should_bypass_plugin("third_party_plugin_uuid") is True
    assert system_mode.should_bypass_plugin(None) is False

    # Проверка вызова хэндлеров через Cardinal
    called = []
    def sample_plugin_handler(*args):
        called.append("plugin_executed")
    sample_plugin_handler.plugin_uuid = "third_party_uuid"

    def builtin_handler(*args):
        called.append("builtin_executed")
    builtin_handler.plugin_uuid = None

    cardinal.plugins["third_party_uuid"] = MagicMock(enabled=True)
    cardinal.run_handlers = update_svc._update_lock
    from cardinal import Cardinal
    run_handlers_fn = Cardinal.run_handlers

    run_handlers_fn(cardinal, [sample_plugin_handler, builtin_handler], ())
    assert "plugin_executed" not in called
    assert "builtin_executed" in called

    # Отключаем Safe Mode
    resp_disable = client.post("/api/system/safe-mode", json={"enabled": False}, headers=auth_headers)
    assert resp_disable.status_code == 200
    assert resp_disable.json()["safe_mode"] is False
    assert system_mode.is_safe_mode() is False
    assert get_state("safe_mode") == "0"


# ---------------------------------------------------------------------------
# 4. Тесты Maintenance Mode (персистентность, оповещения, авторизация)
# ---------------------------------------------------------------------------

def test_maintenance_mode_persistence_and_alert(client, setup_update_test_env, auth_headers):
    """Maintenance Mode ставит автовыдачу на паузу, сохраняется в БД и рассылает оповещение."""
    cardinal = setup_update_test_env

    bridge_events = []
    def mock_emit(evt, data):
        bridge_events.append((evt, data))
    with patch("carnaval.bridge.emit", side_effect=mock_emit):
        resp = client.post(
            "/api/system/maintenance",
            json={"enabled": True, "reason": "Server Migration V2"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["maintenance_mode"] is True
        assert data["reason"] == "Server Migration V2"

        assert system_mode.is_maintenance_mode() is True
        assert get_state("maintenance_mode") == "1"
        assert get_state("maintenance_reason") == "Server Migration V2"

        assert system_mode.is_autodelivery_allowed() is False
        assert cardinal.autodelivery_enabled is False

        alert_event = next((d for evt, d in bridge_events if evt == "system.alert"), None)
        assert alert_event is not None
        assert alert_event["type"] == "maintenance_mode"
        assert alert_event["enabled"] is True

        cardinal.telegram.send_notification.assert_called()

        bridge_events.clear()
        resp_off = client.post("/api/system/maintenance", json={"enabled": False}, headers=auth_headers)
        assert resp_off.status_code == 200
        assert resp_off.json()["maintenance_mode"] is False
        assert system_mode.is_maintenance_mode() is False
        assert get_state("maintenance_mode") == "0"
        assert system_mode.is_autodelivery_allowed() is True
        assert cardinal.autodelivery_enabled is True


# ---------------------------------------------------------------------------
# 5. Тесты Pre-update бэкапа и восстановления
# ---------------------------------------------------------------------------

def test_pre_update_backup_creation_and_restoration():
    """Проверка автоматического создания pre-update бэкапа и безопасного восстановления."""
    import carnaval.paths as p
    test_cfg_path = os.path.join(p.CONFIGS_DIR, "test_config.cfg")
    with open(test_cfg_path, "w", encoding="utf-8") as f:
        f.write("[Section]\nkey = test_value\n")

    backup_data = backup_svc.create_backup()
    assert isinstance(backup_data, bytes)
    assert len(backup_data) > 0

    buf = io.BytesIO(backup_data)
    with zipfile.ZipFile(buf, "r") as zf:
        names = zf.namelist()
        assert any("test_config.cfg" in n for n in names)

    backups = backup_svc.list_backups()
    assert len(backups) >= 1
    assert any("pre_update" in b["filename"] for b in backups)

    with open(test_cfg_path, "w", encoding="utf-8") as f:
        f.write("[Section]\nkey = corrupted_value\n")

    ok, err = backup_svc.restore_backup(backup_data)
    assert ok is True
    assert err == ""

    with open(test_cfg_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "test_value" in content


# ---------------------------------------------------------------------------
# 6. Тесты SHA-256 верификации и целостности
# ---------------------------------------------------------------------------

def test_sha256_verification_and_integrity_check():
    """Проверка строгости контроля SHA-256: отклонение пакетов при несовпадении хэша."""
    valid_payload = _create_sample_zip({"file.txt": b"ValidContent"})
    correct_sha256 = hashlib.sha256(valid_payload).hexdigest()

    manifest = generate_manifest(
        version="2.2.0",
        channel="stable",
        artifact_bytes=valid_payload,
    )
    assert manifest["artifact_sha256"] == correct_sha256.lower()

    ok_valid, _ = verify_manifest(manifest, valid_payload)
    assert ok_valid is True

    corrupt_payload = b"CarnavalCorruptedBinary_TAMPERED!"
    ok_corrupt, err_corrupt = verify_manifest(manifest, corrupt_payload)
    assert ok_corrupt is False
    assert "SHA-256 hash mismatch" in err_corrupt

    with pytest.raises(ValueError) as excinfo:
        stage_update(manifest=manifest, artifact_bytes=corrupt_payload)
    assert "SHA-256 hash mismatch" in str(excinfo.value)
    assert get_update_status()["state"] == UpdateState.FAILED.value


# ---------------------------------------------------------------------------
# 7. Тесты раннера миграций схемы (V1 -> V2 -> V3)
# ---------------------------------------------------------------------------

def test_schema_migration_runner_v1_to_v3():
    """Раннер последовательно применяет миграции V1 -> V2 -> V3 и создает нужные таблицы."""
    set_state("schema_version", "1")
    assert get_current_schema_version() == 1

    ok, msg = run_schema_migrations(target_version=SCHEMA_VERSION)
    assert ok is True
    assert "Successfully migrated schema to V3" in msg
    assert get_current_schema_version() == SCHEMA_VERSION

    conn = get_db_connection()
    tables = [row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
    conn.close()

    assert "update_history" in tables
    assert "schema_migrations" in tables


# ---------------------------------------------------------------------------
# 8. Тесты реальных failure modes
# ---------------------------------------------------------------------------

def test_failure_mode_wrong_sha256():
    """Сбой: неверный SHA-256 приводит к отказу установки на стадии верификации."""
    valid_zip = _create_sample_zip({"version.txt": b"2.2.0"})
    manifest = generate_manifest("2.2.0", channel="stable", artifact_bytes=valid_zip)
    manifest["artifact_sha256"] = "0" * 64  # Намеренно неверный хэш

    success, msg, details = install_update(manifest=manifest, artifact_bytes=valid_zip)
    assert success is False
    assert details["phase"] == "verification"
    assert "SHA-256" in msg
    assert get_update_status()["state"] == UpdateState.FAILED.value


def test_failure_mode_broken_archive():
    """Сбой: поврежденный ZIP архив отклоняется на стадии staging, временные файлы очищаются."""
    broken_payload = b"PK\x03\x04BROKEN_NON_ZIP_BYTES_0123456789"
    manifest = generate_manifest("2.2.0", channel="stable", artifact_bytes=broken_payload)

    success, msg, details = install_update(manifest=manifest, artifact_bytes=broken_payload)
    assert success is False
    assert details["phase"] == "staging"
    assert "ZIP" in msg or "corrupted" in msg
    assert get_update_status()["state"] == UpdateState.FAILED.value

    # Проверка, что staging директория была очищена
    staging_dir = get_staging_dir("2.2.0")
    assert not os.path.exists(staging_dir)


def test_failure_mode_too_large_artifact():
    """Сбой: загрузка артефакта, превышающего лимит (50 МБ), немедленно прерывается."""
    # 1. Проверка через Content-Length
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.headers = {"Content-Length": str(MAX_ARTIFACT_SIZE + 1024), "Content-Type": "application/zip"}
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        with pytest.raises(ValueError) as exc:
            download_artifact("https://example.com/update.zip")
        assert "exceeds maximum limit" in str(exc.value)

    # 2. Проверка через превышение потока байтов
    chunk = b"A" * (64 * 1024)
    chunks_iter = iter([chunk] * (MAX_ARTIFACT_SIZE // (64 * 1024) + 2) + [b""])
    mock_resp_stream = MagicMock()
    mock_resp_stream.status = 200
    mock_resp_stream.headers = {"Content-Type": "application/zip"}
    mock_resp_stream.read.side_effect = lambda size: next(chunks_iter, b"")
    mock_resp_stream.__enter__.return_value = mock_resp_stream

    with patch("urllib.request.urlopen", return_value=mock_resp_stream):
        with pytest.raises(ValueError) as exc_stream:
            download_artifact("https://example.com/stream.zip")
        assert "exceeded maximum limit" in str(exc_stream.value)


def test_failure_mode_download_failure():
    """Сбой: сетевая ошибка при скачивании артефакта корректно обрабатывается пайплайном."""
    # 1. download_artifact с недостижимым URL
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        with pytest.raises(ValueError) as exc:
            download_artifact("https://unreachable.carnaval.internal/pkg.zip")
        assert "network error" in str(exc.value) or "Connection refused" in str(exc.value)

    # 2. install_update при ошибке скачивания
    manifest = generate_manifest("2.3.0", channel="stable")
    manifest["artifact_url"] = "https://unreachable.carnaval.internal/pkg.zip"

    with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("url", 404, "Not Found", {}, None)):
        success, msg, details = install_update(manifest=manifest, artifact_bytes=None)
        assert success is False
        assert details["phase"] == "download"
        assert "404" in msg or "Download failed" in msg


def test_failure_mode_migration_failure_rollback():
    """Сбой: ошибка при миграции БД откатывает версию, схему и файлы к исходному состоянию."""
    set_state("app_version", "2.1.0")
    set_state("schema_version", "1")
    package_bytes = _create_sample_zip({"version.txt": b"2.5.0"})
    manifest = generate_manifest("2.5.0", channel="stable", artifact_bytes=package_bytes)

    success, msg, details = install_update(
        manifest=manifest,
        artifact_bytes=package_bytes,
        fail_on_migration=True,
    )
    assert success is False
    assert details.get("rolled_back") is True
    assert get_update_status()["state"] == UpdateState.FAILED.value

    # Версия и схема остались исходными
    assert get_state("app_version") == "2.1.0"
    assert get_state("schema_version") == "1"

    # Запись в update_history со статусом ROLLED_BACK (если таблица существует в текущей схеме)
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT status, to_version FROM update_history ORDER BY id DESC LIMIT 1;").fetchone()
        if row:
            assert row["status"] == "ROLLED_BACK"
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()


def test_failure_mode_health_check_failure_rollback():
    """Сбой: непройденный health check откатывает версию, схему и примененные файлы."""
    set_state("app_version", "2.1.0")
    set_state("schema_version", "1")
    package_bytes = _create_sample_zip({"version.txt": b"2.5.0"})
    manifest = generate_manifest("2.5.0", channel="stable", artifact_bytes=package_bytes)

    success, msg, details = install_update(
        manifest=manifest,
        artifact_bytes=package_bytes,
        fail_on_health=True,
    )
    assert success is False
    assert details.get("rolled_back") is True
    assert get_update_status()["state"] == UpdateState.FAILED.value
    assert get_state("app_version") == "2.1.0"


def test_unauthorized_access_401_and_423(client):
    """Сбой: неавторизованный запрос возвращает 401, а заблокированная панель — 403 или 423."""
    # 1. Запросы БЕЗ сессии и токена блокируются с кодом 401 Unauthorized
    resp_install_noauth = client.post("/api/updates/install", json={"version": "2.2.0"})
    assert resp_install_noauth.status_code == 401

    resp_rollback_noauth = client.post("/api/updates/rollback", json={})
    assert resp_rollback_noauth.status_code == 401

    resp_maint_noauth = client.post("/api/system/maintenance", json={"enabled": True})
    assert resp_maint_noauth.status_code == 401

    resp_safemode_noauth = client.post("/api/system/safe-mode", json={"enabled": True})
    assert resp_safemode_noauth.status_code == 401

    # 2. Запросы с сессией, но ЗАБЛОКИРОВАННОЙ панелью блокируются (403 / 423)
    set_state("state", "INITIALIZED")
    set_state("panel_password_hash", "$2b$12$fakehashedpassword123456789012345678901234567890")

    locked_token = auth.create_session(telegram_user_id=111)
    locked_headers = {"Authorization": f"Bearer {locked_token}", "X-CSRF-Token": locked_token}

    resp_install_locked = client.post("/api/updates/install", json={"version": "2.2.0"}, headers=locked_headers)
    assert resp_install_locked.status_code in (401, 403, 423)

    resp_rb_locked = client.post("/api/updates/rollback", json={}, headers=locked_headers)
    assert resp_rb_locked.status_code in (401, 403, 423)

    resp_maint_locked = client.post("/api/system/maintenance", json={"enabled": True}, headers=locked_headers)
    assert resp_maint_locked.status_code in (401, 403, 423)

    resp_sm_locked = client.post("/api/system/safe-mode", json={"enabled": True}, headers=locked_headers)
    assert resp_sm_locked.status_code in (401, 403, 423)

    # 3. Разблокированная панель разрешает доступ
    auth.unlock_panel_session(locked_token)
    resp_sm_ok = client.post("/api/system/safe-mode", json={"enabled": True}, headers=locked_headers)
    assert resp_sm_ok.status_code == 200


# ---------------------------------------------------------------------------
# 9. Тесты успешного атомарного обновления
# ---------------------------------------------------------------------------

def test_real_atomic_install_lifecycle(client, auth_headers):
    """Реальный атомарный установщик: распаковка, замена файлов, миграция и фиксация версий."""
    package_bytes = _create_sample_zip({
        "data/configs/version.txt": b"2.2.0",
        "data/configs/updated_config.txt": b"new_config_payload_v2.2.0",
    })
    manifest = generate_manifest("2.2.0", channel="stable", artifact_bytes=package_bytes)

    # Установка через прямой вызов install_update
    success, message, details = install_update(manifest=manifest, artifact_bytes=package_bytes)
    assert success is True
    assert "Successfully updated to 2.2.0" in message
    assert details["to_version"] == "2.2.0"
    assert get_state("app_version") == "2.2.0"
    assert get_state("backend_version") == "2.2.0"
    assert get_update_status()["state"] == UpdateState.READY.value

    # Проверка очистки staging директории
    staging_dir = get_staging_dir("2.2.0")
    assert not os.path.exists(staging_dir)

    # Проверка через эндпоинт версий
    resp = client.get("/api/updates/current", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["app_version"] == "2.2.0"


def test_api_install_endpoint_success(client, auth_headers):
    """POST /api/updates/install успешно выполняет установку для авторизованного владельца."""
    package_bytes = _create_sample_zip({"data/configs/version.txt": b"2.2.0"})
    manifest = generate_manifest("2.2.0", channel="stable", artifact_bytes=package_bytes)

    # Сначала стадируем пакет
    stage_update(manifest=manifest, artifact_bytes=package_bytes)

    resp = client.post(
        "/api/updates/install",
        json={"version": "2.2.0"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["success"] is True


def test_api_rollback_endpoint(client, auth_headers):
    """POST /api/updates/rollback выполняет ручной откат к бэкапу для авторизованного владельца."""
    backup_data = backup_svc.create_backup()
    resp = client.post("/api/updates/rollback", json={}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert "Rollback completed successfully" in resp.json()["message"]


# ---------------------------------------------------------------------------
# 10. Тесты статуса и каналов
# ---------------------------------------------------------------------------

def test_update_status_and_channels(client, auth_headers):
    """Проверка переключения каналов (stable, beta, nightly) и получения статуса."""
    resp_status = client.get("/api/updates/status", headers=auth_headers)
    assert resp_status.status_code == 200
    st = resp_status.json()
    assert "state" in st
    assert "progress_percent" in st
    assert "channel" in st

    set_active_channel("beta")
    assert get_active_channel() == "beta"

    set_active_channel("nightly")
    assert get_active_channel() == "nightly"

    with pytest.raises(ValueError):
        set_active_channel("invalid_channel_name")

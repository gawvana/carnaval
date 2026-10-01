"""
tests/test_carnaval_update_system.py — комплексное тестирование подсистемы обновлений Carnaval:
- Эндпоинт текущих версий (/api/updates/current)
- Генерация и проверка манифеста обновлений (/api/updates/manifest, /api/updates/check)
- Персистентность и поведение Safe Mode (обход сторонних плагинов)
- Персистентность и поведение Maintenance Mode (пауза автовыдачи + рассылка предупреждений)
- Автоматический pre-update бэкап и восстановление (carnaval.services.backup)
- Криптографическая верификация контрольной суммы SHA-256
- Раннер миграций схемы SQLite (V1 -> V2 -> V3)
- Пайплайн установки и автоматический Safe Rollback при сбоях
- Ручной откат к бэкапу (/api/updates/rollback)
- Отслеживание статуса и каналов (/api/updates/status)
"""

import configparser
import hashlib
import io
import os
import sqlite3
import time
import zipfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from carnaval import bridge
from carnaval.db import get_db_connection, get_state, init_db, set_state, transaction
from carnaval.deps import set_cardinal
from carnaval.paths import BACKUPS_DIR, CONFIGS_DIR, init_persistent_dirs
from carnaval.server import build_app
import carnaval.services.backup as backup_svc
from carnaval.services import system_mode
from carnaval.services import update as update_svc
from carnaval.services.update import (
    APP_VERSION,
    BACKEND_VERSION,
    CARDINAL_VERSION,
    SCHEMA_VERSION,
    PLUGIN_API_VERSION,
    UpdateChannel,
    UpdateState,
    generate_manifest,
    get_active_channel,
    get_current_schema_version,
    get_current_versions,
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

    # Задаем свойство autodelivery_enabled на mock Cardinal
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


# ---------------------------------------------------------------------------
# 1. Тесты эндпоинта текущих версий
# ---------------------------------------------------------------------------

def test_current_version_endpoint(client):
    """GET /api/updates/current возвращает полные версионные метаданные и системные режимы."""
    response = client.get("/api/updates/current")
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

    assert "channel" in data
    assert "safe_mode" in data
    assert "maintenance_mode" in data


# ---------------------------------------------------------------------------
# 2. Тесты генерации и проверки манифеста
# ---------------------------------------------------------------------------

def test_manifest_generation_and_check(client):
    """Проверка генерации манифеста, валидации каналов и эндпоинта проверки обновлений."""
    # Проверка эндпоинта GET /api/updates/manifest
    resp_manifest = client.get("/api/updates/manifest?channel=beta")
    assert resp_manifest.status_code == 200
    manifest = resp_manifest.json()
    assert manifest["channel"] == "beta"
    assert "version" in manifest
    assert "artifact_sha256" in manifest
    assert "artifact_size" in manifest
    assert "min_version" in manifest
    assert "release_date" in manifest

    # Проверка POST /api/updates/check
    resp_check = client.post("/api/updates/check", json={"channel": "nightly"})
    assert resp_check.status_code == 200
    check_data = resp_check.json()
    assert check_data["channel"] == "nightly"
    assert check_data["update_available"] is True
    assert "manifest" in check_data

    # Тестирование verify_manifest
    dummy_bundle = b"PK\x03\x04test_carnaval_package_bytes"
    valid_manifest = generate_manifest(
        version="2.2.0",
        channel="stable",
        artifact_bytes=dummy_bundle,
        min_version="1.0.0",
    )
    ok, err = verify_manifest(valid_manifest, dummy_bundle)
    assert ok is True
    assert err == ""

    # Проверка отказа при несовместимой min_version
    incompatible_manifest = generate_manifest(
        version="3.0.0",
        channel="stable",
        artifact_bytes=dummy_bundle,
        min_version="99.0.0",
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
# 3. Тесты Safe Mode (персистентность и обход сторонних плагинов)
# ---------------------------------------------------------------------------

def test_safe_mode_persistence_and_bypass(client, setup_update_test_env):
    """Включение Safe Mode персистентно сохраняется и блокирует сторонние плагины."""
    cardinal = setup_update_test_env

    # Начальное состояние — выключен
    assert system_mode.is_safe_mode() is False
    assert system_mode.should_bypass_plugin("plugin-123-uuid") is False

    # Включаем Safe Mode через API
    resp_enable = client.post("/api/system/safe-mode", json={"enabled": True})
    assert resp_enable.status_code == 200
    assert resp_enable.json()["safe_mode"] is True

    # Проверка персистентности в SQLite
    assert system_mode.is_safe_mode() is True
    assert get_state("safe_mode") == "1"

    # Проверка GET /api/system/mode
    mode_resp = client.get("/api/system/mode")
    assert mode_resp.status_code == 200
    assert mode_resp.json()["safe_mode"] is True

    # Проверка обхода сторонних плагинов
    assert system_mode.should_bypass_plugin("third_party_plugin_uuid") is True
    # Встроенный хэндлер без uuid не обходится
    assert system_mode.should_bypass_plugin(None) is False

    # Проверка вызова хэндлеров через Cardinal: плагин со сторонним UUID не выполняется
    called = []
    def sample_plugin_handler(*args):
        called.append("plugin_executed")
    sample_plugin_handler.plugin_uuid = "third_party_uuid"

    def builtin_handler(*args):
        called.append("builtin_executed")
    builtin_handler.plugin_uuid = None

    cardinal.plugins["third_party_uuid"] = MagicMock(enabled=True)
    cardinal.run_handlers = update_svc._update_lock  # no-op, test cardinal implementation
    from cardinal import Cardinal
    run_handlers_fn = Cardinal.run_handlers

    # Вызываем реальный метод run_handlers
    run_handlers_fn(cardinal, [sample_plugin_handler, builtin_handler], ())
    # sample_plugin_handler должен быть пропущен в safe mode!
    assert "plugin_executed" not in called
    assert "builtin_executed" in called

    # Отключаем Safe Mode
    resp_disable = client.post("/api/system/safe-mode", json={"enabled": False})
    assert resp_disable.status_code == 200
    assert resp_disable.json()["safe_mode"] is False
    assert system_mode.is_safe_mode() is False
    assert get_state("safe_mode") == "0"


# ---------------------------------------------------------------------------
# 4. Тесты Maintenance Mode (персистентность, оповещения, пауза автовыдачи)
# ---------------------------------------------------------------------------

def test_maintenance_mode_persistence_and_alert(client, setup_update_test_env):
    """Maintenance Mode ставит автовыдачу на паузу, сохраняется в БД и рассылает оповещение."""
    cardinal = setup_update_test_env

    # Создаем mock для перехвата событий SSE bridge
    bridge_events = []
    def mock_emit(evt, data):
        bridge_events.append((evt, data))
    with patch("carnaval.bridge.emit", side_effect=mock_emit):
        # 1. Включаем Maintenance Mode
        resp = client.post(
            "/api/system/maintenance",
            json={"enabled": True, "reason": "Server Migration V2"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["maintenance_mode"] is True
        assert data["reason"] == "Server Migration V2"

        # Персистентность в SQLite
        assert system_mode.is_maintenance_mode() is True
        assert get_state("maintenance_mode") == "1"
        assert get_state("maintenance_reason") == "Server Migration V2"

        # Проверка остановки автовыдачи
        assert system_mode.is_autodelivery_allowed() is False
        assert cardinal.autodelivery_enabled is False

        # Проверка рассылки предупреждения
        alert_event = next((d for evt, d in bridge_events if evt == "system.alert"), None)
        assert alert_event is not None
        assert alert_event["type"] == "maintenance_mode"
        assert alert_event["enabled"] is True
        assert alert_event["reason"] == "Server Migration V2"

        # Проверка отправки уведомления в Telegram bot Cardinal
        cardinal.telegram.send_notification.assert_called()

        # 2. Отключаем Maintenance Mode
        bridge_events.clear()
        resp_off = client.post("/api/system/maintenance", json={"enabled": False})
        assert resp_off.status_code == 200
        assert resp_off.json()["maintenance_mode"] is False
        assert system_mode.is_maintenance_mode() is False
        assert get_state("maintenance_mode") == "0"

        # Автовыдача возобновляется
        assert system_mode.is_autodelivery_allowed() is True
        assert cardinal.autodelivery_enabled is True


# ---------------------------------------------------------------------------
# 5. Тесты Pre-update бэкапа и восстановления
# ---------------------------------------------------------------------------

def test_pre_update_backup_creation_and_restoration():
    """Проверка автоматического создания pre-update бэкапа и безопасного восстановления."""
    # Создаем фиктивный конфигурационный файл для бэкапа
    import carnaval.paths as p
    test_cfg_path = os.path.join(p.CONFIGS_DIR, "test_config.cfg")
    with open(test_cfg_path, "w", encoding="utf-8") as f:
        f.write("[Section]\nkey = test_value\n")

    # Создаем pre-update бэкап
    backup_data = backup_svc.create_backup()
    assert isinstance(backup_data, bytes)
    assert len(backup_data) > 0

    # Проверяем структуру zip архива
    buf = io.BytesIO(backup_data)
    with zipfile.ZipFile(buf, "r") as zf:
        names = zf.namelist()
        assert any("test_config.cfg" in n for n in names)

    # Проверяем, что файл сохранен на диск в BACKUPS_DIR
    backups = backup_svc.list_backups()
    assert len(backups) >= 1
    assert any("pre_update" in b["filename"] for b in backups)

    # Модифицируем файл на диске
    with open(test_cfg_path, "w", encoding="utf-8") as f:
        f.write("[Section]\nkey = corrupted_value\n")

    # Восстанавливаем из бэкапа
    ok, err = backup_svc.restore_backup(backup_data)
    assert ok is True
    assert err == ""

    # Проверяем, что исходное значение восстановилось
    with open(test_cfg_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "test_value" in content


# ---------------------------------------------------------------------------
# 6. Тесты SHA-256 верификации
# ---------------------------------------------------------------------------

def test_sha256_verification_and_integrity_check():
    """Проверка строгости контроля SHA-256: отклонение поврежденных пакетов."""
    valid_payload = b"CarnavalValidBinaryPackageContent_12345"
    correct_sha256 = hashlib.sha256(valid_payload).hexdigest()

    manifest = generate_manifest(
        version="2.2.0",
        channel="stable",
        artifact_bytes=valid_payload,
    )
    assert manifest["artifact_sha256"] == correct_sha256.lower()

    # Корректный хэш проходит проверку
    ok_valid, _ = verify_manifest(manifest, valid_payload)
    assert ok_valid is True

    # Поврежденный байтовый поток не проходит проверку
    corrupt_payload = b"CarnavalCorruptedBinary_TAMPERED!"
    ok_corrupt, err_corrupt = verify_manifest(manifest, corrupt_payload)
    assert ok_corrupt is False
    assert "SHA-256 hash mismatch" in err_corrupt

    # Стадирование поврежденного пакета вызывает исключение
    with pytest.raises(ValueError) as excinfo:
        stage_update(manifest=manifest, artifact_bytes=corrupt_payload)
    assert "SHA-256 hash mismatch" in str(excinfo.value)
    assert get_update_status()["state"] == UpdateState.FAILED.value


# ---------------------------------------------------------------------------
# 7. Тесты раннера миграций схемы (V1 -> V2 -> V3)
# ---------------------------------------------------------------------------

def test_schema_migration_runner_v1_to_v3():
    """Раннер последовательно применяет миграции V1 -> V2 -> V3 и создает нужные таблицы."""
    # Принудительно выставляем версию схемы 1
    set_state("schema_version", "1")
    assert get_current_schema_version() == 1

    # Запускаем миграции до версии SCHEMA_VERSION (3)
    ok, msg = run_schema_migrations(target_version=SCHEMA_VERSION)
    assert ok is True
    assert "Successfully migrated schema to V3" in msg

    # Проверяем, что версия обновилась в БД
    assert get_current_schema_version() == SCHEMA_VERSION

    # Проверяем наличие созданных таблиц
    conn = get_db_connection()
    tables = [row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
    conn.close()

    assert "update_history" in tables
    assert "schema_migrations" in tables


# ---------------------------------------------------------------------------
# 8. Тесты установки и механизма Safe Rollback
# ---------------------------------------------------------------------------

def test_install_update_success(client):
    """Успешная установка валидного обновления обновляет версию и фиксирует историю."""
    package_bytes = b"CarnavalUpdate_v2.2.0_Valid_Content"
    manifest = generate_manifest("2.2.0", channel="stable", artifact_bytes=package_bytes)

    success, message, details = install_update(manifest=manifest, artifact_bytes=package_bytes)
    assert success is True
    assert "Successfully updated to 2.2.0" in message
    assert details["to_version"] == "2.2.0"
    assert get_state("app_version") == "2.2.0"
    assert get_state("backend_version") == "2.2.0"
    assert get_update_status()["state"] == UpdateState.READY.value

    # Проверка через эндпоинт
    resp = client.get("/api/updates/current")
    assert resp.status_code == 200
    assert resp.json()["app_version"] == "2.2.0"


def test_install_update_safe_rollback_on_failure():
    """При сбое миграции или health check система автоматически откатывается (Safe Rollback)."""
    set_state("app_version", "2.1.0")
    set_state("schema_version", "1")
    package_bytes = b"PackageToFail"
    manifest = generate_manifest("2.5.0", channel="stable", artifact_bytes=package_bytes)

    # 1. Сбой на этапе миграции
    success, msg, details = install_update(
        manifest=manifest,
        artifact_bytes=package_bytes,
        fail_on_migration=True,
    )
    assert success is False
    assert details.get("rolled_back") is True
    assert get_update_status()["state"] == UpdateState.FAILED.value
    # Версия осталась исходной (2.1.0)
    assert get_state("app_version") == "2.1.0"
    assert get_state("schema_version") == "1"

    # 2. Сбой на этапе Health Check
    success_hc, msg_hc, details_hc = install_update(
        manifest=manifest,
        artifact_bytes=package_bytes,
        fail_on_health=True,
    )
    assert success_hc is False
    assert details_hc.get("rolled_back") is True
    assert get_state("app_version") == "2.1.0"


def test_api_rollback_endpoint(client):
    """POST /api/updates/rollback выполняет ручной откат к бэкапу."""
    # Создаем бэкап
    backup_data = backup_svc.create_backup()

    resp = client.post("/api/updates/rollback", json={})
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert "Rollback completed successfully" in resp.json()["message"]


# ---------------------------------------------------------------------------
# 9. Тесты отслеживания статуса и переключения каналов
# ---------------------------------------------------------------------------

def test_update_status_and_channels(client):
    """Проверка переключения каналов (stable, beta, nightly) и получения статуса."""
    # Проверка GET /api/updates/status
    resp_status = client.get("/api/updates/status")
    assert resp_status.status_code == 200
    st = resp_status.json()
    assert "state" in st
    assert "progress_percent" in st
    assert "channel" in st

    # Смена канала на beta
    set_active_channel("beta")
    assert get_active_channel() == "beta"

    # Смена канала на nightly
    set_active_channel("nightly")
    assert get_active_channel() == "nightly"

    # Некорректный канал должен вызывать ошибку
    with pytest.raises(ValueError):
        set_active_channel("invalid_channel_name")

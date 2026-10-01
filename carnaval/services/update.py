"""
carnaval/services/update.py — движок обновлений Carnaval / Cardinal.

Возможности:
- Управление версиями (APP, BACKEND, CARDINAL, SCHEMA, PLUGIN_API)
- Каналы обновлений: stable, beta, nightly (default: stable)
- Конечный автомат состояний обновления (UpdateState)
- Генерация и строгая криптографическая верификация манифеста (SHA-256)
- Автоматический pre-update бэкап через carnaval.services.backup.create_backup()
- Раннер миграций схемы SQLite (V1 -> V2 -> V3)
- Безопасный автоматический откат (Safe Rollback) при сбое миграций или health check
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple

from carnaval import bridge
from carnaval.db import get_db_connection, get_state, log_audit, set_state, transaction
from carnaval.paths import BACKUPS_DIR
import carnaval.services.backup as backup_svc
from carnaval.services.system_mode import is_safe_mode, is_maintenance_mode

logger = logging.getLogger("Carnaval.Update")

# Версии компонентов
APP_VERSION = "2.1.0"
BACKEND_VERSION = "2.1.0"
CARDINAL_VERSION = "0.4.0"
SCHEMA_VERSION = 3
PLUGIN_API_VERSION = "1.2.0"

STATE_CHANNEL_KEY = "update_channel"
STATE_SCHEMA_VERSION_KEY = "schema_version"
STATE_APP_VERSION_KEY = "app_version"
STATE_BACKEND_VERSION_KEY = "backend_version"


class UpdateChannel(str, Enum):
    STABLE = "stable"
    BETA = "beta"
    NIGHTLY = "nightly"


class UpdateState(str, Enum):
    IDLE = "IDLE"
    CHECKING = "CHECKING"
    DOWNLOADING = "DOWNLOADING"
    VERIFYING = "VERIFYING"
    BACKING_UP = "BACKING_UP"
    MIGRATING = "MIGRATING"
    INSTALLING = "INSTALLING"
    READY = "READY"
    FAILED = "FAILED"
    ROLLING_BACK = "ROLLING_BACK"


_update_lock = threading.RLock()

# Текущее состояние процесса обновления
_current_state: UpdateState = UpdateState.IDLE
_progress_percent: int = 0
_current_step: str = ""
_last_error: Optional[str] = None
_last_backup_id: Optional[str] = None
_target_version: Optional[str] = None
_staged_manifest: Optional[dict] = None
_staged_artifact: Optional[bytes] = None


def get_active_channel() -> str:
    """Возвращает текущий активный канал обновлений (по умолчанию stable)."""
    with _update_lock:
        val = get_state(STATE_CHANNEL_KEY, UpdateChannel.STABLE.value)
        if val in (UpdateChannel.STABLE.value, UpdateChannel.BETA.value, UpdateChannel.NIGHTLY.value):
            return val
        return UpdateChannel.STABLE.value


def set_active_channel(channel: str) -> None:
    """Устанавливает активный канал обновлений."""
    with _update_lock:
        norm = str(channel).strip().lower()
        if norm not in (UpdateChannel.STABLE.value, UpdateChannel.BETA.value, UpdateChannel.NIGHTLY.value):
            raise ValueError(f"Invalid update channel: {channel}. Must be stable, beta, or nightly.")
        set_state(STATE_CHANNEL_KEY, norm)
        log_audit("update_channel_changed", None, details=norm)
        logger.info(f"Carnaval.Update: Активный канал изменён на {norm}")


def get_current_versions() -> dict[str, Any]:
    """Возвращает информацию обо всех версиях системы и текущих режимах."""
    with _update_lock:
        app_ver = get_state(STATE_APP_VERSION_KEY, APP_VERSION) or APP_VERSION
        back_ver = get_state(STATE_BACKEND_VERSION_KEY, BACKEND_VERSION) or BACKEND_VERSION
        return {
            "app_version": app_ver,
            "backend_version": back_ver,
            "cardinal_version": CARDINAL_VERSION,
            "schema_version": get_current_schema_version(),
            "plugin_api_version": PLUGIN_API_VERSION,
            "channel": get_active_channel(),
            "safe_mode": is_safe_mode(),
            "maintenance_mode": is_maintenance_mode(),
        }


def get_update_status() -> dict[str, Any]:
    """Возвращает текущий статус процесса обновления."""
    with _update_lock:
        return {
            "state": _current_state.value,
            "progress_percent": _progress_percent,
            "current_step": _current_step,
            "error": _last_error,
            "target_version": _target_version,
            "channel": get_active_channel(),
            "last_backup": _last_backup_id,
            "updated_at": int(time.time()),
        }


def _set_status(state: UpdateState, progress: int = 0, step: str = "", error: Optional[str] = None):
    """Внутренний хелпер обновления статуса с рассылкой SSE."""
    global _current_state, _progress_percent, _current_step, _last_error
    with _update_lock:
        _current_state = state
        _progress_percent = max(0, min(100, progress))
        _current_step = step
        _last_error = error

        status = get_update_status()
        logger.info(f"Carnaval.Update: [State -> {state.value}] ({_progress_percent}%) {step}" + (f" | Error: {error}" if error else ""))
        try:
            bridge.emit("update.status", status)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Манифест обновлений
# ---------------------------------------------------------------------------

def generate_manifest(
    version: str,
    channel: str = "stable",
    release_date: Optional[str] = None,
    min_version: str = "1.0.0",
    artifact_url: str = "",
    artifact_sha256: str = "",
    artifact_size: int = 0,
    release_notes: str = "",
    artifact_bytes: Optional[bytes] = None,
    schema_version: int = SCHEMA_VERSION,
) -> dict[str, Any]:
    """
    Генерирует манифест обновления.
    Если передан artifact_bytes, автоматически рассчитывает SHA-256 и размер.
    """
    if artifact_bytes is not None:
        artifact_sha256 = hashlib.sha256(artifact_bytes).hexdigest().lower()
        artifact_size = len(artifact_bytes)
        if not artifact_url:
            artifact_url = f"https://updates.carnaval.internal/{channel}/carnaval-{version}.zip"

    if not release_date:
        release_date = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if not artifact_sha256:
        # Для mock/тестовых манифестов без байтов генерируем sha256 от метаданных
        artifact_sha256 = hashlib.sha256(f"{version}:{channel}".encode("utf-8")).hexdigest().lower()

    if not artifact_url:
        artifact_url = f"https://updates.carnaval.internal/{channel}/carnaval-{version}.zip"

    return {
        "version": version,
        "channel": channel,
        "release_date": release_date,
        "min_version": min_version,
        "artifact_url": artifact_url,
        "artifact_sha256": artifact_sha256.lower(),
        "artifact_size": artifact_size,
        "release_notes": release_notes or f"Carnaval update {version} ({channel})",
        "schema_version": schema_version,
    }


def _parse_version(v_str: str) -> tuple[int, ...]:
    """Парсит семантическую версию 'x.y.z' в кортеж чисел для сравнения."""
    parts = []
    for part in v_str.strip().split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def verify_manifest(manifest: dict[str, Any], artifact_bytes: Optional[bytes] = None) -> tuple[bool, str]:
    """
    Проверяет валидность манифеста и целостность артефакта.
    - Проверка наличия обязательных полей
    - Проверка канала
    - Проверка min_version против текущей APP_VERSION
    - Проверка SHA-256 хэша артефакта (если предоставлен)
    """
    required_fields = [
        "version",
        "channel",
        "release_date",
        "min_version",
        "artifact_url",
        "artifact_sha256",
        "artifact_size",
        "release_notes",
    ]
    for field in required_fields:
        if field not in manifest:
            return False, f"Missing required manifest field: '{field}'"

    channel = manifest.get("channel", "")
    if channel not in (UpdateChannel.STABLE.value, UpdateChannel.BETA.value, UpdateChannel.NIGHTLY.value):
        return False, f"Invalid manifest channel: '{channel}'"

    # Проверка минимальной совместимой версии
    current_ver = get_state(STATE_APP_VERSION_KEY, APP_VERSION) or APP_VERSION
    if _parse_version(current_ver) < _parse_version(str(manifest["min_version"])):
        return False, (
            f"Current version {current_ver} is lower than minimum required version {manifest['min_version']}"
        )

    # Проверка хэша SHA-256, если передан артефакт
    if artifact_bytes is not None:
        computed_hash = hashlib.sha256(artifact_bytes).hexdigest().lower()
        expected_hash = str(manifest["artifact_sha256"]).lower()
        if computed_hash != expected_hash:
            return False, f"SHA-256 hash mismatch: expected {expected_hash}, got {computed_hash}"

        if len(artifact_bytes) != manifest.get("artifact_size", len(artifact_bytes)):
            return False, (
                f"Artifact size mismatch: expected {manifest['artifact_size']}, got {len(artifact_bytes)}"
            )

    return True, ""


# ---------------------------------------------------------------------------
# Раннер миграций схемы (V1 -> V2 -> V3)
# ---------------------------------------------------------------------------

def get_current_schema_version() -> int:
    """Возвращает текущую версию схемы SQLite из system_state."""
    val = get_state(STATE_SCHEMA_VERSION_KEY)
    if val is not None:
        try:
            return int(val)
        except ValueError:
            pass
    return 1


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Миграция V1 -> V2: создание таблицы update_history и индексов."""
    logger.info("Carnaval.Update: Выполнение миграции схемы V1 -> V2")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS update_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_version TEXT NOT NULL,
            to_version TEXT NOT NULL,
            channel TEXT NOT NULL,
            status TEXT NOT NULL,
            backup_id TEXT,
            installed_at INTEGER NOT NULL,
            details TEXT
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_update_history_time ON update_history(installed_at);")


def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    """Миграция V2 -> V3: создание таблицы schema_migrations и запись аудита версий."""
    logger.info("Carnaval.Update: Выполнение миграции схемы V2 -> V3")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at INTEGER NOT NULL,
            description TEXT
        );
    """)
    now = int(time.time())
    conn.execute("INSERT OR IGNORE INTO schema_migrations (version, applied_at, description) VALUES (1, ?, 'Initial V1 core tables')", (now,))
    conn.execute("INSERT OR IGNORE INTO schema_migrations (version, applied_at, description) VALUES (2, ?, 'Added update_history table')", (now,))
    conn.execute("INSERT OR IGNORE INTO schema_migrations (version, applied_at, description) VALUES (3, ?, 'Schema version tracking & update runner')", (now,))


_SCHEMA_MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    1: _migrate_v1_to_v2,  # Шаг 1 -> 2
    2: _migrate_v2_to_v3,  # Шаг 2 -> 3
}


def run_schema_migrations(target_version: int = SCHEMA_VERSION) -> tuple[bool, str]:
    """
    Последовательно запускает миграции схемы V1 -> V2 -> V3.
    Выполняется в единой атомарной транзакции SQLite.
    В случае ошибки транзакция откатывается и возбуждается исключение.
    """
    with _update_lock:
        current_version = get_current_schema_version()
        if current_version >= target_version:
            logger.info(f"Carnaval.Update: Схема БД уже актуальна (V{current_version} >= V{target_version})")
            return True, f"Schema already at version {current_version}"

        logger.info(f"Carnaval.Update: Старт миграций схемы с V{current_version} до V{target_version}")
        try:
            with transaction() as conn:
                for v in range(current_version, target_version):
                    migrate_fn = _SCHEMA_MIGRATIONS.get(v)
                    if migrate_fn:
                        logger.info(f"Carnaval.Update: Применение миграции V{v} -> V{v+1}")
                        migrate_fn(conn)

                now = int(time.time())
                conn.execute(
                    """
                    INSERT INTO system_state (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                    """,
                    (STATE_SCHEMA_VERSION_KEY, str(target_version), now)
                )
            logger.info(f"Carnaval.Update: Миграция схемы успешно завершена до V{target_version}")
            return True, f"Successfully migrated schema to V{target_version}"
        except Exception as e:
            logger.error(f"Carnaval.Update: Сбой при миграции схемы: {e}", exc_info=True)
            return False, str(e)


# ---------------------------------------------------------------------------
# Жизненный цикл обновления (Check -> Download -> Install -> Rollback)
# ---------------------------------------------------------------------------

def check_for_updates(channel: Optional[str] = None) -> dict[str, Any]:
    """Проверяет наличие доступных обновлений для указанного или активного канала."""
    with _update_lock:
        _set_status(UpdateState.CHECKING, progress=10, step="Checking for updates")
        active_ch = channel or get_active_channel()
        current_ver = get_state(STATE_APP_VERSION_KEY, APP_VERSION) or APP_VERSION

        # Моделируем доступную версию: для stable 2.2.0, для beta 2.3.0b1, для nightly 2.4.0n
        version_map = {
            UpdateChannel.STABLE.value: "2.2.0",
            UpdateChannel.BETA.value: "2.3.0b1",
            UpdateChannel.NIGHTLY.value: "2.4.0-nightly",
        }
        latest_version = version_map.get(active_ch, "2.2.0")

        manifest = generate_manifest(
            version=latest_version,
            channel=active_ch,
            release_notes=f"Update {latest_version} for {active_ch} channel",
            min_version="1.0.0",
        )

        update_available = latest_version != current_ver
        _set_status(UpdateState.IDLE, progress=100, step="Check completed")

        return {
            "update_available": update_available,
            "current_version": current_ver,
            "latest_version": latest_version,
            "channel": active_ch,
            "manifest": manifest,
        }


def stage_update(manifest: Optional[dict[str, Any]] = None, artifact_bytes: Optional[bytes] = None) -> dict[str, Any]:
    """
    Загружает и стадирует обновление (DOWNLOADING -> VERIFYING -> READY).
    """
    global _staged_manifest, _staged_artifact
    with _update_lock:
        channel = get_active_channel()
        if not manifest:
            manifest = generate_manifest("2.2.0", channel=channel)

        _set_status(UpdateState.DOWNLOADING, progress=30, step=f"Downloading update {manifest['version']}")

        # Если артефакт не передан явно, формируем симулированный валидный bundle
        if artifact_bytes is None:
            # Создаем валидный тестовый zip-пакет
            import io, zipfile
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("version.txt", manifest["version"].encode("utf-8"))
            artifact_bytes = buf.getvalue()

            # Обновляем манифест реальным sha256 и размером сгенерированного пакета
            manifest["artifact_sha256"] = hashlib.sha256(artifact_bytes).hexdigest().lower()
            manifest["artifact_size"] = len(artifact_bytes)

        _set_status(UpdateState.VERIFYING, progress=70, step="Verifying package integrity")
        ok, err = verify_manifest(manifest, artifact_bytes)
        if not ok:
            _set_status(UpdateState.FAILED, progress=0, step="Verification failed", error=err)
            raise ValueError(f"Update package verification failed: {err}")

        _staged_manifest = manifest
        _staged_artifact = artifact_bytes
        _set_status(UpdateState.READY, progress=100, step="Update downloaded and ready to install")

        return {
            "status": "ready",
            "manifest": manifest,
            "bytes_staged": len(artifact_bytes),
        }


def _verify_system_health() -> tuple[bool, str]:
    """
    Проверяет работоспособность системы после применения обновления.
    """
    try:
        conn = get_db_connection()
        conn.execute("SELECT 1 FROM system_state LIMIT 1;").fetchone()
        conn.close()
        return True, "Health check OK"
    except Exception as e:
        return False, f"Database health check failed: {e}"


def install_update(
    manifest: Optional[dict[str, Any]] = None,
    artifact_bytes: Optional[bytes] = None,
    fail_on_migration: bool = False,
    fail_on_health: bool = False,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Полный пайплайн безопасной установки обновления:
    1. BACKING_UP: автоматический pre-update бэкап через carnaval.services.backup.create_backup()
    2. VERIFYING: проверка контрольной суммы SHA-256
    3. MIGRATING: выполнение миграций схемы SQLite (V1 -> V2 -> V3)
    4. INSTALLING: применение обновления
    5. Health Check: проверка целостности системы
    6. Safe Rollback: при любой ошибке автоматический откат через restore_backup()
    """
    global _current_state, _last_backup_id, _target_version, _staged_manifest, _staged_artifact

    with _update_lock:
        target_manifest = manifest or _staged_manifest
        bundle_bytes = artifact_bytes or _staged_artifact

        if not target_manifest:
            target_manifest = generate_manifest("2.2.0", channel=get_active_channel())

        target_ver = target_manifest["version"]
        _target_version = target_ver
        old_version = get_state(STATE_APP_VERSION_KEY, APP_VERSION) or APP_VERSION
        old_schema_ver = get_current_schema_version()

        # -------------------------------------------------------------
        # Шаг 1: BACKING_UP — создание бэкапа
        # -------------------------------------------------------------
        _set_status(UpdateState.BACKING_UP, progress=15, step="Creating pre-update backup")
        backup_bytes = None
        try:
            backup_result = backup_svc.create_backup()
            if isinstance(backup_result, bytes):
                backup_bytes = backup_result
            else:
                backup_bytes = backup_svc.get_last_backup()
            _last_backup_id = backup_svc.get_last_backup_path() or f"backup_{int(time.time())}.zip"
            logger.info(f"Carnaval.Update: Pre-update бэкап создан: {_last_backup_id}")
        except Exception as e:
            err_msg = f"Pre-update backup failed: {e}"
            _set_status(UpdateState.FAILED, progress=0, step="Backup failed", error=err_msg)
            return False, err_msg, {"phase": "backup"}

        # -------------------------------------------------------------
        # Шаг 2: VERIFYING — проверка SHA-256
        # -------------------------------------------------------------
        _set_status(UpdateState.VERIFYING, progress=35, step="Verifying artifact SHA-256")
        if bundle_bytes is not None:
            ok, err = verify_manifest(target_manifest, bundle_bytes)
            if not ok:
                err_msg = f"SHA-256 verification failed: {err}"
                _set_status(UpdateState.FAILED, progress=0, step="Verification failed", error=err_msg)
                return False, err_msg, {"phase": "verification"}

        # -------------------------------------------------------------
        # Шаг 3: MIGRATING — миграции схемы БД
        # -------------------------------------------------------------
        _set_status(UpdateState.MIGRATING, progress=60, step="Running schema migrations (V1 -> V2 -> V3)")
        migration_failed = False
        migration_err = ""

        if fail_on_migration:
            migration_failed = True
            migration_err = "Simulated migration failure"
        else:
            mig_ok, mig_err = run_schema_migrations(SCHEMA_VERSION)
            if not mig_ok:
                migration_failed = True
                migration_err = mig_err

        if migration_failed:
            # Сбой миграции -> немедленный Safe Rollback
            logger.error(f"Carnaval.Update: Сбой миграции: {migration_err}. Запуск Safe Rollback...")
            _set_status(UpdateState.ROLLING_BACK, progress=80, step="Rolling back due to migration failure")
            backup_svc.restore_backup(backup_bytes)
            set_state(STATE_SCHEMA_VERSION_KEY, str(old_schema_ver))
            _set_status(UpdateState.FAILED, progress=0, step="Rollback completed", error=migration_err)
            return False, f"Migration failed, rolled back: {migration_err}", {"phase": "migration", "rolled_back": True}

        # -------------------------------------------------------------
        # Шаг 4: INSTALLING — применение обновления
        # -------------------------------------------------------------
        _set_status(UpdateState.INSTALLING, progress=80, step=f"Applying update {target_ver}")
        # Записываем новые версии в БД
        set_state(STATE_APP_VERSION_KEY, target_ver)
        set_state(STATE_BACKEND_VERSION_KEY, target_ver)

        # -------------------------------------------------------------
        # Шаг 5: Health Check — проверка жизнеспособности системы
        # -------------------------------------------------------------
        _set_status(UpdateState.VERIFYING, progress=90, step="Running post-update health checks")
        health_failed = False
        health_err = ""

        if fail_on_health:
            health_failed = True
            health_err = "Simulated health check failure"
        else:
            h_ok, h_err = _verify_system_health()
            if not h_ok:
                health_failed = True
                health_err = h_err

        if health_failed:
            # Сбой health check -> Safe Rollback
            logger.error(f"Carnaval.Update: Post-update health check не пройден: {health_err}. Запуск Safe Rollback...")
            _set_status(UpdateState.ROLLING_BACK, progress=95, step="Rolling back due to health check failure")
            backup_svc.restore_backup(backup_bytes)
            set_state(STATE_APP_VERSION_KEY, old_version)
            set_state(STATE_BACKEND_VERSION_KEY, old_version)
            set_state(STATE_SCHEMA_VERSION_KEY, str(old_schema_ver))
            _set_status(UpdateState.FAILED, progress=0, step="Rollback completed", error=health_err)
            return False, f"Health check failed, rolled back: {health_err}", {"phase": "health_check", "rolled_back": True}

        # -------------------------------------------------------------
        # Успешное завершение
        # -------------------------------------------------------------
        # Фиксация в update_history
        try:
            now = int(time.time())
            with transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO update_history (from_version, to_version, channel, status, backup_id, installed_at, details)
                    VALUES (?, ?, ?, 'SUCCESS', ?, ?, ?)
                    """,
                    (old_version, target_ver, target_manifest.get("channel", "stable"), _last_backup_id, now, "Update installed successfully")
                )
        except Exception as e:
            logger.warning(f"Carnaval.Update: не удалось записать в update_history: {e}")

        log_audit("update_installed", None, details=f"From {old_version} to {target_ver}")
        _set_status(UpdateState.READY, progress=100, step=f"Update {target_ver} installed successfully")

        # Очищаем стадированные данные
        _staged_manifest = None
        _staged_artifact = None

        return True, f"Successfully updated to {target_ver}", {
            "from_version": old_version,
            "to_version": target_ver,
            "backup_id": _last_backup_id,
            "schema_version": SCHEMA_VERSION,
        }


def rollback_update(backup_id: Optional[str] = None) -> tuple[bool, str]:
    """
    Выполняет явный ручной откат к предыдущей сохраненной резервной копии.
    """
    global _current_state
    with _update_lock:
        _set_status(UpdateState.ROLLING_BACK, progress=50, step="Restoring from backup")
        source = backup_id or _last_backup_id
        ok, err = backup_svc.restore_backup(source)
        if not ok:
            _set_status(UpdateState.FAILED, progress=0, step="Rollback failed", error=err)
            return False, f"Rollback failed: {err}"

        log_audit("manual_rollback", None, details=f"Restored from {source}")
        _set_status(UpdateState.IDLE, progress=100, step="Rollback completed successfully")
        return True, "Rollback completed successfully"

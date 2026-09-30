"""
carnaval/db.py — работа с локальной базой данных SQLite.

Особенности:
- Режим WAL (Write-Ahead Logging) для безопасного конкурентного доступа
- Включенные foreign_keys и busy_timeout = 5000ms
- Таблицы: system_state, users, sessions, secrets, audit_logs, rate_limits
- Атомарные транзакции через контекстный менеджер
"""

from __future__ import annotations

import sqlite3
import time
import logging
from contextlib import contextmanager
from typing import Generator, Optional

from carnaval.paths import DB_PATH, init_persistent_dirs

logger = logging.getLogger("Carnaval.DB")


def get_db_connection() -> sqlite3.Connection:
    """Создает и настраивает соединение с базой данных."""
    from carnaval import paths
    paths.init_persistent_dirs()
    conn = sqlite3.connect(paths.DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


@contextmanager
def transaction() -> Generator[sqlite3.Connection, None, None]:
    """Контекстный менеджер для атомарных транзакций."""
    conn = get_db_connection()
    try:
        conn.execute("BEGIN IMMEDIATE;")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Инициализация схемы базы данных."""
    init_persistent_dirs()
    conn = get_db_connection()
    try:
        with conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS system_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                telegram_user_id INTEGER PRIMARY KEY,
                role TEXT NOT NULL DEFAULT 'user',
                first_name TEXT,
                username TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS sessions (
                session_id_hash TEXT PRIMARY KEY,
                telegram_user_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                last_seen_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                revoked_at INTEGER,
                panel_unlocked INTEGER NOT NULL DEFAULT 0,
                unlocked_at INTEGER,
                ip TEXT,
                user_agent_hash TEXT,
                FOREIGN KEY (telegram_user_id) REFERENCES users (telegram_user_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(telegram_user_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

            CREATE TABLE IF NOT EXISTS secrets (
                name TEXT PRIMARY KEY,
                ciphertext BLOB NOT NULL,
                nonce BLOB NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                telegram_user_id INTEGER,
                ip TEXT,
                details TEXT,
                created_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_logs(created_at);

            CREATE TABLE IF NOT EXISTS rate_limits (
                key TEXT PRIMARY KEY,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_attempt INTEGER NOT NULL,
                blocked_until INTEGER NOT NULL DEFAULT 0
            );
            """)

            # Инициализация дефолтного состояния системы если не существует
            cur = conn.execute("SELECT value FROM system_state WHERE key = 'state'")
            if not cur.fetchone():
                now = int(time.time())
                conn.execute(
                    "INSERT INTO system_state (key, value, updated_at) VALUES ('state', 'UNINITIALIZED', ?)",
                    (now,)
                )
        logger.info("Carnaval.DB: схема базы данных успешно проверена/инициализирована")
    finally:
        conn.close()


def get_state(key: str, default: Optional[str] = None) -> Optional[str]:
    """Получает значение из system_state."""
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT value FROM system_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default
    finally:
        conn.close()


def set_state(key: str, value: str) -> None:
    """Устанавливает значение в system_state."""
    now = int(time.time())
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO system_state (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now)
        )


def log_audit(action: str, telegram_user_id: Optional[int], ip: str = "", details: str = "") -> None:
    """
    Записывает аудит-событие в БД.
    НИКОГДА не сохраняет пароли, токены или ключи.
    """
    now = int(time.time())
    try:
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO audit_logs (action, telegram_user_id, ip, details, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (action, telegram_user_id, ip, details, now)
            )
    except Exception as e:
        logger.warning(f"Carnaval.DB: не удалось записать аудит: {e}")

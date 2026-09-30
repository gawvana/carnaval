"""
carnaval/secrets_manager.py — централизованный сервис безопасного хранения секретов.

Криптография:
- AES-256-GCM (Authenticated Encryption with Associated Data).
- Мастер-ключ 256 бит (32 байта) в data/secrets/master.key (0600).
- Случайный 96-битный nonce для каждой операции шифрования.
- Никогда не логирует и не возвращает открытые секреты в API.
"""

from __future__ import annotations

import os
import secrets
import time
import logging
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from carnaval.paths import MASTER_KEY_PATH, SECRETS_DIR, init_persistent_dirs
from carnaval.db import get_db_connection, transaction

logger = logging.getLogger("Carnaval.Secrets")

_master_key: Optional[bytes] = None


def _get_or_create_master_key() -> bytes:
    """
    Загружает существующий мастер-ключ или безопасно генерирует новый при первом запуске.
    Никогда не перезаписывает поврежденный ключ тихо.
    """
    global _master_key
    if _master_key is not None:
        return _master_key

    init_persistent_dirs()

    if os.path.exists(MASTER_KEY_PATH):
        with open(MASTER_KEY_PATH, "rb") as f:
            key = f.read()
        if len(key) != 32:
            logger.critical("Carnaval.Secrets: мастер-ключ поврежден или имеет неверную длину!")
            raise RuntimeError("Master encryption key is corrupted. Manual recovery required.")
        _master_key = key
        return _master_key

    # Создание нового мастер-ключа
    key = secrets.token_bytes(32)
    fd = os.open(MASTER_KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)

    if os.name != "nt":
        try:
            os.chmod(MASTER_KEY_PATH, 0o600)
        except Exception:
            pass

    logger.info("Carnaval.Secrets: мастер-ключ шифрования успешно создан")
    _master_key = key
    return _master_key


class SecretManager:
    """Менеджер шифрования и хранения секретов приложения."""

    @staticmethod
    def set_secret(name: str, value: str) -> None:
        """Шифрует и сохраняет секрет в базу данных."""
        if not name or not isinstance(name, str):
            raise ValueError("Secret name must be non-empty string")
        if value is None:
            raise ValueError("Secret value cannot be None")

        key = _get_or_create_master_key()
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, value.encode("utf-8"), None)
        now = int(time.time())

        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO secrets (name, ciphertext, nonce, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    ciphertext = excluded.ciphertext,
                    nonce = excluded.nonce,
                    updated_at = excluded.updated_at
                """,
                (name, ciphertext, nonce, now, now)
            )

    @staticmethod
    def get_secret(name: str) -> Optional[str]:
        """Расшифровывает и возвращает секрет только для внутренних нужд backend."""
        conn = get_db_connection()
        try:
            row = conn.execute("SELECT ciphertext, nonce FROM secrets WHERE name = ?", (name,)).fetchone()
            if not row:
                return None
            key = _get_or_create_master_key()
            aesgcm = AESGCM(key)
            plaintext = aesgcm.decrypt(row["nonce"], row["ciphertext"], None)
            return plaintext.decode("utf-8")
        except Exception as e:
            logger.error(f"Carnaval.Secrets: ошибка расшифровки секрета '{name}': {e}")
            return None
        finally:
            conn.close()

    @staticmethod
    def has_secret(name: str) -> bool:
        """Проверяет, настроен ли данный секрет (без расшифровки)."""
        conn = get_db_connection()
        try:
            row = conn.execute("SELECT 1 FROM secrets WHERE name = ?", (name,)).fetchone()
            return row is not None
        finally:
            conn.close()

    @staticmethod
    def delete_secret(name: str) -> bool:
        """Безопасно удаляет секрет из базы данных."""
        with transaction() as conn:
            cur = conn.execute("DELETE FROM secrets WHERE name = ?", (name,))
            return cur.rowcount > 0

    @staticmethod
    def list_configured_secrets() -> list[str]:
        """Возвращает список имен настроенных секретов (без значений)."""
        conn = get_db_connection()
        try:
            rows = conn.execute("SELECT name FROM secrets ORDER BY name ASC").fetchall()
            return [r["name"] for r in rows]
        finally:
            conn.close()

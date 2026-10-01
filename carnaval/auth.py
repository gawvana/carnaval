"""
carnaval/auth.py — серверная аутентификация Telegram Mini App и управление сессиями.

Функционал:
1. Официальная криптографическая проверка Telegram initData (HMAC-SHA256)
2. Защита от Replay Attack (валидация auth_date, допуск 1 час, clock skew 300 сек)
3. Безопасные серверные сессии (хранение sha256 хеша в SQLite, HttpOnly cookie)
4. Двухуровневая авторизация: Telegram Authentication + Panel Security Unlock
5. Rate limiting и защита от подбора паролей с временной блокировкой
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Optional, Tuple
from urllib.parse import parse_qsl

from carnaval.db import get_db_connection, transaction, log_audit
from carnaval.security_utils import verify_password

logger = logging.getLogger("Carnaval.Auth")

# Константы сессий и авторизации
SESSION_TTL = 14400       # 4 часа максимальный срок жизни
SESSION_IDLE_TIMEOUT = 1800  # 30 минут неактивности
PANEL_UNLOCK_TTL = 1800   # 30 минут после ввода пароля панели
MAX_AUTH_DATE_AGE = 3600  # 1 час макс возраст initData
MAX_LOGIN_ATTEMPTS = 5    # Попыток до блокировки
LOCKOUT_DURATION = 300    # 5 минут блокировки при превышении


# ─────────────────────────────────────────────────────────────
# 1. Проверка Telegram Mini App initData
# ─────────────────────────────────────────────────────────────

def verify_telegram_init_data(raw_init_data: str, bot_token: str) -> Optional[dict]:
    """
    Проверяет подпись Telegram Mini App по официальному алгоритму Telegram:
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

    Возвращает dict с данными пользователя (id, username, first_name) или None.
    """
    if not raw_init_data or not bot_token:
        return None

    try:
        parsed_qsl = parse_qsl(raw_init_data, keep_blank_values=True)
        data_dict = dict(parsed_qsl)
    except Exception:
        return None

    received_hash = data_dict.pop("hash", None)
    if not received_hash:
        return None

    # Проверка auth_date на Replay Attack
    try:
        auth_date = int(data_dict.get("auth_date", 0))
    except (ValueError, TypeError):
        return None

    now = int(time.time())
    # Защита от устаревших initData и сдвига часов (+- 300 сек)
    if (now - auth_date) > MAX_AUTH_DATE_AGE or (auth_date - now) > 300:
        logger.warning(f"Carnaval.Auth: initData отклонена по сроку жизни (auth_date={auth_date}, now={now})")
        return None

    # Построение строки проверки
    items = sorted([f"{k}={v}" for k, v in data_dict.items()])
    data_check_string = "\n".join(items).encode("utf-8")

    # Секретный ключ Telegram WebAppData
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(received_hash, expected_hash):
        logger.warning("Carnaval.Auth: неверная HMAC-SHA256 подпись initData")
        return None

    # Извлечение данных пользователя
    user_str = data_dict.get("user")
    if not user_str:
        return None

    try:
        user_data = json.loads(user_str)
        if not isinstance(user_data, dict) or "id" not in user_data:
            return None
        res_dict = dict(user_data)
        res_dict["user"] = user_data
        return res_dict
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# 2. Управление серверными сессиями
# ─────────────────────────────────────────────────────────────

def init(secret: Optional[str] = None) -> None:
    """Для обратной совместимости с тестами и ранними версиями."""
    from carnaval.db import init_db
    init_db()


def create_token(user_id: int, role: str = "user") -> str:
    """Для обратной совместимости: создает серверную сессию в SQLite."""
    from carnaval.db import init_db
    init_db()
    token = create_session(user_id)
    if role != "user":
        with transaction() as conn:
            conn.execute(
                "UPDATE users SET role = ?, updated_at = ? WHERE telegram_user_id = ?",
                (role, int(time.time()), user_id)
            )
    return token


def verify_token(token: str) -> Optional[int]:
    """Для обратной совместимости: возвращает user_id или None."""
    session = get_session(token)
    if session:
        return session["telegram_user_id"]
    return None


def verify_init_data(raw_init_data: str, bot_token: str) -> Optional[dict]:
    """Алиас для verify_telegram_init_data для обратной совместимости."""
    return verify_telegram_init_data(raw_init_data, bot_token)


def _hash_session_token(token: str) -> str:
    """Хеширует токен сессии через SHA-256 для безопасного поиска в БД."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(telegram_user_id: int, ip: str = "", user_agent: str = "") -> str:
    """
    Создает новую сессию для пользователя Telegram.
    Возвращает сырой session_token (передается клиенту в HttpOnly cookie).
    В базе сохраняется только SHA-256 хеш.
    """
    from carnaval.db import init_db
    init_db()

    token = f"{telegram_user_id}.{secrets.token_urlsafe(32)}"
    token_hash = _hash_session_token(token)
    now = int(time.time())
    expires = now + SESSION_TTL
    ua_hash = hashlib.sha256(user_agent.encode("utf-8")).hexdigest() if user_agent else ""

    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO users (telegram_user_id, role, created_at, updated_at)
            VALUES (?, 'user', ?, ?)
            ON CONFLICT(telegram_user_id) DO NOTHING
            """,
            (telegram_user_id, now, now)
        )
        conn.execute(
            """
            INSERT INTO sessions (
                session_id_hash, telegram_user_id, created_at,
                last_seen_at, expires_at, panel_unlocked, ip, user_agent_hash
            )
            VALUES (?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (token_hash, telegram_user_id, now, now, expires, ip, ua_hash)
        )

    log_audit("session_created", telegram_user_id, ip, "Новая сессия Telegram Mini App")
    return token


def get_session(session_token: str) -> Optional[dict]:
    """
    Находит и валидирует активную сессию.
    Проверяет срок жизни и idle timeout.
    Обновляет last_seen_at.
    """
    if not session_token or not isinstance(session_token, str):
        return None

    token_hash = _hash_session_token(session_token)
    now = int(time.time())

    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT s.*, COALESCE(u.role, 'user') as role
            FROM sessions s
            LEFT JOIN users u ON s.telegram_user_id = u.telegram_user_id
            WHERE s.session_id_hash = ? AND s.revoked_at IS NULL
            """,
            (token_hash,)
        ).fetchone()

        if not row:
            return None

        # Проверка абсолютного срока жизни
        if now > row["expires_at"]:
            return None

        # Проверка таймаута неактивности (30 мин)
        if (now - row["last_seen_at"]) > SESSION_IDLE_TIMEOUT:
            return None

        # Проверка таймаута разблокировки панели (если разблокирована)
        panel_unlocked = bool(row["panel_unlocked"])
        if panel_unlocked and row["unlocked_at"]:
            if (now - row["unlocked_at"]) > PANEL_UNLOCK_TTL:
                panel_unlocked = False

        # Обновляем last_seen_at и сбрасываем panel_unlocked при истечении таймаута
        with conn:
            conn.execute(
                """
                UPDATE sessions
                SET last_seen_at = ?, panel_unlocked = ?
                WHERE session_id_hash = ?
                """,
                (now, 1 if panel_unlocked else 0, token_hash)
            )

        return {
            "session_id_hash": row["session_id_hash"],
            "telegram_user_id": row["telegram_user_id"],
            "role": row["role"],
            "panel_unlocked": panel_unlocked,
            "created_at": row["created_at"],
            "ip": row["ip"],
        }
    finally:
        conn.close()


def unlock_panel_session(session_token: str) -> bool:
    """Разблокирует чувствительные разделы панели для текущей сессии."""
    token_hash = _hash_session_token(session_token)
    now = int(time.time())

    with transaction() as conn:
        cur = conn.execute(
            """
            UPDATE sessions
            SET panel_unlocked = 1, unlocked_at = ?
            WHERE session_id_hash = ? AND revoked_at IS NULL
            """,
            (now, token_hash)
        )
        return cur.rowcount > 0


def lock_panel_session(session_token: str) -> bool:
    """Блокирует чувствительные разделы панели для текущей сессии (Lock Panel)."""
    token_hash = _hash_session_token(session_token)

    with transaction() as conn:
        cur = conn.execute(
            """
            UPDATE sessions
            SET panel_unlocked = 0, unlocked_at = NULL
            WHERE session_id_hash = ? AND revoked_at IS NULL
            """,
            (token_hash,)
        )
        return cur.rowcount > 0


def revoke_session(session_token: str) -> bool:
    """Отзывает текущую сессию (Logout)."""
    token_hash = _hash_session_token(session_token)
    now = int(time.time())

    with transaction() as conn:
        cur = conn.execute(
            "UPDATE sessions SET revoked_at = ? WHERE session_id_hash = ?",
            (now, token_hash)
        )
        return cur.rowcount > 0


def revoke_all_user_sessions(telegram_user_id: int, keep_token_hash: Optional[str] = None) -> int:
    """Отзывает все сессии пользователя (Logout from all devices)."""
    now = int(time.time())

    with transaction() as conn:
        if keep_token_hash:
            cur = conn.execute(
                """
                UPDATE sessions
                SET revoked_at = ?
                WHERE telegram_user_id = ? AND revoked_at IS NULL AND session_id_hash != ?
                """,
                (now, telegram_user_id, keep_token_hash)
            )
        else:
            cur = conn.execute(
                """
                UPDATE sessions
                SET revoked_at = ?
                WHERE telegram_user_id = ? AND revoked_at IS NULL
                """,
                (now, telegram_user_id)
            )
        return cur.rowcount


def list_user_sessions(telegram_user_id: int) -> list[dict]:
    """Возвращает список всех активных сессий пользователя для страницы безопасности."""
    now = int(time.time())
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT session_id_hash, created_at, last_seen_at, ip, panel_unlocked
            FROM sessions
            WHERE telegram_user_id = ? AND revoked_at IS NULL AND expires_at > ?
            ORDER BY last_seen_at DESC
            """,
            (telegram_user_id, now)
        ).fetchall()
        return [
            {
                "session_id_short": r["session_id_hash"][:8],
                "created_at": r["created_at"],
                "last_seen_at": r["last_seen_at"],
                "ip": r["ip"],
                "panel_unlocked": bool(r["panel_unlocked"]),
            }
            for r in rows
        ]
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────
# 3. Rate limiting и защита от подбора пароля
# ─────────────────────────────────────────────────────────────

def check_login_rate_limit(key: str) -> Tuple[bool, int]:
    """
    Проверяет, заблокирован ли ключ (IP или user_id).
    Возвращает (is_allowed, seconds_remaining).
    """
    now = int(time.time())
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT attempts, last_attempt, blocked_until FROM rate_limits WHERE key = ?",
            (key,)
        ).fetchone()

        if not row:
            return True, 0

        blocked_until = row["blocked_until"]
        if blocked_until > now:
            return False, blocked_until - now

        return True, 0
    finally:
        conn.close()


def record_failed_attempt(key: str) -> Tuple[bool, int]:
    """
    Записывает неудачную попытку входа.
    При превышении лимита блокирует на LOCKOUT_DURATION.
    Возвращает (is_blocked_now, seconds_blocked).
    """
    now = int(time.time())
    with transaction() as conn:
        row = conn.execute("SELECT attempts FROM rate_limits WHERE key = ?", (key,)).fetchone()
        attempts = (row["attempts"] + 1) if row else 1
        blocked_until = (now + LOCKOUT_DURATION) if attempts >= MAX_LOGIN_ATTEMPTS else 0

        conn.execute(
            """
            INSERT INTO rate_limits (key, attempts, last_attempt, blocked_until)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                attempts = excluded.attempts,
                last_attempt = excluded.last_attempt,
                blocked_until = excluded.blocked_until
            """,
            (key, attempts, now, blocked_until)
        )

        if attempts >= MAX_LOGIN_ATTEMPTS:
            return True, LOCKOUT_DURATION
        return False, 0


def reset_rate_limit(key: str) -> None:
    """Сбрасывает счетчик неудачных попыток при успешном входе."""
    with transaction() as conn:
        conn.execute("DELETE FROM rate_limits WHERE key = ?", (key,))

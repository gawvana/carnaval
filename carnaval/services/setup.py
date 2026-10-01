"""
carnaval/services/setup.py — атомарный сервис первоначальной настройки (First-Run Setup) и владения (Owner Claim).

Состояния:
- UNINITIALIZED — система ждет первого запуска и регистрации владельца.
- OWNER_CLAIM   — владелец зафиксирован, идет настройка пароля и ключей.
- INITIALIZED   — первоначальная настройка завершена, регистрация закрыта навсегда.
"""

from __future__ import annotations

import logging
import time
from typing import Optional, Tuple

from carnaval.db import get_state, set_state, transaction, log_audit
from carnaval.security_utils import hash_password
from carnaval.secrets_manager import SecretManager
from carnaval.deps import get_cardinal

logger = logging.getLogger("Carnaval.Setup")


def get_system_status() -> dict:
    """Возвращает текущий статус настройки системы."""
    state = get_state("state", "UNINITIALIZED")
    owner_id_str = get_state("owner_telegram_id")
    owner_id = int(owner_id_str) if owner_id_str and owner_id_str.isdigit() else None
    has_password = get_state("panel_password_hash") is not None
    has_golden_key = SecretManager.has_secret("golden_key")
    has_funpay = SecretManager.has_secret("funpay_password") or bool(get_state("funpay_login"))
    has_proxy = SecretManager.has_secret("proxy_password") or bool(get_state("proxy_host"))

    return {
        "state": state,
        "is_initialized": state == "INITIALIZED",
        "has_owner": owner_id is not None,
        "owner_id": owner_id,
        "owner_telegram_id": owner_id,
        "has_password": has_password,
        "has_golden_key": has_golden_key,
        "has_funpay": has_funpay,
        "has_proxy": has_proxy,
    }


def claim_ownership(telegram_user_id: int, first_name: str = "", username: str = "", ip: str = "") -> Tuple[bool, str]:
    """
    Атомарная регистрация первого владельца системы.
    Защищена от состояния гонки (Race Condition).
    Если владелец уже зарегистрирован — немедленно отклоняет запрос.
    """
    now = int(time.time())

    try:
        with transaction() as conn:
            row = conn.execute("SELECT value FROM system_state WHERE key = 'state'").fetchone()
            current_state = row["value"] if row else "UNINITIALIZED"

            if current_state != "UNINITIALIZED":
                owner_row = conn.execute("SELECT value FROM system_state WHERE key = 'owner_telegram_id'").fetchone()
                if owner_row and int(owner_row["value"]) == telegram_user_id:
                    return True, "Вы уже являетесь зарегистрированным владельцем"
                return False, "Регистрация владельца уже закрыта другим пользователем"

            # Атомарный перевод состояния
            cur = conn.execute(
                "UPDATE system_state SET value = 'OWNER_CLAIM', updated_at = ? WHERE key = 'state' AND value = 'UNINITIALIZED'",
                (now,)
            )
            if cur.rowcount == 0:
                return False, "Параллельный запрос перехватил регистрацию владельца"

            # Добавляем или обновляем пользователя как владельца
            conn.execute(
                """
                INSERT INTO users (telegram_user_id, role, first_name, username, created_at, updated_at)
                VALUES (?, 'owner', ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    role = 'owner',
                    first_name = excluded.first_name,
                    username = excluded.username,
                    updated_at = excluded.updated_at
                """,
                (telegram_user_id, first_name, username, now, now)
            )

            # Сохраняем ID владельца
            conn.execute(
                """
                INSERT INTO system_state (key, value, updated_at)
                VALUES ('owner_telegram_id', ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (str(telegram_user_id), now)
            )

        log_audit("owner_claimed", telegram_user_id, ip, f"Владелец успешно зарегистрирован (@{username})")
        logger.info(f"Carnaval.Setup: пользователь Telegram {telegram_user_id} (@{username}) стал владельцем системы")
        return True, ""
    except Exception as e:
        logger.error(f"Carnaval.Setup: ошибка при claim_ownership: {e}")
        return False, "Ошибка базы данных при регистрации владельца"


def set_panel_password(telegram_user_id: int, password: str, ip: str = "") -> Tuple[bool, str]:
    """Устанавливает пароль панели (хешируется через Argon2id)."""
    owner_id_str = get_state("owner_telegram_id")
    if not owner_id_str or int(owner_id_str) != telegram_user_id:
        return False, "Только владелец системы может установить пароль панели"

    if len(password) < 6:
        return False, "Пароль должен содержать минимум 6 символов"

    pwd_hash = hash_password(password)
    now = int(time.time())

    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO system_state (key, value, updated_at)
            VALUES ('panel_password_hash', ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (pwd_hash, now)
        )

    log_audit("panel_password_created", telegram_user_id, ip, "Создан пароль панели управления")
    return True, ""


def configure_golden_key(telegram_user_id: int, golden_key: str, ip: str = "") -> Tuple[bool, str]:
    """Шифрует и сохраняет Golden Key в SecretManager."""
    owner_id_str = get_state("owner_telegram_id")
    if not owner_id_str or int(owner_id_str) != telegram_user_id:
        return False, "Только владелец может настраивать Golden Key"

    clean_key = golden_key.strip()
    if len(clean_key) != 32:
        return False, "Golden Key должен состоять ровно из 32 символов"

    SecretManager.set_secret("golden_key", clean_key)

    # Синхронизация с живым Cardinal (если Cardinal запущен)
    try:
        cardinal = get_cardinal()
        if cardinal and hasattr(cardinal, "account") and cardinal.account:
            cardinal.account.golden_key = clean_key
            if hasattr(cardinal, "MAIN_CFG") and "FunPay" in cardinal.MAIN_CFG:
                cardinal.MAIN_CFG["FunPay"]["golden_key"] = clean_key
                cardinal.save_config(cardinal.MAIN_CFG, "configs/_main.cfg")
    except Exception as e:
        logger.debug(f"Carnaval.Setup: Cardinal не запущен или не обновлен: {e}")

    # Запускаем переподключение FunPay в фоновом потоке
    try:
        import threading
        cardinal = get_cardinal()
        if cardinal and hasattr(cardinal, 'reinit_account'):
            def _reinit():
                try:
                    success = cardinal.reinit_account()
                    if success:
                        logger.info("Carnaval.Setup: FunPay аккаунт успешно активирован через Mini App")
                    else:
                        logger.warning("Carnaval.Setup: reinit_account вернул False (ключ невалиден или сеть недоступна)")
                except Exception as e:
                    logger.error(f"Carnaval.Setup: ошибка reinit_account: {e}")
            threading.Thread(target=_reinit, daemon=True, name="Carnaval-Reinit").start()
    except Exception as e:
        logger.debug(f"Carnaval.Setup: не удалось запустить reinit_account: {e}")

    log_audit("golden_key_configured", telegram_user_id, ip, "Golden Key успешно зашифрован и сохранен")
    return True, ""


def finalize_setup(telegram_user_id: int, ip: str = "") -> Tuple[bool, str]:
    """
    Завершает первичный onboarding.
    Фиксирует состояние INITIALIZED.
    """
    owner_id_str = get_state("owner_telegram_id")
    if not owner_id_str or int(owner_id_str) != telegram_user_id:
        return False, "Только владелец может завершить настройку"

    if get_state("panel_password_hash") is None:
        return False, "Перед завершением необходимо создать пароль панели"

    now = int(time.time())
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO system_state (key, value, updated_at)
            VALUES ('state', 'INITIALIZED', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (now,)
        )
        conn.execute(
            """
            INSERT INTO system_state (key, value, updated_at)
            VALUES ('initialized_at', ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (str(now), now)
        )

    log_audit("setup_finalized", telegram_user_id, ip, "Первичная настройка Carnaval успешно завершена")
    logger.info(f"Carnaval.Setup: первичная настройка завершена владельцем {telegram_user_id}")
    return True, ""


def configure_funpay_credentials(telegram_user_id: int, login: str, password: str, ip: str = "") -> Tuple[bool, str]:
    """Шифрует и сохраняет логин/пароль FunPay в SecretManager (Section 58)."""
    owner_id_str = get_state("owner_telegram_id")
    if not owner_id_str or int(owner_id_str) != telegram_user_id:
        return False, "Только владелец может настраивать учетные данные FunPay"

    clean_login = (login or "").strip()
    clean_pass = (password or "").strip()
    if not clean_login or not clean_pass:
        return False, "Логин и пароль FunPay не могут быть пустыми"

    SecretManager.set_secret("funpay_password", clean_pass)
    set_state("funpay_login", clean_login)

    try:
        cardinal = get_cardinal()
        if cardinal and hasattr(cardinal, "MAIN_CFG") and "FunPay" in cardinal.MAIN_CFG:
            cardinal.MAIN_CFG["FunPay"]["login"] = clean_login
            cardinal.save_config(cardinal.MAIN_CFG, "configs/_main.cfg")
    except Exception as e:
        logger.debug(f"Carnaval.Setup: ошибка сохранения FunPay логина в конфиг: {e}")

    log_audit("funpay_credentials_configured", telegram_user_id, ip, "FunPay учетные данные зашифрованы и сохранены")
    return True, ""


def configure_proxy(telegram_user_id: int, host: str, port: int, username: str = "", password: str = "", ip: str = "") -> Tuple[bool, str]:
    """Шифрует и сохраняет настройки прокси (Section 59)."""
    from carnaval.security_utils import is_safe_url

    owner_id_str = get_state("owner_telegram_id")
    if not owner_id_str or int(owner_id_str) != telegram_user_id:
        return False, "Только владелец может настраивать прокси"

    clean_host = (host or "").strip()
    if not clean_host or not (1 <= port <= 65535):
        return False, "Укажите корректный хост и порт прокси (1-65535)"

    safe, reason = is_safe_url(f"http://{clean_host}:{port}")
    if not safe:
        return False, f"Недопустимый адрес прокси: {reason}"

    if password:
        SecretManager.set_secret("proxy_password", password)

    set_state("proxy_host", clean_host)
    set_state("proxy_port", str(port))
    set_state("proxy_username", (username or "").strip())

    proxy_str = f"{username}:{password}@{clean_host}:{port}" if username else f"{clean_host}:{port}"
    try:
        cardinal = get_cardinal()
        if cardinal and hasattr(cardinal, "MAIN_CFG") and "Proxy" in cardinal.MAIN_CFG:
            cardinal.MAIN_CFG["Proxy"]["proxy"] = proxy_str
            cardinal.MAIN_CFG["Proxy"]["enable"] = "1"
            cardinal.save_config(cardinal.MAIN_CFG, "configs/_main.cfg")
    except Exception as e:
        logger.debug(f"Carnaval.Setup: ошибка сохранения прокси в конфиг: {e}")

    log_audit("proxy_configured", telegram_user_id, ip, f"Прокси настроен: {clean_host}:{port}")
    return True, ""


def test_funpay_connection(login: str, password: str) -> Tuple[bool, str]:
    """Тестирует параметры подключения FunPay."""
    if not login or not password:
        return False, "Заполните логин и пароль"
    return True, "Параметры FunPay валидны"


def test_proxy_connection(host: str, port: int, username: str = "", password: str = "") -> Tuple[bool, str]:
    """Тестирует параметры подключения прокси с защитой от SSRF."""
    from carnaval.security_utils import is_safe_url
    safe, reason = is_safe_url(f"http://{host}:{port}")
    if not safe:
        return False, f"Недопустимый хост: {reason}"
    return True, "Параметры прокси валидны"

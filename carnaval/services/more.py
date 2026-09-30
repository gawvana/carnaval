"""
carnaval/services/more.py — сервис вкладки «Ещё».

Покрывает:
- Настройки уведомлений (MAIN_CFG[Notifications] / NewMessageView / BlockList)
- Приветствие и подтверждение заказа (Greetings / OrderConfirm / ReviewReply)
- Чёрный список (cardinal.blacklist)
- Плагины (cardinal.plugins — просмотр, toggle, загрузка .py)
- Прокси (proxy_dict / Proxy секция)
- Авторизованные пользователи (telegram.authorized_users)
- Аккаунт FunPay / смена golden_key (confirm=True guard)
- Логи Cardinal (последние N строк из logging handlers)
- Бэкап конфигов (zip configs/ → BytesIO)
- Рестарт / выключение (confirm=True guards)
"""

from __future__ import annotations

import io
import logging
import os
import re
import signal
import sys
import threading
import zipfile
from typing import Any
from uuid import UUID

from carnaval.deps import get_cardinal
from carnaval.services.config import mask_secret, mask_proxy_url
from Utils.cardinal_tools import (
    cache_blacklist,
    validate_proxy,
    build_proxy,
    cache_proxy_dict,
    cache_disabled_plugins,
)

_NOTIFICATIONS_LOCK = threading.Lock()
_BLACKLIST_LOCK = threading.Lock()
_PROXY_LOCK = threading.Lock()
_AUTH_USERS_LOCK = threading.Lock()

logger = logging.getLogger("carnaval.more")

# ---------------------------------------------------------------------------
# Уведомления
# ---------------------------------------------------------------------------

# Разделы/ключи, которые трактуются как уведомления для пользователя
NOTIFICATION_FIELDS: dict[str, dict[str, str]] = {
    "BlockList": {
        "blockDelivery": "Блокировать автовыдачу",
        "blockResponse": "Блокировать автоответ",
        "blockNewMessageNotification": "Уведомление о новом сообщении",
        "blockNewOrderNotification": "Уведомление о новом заказе",
        "blockCommandNotification": "Уведомление о команде",
    },
    "NewMessageView": {
        "includeMyMessages": "Показывать мои сообщения",
        "includeFPMessages": "Показывать сообщения FunPay",
        "includeBotMessages": "Показывать сообщения бота",
        "notifyOnlyMyMessages": "Только мои сообщения",
        "notifyOnlyFPMessages": "Только сообщения FunPay",
        "notifyOnlyBotMessages": "Только сообщения бота",
        "showImageName": "Показывать имя изображения",
    },
}

GREETING_FIELDS: list[tuple[str, str, str]] = [
    ("Greetings", "sendGreetings", "toggle"),
    ("Greetings", "greetingsText", "text"),
    ("Greetings", "greetingsCooldown", "text"),
    ("Greetings", "ignoreSystemMessages", "toggle"),
    ("Greetings", "onlyNewChats", "toggle"),
    ("OrderConfirm", "sendReply", "toggle"),
    ("OrderConfirm", "replyText", "text"),
    ("OrderConfirm", "watermark", "toggle"),
    ("ReviewReply", "star1Reply", "toggle"),
    ("ReviewReply", "star1ReplyText", "text"),
    ("ReviewReply", "star2Reply", "toggle"),
    ("ReviewReply", "star2ReplyText", "text"),
    ("ReviewReply", "star3Reply", "toggle"),
    ("ReviewReply", "star3ReplyText", "text"),
    ("ReviewReply", "star4Reply", "toggle"),
    ("ReviewReply", "star4ReplyText", "text"),
    ("ReviewReply", "star5Reply", "toggle"),
    ("ReviewReply", "star5ReplyText", "text"),
]


def get_notifications() -> dict[str, Any]:
    """Возвращает настройки уведомлений из MAIN_CFG."""
    cardinal = get_cardinal()
    cfg = cardinal.MAIN_CFG
    result: dict[str, Any] = {}

    with _NOTIFICATIONS_LOCK:
        for section, fields in NOTIFICATION_FIELDS.items():
            for key, label in fields.items():
                try:
                    val = cfg[section].getboolean(key, fallback=False)
                except Exception:
                    val = False
                result[f"{section}.{key}"] = {"label": label, "enabled": val}
    return result


def update_notification(section: str, key: str, enabled: bool) -> tuple[bool, str]:
    """Обновляет булевый параметр уведомлений в MAIN_CFG."""
    if section not in NOTIFICATION_FIELDS or key not in NOTIFICATION_FIELDS[section]:
        return False, f"Unknown notification key: {section}.{key}"

    cardinal = get_cardinal()
    cfg = cardinal.MAIN_CFG

    with _NOTIFICATIONS_LOCK:
        if not cfg.has_section(section):
            cfg.add_section(section)
        cfg.set(section, key, "1" if enabled else "0")
        try:
            cardinal.save_config(cfg, "configs/_main.cfg")
        except Exception as e:
            return False, str(e)
    return True, ""


# ---------------------------------------------------------------------------
# Приветствие / OrderConfirm / ReviewReply
# ---------------------------------------------------------------------------

def get_greetings() -> dict[str, Any]:
    """Возвращает настройки приветствия, подтверждения заказа и ответа на отзывы."""
    cardinal = get_cardinal()
    cfg = cardinal.MAIN_CFG
    result: dict[str, Any] = {}

    for section, key, field_type in GREETING_FIELDS:
        try:
            if field_type == "toggle":
                val: Any = cfg[section].getboolean(key, fallback=False)
            else:
                val = cfg[section].get(key, fallback="")
        except Exception:
            val = False if field_type == "toggle" else ""
        result[f"{section}.{key}"] = {"type": field_type, "value": val}
    return result


def update_greeting(section: str, key: str, value: str) -> tuple[bool, str]:
    """Обновляет параметр приветствия / OrderConfirm / ReviewReply."""
    allowed_sections = {"Greetings", "OrderConfirm", "ReviewReply"}
    if section not in allowed_sections:
        return False, f"Unknown section: {section}"

    cardinal = get_cardinal()
    cfg = cardinal.MAIN_CFG

    with _NOTIFICATIONS_LOCK:
        if not cfg.has_section(section):
            cfg.add_section(section)
        cfg.set(section, key, str(value).strip())
        try:
            cardinal.save_config(cfg, "configs/_main.cfg")
        except Exception as e:
            return False, str(e)
    return True, ""


# ---------------------------------------------------------------------------
# Чёрный список
# ---------------------------------------------------------------------------

def get_blacklist() -> list[str]:
    """Возвращает текущий ЧС (список юзернеймов)."""
    cardinal = get_cardinal()
    with _BLACKLIST_LOCK:
        return list(cardinal.blacklist)


def add_to_blacklist(username: str) -> tuple[bool, str]:
    """Добавляет юзернейм в ЧС."""
    username = username.strip().lstrip("@")
    if not username:
        return False, "Пустой юзернейм"

    cardinal = get_cardinal()
    with _BLACKLIST_LOCK:
        if username in cardinal.blacklist:
            return False, "Пользователь уже в чёрном списке"
        cardinal.blacklist.append(username)
        try:
            cache_blacklist(cardinal.blacklist)
        except Exception as e:
            cardinal.blacklist.remove(username)
            return False, str(e)
    return True, ""


def remove_from_blacklist(username: str) -> tuple[bool, str]:
    """Удаляет юзернейм из ЧС."""
    username = username.strip().lstrip("@")
    cardinal = get_cardinal()
    with _BLACKLIST_LOCK:
        if username not in cardinal.blacklist:
            return False, "Пользователь не найден в чёрном списке"
        cardinal.blacklist.remove(username)
        try:
            cache_blacklist(cardinal.blacklist)
        except Exception as e:
            cardinal.blacklist.append(username)
            return False, str(e)
    return True, ""


# ---------------------------------------------------------------------------
# Плагины
# ---------------------------------------------------------------------------

def list_plugins() -> list[dict[str, Any]]:
    """Возвращает список плагинов Cardinal."""
    cardinal = get_cardinal()
    result = []
    for uuid, pl in cardinal.plugins.items():
        result.append({
            "uuid": uuid,
            "name": pl.name,
            "version": pl.version,
            "description": pl.description,
            "credits": pl.credits,
            "path": pl.path,
            "enabled": pl.enabled,
            "pinned": pl.pinned,
            "settings_page": pl.settings_page,
        })
    return result


def toggle_plugin(uuid: str) -> tuple[bool, str]:
    """Переключает статус плагина (включён/выключён)."""
    cardinal = get_cardinal()
    if uuid not in cardinal.plugins:
        return False, f"Плагин {uuid} не найден"
    cardinal.toggle_plugin(uuid)
    return True, ""


def upload_plugin(filename: str, content: bytes) -> tuple[bool, str]:
    """
    Безопасно сохраняет .py файл плагина в plugins/.
    НЕ исполняет файл — только кладёт на диск.
    """
    if not filename.endswith(".py"):
        return False, "Только .py файлы разрешены"

    # Базовое имя — никаких path traversal
    safe_name = os.path.basename(filename)
    if not re.match(r"^[A-Za-z0-9_\-]+\.py$", safe_name):
        return False, "Недопустимое имя файла"

    os.makedirs("plugins", exist_ok=True)
    dest = os.path.join("plugins", safe_name)
    if os.path.exists(dest):
        return False, "Файл с таким именем уже существует"

    try:
        with open(dest, "wb") as f:
            f.write(content)
    except Exception as e:
        return False, str(e)
    return True, ""


def delete_plugin(uuid: str) -> tuple[bool, str]:
    """Удаляет плагин по uuid."""
    cardinal = get_cardinal()
    if uuid not in cardinal.plugins:
        return False, f"Плагин {uuid} не найден"
    pl = cardinal.plugins[uuid]
    path = getattr(pl, "path", None)
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except Exception as e:
            return False, f"Ошибка удаления файла плагина: {e}"
    del cardinal.plugins[uuid]
    return True, ""



# ---------------------------------------------------------------------------
# Прокси
# ---------------------------------------------------------------------------

def _mask_proxy(proxy_str: str) -> str:
    return mask_proxy_url(proxy_str)


def get_proxy_info() -> dict[str, Any]:
    """Возвращает информацию о прокси (активный — маскированный)."""
    cardinal = get_cardinal()
    cfg = cardinal.MAIN_CFG

    with _PROXY_LOCK:
        enabled = cfg["Proxy"].getboolean("enable", fallback=False)
        check = cfg["Proxy"].getboolean("check", fallback=False)
        current_proxy = cfg["Proxy"].get("proxy", fallback="")
        proxy_list = [
            {"id": pid, "proxy": _mask_proxy(p)}
            for pid, p in cardinal.proxy_dict.items()
        ]

    return {
        "enabled": enabled,
        "check": check,
        "current_proxy": _mask_proxy(current_proxy),
        "proxy_list": proxy_list,
    }


def add_proxy(proxy_str: str) -> tuple[bool, str]:
    """Добавляет прокси в proxy_dict."""
    try:
        scheme, login, password, ip, port = validate_proxy(proxy_str)
        built = build_proxy(scheme, login, password, ip, port)
    except ValueError as e:
        return False, str(e)

    cardinal = get_cardinal()
    with _PROXY_LOCK:
        if built in cardinal.proxy_dict.values():
            return False, "Прокси уже существует"
        max_id = max(cardinal.proxy_dict.keys(), default=-1)
        cardinal.proxy_dict[max_id + 1] = built
        try:
            cache_proxy_dict(cardinal.proxy_dict)
        except Exception as e:
            del cardinal.proxy_dict[max_id + 1]
            return False, str(e)
    return True, ""


def delete_proxy(proxy_id: int) -> tuple[bool, str]:
    """Удаляет прокси из proxy_dict (нельзя удалить активный)."""
    cardinal = get_cardinal()
    with _PROXY_LOCK:
        if proxy_id not in cardinal.proxy_dict:
            return False, "Прокси не найден"
        proxy = cardinal.proxy_dict[proxy_id]
        current = cardinal.account.proxy if cardinal.account.proxy else {}
        if current.get("http") == proxy:
            return False, "Нельзя удалить активный прокси"
        del cardinal.proxy_dict[proxy_id]
        try:
            cache_proxy_dict(cardinal.proxy_dict)
        except Exception as e:
            cardinal.proxy_dict[proxy_id] = proxy
            return False, str(e)
    return True, ""


def set_active_proxy(proxy_id: int) -> tuple[bool, str]:
    """Устанавливает прокси как активный (меняет MAIN_CFG и account.proxy)."""
    cardinal = get_cardinal()
    with _PROXY_LOCK:
        if proxy_id not in cardinal.proxy_dict:
            return False, "Прокси не найден"
        proxy_str = cardinal.proxy_dict[proxy_id]
        try:
            scheme, login, password, ip, port = validate_proxy(proxy_str)
            built = build_proxy(scheme, login, password, ip, port)
        except Exception as e:
            return False, str(e)

        proxy_dict = {"http": built, "https": built}
        cardinal.MAIN_CFG["Proxy"]["proxy"] = built
        cardinal.save_config(cardinal.MAIN_CFG, "configs/_main.cfg")
        if cardinal.MAIN_CFG["Proxy"].getboolean("enable", fallback=False):
            cardinal.account.proxy = proxy_dict
    return True, ""


def set_proxy_enabled(enabled: bool) -> tuple[bool, str]:
    """Включает/выключает использование прокси глобально."""
    cardinal = get_cardinal()
    with _PROXY_LOCK:
        cardinal.MAIN_CFG["Proxy"]["enable"] = "1" if enabled else "0"
        cardinal.save_config(cardinal.MAIN_CFG, "configs/_main.cfg")
    return True, ""


# ---------------------------------------------------------------------------
# Авторизованные пользователи
# ---------------------------------------------------------------------------

def get_authorized_users() -> list[int]:
    """Возвращает список авторизованных Telegram user ID."""
    cardinal = get_cardinal()
    tg = cardinal.telegram
    if not tg:
        return []
    with _AUTH_USERS_LOCK:
        return list(tg.authorized_users)


def add_authorized_user(user_id: int) -> tuple[bool, str]:
    """Добавляет пользователя в список авторизованных."""
    cardinal = get_cardinal()
    tg = cardinal.telegram
    if not tg:
        return False, "Telegram-бот не запущен"

    with _AUTH_USERS_LOCK:
        if user_id in tg.authorized_users:
            return False, "Пользователь уже авторизован"
        tg.authorized_users.append(user_id)
        # Сохраняем в конфиг
        try:
            cardinal.MAIN_CFG["Telegram"]["authorizedUsers"] = ",".join(
                str(uid) for uid in tg.authorized_users
            )
            cardinal.save_config(cardinal.MAIN_CFG, "configs/_main.cfg")
        except Exception as e:
            tg.authorized_users.remove(user_id)
            return False, str(e)
    return True, ""


def remove_authorized_user(user_id: int) -> tuple[bool, str]:
    """Удаляет пользователя из списка авторизованных."""
    cardinal = get_cardinal()
    tg = cardinal.telegram
    if not tg:
        return False, "Telegram-бот не запущен"

    with _AUTH_USERS_LOCK:
        auth_users = tg.authorized_users
        if isinstance(auth_users, dict):
            if user_id not in auth_users and str(user_id) not in auth_users:
                return False, "Пользователь не найден"
            if len(auth_users) <= 1:
                return False, "Нельзя удалить последнего администратора"
            auth_users.pop(user_id, None)
            auth_users.pop(str(user_id), None)
            try:
                from tg_bot import utils as tg_utils
                tg_utils.save_authorized_users(auth_users)
            except Exception:
                pass
        elif isinstance(auth_users, (list, set)):
            if user_id not in auth_users:
                return False, "Пользователь не найден"
            if len(auth_users) <= 1:
                return False, "Нельзя удалить последнего администратора"
            if isinstance(auth_users, list):
                auth_users.remove(user_id)
            else:
                auth_users.discard(user_id)

        try:
            if "Telegram" in cardinal.MAIN_CFG and "authorizedUsers" in cardinal.MAIN_CFG["Telegram"]:
                cardinal.MAIN_CFG["Telegram"]["authorizedUsers"] = ",".join(
                    str(uid) for uid in auth_users
                )
                cardinal.save_config(cardinal.MAIN_CFG, "configs/_main.cfg")
        except Exception:
            pass
    return True, ""


# ---------------------------------------------------------------------------
# Аккаунт FunPay / смена golden_key
# ---------------------------------------------------------------------------

def get_account_info() -> dict[str, Any]:
    """Возвращает маскированную информацию об аккаунте FunPay."""
    cardinal = get_cardinal()
    acc = cardinal.account

    username = getattr(acc, "username", None) or ""
    user_id = getattr(acc, "id", None) or 0
    golden_key = getattr(acc, "golden_key", "") or ""

    return {
        "username": username,
        "id": user_id,
        "golden_key": mask_secret(golden_key, 4, 4),
    }


def change_golden_key(new_key: str, confirm: bool = False) -> tuple[bool, str]:
    """Меняет golden_key. Требует confirm=True."""
    if not confirm:
        return False, "Требуется подтверждение (confirm=true)"
    new_key = new_key.strip()
    if not new_key:
        return False, "golden_key не может быть пустым"

    cardinal = get_cardinal()
    cardinal.MAIN_CFG["FunPay"]["golden_key"] = new_key
    try:
        cardinal.save_config(cardinal.MAIN_CFG, "configs/_main.cfg")
        # Применяем к аккаунту без перезапуска
        cardinal.account.golden_key = new_key
    except Exception as e:
        return False, str(e)
    return True, ""


# ---------------------------------------------------------------------------
# Логи Cardinal
# ---------------------------------------------------------------------------

class _MemoryLogHandler(logging.Handler):
    """In-memory circular buffer для хранения последних логов."""
    _instance: _MemoryLogHandler | None = None
    _lock = threading.Lock()
    MAX_LINES = 500

    def __init__(self):
        super().__init__()
        self._lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        msg = self.format(record)
        with self._lock:
            self._lines.append(msg)
            if len(self._lines) > self.MAX_LINES:
                self._lines = self._lines[-self.MAX_LINES:]

    def get_lines(self, n: int = 100) -> list[str]:
        with self._lock:
            return list(self._lines[-n:])

    @classmethod
    def install(cls) -> _MemoryLogHandler:
        """Устанавливает обработчик в корневой logger (один раз)."""
        with cls._lock:
            if cls._instance is None:
                handler = cls()
                handler.setFormatter(
                    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                                      datefmt="%H:%M:%S")
                )
                logging.getLogger().addHandler(handler)
                cls._instance = handler
        return cls._instance


# Устанавливаем обработчик при импорте модуля
_memory_handler = _MemoryLogHandler.install()


def get_logs(n: int = 150) -> list[str]:
    """Возвращает последние n строк лога Cardinal."""
    return _memory_handler.get_lines(n)


def clear_logs() -> tuple[bool, str]:
    """Очищает историю логов."""
    with _memory_handler._lock:
        _memory_handler._lines.clear()
    return True, ""


# ---------------------------------------------------------------------------
# Бэкап конфигов
# ---------------------------------------------------------------------------

def create_configs_backup() -> bytes:
    """Создаёт zip-архив директории configs/ и возвращает байты."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        configs_dir = "configs"
        if os.path.isdir(configs_dir):
            for root, _dirs, files in os.walk(configs_dir):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    arcname = os.path.relpath(fpath, start=".")
                    zf.write(fpath, arcname)
        # Добавляем storage/cache если есть
        cache_dir = os.path.join("storage", "cache")
        if os.path.isdir(cache_dir):
            for fname in os.listdir(cache_dir):
                fpath = os.path.join(cache_dir, fname)
                if os.path.isfile(fpath):
                    zf.write(fpath, os.path.join("storage", "cache", fname))
    buf.seek(0)
    return buf.read()


def restore_backup(zip_bytes: bytes) -> tuple[bool, str]:
    """Безопасно распаковывает архив с конфигурацией."""
    try:
        buf = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(buf, "r") as zf:
            for member in zf.namelist():
                # Безопасность: никаких абсолютных путей или ..
                if member.startswith("/") or ".." in member:
                    continue
                if member.startswith("configs/") or member.startswith("storage/cache/"):
                    zf.extract(member, path=".")
        return True, ""
    except Exception as e:
        return False, str(e)



# ---------------------------------------------------------------------------
# Системные команды
# ---------------------------------------------------------------------------

def restart_cardinal(confirm: bool = False) -> tuple[bool, str]:
    """
    Перезапускает Cardinal через os.execv.
    Требует confirm=True.
    """
    if not confirm:
        return False, "Требуется подтверждение (confirm=true)"

    def _do_restart():
        import time as _time
        _time.sleep(0.5)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    threading.Thread(target=_do_restart, daemon=True).start()
    return True, ""


def shutdown_cardinal(confirm: bool = False) -> tuple[bool, str]:
    """
    Завершает процесс Cardinal.
    Требует confirm=True.
    """
    if not confirm:
        return False, "Требуется подтверждение (confirm=true)"

    def _do_shutdown():
        import time as _time
        _time.sleep(0.5)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=_do_shutdown, daemon=True).start()
    return True, ""

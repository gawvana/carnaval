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
from typing import Any, Optional, Tuple, Dict, List, Union
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
    ("Other", "watermark", "text"),
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
# Приветствие / OrderConfirm / ReviewReply / Watermark
# ---------------------------------------------------------------------------

def get_greetings() -> dict[str, Any]:
    """Возвращает настройки приветствия, подтверждения заказа и ответа на отзывы."""
    cardinal = get_cardinal()
    cfg = cardinal.MAIN_CFG
    result: dict[str, Any] = {}

    for section, key, field_type in GREETING_FIELDS:
        try:
            if not cfg.has_section(section):
                val: Any = False if field_type == "toggle" else ""
            elif field_type == "toggle":
                val = cfg[section].getboolean(key, fallback=False)
            else:
                val = cfg[section].get(key, fallback="")
        except Exception:
            val = False if field_type == "toggle" else ""
        result[f"{section}.{key}"] = {"type": field_type, "value": val}
    return result


def update_greeting(section: str, key: str, value: str) -> tuple[bool, str]:
    """Обновляет параметр приветствия / OrderConfirm / ReviewReply / Watermark."""
    allowed_sections = {"Greetings", "OrderConfirm", "ReviewReply", "Other"}
    if section not in allowed_sections:
        return False, f"Unknown section: {section}"

    clean_val = str(value)

    if section == "Greetings" and key == "greetingsCooldown":
        try:
            cd = float(clean_val.strip())
            if cd < 0:
                return False, "Кулдаун не может быть отрицательным"
            clean_val = str(cd)
        except ValueError:
            return False, "Некорректное значение кулдауна (ожидается число)"
    elif section == "Other" and key == "watermark":
        w = clean_val.strip()
        if w == "-":
            clean_val = ""
        elif re.fullmatch(r"\[[a-zA-Z]+]", w):
            return False, "Водяной знак не может иметь формат [tag]"
        else:
            clean_val = w

    cardinal = get_cardinal()
    cfg = cardinal.MAIN_CFG

    with _NOTIFICATIONS_LOCK:
        if not cfg.has_section(section):
            cfg.add_section(section)
        cfg.set(section, key, clean_val if key == "watermark" and clean_val == "" else clean_val.strip())
        try:
            cardinal.save_config(cfg, "configs/_main.cfg")
        except Exception as e:
            return False, str(e)
    return True, ""


def get_greetings_text() -> str:
    cardinal = get_cardinal()
    if cardinal.MAIN_CFG.has_section("Greetings"):
        return cardinal.MAIN_CFG["Greetings"].get("greetingsText", "")
    return ""


def update_greetings_text(text: str) -> tuple[bool, str]:
    return update_greeting("Greetings", "greetingsText", text)


def get_greetings_cooldown() -> float:
    cardinal = get_cardinal()
    if cardinal.MAIN_CFG.has_section("Greetings"):
        try:
            return float(cardinal.MAIN_CFG["Greetings"].get("greetingsCooldown", "0"))
        except ValueError:
            return 0.0
    return 0.0


def update_greetings_cooldown(cooldown: float) -> tuple[bool, str]:
    if cooldown < 0:
        return False, "Кулдаун не может быть отрицательным"
    return update_greeting("Greetings", "greetingsCooldown", str(cooldown))


def get_order_confirm_reply_text() -> str:
    cardinal = get_cardinal()
    if cardinal.MAIN_CFG.has_section("OrderConfirm"):
        return cardinal.MAIN_CFG["OrderConfirm"].get("replyText", "")
    return ""


def update_order_confirm_reply_text(text: str) -> tuple[bool, str]:
    return update_greeting("OrderConfirm", "replyText", text)


def get_order_confirm_settings() -> dict[str, Any]:
    cardinal = get_cardinal()
    cfg = cardinal.MAIN_CFG
    if not cfg.has_section("OrderConfirm"):
        return {"sendReply": False, "replyText": "", "watermark": False}
    return {
        "sendReply": cfg["OrderConfirm"].getboolean("sendReply", fallback=False),
        "replyText": cfg["OrderConfirm"].get("replyText", fallback=""),
        "watermark": cfg["OrderConfirm"].getboolean("watermark", fallback=False),
    }


def get_review_reply_settings() -> dict[str, Any]:
    cardinal = get_cardinal()
    cfg = cardinal.MAIN_CFG
    stars_dict = {}
    for star in range(1, 6):
        if cfg.has_section("ReviewReply"):
            enabled = cfg["ReviewReply"].getboolean(f"star{star}Reply", fallback=False)
            text = cfg["ReviewReply"].get(f"star{star}ReplyText", fallback="")
        else:
            enabled, text = False, ""
        stars_dict[str(star)] = {
            "star": star,
            "enabled": enabled,
            "text": text,
        }
    return {"stars": stars_dict}


def get_review_reply_star(star: int) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    if not (1 <= star <= 5):
        return None, "Рейтинг должен быть от 1 до 5"
    cardinal = get_cardinal()
    cfg = cardinal.MAIN_CFG
    if cfg.has_section("ReviewReply"):
        enabled = cfg["ReviewReply"].getboolean(f"star{star}Reply", fallback=False)
        text = cfg["ReviewReply"].get(f"star{star}ReplyText", fallback="")
    else:
        enabled, text = False, ""
    return {
        "star": star,
        "enabled": enabled,
        "text": text,
    }, None


def update_review_reply_star(star: int, enabled: Optional[bool] = None, text: Optional[str] = None) -> tuple[bool, str]:
    if not (1 <= star <= 5):
        return False, "Рейтинг должен быть от 1 до 5"
    cardinal = get_cardinal()
    cfg = cardinal.MAIN_CFG
    with _NOTIFICATIONS_LOCK:
        if not cfg.has_section("ReviewReply"):
            cfg.add_section("ReviewReply")
        if enabled is not None:
            cfg.set("ReviewReply", f"star{star}Reply", "1" if enabled else "0")
        if text is not None:
            cfg.set("ReviewReply", f"star{star}ReplyText", str(text))
        try:
            cardinal.save_config(cfg, "configs/_main.cfg")
        except Exception as e:
            return False, str(e)
    return True, ""


def get_watermark() -> str:
    cardinal = get_cardinal()
    if cardinal.MAIN_CFG.has_section("Other"):
        return cardinal.MAIN_CFG["Other"].get("watermark", "")
    return ""


def update_watermark(watermark: str) -> tuple[bool, str]:
    return update_greeting("Other", "watermark", watermark)


# ---------------------------------------------------------------------------
# Чёрный список
# ---------------------------------------------------------------------------

_BLACKLIST_REASONS_FILE = "storage/cache/blacklist_reasons.json"


def _load_blacklist_reasons() -> dict[str, str]:
    if not os.path.exists(_BLACKLIST_REASONS_FILE):
        return {}
    try:
        import json
        with open(_BLACKLIST_REASONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_blacklist_reasons(reasons: dict[str, str]) -> None:
    try:
        import json
        os.makedirs(os.path.dirname(_BLACKLIST_REASONS_FILE), exist_ok=True)
        with open(_BLACKLIST_REASONS_FILE, "w", encoding="utf-8") as f:
            json.dump(reasons, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Failed to save blacklist reasons: {e}")


def get_blacklist() -> list[str]:
    """Возвращает текущий ЧС (список юзернеймов)."""
    cardinal = get_cardinal()
    with _BLACKLIST_LOCK:
        return list(cardinal.blacklist)


def get_blacklist_detailed() -> list[dict[str, Any]]:
    """Возвращает текущий ЧС с причинами блокировки."""
    cardinal = get_cardinal()
    with _BLACKLIST_LOCK:
        reasons = _load_blacklist_reasons()
        return [{"username": u, "reason": reasons.get(u, "")} for u in cardinal.blacklist]


def add_to_blacklist(username: str, reason: Optional[str] = None) -> tuple[bool, str]:
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
        if reason:
            reasons = _load_blacklist_reasons()
            reasons[username] = reason.strip()
            _save_blacklist_reasons(reasons)
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
        reasons = _load_blacklist_reasons()
        if username in reasons:
            reasons.pop(username, None)
            _save_blacklist_reasons(reasons)
    return True, ""


# ---------------------------------------------------------------------------
# Плагины
# ---------------------------------------------------------------------------

def list_plugins() -> list[dict[str, Any]]:
    """Возвращает список плагинов Cardinal."""
    cardinal = get_cardinal()
    from carnaval.services.system_mode import is_safe_mode
    safe = is_safe_mode()
    result = []
    plugins_dict = getattr(cardinal, "plugins", {})
    if isinstance(plugins_dict, dict):
        for uuid, pl in plugins_dict.items():
            commands = list(getattr(pl, "commands", {}).keys()) if hasattr(pl, "commands") and isinstance(pl.commands, dict) else []
            desc = getattr(pl, "description", "")
            credits_val = getattr(pl, "credits", "")
            result.append({
                "uuid": uuid,
                "name": getattr(pl, "name", uuid),
                "version": getattr(pl, "version", "1.0.0"),
                "description": desc,
                "desc": desc,
                "credits": credits_val,
                "author": credits_val,
                "path": getattr(pl, "path", ""),
                "enabled": getattr(pl, "enabled", True),
                "pinned": getattr(pl, "pinned", False),
                "settings_page": getattr(pl, "settings_page", False),
                "commands": commands,
                "bypassed": safe,
            })
    return result


def toggle_plugin(uuid: str) -> tuple[bool, str]:
    """Переключает статус плагина (включён/выключён)."""
    cardinal = get_cardinal()
    if uuid not in cardinal.plugins:
        return False, f"Плагин {uuid} не найден"
    if hasattr(cardinal, "toggle_plugin"):
        cardinal.toggle_plugin(uuid)
    else:
        pl = cardinal.plugins[uuid]
        pl.enabled = not getattr(pl, "enabled", True)
    return True, ""


def reload_plugin(uuid: str) -> tuple[bool, str]:
    """Перезагружает конкретный плагин по UUID."""
    cardinal = get_cardinal()
    if uuid not in cardinal.plugins:
        return False, f"Плагин {uuid} не найден"
    if hasattr(cardinal, "reload_plugin"):
        return cardinal.reload_plugin(uuid)

    pl = cardinal.plugins[uuid]
    path = getattr(pl, "path", None)
    if not path or not os.path.exists(path):
        return False, f"Файл плагина не найден: {path}"
    filename = os.path.basename(path)
    try:
        if hasattr(cardinal, "load_plugin"):
            plugin_module, data = cardinal.load_plugin(filename)
            pl.name = data.get("NAME", pl.name)
            pl.version = data.get("VERSION", pl.version)
            pl.description = data.get("DESCRIPTION", pl.description)
            pl.credits = data.get("CREDITS", pl.credits)
            pl.settings_page = data.get("SETTINGS_PAGE", pl.settings_page)
            pl.delete_handler = data.get("BIND_TO_DELETE", pl.delete_handler)
            pl.plugin = plugin_module
            if hasattr(pl, "commands") and isinstance(pl.commands, dict):
                pl.commands.clear()
            if hasattr(cardinal, "handler_bind_var_names"):
                for h_list in cardinal.handler_bind_var_names.values():
                    h_list[:] = [fn for fn in h_list if getattr(fn, "plugin_uuid", None) != uuid]
            if hasattr(cardinal, "add_handlers_from_plugin"):
                cardinal.add_handlers_from_plugin(plugin_module, uuid)
        return True, ""
    except Exception as e:
        return False, f"Ошибка перезагрузки плагина: {e}"


def reload_all_plugins() -> tuple[bool, str]:
    """Перезагружает все плагины в Cardinal."""
    cardinal = get_cardinal()
    if hasattr(cardinal, "reload_all_plugins"):
        return cardinal.reload_all_plugins()
    if hasattr(cardinal, "reload_plugins"):
        return cardinal.reload_plugins()

    if not os.path.exists("plugins"):
        return True, ""

    try:
        if hasattr(cardinal, "handler_bind_var_names"):
            for h_list in cardinal.handler_bind_var_names.values():
                h_list[:] = [fn for fn in h_list if getattr(fn, "plugin_uuid", None) is None]
        if hasattr(cardinal, "plugins") and isinstance(cardinal.plugins, dict):
            cardinal.plugins.clear()
        if hasattr(cardinal, "load_plugins"):
            cardinal.load_plugins()
        if hasattr(cardinal, "add_handlers"):
            cardinal.add_handlers()
        return True, ""
    except Exception as e:
        return False, f"Ошибка перезагрузки всех плагинов: {e}"


def upload_plugin(filename: str, content: bytes) -> tuple[bool, str]:
    """
    Безопасно сохраняет .py файл плагина в plugins/ и инициализирует в Cardinal.
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

    # Регистрируем плагин в Cardinal если кардинал активен
    try:
        cardinal = get_cardinal()
        if cardinal and hasattr(cardinal, "load_plugin"):
            plugin_module, data = cardinal.load_plugin(safe_name)
            uuid = data["UUID"]
            from cardinal import PluginData
            plugin_data = PluginData(
                data["NAME"], data["VERSION"], data["DESCRIPTION"], data["CREDITS"], uuid,
                dest, plugin_module, data["SETTINGS_PAGE"], data["BIND_TO_DELETE"],
                True, False
            )
            cardinal.plugins[uuid] = plugin_data
            if hasattr(cardinal, "add_handlers_from_plugin"):
                cardinal.add_handlers_from_plugin(plugin_module, uuid)
    except Exception as e:
        logger.warning(f"Плагин сохранён, но не удалось загрузить в память Cardinal: {e}")

    return True, ""


def delete_plugin(uuid: str) -> tuple[bool, str]:
    """Удаляет плагин по uuid."""
    cardinal = get_cardinal()
    if uuid not in cardinal.plugins:
        return False, f"Плагин {uuid} не найден"
    pl = cardinal.plugins[uuid]
    delete_handler = getattr(pl, "delete_handler", None)
    if delete_handler and callable(delete_handler):
        try:
            delete_handler(cardinal)
        except Exception as e:
            logger.error(f"Plugin delete handler error: {e}")
    path = getattr(pl, "path", None)
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except Exception as e:
            return False, f"Ошибка удаления файла плагина: {e}"
    del cardinal.plugins[uuid]
    if hasattr(cardinal, "disabled_plugins") and uuid in cardinal.disabled_plugins:
        try:
            cardinal.disabled_plugins.remove(uuid)
        except Exception:
            pass
    if hasattr(cardinal, "pinned_plugins") and uuid in cardinal.pinned_plugins:
        try:
            cardinal.pinned_plugins.remove(uuid)
        except Exception:
            pass
    if hasattr(cardinal, "handler_bind_var_names"):
        for h_list in cardinal.handler_bind_var_names.values():
            h_list[:] = [fn for fn in h_list if getattr(fn, "plugin_uuid", None) != uuid]
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


def set_proxy_check_enabled(enabled: bool) -> tuple[bool, str]:
    """Включает/выключает автоматическую проверку прокси."""
    cardinal = get_cardinal()
    with _PROXY_LOCK:
        cardinal.MAIN_CFG["Proxy"]["check"] = "1" if enabled else "0"
        cardinal.save_config(cardinal.MAIN_CFG, "configs/_main.cfg")
    return True, ""


def test_proxy(proxy_id: int) -> dict[str, Any]:
    """Тестирует работоспособность конкретного прокси."""
    cardinal = get_cardinal()
    with _PROXY_LOCK:
        if proxy_id not in cardinal.proxy_dict:
            return {"ok": False, "error": f"Прокси #{proxy_id} не найден"}
        proxy_str = cardinal.proxy_dict[proxy_id]

    import time as _time
    from Utils.cardinal_tools import check_proxy
    t0 = _time.time()
    try:
        ok = check_proxy({"http": proxy_str, "https": proxy_str})
        elapsed = round(_time.time() - t0, 3)
        return {
            "ok": ok,
            "proxy_id": proxy_id,
            "proxy": _mask_proxy(proxy_str),
            "ping": elapsed if ok else None,
            "error": "" if ok else "Не удалось подключиться к прокси",
        }
    except Exception as e:
        return {"ok": False, "proxy_id": proxy_id, "proxy": _mask_proxy(proxy_str), "error": str(e)}


# ---------------------------------------------------------------------------
# Авторизованные пользователи
# ---------------------------------------------------------------------------

def get_authorized_users() -> list[dict]:
    """Возвращает список авторизованных пользователей с метаданными."""
    cardinal = get_cardinal()
    tg = cardinal.telegram
    if not tg:
        return []
    with _AUTH_USERS_LOCK:
        auth_users = tg.authorized_users
        if isinstance(auth_users, dict):
            return [{'user_id': uid, 'data': data} for uid, data in auth_users.items()]
        # Fallback for list type
        return [{'user_id': uid, 'data': {}} for uid in auth_users]


def add_authorized_user(user_id: int, role: Optional[str] = None, comment: Optional[str] = None) -> tuple[bool, str]:
    """Добавляет пользователя в список авторизованных."""
    cardinal = get_cardinal()
    tg = getattr(cardinal, "telegram", None)
    if not tg:
        return False, "Telegram-бот не запущен"

    with _AUTH_USERS_LOCK:
        auth_users = getattr(tg, "authorized_users", None)
        if auth_users is None:
            tg.authorized_users = {}
            auth_users = tg.authorized_users

        if isinstance(auth_users, dict):
            if user_id in auth_users or str(user_id) in auth_users:
                return False, "Пользователь уже авторизован"
            meta = {}
            if role:
                meta["role"] = role
            if comment:
                meta["comment"] = comment
            auth_users[user_id] = meta
            try:
                from tg_bot.utils import save_authorized_users
                save_authorized_users(auth_users)
            except Exception:
                pass
        elif isinstance(auth_users, (list, set)):
            if user_id in auth_users or str(user_id) in auth_users:
                return False, "Пользователь уже авторизован"
            if isinstance(auth_users, list):
                auth_users.append(user_id)
            else:
                auth_users.add(user_id)

        try:
            if hasattr(cardinal, "MAIN_CFG") and "Telegram" in cardinal.MAIN_CFG and "authorizedUsers" in cardinal.MAIN_CFG["Telegram"]:
                raw = cardinal.MAIN_CFG["Telegram"]["authorizedUsers"]
                curr = [u.strip() for u in raw.split(",") if u.strip()]
                if str(user_id) not in curr:
                    curr.append(str(user_id))
                    cardinal.MAIN_CFG["Telegram"]["authorizedUsers"] = ",".join(curr)
                    if hasattr(cardinal, "save_config"):
                        cardinal.save_config(cardinal.MAIN_CFG, "configs/_main.cfg")
        except Exception:
            pass

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
    """Возвращает маскированную информацию об аккаунте FunPay и статус подключения."""
    cardinal = get_cardinal()
    acc = getattr(cardinal, "account", None)

    username = getattr(acc, "username", None) or ""
    user_id = getattr(acc, "id", None) or 0
    from carnaval.secrets_manager import SecretManager
    has_key = (
        SecretManager.has_secret("golden_key")
        or bool(getattr(acc, "golden_key", ""))
        or bool(os.getenv("FUNPAY_GOLDEN_KEY", "").strip())
        or bool(os.getenv("GOLDEN_KEY", "").strip())
    )

    from carnaval.services.account_lifecycle import lifecycle_manager
    st = lifecycle_manager.get_status()

    return {
        "username": username,
        "id": user_id,
        "state": st.get("state", "NO_KEY"),
        "is_ready": st.get("is_ready", False),
        "is_connected": st.get("is_connected", False),
        "golden_key_configured": has_key,
        "golden_key_masked": "••••••••••••••••" if has_key else "",
        "error": st.get("error"),
    }


async def change_golden_key(new_key: str, confirm: bool = False) -> tuple[bool, str, dict[str, Any]]:
    """Меняет golden_key через AccountLifecycleManager. Требует confirm=True."""
    if not confirm:
        return False, "Требуется подтверждение (confirm=true)", {}
    clean_key = new_key.strip()
    if len(clean_key) != 32:
        from carnaval.services.account_lifecycle import AccountLifecycleManager, ErrorCode
        mgr = AccountLifecycleManager()
        mgr._set_error(
            ErrorCode.INVALID_KEY_FORMAT,
            f"Golden Key должен состоять ровно из 32 символов (получено {len(clean_key)})"
        )
        return False, "Golden Key должен состоять ровно из 32 символов", mgr.get_status()

    from carnaval.services.account_lifecycle import AccountLifecycleManager
    mgr = AccountLifecycleManager()
    res = await mgr.change_golden_key(clean_key)
    account_status = res.get("status", {})
    if not res.get("ok"):
        err_msg = (
            account_status.get("error", {}).get("message")
            if account_status.get("error")
            else "Ошибка смены Golden Key"
        )
        return False, err_msg or "Ошибка смены Golden Key", account_status

    return True, "", account_status


async def delete_golden_key(confirm: bool = False) -> tuple[bool, str, dict[str, Any]]:
    """Удаляет golden_key через AccountLifecycleManager. Требует confirm=True."""
    if not confirm:
        return False, "Требуется подтверждение (confirm=true)", {}

    from carnaval.services.account_lifecycle import AccountLifecycleManager
    mgr = AccountLifecycleManager()
    res = await mgr.disconnect_account()
    account_status = res.get("status", {})
    if not res.get("ok"):
        return False, "Ошибка отключения аккаунта FunPay", account_status

    return True, "", account_status


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
    """
    Создаёт zip-архив безопасных файлов конфигурации.
    Строгий whitelist:
    - configs/ (кроме *.key, *.secret, *.pem, master.key, .env)
    - storage/products/
    НЕ включает master.key, carnaval_secret.key, sessions, .env, токены.
    """
    buf = io.BytesIO()
    added_names = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        configs_dirs = []
        try:
            from carnaval.paths import CONFIGS_DIR
            if os.path.isdir(CONFIGS_DIR):
                configs_dirs.append(CONFIGS_DIR)
        except Exception:
            pass
        if os.path.isdir("configs") and os.path.abspath("configs") not in [os.path.abspath(d) for d in configs_dirs]:
            configs_dirs.append("configs")

        for cdir in configs_dirs:
            for root, _dirs, files in os.walk(cdir):
                for fname in files:
                    lower = fname.lower()
                    if lower.endswith((".key", ".secret", ".pem")) or "master" in lower or ".env" in lower or "app.db" in lower:
                        continue
                    fpath = os.path.join(root, fname)
                    rel = os.path.relpath(fpath, start=cdir)
                    arcname = os.path.join("configs", rel).replace("\\", "/")
                    if arcname in added_names:
                        continue
                    added_names.add(arcname)
                    if fname == "_main.cfg":
                        try:
                            from configparser import ConfigParser
                            cp = ConfigParser(interpolation=None)
                            cp.read(fpath, encoding="utf-8")
                            if "Telegram" in cp and "token" in cp["Telegram"]:
                                cp["Telegram"]["token"] = "MASKED_IN_BACKUP"
                            if "Telegram" in cp and "secretPassword" in cp["Telegram"]:
                                cp["Telegram"]["secretPassword"] = "MASKED_IN_BACKUP"
                            if "FunPay" in cp and "golden_key" in cp["FunPay"]:
                                cp["FunPay"]["golden_key"] = "MASKED_IN_BACKUP"
                            if "Carnaval" in cp and "secretKey" in cp["Carnaval"]:
                                cp["Carnaval"]["secretKey"] = "MASKED_IN_BACKUP"
                            out_str = io.StringIO()
                            cp.write(out_str)
                            zf.writestr(arcname, out_str.getvalue().encode("utf-8"))
                            continue
                        except Exception:
                            pass
                    zf.write(fpath, arcname)

        # Добавляем storage/products (товары автовыдачи)
        products_dirs = []
        try:
            from carnaval.paths import PRODUCTS_DIR
            if os.path.isdir(PRODUCTS_DIR):
                products_dirs.append(PRODUCTS_DIR)
        except Exception:
            pass
        default_prod = os.path.join("storage", "products")
        if os.path.isdir(default_prod) and os.path.abspath(default_prod) not in [os.path.abspath(d) for d in products_dirs]:
            products_dirs.append(default_prod)

        for pdir in products_dirs:
            for root, _dirs, files in os.walk(pdir):
                for fname in files:
                    lower = fname.lower()
                    if lower.endswith((".key", ".secret", ".pem")):
                        continue
                    fpath = os.path.join(root, fname)
                    rel = os.path.relpath(fpath, start=pdir)
                    arcname = os.path.join("storage", "products", rel).replace("\\", "/")
                    if arcname in added_names:
                        continue
                    added_names.add(arcname)
                    zf.write(fpath, arcname)
    buf.seek(0)
    return buf.read()


def create_backup(target: Any = None) -> tuple[bool, str] | bytes:
    """Создаёт резервную копию конфигурации без секретов."""
    try:
        data = create_configs_backup()
        if target is not None:
            if hasattr(target, "write"):
                target.write(data)
            return True, ""
        return data
    except Exception as e:
        if target is not None:
            return False, str(e)
        raise


def restore_backup(zip_bytes: bytes) -> tuple[bool, str]:
    """
    Безопасно валидирует и распаковывает архив с конфигурацией.
    Защита:
    - Zip Slip / Path Traversal
    - Zip Bomb (лимит по числу файлов и суммарному размеру)
    - Запрет симлинков
    - Игнорирование любых потенциальных файлов секретов
    """
    try:
        buf = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(buf, "r") as zf:
            from carnaval.security_utils import validate_zip_archive
            validate_zip_archive(zf, ".")

            for member in zf.namelist():
                lower = member.lower()
                if lower.endswith((".key", ".secret", ".pem")) or "master" in lower or ".env" in lower or "app.db" in lower:
                    continue
                if member.startswith("/") or ".." in member:
                    continue

                if member.startswith("configs/"):
                    sub = member[len("configs/"):]
                    data = zf.read(member)
                    from carnaval.paths import CONFIGS_DIR
                    dest_path = os.path.join(CONFIGS_DIR, sub) if sub else CONFIGS_DIR
                    if dest_path.endswith((".cfg", ".ini")) and os.path.isfile(dest_path):
                        try:
                            from configparser import ConfigParser
                            old_cp = ConfigParser(delimiters=(":", "="), interpolation=None)
                            old_cp.optionxform = str
                            old_cp.read(dest_path, encoding="utf-8")

                            new_cp = ConfigParser(delimiters=(":", "="), interpolation=None)
                            new_cp.optionxform = str
                            new_cp.read_string(data.decode("utf-8"))

                            for sec in new_cp.sections():
                                for opt in new_cp.options(sec):
                                    val = new_cp.get(sec, opt)
                                    if "MASKED_IN_BACKUP" in val:
                                        if old_cp.has_section(sec) and old_cp.has_option(sec, opt):
                                            old_val = old_cp.get(sec, opt)
                                            if "MASKED_IN_BACKUP" not in old_val:
                                                new_cp.set(sec, opt, old_val)
                                                continue
                                        from carnaval.secrets_manager import SecretManager
                                        if opt.lower() == "golden_key":
                                            sec_val = SecretManager.get_secret("golden_key") or os.getenv("FUNPAY_GOLDEN_KEY", "") or os.getenv("GOLDEN_KEY", "")
                                            if sec_val:
                                                new_cp.set(sec, opt, sec_val)
                                        elif opt.lower() == "token":
                                            sec_val = os.getenv("TG_BOT_TOKEN", "") or os.getenv("TG_TOKEN", "")
                                            if sec_val:
                                                new_cp.set(sec, opt, sec_val)
                                        elif opt.lower() == "secretkey":
                                            sec_val = os.getenv("CARNAVAL_SECRET", "")
                                            if sec_val:
                                                new_cp.set(sec, opt, sec_val)

                            out_buf = io.StringIO()
                            new_cp.write(out_buf)
                            data = out_buf.getvalue().encode("utf-8")
                        except Exception as ex:
                            logger.warning(f"Carnaval.More: не удалось восстановить секреты при restore: {ex}")

                    try:
                        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                        with open(dest_path, "wb") as f_out:
                            f_out.write(data)
                        # Также обновляем в корневой папке configs/ если CONFIGS_DIR другой
                        if os.path.abspath(CONFIGS_DIR) != os.path.abspath("configs"):
                            root_dest = os.path.join("configs", sub)
                            os.makedirs(os.path.dirname(root_dest), exist_ok=True)
                            with open(root_dest, "wb") as f_out2:
                                f_out2.write(data)
                    except Exception:
                        pass
                elif member.startswith("storage/products/"):
                    zf.extract(member, path=".")
                    try:
                        from carnaval.paths import PRODUCTS_DIR
                        sub = member[len("storage/products/"):]
                        if sub:
                            dest_path = os.path.join(PRODUCTS_DIR, sub)
                            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                            with open(dest_path, "wb") as f_out:
                                f_out.write(zf.read(member))
                    except Exception:
                        pass

        return True, ""
    except Exception as e:
        logger.error(f"Carnaval.More: ошибка восстановления бэкапа: {e}")
        return False, str(e)



# ---------------------------------------------------------------------------
# Системные команды
# ---------------------------------------------------------------------------

def restart_cardinal(confirm: bool = False) -> tuple[bool, str]:
    """
    Перезапускает Cardinal (кросс-платформенно).
    Требует confirm=True.
    """
    if not confirm:
        return False, "Требуется подтверждение (confirm=true)"

    def _do_restart():
        import time as _time
        import subprocess
        _time.sleep(0.5)
        if sys.platform == "win32":
            subprocess.Popen([sys.executable] + sys.argv)
            os._exit(0)
        else:
            try:
                os.execv(sys.executable, [sys.executable] + sys.argv)
            except Exception:
                os._exit(0)

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
        os._exit(0)

    threading.Thread(target=_do_shutdown, daemon=True).start()
    return True, ""


# ---------------------------------------------------------------------------
# Дополнительные функции для паритета с TG-ботом
# ---------------------------------------------------------------------------

def get_authorized_user_detail(target_user_id: int) -> Optional[dict[str, Any]]:
    """Возвращает информацию о конкретном авторизованном пользователе."""
    cardinal = get_cardinal()
    tg = cardinal.telegram
    if not tg:
        return None
    with _AUTH_USERS_LOCK:
        auth_users = tg.authorized_users
        if isinstance(auth_users, dict):
            if target_user_id in auth_users:
                return {"user_id": target_user_id, "data": auth_users[target_user_id]}
            elif str(target_user_id) in auth_users:
                return {"user_id": target_user_id, "data": auth_users[str(target_user_id)]}
        elif isinstance(auth_users, list):
            if target_user_id in auth_users or str(target_user_id) in auth_users:
                return {"user_id": target_user_id, "data": {}}
    return None


def pin_plugin(uuid: str, pinned: Optional[bool] = None) -> tuple[bool, str]:
    """Закрепляет или открепляет плагин."""
    cardinal = get_cardinal()
    if uuid not in cardinal.plugins:
        return False, f"Плагин {uuid} не найден"
    pl = cardinal.plugins[uuid]
    target_pinned = bool(pinned) if pinned is not None else not getattr(pl, "pinned", False)

    if hasattr(cardinal, "pin_plugin"):
        if getattr(pl, "pinned", False) != target_pinned:
            cardinal.pin_plugin(uuid)
        else:
            pl.pinned = target_pinned
    else:
        pl.pinned = target_pinned
        if hasattr(cardinal, "pinned_plugins"):
            if target_pinned and uuid not in cardinal.pinned_plugins:
                cardinal.pinned_plugins.append(uuid)
            elif not target_pinned and uuid in cardinal.pinned_plugins:
                cardinal.pinned_plugins.remove(uuid)
    return True, ""


def get_plugin_commands(uuid: str) -> tuple[Optional[dict[str, str]], Optional[str]]:
    """Возвращает список команд плагина."""
    cardinal = get_cardinal()
    if uuid not in cardinal.plugins:
        return None, f"Плагин {uuid} не найден"
    pl = cardinal.plugins[uuid]
    commands = getattr(pl, "commands", {}) or {}
    return commands, None


def list_available_configs() -> list[dict[str, Any]]:
    """Возвращает метаданные доступных для скачивания/загрузки конфигурационных файлов."""
    configs_meta = [
        {"type": "main", "filename": "_main.cfg", "path": "configs/_main.cfg", "description": "Основной конфиг Cardinal"},
        {"type": "autoResponse", "filename": "auto_response.cfg", "path": "configs/auto_response.cfg", "description": "Конфиг автоответчика"},
        {"type": "autoDelivery", "filename": "auto_delivery.cfg", "path": "configs/auto_delivery.cfg", "description": "Конфиг автовыдачи"},
    ]
    result = []
    import datetime as _dt
    for item in configs_meta:
        path = item["path"]
        exists = os.path.exists(path)
        size = os.path.getsize(path) if exists else 0
        mtime = _dt.datetime.fromtimestamp(os.path.getmtime(path)).isoformat() if exists else None
        result.append({
            "type": item["type"],
            "filename": item["filename"],
            "path": path,
            "exists": exists,
            "size": size,
            "last_modified": mtime,
            "description": item["description"],
        })
    return result


def get_config_content(config_type: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Возвращает (content, filename, error) для указанного типа конфига.
    """
    type_map = {
        "main": ("configs/_main.cfg", "_main.cfg"),
        "autoresponse": ("configs/auto_response.cfg", "auto_response.cfg"),
        "auto_response": ("configs/auto_response.cfg", "auto_response.cfg"),
        "autodelivery": ("configs/auto_delivery.cfg", "auto_delivery.cfg"),
        "auto_delivery": ("configs/auto_delivery.cfg", "auto_delivery.cfg"),
    }
    key = config_type.strip().lower()
    if key not in type_map:
        return None, None, f"Неизвестный тип конфига: {config_type}. Допустимы: main, autoResponse, autoDelivery"
    path, filename = type_map[key]
    if not os.path.exists(path):
        return None, None, f"Файл {path} не найден"
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        if filename == "_main.cfg":
            try:
                from configparser import ConfigParser
                import io
                cp = ConfigParser(interpolation=None)
                cp.read_string(content)
                if "Telegram" in cp and "token" in cp["Telegram"]:
                    cp["Telegram"]["token"] = "[MASKED_BY_CARNAVAL]"
                if "Telegram" in cp and "secretPassword" in cp["Telegram"]:
                    cp["Telegram"]["secretPassword"] = "[MASKED_BY_CARNAVAL]"
                if "FunPay" in cp and "golden_key" in cp["FunPay"]:
                    cp["FunPay"]["golden_key"] = "[MASKED_BY_CARNAVAL]"
                if "Carnaval" in cp and "secretKey" in cp["Carnaval"]:
                    cp["Carnaval"]["secretKey"] = "[MASKED_BY_CARNAVAL]"
                out_str = io.StringIO()
                cp.write(out_str)
                content = out_str.getvalue()
            except Exception:
                pass

        return content, filename, None
    except Exception as e:
        return None, None, str(e)


def save_config_file(config_type: str, content: str) -> tuple[bool, str]:
    """
    Валидирует и сохраняет конфигурационный файл, обновляя состояние Cardinal.
    """
    type_map = {
        "main": ("configs/_main.cfg", "_main.cfg", "main"),
        "autoresponse": ("configs/auto_response.cfg", "auto_response.cfg", "auto_response"),
        "auto_response": ("configs/auto_response.cfg", "auto_response.cfg", "auto_response"),
        "autodelivery": ("configs/auto_delivery.cfg", "auto_delivery.cfg", "auto_delivery"),
        "auto_delivery": ("configs/auto_delivery.cfg", "auto_delivery.cfg", "auto_delivery"),
    }
    key = config_type.strip().lower()
    if key not in type_map:
        return False, f"Неизвестный тип конфига: {config_type}. Допустимы: main, autoResponse, autoDelivery"
    path, filename, norm_type = type_map[key]

    if not content or not content.strip():
        return False, "Содержимое конфига не может быть пустым"

    os.makedirs("storage/cache", exist_ok=True)
    temp_path = f"storage/cache/temp_{norm_type}.cfg"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        return False, f"Не удалось записать временный файл: {e}"

    from Utils import config_loader as cfg_loader
    cardinal = get_cardinal()

    try:
        if norm_type == "main":
            new_cfg = cfg_loader.load_main_config(temp_path)
            cardinal.save_config(new_cfg, path)
            cardinal.MAIN_CFG = new_cfg
        elif norm_type == "auto_response":
            new_cfg = cfg_loader.load_auto_response_config(temp_path)
            raw_new_cfg = cfg_loader.load_raw_auto_response_config(temp_path)
            cardinal.RAW_AR_CFG, cardinal.AR_CFG = raw_new_cfg, new_cfg
            cardinal.save_config(cardinal.RAW_AR_CFG, path)
        elif norm_type == "auto_delivery":
            new_cfg = cfg_loader.load_auto_delivery_config(temp_path)
            cardinal.AD_CFG = new_cfg
            cardinal.save_config(cardinal.AD_CFG, path)
        return True, ""
    except Exception as e:
        logger.error(f"Ошибка проверки конфига {config_type}: {e}", exc_info=True)
        return False, f"Ошибка валидации конфига: {e}"
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


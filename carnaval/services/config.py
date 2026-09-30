"""
carnaval/services/config.py — потокобезопасная работа с конфигурацией Cardinal.

Правила безопасности:
- golden_key, Telegram.token, secretKeyHash маскируются и никогда не отдаются наружу в открытом виде.
- Пароли в прокси маскируются.
- Запись конфига производится под threading.Lock с валидацией значений.
- Смена golden_key требует confirm=True.
"""

from __future__ import annotations

import re
import threading
from typing import Any, Dict

from carnaval.deps import get_cardinal
from Utils.config_loader import check_param

_CONFIG_LOCK = threading.Lock()

# Схема допустимых значений настроек _main.cfg (по Utils/config_loader.py)
CONFIG_SCHEMA: dict[str, dict[str, Any]] = {
    "FunPay": {
        "golden_key": "any",
        "user_agent": "any+empty",
        "autoRaise": ["0", "1"],
        "autoResponse": ["0", "1"],
        "autoDelivery": ["0", "1"],
        "multiDelivery": ["0", "1"],
        "autoRestore": ["0", "1"],
        "autoDisable": ["0", "1"],
        "oldMsgGetMode": ["0", "1"],
        "keepSentMessagesUnread": ["0", "1"],
        "locale": ["ru", "en", "uk"],
    },
    "Telegram": {
        "enabled": ["0", "1"],
        "token": "any+empty",
        "secretKeyHash": "any",
        "proxy": "any+empty",
        "blockLogin": ["0", "1"],
    },
    "BlockList": {
        "blockDelivery": ["0", "1"],
        "blockResponse": ["0", "1"],
        "blockNewMessageNotification": ["0", "1"],
        "blockNewOrderNotification": ["0", "1"],
        "blockCommandNotification": ["0", "1"],
    },
    "NewMessageView": {
        "includeMyMessages": ["0", "1"],
        "includeFPMessages": ["0", "1"],
        "includeBotMessages": ["0", "1"],
        "notifyOnlyMyMessages": ["0", "1"],
        "notifyOnlyFPMessages": ["0", "1"],
        "notifyOnlyBotMessages": ["0", "1"],
        "showImageName": ["0", "1"],
    },
    "Greetings": {
        "ignoreSystemMessages": ["0", "1"],
        "onlyNewChats": ["0", "1"],
        "sendGreetings": ["0", "1"],
        "greetingsText": "any",
        "greetingsCooldown": "any",
    },
    "OrderConfirm": {
        "watermark": ["0", "1"],
        "sendReply": ["0", "1"],
        "replyText": "any",
    },
    "ReviewReply": {
        "star1Reply": ["0", "1"],
        "star2Reply": ["0", "1"],
        "star3Reply": ["0", "1"],
        "star4Reply": ["0", "1"],
        "star5Reply": ["0", "1"],
        "star1ReplyText": "any+empty",
        "star2ReplyText": "any+empty",
        "star3ReplyText": "any+empty",
        "star4ReplyText": "any+empty",
        "star5ReplyText": "any+empty",
    },
    "Proxy": {
        "enable": ["0", "1"],
        "proxy": "any+empty",
        "check": ["0", "1"],
    },
    "Other": {
        "watermark": "any+empty",
        "requestsDelay": [str(i) for i in range(1, 101)],
        "language": ["ru", "en", "uk"],
    },
    "Carnaval": {
        "enabled": ["0", "1"],
        "host": "any",
        "port": "any",
        "secretKey": "any+empty",
    },
}

# Опасные ключи настроек, требующие confirm=True для изменения
DANGEROUS_KEYS = {
    ("FunPay", "golden_key"),
}


def mask_secret(val: str, prefix_len: int = 4, suffix_len: int = 4) -> str:
    """Маскирует строку секретов (golden_key, tokens)."""
    if not val:
        return ""
    if len(val) <= (prefix_len + suffix_len):
        return "…" * 4
    return f"{val[:prefix_len]}…{val[-suffix_len:]}"


def mask_proxy_url(proxy_str: str) -> str:
    """Маскирует пароль в строке прокси (scheme://user:pass@host:port)."""
    if not proxy_str:
        return ""
    return re.sub(r":([^:@]+)@", r":****@", proxy_str)


def get_masked_settings() -> dict[str, dict[str, str]]:
    """
    Возвращает словарь настроек _main.cfg с замаскированными секретами.
    Никогда не отдает golden_key, Telegram.token, secretKeyHash и пароли прокси в открытом виде!
    """
    cardinal = get_cardinal()
    cfg = cardinal.MAIN_CFG
    result: dict[str, dict[str, str]] = {}

    with _CONFIG_LOCK:
        for section in cfg.sections():
            result[section] = {}
            for key, val in cfg.items(section):
                # Маскирование чувствительных данных
                if section == "FunPay" and key == "golden_key":
                    result[section][key] = mask_secret(val, 4, 4)
                elif section == "Telegram" and key == "token":
                    result[section][key] = mask_secret(val, 6, 4)
                elif section == "Telegram" and key == "secretKeyHash":
                    result[section][key] = "********"
                elif section == "Carnaval" and key == "secretKey":
                    result[section][key] = "********" if val else ""
                elif (section == "Proxy" and key == "proxy") or (section == "Telegram" and key == "proxy"):
                    result[section][key] = mask_proxy_url(val)
                else:
                    result[section][key] = val

    return result


def update_setting(section: str, key: str, value: str, confirm: bool = False) -> tuple[bool, str]:
    """
    Валидирует и сохраняет настройку в _main.cfg.
    Возвращает (success: bool, error_message: str).
    """
    cardinal = get_cardinal()
    cfg = cardinal.MAIN_CFG

    if section not in CONFIG_SCHEMA or key not in CONFIG_SCHEMA[section]:
        return False, f"Unknown parameter '{section}.{key}'"

    # Проверка опасных ключей на подтверждение
    if (section, key) in DANGEROUS_KEYS and not confirm:
        return False, f"Modification of '{section}.{key}' requires confirm=true"

    allowed = CONFIG_SCHEMA[section][key]
    val_str = str(value).strip()

    # Валидация значения
    if allowed == "any":
        if not val_str:
            return False, f"Parameter '{key}' cannot be empty"
    elif allowed == "any+empty":
        pass  # может быть пустым
    elif isinstance(allowed, list):
        if val_str not in allowed:
            return False, f"Value '{val_str}' not in allowed values: {allowed}"

    with _CONFIG_LOCK:
        if not cfg.has_section(section):
            cfg.add_section(section)
        cfg.set(section, key, val_str)
        try:
            cardinal.save_config(cfg, "configs/_main.cfg")
        except Exception as e:
            return False, f"Failed to save config: {e}"

    return True, ""

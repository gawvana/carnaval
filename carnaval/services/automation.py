"""
carnaval/services/automation.py — логика управления автоматизацией:
- Автовыдача (AD_CFG, configs/auto_delivery.cfg, тесты)
- Товарные файлы (storage/products/* с блокировками cardinal_tools.get_products_file_lock)
- Автоответчик (RAW_AR_CFG / AR_CFG, configs/auto_response.cfg)
- Шаблоны ответов (answer_templates.json)
- Лоты FunPay (c.profile)
"""

from __future__ import annotations

import os
import re
import string
import random
import time
import uuid
from collections import deque
import asyncio
import threading
import json
import hashlib
from typing import Any, Optional

from carnaval.deps import get_cardinal
from Utils import cardinal_tools
from Utils import config_loader as cfg_loader
from tg_bot import utils as tg_utils

_AD_LOCK = threading.Lock()
_AR_LOCK = threading.Lock()
_TEMPLATES_LOCK = threading.Lock()
_TRACES_LOCK = threading.Lock()
_TRACES_BUFFER: deque[dict[str, Any]] = deque(maxlen=200)

FILENAME_REGEX = re.compile(r"^[А-Яа-яЁёA-Za-z0-9_\-\. ]+$")


def _sanitize_filename(name: str) -> str:
    """Безопасная очистка и валидация имени файла (защита от path traversal)."""
    base = os.path.basename(name.strip())
    if not base or not FILENAME_REGEX.match(base):
        raise ValueError(f"Invalid filename '{name}'. Use only alphanumeric, spaces, hyphens and underscores.")
    return base


def _get_product_path(filename: str) -> str:
    safe = _sanitize_filename(filename)
    path = os.path.abspath(os.path.join("storage", "products", safe))
    products_dir = os.path.abspath(os.path.join("storage", "products"))
    if not path.startswith(products_dir):
        raise ValueError("Path traversal attempt detected")
    return path


# ─────────────────────────────────────────────────────────────
# 1. Автовыдача товаров (AD_CFG)
# ─────────────────────────────────────────────────────────────

def list_delivery_lots() -> list[dict[str, Any]]:
    """Получить список всех лотов с настроенной автовыдачей."""
    cardinal = get_cardinal()
    cfg = cardinal.AD_CFG
    lots = []

    with _AD_LOCK:
        for idx, section in enumerate(cfg.sections()):
            sec = cfg[section]
            file_name = sec.get("productsFileName")
            goods_count = 0
            has_file = False

            if file_name:
                try:
                    fpath = _get_product_path(file_name)
                    if os.path.exists(fpath):
                        has_file = True
                        goods_count = cardinal_tools.count_products(fpath)
                except Exception:
                    pass

            lots.append({
                "index": idx,
                "name": section,
                "response": sec.get("response", ""),
                "productsFileName": file_name or "",
                "disable": sec.getboolean("disable", fallback=False),
                "goods_count": goods_count,
                "has_file": has_file,
            })

    return lots


def get_delivery_lot(index: int) -> Optional[dict[str, Any]]:
    """Получить лот автовыдачи по числовому индексу."""
    lots = list_delivery_lots()
    if 0 <= index < len(lots):
        return lots[index]
    return None


def create_delivery_lot(name: str, response: str, products_file: Optional[str] = None, disable: bool = False) -> dict[str, Any]:
    """Создать новое правило автовыдачи для лота."""
    cardinal = get_cardinal()
    cfg = cardinal.AD_CFG
    name_clean = name.strip()

    if not name_clean:
        raise ValueError("Lot name cannot be empty")

    if products_file and "$product" not in response:
        raise ValueError("Delivery response must contain '$product' placeholder when goods file is attached")

    with _AD_LOCK:
        if name_clean in cfg.sections():
            raise ValueError(f"Auto-delivery for lot '{name_clean}' already exists")

        cfg.add_section(name_clean)
        cfg.set(name_clean, "response", response)
        if products_file:
            cfg.set(name_clean, "productsFileName", _sanitize_filename(products_file))
        cfg.set(name_clean, "disable", "1" if disable else "0")

        os.makedirs("configs", exist_ok=True)
        cardinal.save_config(cfg, "configs/auto_delivery.cfg")
        idx = len(cfg.sections()) - 1

    return get_delivery_lot(idx) or {"index": idx, "name": name_clean}


def update_delivery_lot(index: int, response: Optional[str] = None, products_file: Optional[str] = None, disable: Optional[bool] = None) -> dict[str, Any]:
    """Обновить настройки автовыдачи для существующего лота."""
    cardinal = get_cardinal()
    cfg = cardinal.AD_CFG

    with _AD_LOCK:
        sections = cfg.sections()
        if not (0 <= index < len(sections)):
            raise IndexError(f"Lot index {index} out of range")

        lot_name = sections[index]
        sec = cfg[lot_name]

        current_file = sec.get("productsFileName")
        new_file = _sanitize_filename(products_file) if products_file is not None and products_file.strip() else None

        target_file = new_file if products_file is not None else current_file
        target_resp = response if response is not None else sec.get("response", "")

        if target_file and "$product" not in target_resp:
            raise ValueError("Delivery response must contain '$product' when goods file is attached")

        if response is not None:
            cfg.set(lot_name, "response", response)
        if products_file is not None:
            if new_file:
                cfg.set(lot_name, "productsFileName", new_file)
            else:
                cfg.remove_option(lot_name, "productsFileName")
        if disable is not None:
            cfg.set(lot_name, "disable", "1" if disable else "0")

        os.makedirs("configs", exist_ok=True)
        cardinal.save_config(cfg, "configs/auto_delivery.cfg")

    return get_delivery_lot(index) or {"index": index, "name": lot_name}


def delete_delivery_lot(index: int) -> bool:
    """Удалить правило автовыдачи."""
    cardinal = get_cardinal()
    cfg = cardinal.AD_CFG

    with _AD_LOCK:
        sections = cfg.sections()
        if not (0 <= index < len(sections)):
            raise IndexError(f"Lot index {index} out of range")

        lot_name = sections[index]
        cfg.remove_section(lot_name)
        os.makedirs("configs", exist_ok=True)
        cardinal.save_config(cfg, "configs/auto_delivery.cfg")

    return True


def create_delivery_test(index: int) -> dict[str, str]:
    """
    Генерирует секретный ключ для тестирования автовыдачи лота.
    Ключ сохраняется в c.delivery_tests[key] = lot_name.
    """
    cardinal = get_cardinal()
    cfg = cardinal.AD_CFG

    with _AD_LOCK:
        sections = cfg.sections()
        if not (0 <= index < len(sections)):
            raise IndexError(f"Lot index {index} out of range")
        lot_name = sections[index]

    key = "".join(random.choices(string.ascii_letters + string.digits, k=50))
    cardinal.delivery_tests[key] = lot_name
    return {"key": key, "lot_name": lot_name}


# ─────────────────────────────────────────────────────────────
# 2. Файлы товаров (storage/products/*)
# ─────────────────────────────────────────────────────────────

def list_products_files() -> list[dict[str, Any]]:
    """Получить список всех файлов на складе товаров."""
    products_dir = os.path.join("storage", "products")
    os.makedirs(products_dir, exist_ok=True)
    files = []

    for name in os.listdir(products_dir):
        fpath = os.path.join(products_dir, name)
        if not os.path.isfile(fpath):
            continue
        try:
            count = cardinal_tools.count_products(fpath)
            stat = os.stat(fpath)
            files.append({
                "name": name,
                "count": count,
                "size_bytes": stat.st_size,
                "modified": int(stat.st_mtime),
            })
        except Exception:
            pass

    return sorted(files, key=lambda f: f["name"].lower())


def get_products_file_goods(filename: str, limit: int = 100) -> list[str]:
    """Получить строки товаров из файла под блокировкой."""
    fpath = _get_product_path(filename)
    lock = cardinal_tools.get_products_file_lock(fpath)

    with lock:
        if not os.path.exists(fpath):
            raise FileNotFoundError(f"Products file '{filename}' not found")
        with open(fpath, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]

    return lines[:limit]


def create_products_file(filename: str, goods: list[str] | None = None) -> dict[str, Any]:
    """Создать новый файл с товарами под блокировкой."""
    fpath = _get_product_path(filename)
    lock = cardinal_tools.get_products_file_lock(fpath)

    with lock:
        if os.path.exists(fpath):
            raise FileExistsError(f"Products file '{filename}' already exists")
        with open(fpath, "w", encoding="utf-8") as f:
            if goods:
                f.write("\n".join(g.strip() for g in goods if g.strip()) + "\n")

    return {
        "name": _sanitize_filename(filename),
        "count": len(goods) if goods else 0,
    }


def add_goods_to_file(filename: str, goods: list[str], at_zero_position: bool = False) -> int:
    """Добавить товары в существующий файл под блокировкой."""
    fpath = _get_product_path(filename)
    clean_goods = [g.strip() for g in goods if g.strip()]
    if not clean_goods:
        return cardinal_tools.count_products(fpath)

    cardinal_tools.add_products(fpath, clean_goods, at_zero_position=at_zero_position)
    return cardinal_tools.count_products(fpath)


def delete_products_file(filename: str) -> bool:
    """Удалить товарный файл."""
    fpath = _get_product_path(filename)
    lock = cardinal_tools.get_products_file_lock(fpath)

    with lock:
        if os.path.exists(fpath):
            os.remove(fpath)
            return True
        return False


# ─────────────────────────────────────────────────────────────
# 3. Автоответчик (AR_CFG / RAW_AR_CFG)
# ─────────────────────────────────────────────────────────────

def list_auto_response_commands() -> list[dict[str, Any]]:
    """Получить список всех правил автоответа."""
    cardinal = get_cardinal()
    raw_cfg = cardinal.RAW_AR_CFG
    commands = []

    with _AR_LOCK:
        for idx, cmd in enumerate(raw_cfg.sections()):
            sec = raw_cfg[cmd]
            commands.append({
                "index": idx,
                "command": cmd,
                "response": sec.get("response", ""),
                "telegramNotification": sec.getboolean("telegramNotification", fallback=False),
                "enabled": sec.getboolean("enabled", fallback=True),
                "notificationText": sec.get("notificationText", ""),
            })

    return commands


def create_auto_response_command(command: str, response: str, telegram_notification: bool = False, enabled: bool = True, notification_text: str = "") -> dict[str, Any]:
    """Создать новую команду автоответа."""
    cardinal = get_cardinal()
    raw_cmd = command.strip()

    if not raw_cmd:
        raise ValueError("Command cannot be empty")
    if not response.strip():
        raise ValueError("Response text cannot be empty")

    with _AR_LOCK:
        if raw_cmd in cardinal.RAW_AR_CFG.sections():
            raise ValueError(f"Command '{raw_cmd}' already exists")

        cardinal.RAW_AR_CFG.add_section(raw_cmd)
        cardinal.RAW_AR_CFG.set(raw_cmd, "response", response)
        cardinal.RAW_AR_CFG.set(raw_cmd, "telegramNotification", "1" if telegram_notification else "0")
        cardinal.RAW_AR_CFG.set(raw_cmd, "enabled", "1" if enabled else "0")
        if notification_text:
            cardinal.RAW_AR_CFG.set(raw_cmd, "notificationText", notification_text)

        os.makedirs("configs", exist_ok=True)
        cardinal.save_config(cardinal.RAW_AR_CFG, "configs/auto_response.cfg")

        # Перезагружаем конфиги для синхронизации расширенных наборов (a|b)
        if os.path.exists("configs/auto_response.cfg"):
            try:
                cardinal.AR_CFG = cfg_loader.load_auto_response_config("configs/auto_response.cfg")
                cardinal.RAW_AR_CFG = cfg_loader.load_raw_auto_response_config("configs/auto_response.cfg")
            except Exception:
                pass
        idx = len(cardinal.RAW_AR_CFG.sections()) - 1

    return list_auto_response_commands()[idx]


def update_auto_response_command(index: int, command: Optional[str] = None, response: Optional[str] = None, telegram_notification: Optional[bool] = None, enabled: Optional[bool] = None, notification_text: Optional[str] = None) -> dict[str, Any]:
    """Обновить существующую команду автоответа."""
    cardinal = get_cardinal()

    with _AR_LOCK:
        sections = cardinal.RAW_AR_CFG.sections()
        if not (0 <= index < len(sections)):
            raise IndexError(f"Command index {index} out of range")

        old_cmd = sections[index]
        sec = cardinal.RAW_AR_CFG[old_cmd]

        new_cmd = command.strip() if command else old_cmd
        new_resp = response if response is not None else sec.get("response", "")
        new_tg = "1" if (telegram_notification if telegram_notification is not None else sec.getboolean("telegramNotification")) else "0"
        new_en = "1" if (enabled if enabled is not None else sec.getboolean("enabled")) else "0"
        new_ntfc = notification_text if notification_text is not None else sec.get("notificationText", "")

        if new_cmd != old_cmd:
            cardinal.RAW_AR_CFG.remove_section(old_cmd)
            cardinal.RAW_AR_CFG.add_section(new_cmd)

        cardinal.RAW_AR_CFG.set(new_cmd, "response", new_resp)
        cardinal.RAW_AR_CFG.set(new_cmd, "telegramNotification", new_tg)
        cardinal.RAW_AR_CFG.set(new_cmd, "enabled", new_en)
        if new_ntfc:
            cardinal.RAW_AR_CFG.set(new_cmd, "notificationText", new_ntfc)
        elif cardinal.RAW_AR_CFG.has_option(new_cmd, "notificationText"):
            cardinal.RAW_AR_CFG.remove_option(new_cmd, "notificationText")

        os.makedirs("configs", exist_ok=True)
        cardinal.save_config(cardinal.RAW_AR_CFG, "configs/auto_response.cfg")
        if os.path.exists("configs/auto_response.cfg"):
            try:
                cardinal.AR_CFG = cfg_loader.load_auto_response_config("configs/auto_response.cfg")
                cardinal.RAW_AR_CFG = cfg_loader.load_raw_auto_response_config("configs/auto_response.cfg")
            except Exception:
                pass

    return list_auto_response_commands()[index]


def delete_auto_response_command(index: int) -> bool:
    """Удалить команду автоответа."""
    cardinal = get_cardinal()

    with _AR_LOCK:
        sections = cardinal.RAW_AR_CFG.sections()
        if not (0 <= index < len(sections)):
            raise IndexError(f"Command index {index} out of range")

        cmd = sections[index]
        cardinal.RAW_AR_CFG.remove_section(cmd)
        os.makedirs("configs", exist_ok=True)
        cardinal.save_config(cardinal.RAW_AR_CFG, "configs/auto_response.cfg")
        if os.path.exists("configs/auto_response.cfg"):
            try:
                cardinal.AR_CFG = cfg_loader.load_auto_response_config("configs/auto_response.cfg")
                cardinal.RAW_AR_CFG = cfg_loader.load_raw_auto_response_config("configs/auto_response.cfg")
            except Exception:
                pass

    return True


# ─────────────────────────────────────────────────────────────
# 4. Шаблоны ответов (answer_templates.json)
# ─────────────────────────────────────────────────────────────

def _get_templates_list() -> list[str]:
    cardinal = get_cardinal()
    if cardinal.telegram and hasattr(cardinal.telegram, "answer_templates"):
        return cardinal.telegram.answer_templates
    return tg_utils.load_answer_templates()


def _save_templates_list(tmpls: list[str]) -> None:
    cardinal = get_cardinal()
    tg_utils.save_answer_templates(tmpls)
    if cardinal.telegram and hasattr(cardinal.telegram, "answer_templates"):
        cardinal.telegram.answer_templates = tmpls


def list_templates() -> list[dict[str, Any]]:
    """Получить список всех шаблонов ответов."""
    with _TEMPLATES_LOCK:
        raw = _get_templates_list()
        return [{"index": i, "text": text} for i, text in enumerate(raw)]


def create_template(text: str) -> dict[str, Any]:
    """Добавить шаблон ответа."""
    clean = text.strip()
    if not clean:
        raise ValueError("Template text cannot be empty")

    with _TEMPLATES_LOCK:
        tmpls = _get_templates_list()
        if clean in tmpls:
            raise ValueError("Such template already exists")
        tmpls.append(clean)
        _save_templates_list(tmpls)
        idx = len(tmpls) - 1

    return {"index": idx, "text": clean}


def update_template(index: int, text: str) -> dict[str, Any]:
    """Обновить существующий шаблон ответа."""
    clean = text.strip()
    if not clean:
        raise ValueError("Template text cannot be empty")

    with _TEMPLATES_LOCK:
        tmpls = _get_templates_list()
        if not (0 <= index < len(tmpls)):
            raise IndexError(f"Template index {index} out of range")
        tmpls[index] = clean
        _save_templates_list(tmpls)

    return {"index": index, "text": clean}


def delete_template(index: int) -> bool:
    """Удалить шаблон ответа."""
    with _TEMPLATES_LOCK:
        tmpls = _get_templates_list()
        if not (0 <= index < len(tmpls)):
            raise IndexError(f"Template index {index} out of range")
        tmpls.pop(index)
        _save_templates_list(tmpls)

    return True


def render_template(index: int, username: Optional[str] = None) -> str:
    """Отрендерить шаблон с подстановкой $username."""
    with _TEMPLATES_LOCK:
        tmpls = _get_templates_list()
        if not (0 <= index < len(tmpls)):
            raise IndexError(f"Template index {index} out of range")
        tmpl = tmpls[index]
    safe_user = cardinal_tools.safe_text(username or "")
    return tmpl.replace("$username", safe_user)


async def send_template_to_chat(index: int, chat_id: int, username: Optional[str] = None) -> bool:
    """Отправить шаблон в указанный чат FunPay."""
    from carnaval.services import chats as chats_svc
    text = render_template(index, username)
    return await chats_svc.send_message(chat_id, text, chat_name=username)


def list_templates_answer_mode(username: Optional[str] = None) -> list[dict[str, Any]]:
    """Получить шаблоны в режиме ответа (с предпросмотром подстановки $username)."""
    with _TEMPLATES_LOCK:
        tmpls = _get_templates_list()
        safe_user = cardinal_tools.safe_text(username or "")
        return [
            {
                "index": i,
                "text": t,
                "rendered": t.replace("$username", safe_user),
            }
            for i, t in enumerate(tmpls)
        ]



# ─────────────────────────────────────────────────────────────
# 5. Лоты FunPay продавца
# ─────────────────────────────────────────────────────────────

async def get_funpay_lots(refresh: bool = False) -> list[dict[str, Any]]:
    """Получить список лотов продавца с FunPay."""
    cardinal = get_cardinal()
    acc = cardinal.account
    if not acc or not getattr(acc, "id", None):
        return []

    def _fetch():
        try:
            if refresh or not getattr(cardinal, "profile", None):
                cardinal.update_lots_and_categories()
            profile = getattr(cardinal, "profile", None)
            if not profile and acc and getattr(acc, "id", None):
                profile = acc.get_user(acc.id)
                cardinal.profile = profile

            lots = []
            if profile and hasattr(profile, "get_sorted_lots"):
                sorted_lots = profile.get_sorted_lots(1)
                for lot_id, lot in sorted_lots.items():
                    lots.append({
                        "id": str(lot_id),
                        "description": getattr(lot, "description", ""),
                        "price": getattr(lot, "price", 0.0),
                        "currency": str(getattr(lot, "currency", "")),
                        "server": getattr(lot, "server", None),
                        "side": getattr(lot, "side", None),
                        "subcategory_name": getattr(lot, "subcategory_name", ""),
                        "title": getattr(lot, "title", getattr(lot, "description", "")),
                    })
            return lots
        except Exception:
            return []

    return await asyncio.to_thread(_fetch)


# ─────────────────────────────────────────────────────────────
# 6. Эмуляция автоматизации и кольцевой буфер трассировок
# ─────────────────────────────────────────────────────────────

def record_execution_trace(trace: dict[str, Any]) -> None:
    """Сохраняет трассировку выполнения правила в кольцевой буфер."""
    with _TRACES_LOCK:
        _TRACES_BUFFER.append(trace)


def get_execution_traces(limit: int = 50) -> list[dict[str, Any]]:
    """
    Возвращает кольцевой буфер недавних оценок правил.
    Свежие записи возвращаются первыми.
    """
    with _TRACES_LOCK:
        traces = list(_TRACES_BUFFER)
    return list(reversed(traces))[:limit]


def clear_execution_traces() -> None:
    """Очищает кольцевой буфер трассировок (полезно для тестов)."""
    with _TRACES_LOCK:
        _TRACES_BUFFER.clear()


def _simulate_delivery(cardinal: Any, payload: dict[str, Any]) -> tuple[Optional[str], list[dict[str, Any]], Optional[dict[str, Any]], bool]:
    conditions: list[dict[str, Any]] = []
    lot_name_input = str(payload.get("lot_name") or payload.get("description") or payload.get("name") or "").strip()
    buyer_username = str(payload.get("buyer_username") or payload.get("username") or payload.get("buyer") or "TestBuyer").strip()
    amount = max(1, int(payload.get("amount", 1)))
    order_id = str(payload.get("order_id") or payload.get("id") or "TEST12345")
    chat_id = int(payload.get("chat_id", 12345))

    # 1. Глобальный переключатель автовыдачи
    global_enabled = True
    if hasattr(cardinal, "MAIN_CFG") and cardinal.MAIN_CFG.has_section("FunPay"):
        try:
            global_enabled = cardinal.MAIN_CFG.getboolean("FunPay", "autoDelivery", fallback=True)
        except Exception:
            global_enabled = True
    if hasattr(cardinal, "autodelivery_enabled"):
        global_enabled = bool(global_enabled and cardinal.autodelivery_enabled)

    conditions.append({
        "name": "global_auto_delivery",
        "passed": bool(global_enabled),
        "details": "Auto-delivery is enabled globally" if global_enabled else "Auto-delivery is disabled globally in config",
    })

    # 2. Проверка чёрного списка
    bl_blocked = False
    if hasattr(cardinal, "blacklist") and buyer_username in cardinal.blacklist:
        bl_enabled = True
        if hasattr(cardinal, "bl_delivery_enabled"):
            bl_enabled = cardinal.bl_delivery_enabled
        elif hasattr(cardinal, "MAIN_CFG") and cardinal.MAIN_CFG.has_section("BlockList"):
            bl_enabled = cardinal.MAIN_CFG.getboolean("BlockList", "blockDelivery", fallback=True)
        if bl_enabled:
            bl_blocked = True

    conditions.append({
        "name": "buyer_not_blacklisted",
        "passed": not bl_blocked,
        "details": "Buyer is not blacklisted" if not bl_blocked else f"Buyer '{buyer_username}' is blacklisted and delivery is blocked",
    })

    # 3. Поиск подходящего правила в AD_CFG
    matched_rule_name = None
    rule_section = None
    ad_cfg = getattr(cardinal, "AD_CFG", None)

    if ad_cfg and hasattr(ad_cfg, "sections"):
        matched_lots = []
        # Pass 0: exact match
        for s in ad_cfg.sections():
            if lot_name_input == s:
                matched_lots.append(s)
        # Pass 1: startswith
        if not matched_lots:
            for s in ad_cfg.sections():
                if lot_name_input.startswith(s):
                    matched_lots.append(s)
        # Pass 2: substring
        if not matched_lots:
            for s in ad_cfg.sections():
                if s in lot_name_input:
                    matched_lots.append(s)

        if matched_lots:
            matched_rule_name = max(matched_lots, key=len)
            rule_section = ad_cfg[matched_rule_name]

    rule_matched = matched_rule_name is not None
    conditions.append({
        "name": "lot_rule_matched",
        "passed": rule_matched,
        "details": f"Matched rule '{matched_rule_name}'" if rule_matched else f"No auto-delivery rule found for '{lot_name_input}'",
    })

    # 4. Проверка активности лота (disable = 0)
    rule_active = False
    if rule_section is not None:
        disabled = rule_section.getboolean("disable", fallback=False)
        rule_active = not disabled
        conditions.append({
            "name": "rule_not_disabled",
            "passed": rule_active,
            "details": "Rule is active" if rule_active else f"Auto-delivery is disabled for lot '{matched_rule_name}'",
        })
    else:
        conditions.append({
            "name": "rule_not_disabled",
            "passed": False,
            "details": "No rule matched to check disable status",
        })

    # 5. Проверка наличия товаров на складе (без списания и мутаций)
    goods_available = False
    products_file = None
    sample_goods: list[str] = []
    goods_count = 0
    if rule_section is not None and rule_active:
        products_file = rule_section.get("productsFileName")
        if products_file:
            try:
                fpath = _get_product_path(products_file)
                if os.path.exists(fpath):
                    with open(fpath, "r", encoding="utf-8") as f:
                        lines = [l.strip() for l in f if l.strip()]
                    goods_count = len(lines)
                    sample_goods = lines[:amount]
                    goods_available = goods_count >= amount
                    conditions.append({
                        "name": "goods_availability",
                        "passed": goods_available,
                        "details": f"Stock has {goods_count} items (required {amount})" if goods_available else f"Insufficient stock: {goods_count} < {amount}",
                    })
                else:
                    conditions.append({
                        "name": "goods_availability",
                        "passed": False,
                        "details": f"Products file '{products_file}' does not exist on disk",
                    })
            except Exception as e:
                conditions.append({
                    "name": "goods_availability",
                    "passed": False,
                    "details": f"Error accessing products file '{products_file}': {e}",
                })
        else:
            goods_available = True
            conditions.append({
                "name": "goods_availability",
                "passed": True,
                "details": "No goods file configured (text-only delivery)",
            })
    else:
        conditions.append({
            "name": "goods_availability",
            "passed": False,
            "details": "Rule not active or not matched",
        })

    success = bool(global_enabled and not bl_blocked and rule_matched and rule_active and goods_available)

    action_preview = None
    if rule_section is not None:
        raw_response = rule_section.get("response", "")
        formatted_resp = raw_response
        if products_file and sample_goods:
            formatted_resp = formatted_resp.replace("$product", "\n".join(sample_goods))
        elif "$product" in formatted_resp:
            formatted_resp = formatted_resp.replace("$product", "[PREVIEW_PRODUCT_KEY]")
        formatted_resp = formatted_resp.replace("$order_id", order_id)
        formatted_resp = formatted_resp.replace("$buyer", buyer_username)
        formatted_resp = formatted_resp.replace("$username", buyer_username)

        action_preview = {
            "action": "deliver_product",
            "delivery_text": formatted_resp,
            "recipient": buyer_username,
            "chat_id": chat_id,
            "products_file": products_file or None,
            "goods_delivered_count": len(sample_goods) if products_file else 0,
            "goods_left_estimate": max(0, goods_count - amount) if products_file else None,
            "sample_goods": sample_goods,
            "will_deliver": success,
        }

    return matched_rule_name, conditions, action_preview, success


def _simulate_response(cardinal: Any, payload: dict[str, Any]) -> tuple[Optional[str], list[dict[str, Any]], Optional[dict[str, Any]], bool]:
    conditions: list[dict[str, Any]] = []
    message_text = str(payload.get("message") or payload.get("text") or payload.get("command") or "")
    author = str(payload.get("author") or payload.get("username") or payload.get("user") or "TestUser").strip()
    chat_id = int(payload.get("chat_id", 12345))
    chat_name = str(payload.get("chat_name") or author)

    # 1. Глобальный переключатель автоответа
    global_enabled = True
    if hasattr(cardinal, "MAIN_CFG") and cardinal.MAIN_CFG.has_section("FunPay"):
        try:
            global_enabled = cardinal.MAIN_CFG.getboolean("FunPay", "autoResponse", fallback=True)
        except Exception:
            global_enabled = True
    if hasattr(cardinal, "autoresponse_enabled"):
        global_enabled = bool(global_enabled and cardinal.autoresponse_enabled)

    conditions.append({
        "name": "global_auto_response",
        "passed": bool(global_enabled),
        "details": "Auto-response is enabled globally" if global_enabled else "Auto-response is disabled globally in config",
    })

    # 2. Проверка чёрного списка
    bl_blocked = False
    if hasattr(cardinal, "blacklist") and author in cardinal.blacklist:
        bl_enabled = True
        if hasattr(cardinal, "bl_response_enabled"):
            bl_enabled = cardinal.bl_response_enabled
        elif hasattr(cardinal, "MAIN_CFG") and cardinal.MAIN_CFG.has_section("BlockList"):
            bl_enabled = cardinal.MAIN_CFG.getboolean("BlockList", "blockResponse", fallback=True)
        if bl_enabled:
            bl_blocked = True

    conditions.append({
        "name": "user_not_blacklisted",
        "passed": not bl_blocked,
        "details": "User is not blacklisted" if not bl_blocked else f"User '{author}' is in blacklist and auto-response is blocked",
    })

    # 3. Сопоставление команды
    cmd_clean = message_text.strip().lower()
    matched_rule_name = None
    rule_section = None

    ar_cfg = getattr(cardinal, "AR_CFG", None)
    raw_ar_cfg = getattr(cardinal, "RAW_AR_CFG", None)

    if ar_cfg and hasattr(ar_cfg, "__contains__") and cmd_clean in ar_cfg:
        matched_rule_name = cmd_clean
        rule_section = ar_cfg[cmd_clean]
    elif raw_ar_cfg and hasattr(raw_ar_cfg, "sections"):
        for section in raw_ar_cfg.sections():
            variants = [v.strip().lower() for v in section.split("|")]
            if cmd_clean in variants:
                matched_rule_name = section
                rule_section = raw_ar_cfg[section]
                break

    matched = matched_rule_name is not None
    conditions.append({
        "name": "command_matched",
        "passed": matched,
        "details": f"Command matched rule '{matched_rule_name}'" if matched else f"No command rule matched for '{message_text}'",
    })

    # 4. Проверка активности команды
    cmd_enabled = False
    if rule_section is not None:
        cmd_enabled = rule_section.getboolean("enabled", fallback=True)
        conditions.append({
            "name": "command_enabled",
            "passed": cmd_enabled,
            "details": "Command is enabled" if cmd_enabled else f"Command '{matched_rule_name}' is disabled",
        })
    else:
        conditions.append({
            "name": "command_enabled",
            "passed": False,
            "details": "No command matched to check enabled status",
        })

    success = bool(global_enabled and not bl_blocked and matched and cmd_enabled)

    action_preview = None
    if rule_section is not None:
        resp_text = rule_section.get("response", "")
        resp_text = resp_text.replace("$username", author).replace("$chat_name", chat_name)
        # Проверяем RAW_AR_CFG для опций telegramNotification и notificationText
        raw_sec = None
        if raw_ar_cfg and hasattr(raw_ar_cfg, "sections"):
            for section in raw_ar_cfg.sections():
                variants = [v.strip().lower() for v in section.split("|")]
                if cmd_clean in variants or (matched_rule_name and matched_rule_name in variants):
                    raw_sec = raw_ar_cfg[section]
                    break

        tg_notify = False
        if hasattr(rule_section, "has_option") and rule_section.has_option("telegramNotification"):
            tg_notify = rule_section.getboolean("telegramNotification", fallback=False)
        elif raw_sec and hasattr(raw_sec, "getboolean"):
            tg_notify = raw_sec.getboolean("telegramNotification", fallback=False)

        ntfc_text = ""
        if hasattr(rule_section, "get"):
            ntfc_text = rule_section.get("notificationText", "") or ""
        if not ntfc_text and raw_sec and hasattr(raw_sec, "get"):
            ntfc_text = raw_sec.get("notificationText", "") or ""

        if ntfc_text:
            ntfc_text = ntfc_text.replace("$username", author).replace("$chat_name", chat_name)

        action_preview = {
            "action": "send_response",
            "response_text": resp_text,
            "recipient": author,
            "chat_id": chat_id,
            "telegram_notification": tg_notify,
            "notification_text": ntfc_text if tg_notify else None,
            "will_respond": success,
        }

    return matched_rule_name, conditions, action_preview, success


def _simulate_greetings(cardinal: Any, payload: dict[str, Any]) -> tuple[Optional[str], list[dict[str, Any]], Optional[dict[str, Any]], bool]:
    conditions: list[dict[str, Any]] = []
    username = str(payload.get("username") or payload.get("author") or "NewUser").strip()
    chat_id = int(payload.get("chat_id", 54321))
    is_new_chat_payload = payload.get("is_new_chat")

    cfg = getattr(cardinal, "MAIN_CFG", None)
    greetings_sec = cfg["Greetings"] if cfg and cfg.has_section("Greetings") else None

    # 1. Включены ли приветствия
    greetings_enabled = False
    if greetings_sec:
        greetings_enabled = greetings_sec.getboolean("sendGreetings", fallback=False)

    conditions.append({
        "name": "greetings_enabled",
        "passed": greetings_enabled,
        "details": "Greetings are enabled" if greetings_enabled else "Greetings are disabled in Greetings.sendGreetings",
    })

    # 2. Проверка onlyNewChats
    only_new = False
    is_new_chat_eligible = True
    if greetings_sec:
        only_new = greetings_sec.getboolean("onlyNewChats", fallback=False)
        if only_new:
            if is_new_chat_payload is not None:
                is_new_chat_eligible = bool(is_new_chat_payload)
            else:
                threshold = getattr(cardinal, "greeting_chat_id_threshold", 0)
                threshold_ids = getattr(cardinal, "greeting_threshold_chat_ids", set())
                if chat_id <= threshold or chat_id in threshold_ids:
                    is_new_chat_eligible = False

    conditions.append({
        "name": "only_new_chats_check",
        "passed": is_new_chat_eligible if only_new else True,
        "details": "Chat eligible for greeting" if (is_new_chat_eligible or not only_new) else "Chat is not considered new (onlyNewChats is active)",
    })

    # 3. Кулдаун приветствия
    cooldown_passed = True
    cooldown_days = 0.0
    if greetings_sec and not only_new:
        try:
            cooldown_days = float(greetings_sec.get("greetingsCooldown", fallback="0"))
        except ValueError:
            cooldown_days = 0.0
        cooldown_sec = cooldown_days * 86400
        last_time = 0.0
        if "last_interaction_time" in payload:
            last_time = float(payload["last_interaction_time"])
        elif hasattr(cardinal, "old_users") and isinstance(cardinal.old_users, dict):
            last_time = float(cardinal.old_users.get(chat_id, 0))

        if last_time > 0 and (time.time() - last_time) < cooldown_sec:
            cooldown_passed = False

    conditions.append({
        "name": "cooldown_check",
        "passed": cooldown_passed,
        "details": "Greeting cooldown satisfied" if cooldown_passed else f"Greeting cooldown active ({cooldown_days} days)",
    })

    success = bool(greetings_enabled and (is_new_chat_eligible or not only_new) and cooldown_passed)
    matched_rule_name = "Greetings" if greetings_enabled else None

    action_preview = None
    if greetings_sec:
        text = greetings_sec.get("greetingsText", "")
        text = text.replace("$username", username)
        action_preview = {
            "action": "send_greeting",
            "greeting_text": text,
            "recipient": username,
            "chat_id": chat_id,
            "will_send": success,
        }

    return matched_rule_name, conditions, action_preview, success


def simulate_automation(event_type: str, test_payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """
    Эмулирует срабатывание автоматизации без сетевых запросов и изменения состояния.
    Поддерживаемые event_type:
    - 'auto_delivery', 'delivery', 'order', 'new_order'
    - 'auto_response', 'response', 'command'
    - 'greetings', 'greeting'
    - 'message', 'new_message' (пытается автоответчик, затем приветствие)
    """
    t0 = time.perf_counter()
    cardinal = get_cardinal()
    payload = test_payload or {}
    ev_type = (event_type or "").strip().lower()

    if ev_type in ("auto_delivery", "delivery", "order", "new_order", "order_created"):
        matched_rule, conditions, action_preview, success = _simulate_delivery(cardinal, payload)
        category = "auto_delivery"
    elif ev_type in ("auto_response", "response", "command", "command_received"):
        matched_rule, conditions, action_preview, success = _simulate_response(cardinal, payload)
        category = "auto_response"
    elif ev_type in ("greetings", "greeting"):
        matched_rule, conditions, action_preview, success = _simulate_greetings(cardinal, payload)
        category = "greetings"
    elif ev_type in ("message", "new_message", "message_received"):
        msg = payload.get("message") or payload.get("text") or payload.get("command") or ""
        cmd_clean = str(msg).strip().lower()
        has_ar = False
        if hasattr(cardinal, "AR_CFG") and cardinal.AR_CFG and cmd_clean in cardinal.AR_CFG:
            has_ar = True
        elif hasattr(cardinal, "RAW_AR_CFG") and cardinal.RAW_AR_CFG:
            for s in cardinal.RAW_AR_CFG.sections():
                if cmd_clean in [v.strip().lower() for v in s.split("|")]:
                    has_ar = True
                    break
        if has_ar:
            matched_rule, conditions, action_preview, success = _simulate_response(cardinal, payload)
            category = "auto_response"
        else:
            matched_rule, conditions, action_preview, success = _simulate_greetings(cardinal, payload)
            category = "greetings"
    else:
        if "lot_name" in payload or "order_id" in payload:
            matched_rule, conditions, action_preview, success = _simulate_delivery(cardinal, payload)
            category = "auto_delivery"
        elif "command" in payload:
            matched_rule, conditions, action_preview, success = _simulate_response(cardinal, payload)
            category = "auto_response"
        else:
            matched_rule, conditions, action_preview, success = _simulate_delivery(cardinal, payload)
            category = "auto_delivery"

    duration_ms = round((time.perf_counter() - t0) * 1000, 2)

    result = {
        "event_type": event_type,
        "category": category,
        "matched_rule": matched_rule,
        "conditions": conditions,
        "action_preview": action_preview,
        "duration_ms": duration_ms,
        "success": success,
    }

    trace_record = {
        "id": str(uuid.uuid4()),
        "timestamp": time.time(),
        "event_type": event_type,
        "category": category,
        "matched_rule": matched_rule,
        "conditions": conditions,
        "action_preview": action_preview,
        "duration_ms": duration_ms,
        "success": success,
        "simulated": True,
    }
    record_execution_trace(trace_record)

    return result


# ─────────────────────────────────────────────────────────────
# 7. Интерактивные воркфлоу автоматизации (Automation Builder)
# ─────────────────────────────────────────────────────────────

_WORKFLOWS_LOCK = threading.Lock()
_WORKFLOWS_FILE = os.path.join("storage", "cache", "automation_workflows.json")


def _load_workflows_raw() -> list[dict[str, Any]]:
    if not os.path.exists(_WORKFLOWS_FILE):
        return []
    try:
        with open(_WORKFLOWS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and "rules" in data:
                return data["rules"]
            elif isinstance(data, dict) and "workflows" in data:
                return data["workflows"]
    except Exception:
        return []
    return []


def _save_workflows_raw(workflows: list[dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(_WORKFLOWS_FILE), exist_ok=True)
    with open(_WORKFLOWS_FILE, "w", encoding="utf-8") as f:
        json.dump(workflows, f, ensure_ascii=False, indent=2)


def _synthesize_default_workflows() -> list[dict[str, Any]]:
    workflows = []
    cardinal = None
    try:
        cardinal = get_cardinal()
    except Exception:
        pass

    if cardinal:
        # Из AD_CFG
        ad_cfg = getattr(cardinal, "AD_CFG", None)
        if ad_cfg and hasattr(ad_cfg, "sections"):
            for sec_name in ad_cfg.sections():
                sec = ad_cfg[sec_name]
                p_file = sec.get("productsFileName", "")
                resp = sec.get("response", "")
                dis = sec.getboolean("disable", fallback=False)
                wf_id = "wf_ad_" + hashlib.md5(sec_name.encode("utf-8")).hexdigest()[:8]
                workflows.append({
                    "id": wf_id,
                    "name": f"Автовыдача: {sec_name}",
                    "enabled": not dis,
                    "category": "auto_delivery",
                    "nodes": [
                        {
                            "id": f"{wf_id}_1",
                            "type": "trigger",
                            "event_type": "order_created",
                            "label": f"Заказ на '{sec_name}'",
                            "params": {"lot_name": sec_name},
                        },
                        {
                            "id": f"{wf_id}_2",
                            "type": "condition",
                            "condition": "blacklist_check",
                            "label": "Покупатель не в ЧС",
                            "params": {},
                        },
                        {
                            "id": f"{wf_id}_3",
                            "type": "condition",
                            "condition": "lot_active",
                            "label": "Лот активен",
                            "params": {},
                        },
                        {
                            "id": f"{wf_id}_4",
                            "type": "action",
                            "action": "deliver_product",
                            "label": "Выдать товар",
                            "params": {
                                "lot_name": sec_name,
                                "response": resp,
                                "productsFileName": p_file,
                            },
                        },
                        {
                            "id": f"{wf_id}_5",
                            "type": "notification",
                            "action": "send_notification",
                            "label": "Уведомление в Telegram",
                            "params": {"text": f"Выдан заказ по лоту {sec_name}"},
                        },
                    ],
                })

        # Из RAW_AR_CFG
        raw_ar = getattr(cardinal, "RAW_AR_CFG", None)
        if raw_ar and hasattr(raw_ar, "sections"):
            for cmd_name in raw_ar.sections():
                sec = raw_ar[cmd_name]
                resp = sec.get("response", "")
                en = sec.getboolean("enabled", fallback=True)
                tg_notif = sec.getboolean("telegramNotification", fallback=False)
                ntfc_text = sec.get("notificationText", "")
                wf_id = "wf_ar_" + hashlib.md5(cmd_name.encode("utf-8")).hexdigest()[:8]
                nodes = [
                    {
                        "id": f"{wf_id}_1",
                        "type": "trigger",
                        "event_type": "command_received",
                        "label": f"Команда: {cmd_name}",
                        "params": {"command": cmd_name},
                    },
                    {
                        "id": f"{wf_id}_2",
                        "type": "condition",
                        "condition": "blacklist_check",
                        "label": "Пользователь не в ЧС",
                        "params": {},
                    },
                    {
                        "id": f"{wf_id}_3",
                        "type": "condition",
                        "condition": "text_contains",
                        "label": f"Текст содержит '{cmd_name}'",
                        "params": {"text": cmd_name},
                    },
                    {
                        "id": f"{wf_id}_4",
                        "type": "action",
                        "action": "send_response",
                        "label": "Отправка автоответа",
                        "params": {"response": resp},
                    },
                ]
                if tg_notif:
                    nodes.append({
                        "id": f"{wf_id}_5",
                        "type": "notification",
                        "action": "send_notification",
                        "label": "Уведомление в Telegram",
                        "params": {"text": ntfc_text or f"Вызвана команда {cmd_name}"},
                    })
                workflows.append({
                    "id": wf_id,
                    "name": f"Автоответ: {cmd_name}",
                    "enabled": en,
                    "category": "auto_response",
                    "nodes": nodes,
                })

    if not workflows:
        wf_id = "wf_default_order"
        workflows.append({
            "id": wf_id,
            "name": "Основная автовыдача",
            "enabled": True,
            "category": "auto_delivery",
            "nodes": [
                {
                    "id": f"{wf_id}_1",
                    "type": "trigger",
                    "event_type": "order_created",
                    "label": "Новый оплаченный заказ",
                    "params": {"lot_name": "Тестовый лот"},
                },
                {
                    "id": f"{wf_id}_2",
                    "type": "condition",
                    "condition": "blacklist_check",
                    "label": "Покупатель не в ЧС",
                    "params": {},
                },
                {
                    "id": f"{wf_id}_3",
                    "type": "condition",
                    "condition": "lot_active",
                    "label": "Лот активен",
                    "params": {},
                },
                {
                    "id": f"{wf_id}_4",
                    "type": "action",
                    "action": "deliver_product",
                    "label": "Выдать товар из хранилища",
                    "params": {
                        "lot_name": "Тестовый лот",
                        "response": "Спасибо за покупку! Ваш ключ: $product",
                    },
                },
                {
                    "id": f"{wf_id}_5",
                    "type": "notification",
                    "action": "send_notification",
                    "label": "Уведомление в Telegram",
                    "params": {"text": "Заказ $order_id успешно выполнен"},
                },
            ],
        })

    return workflows


def list_workflows() -> list[dict[str, Any]]:
    """Возвращает список сохраненных воркфлоу автоматизаций."""
    with _WORKFLOWS_LOCK:
        stored = _load_workflows_raw()
        if not stored:
            stored = _synthesize_default_workflows()
            _save_workflows_raw(stored)
        return stored


def get_workflow(workflow_id: str) -> Optional[dict[str, Any]]:
    workflows = list_workflows()
    for wf in workflows:
        if str(wf.get("id")) == str(workflow_id):
            return wf
    return None


def _sync_workflow_to_cardinal(workflow: dict[str, Any]) -> None:
    """Синхронизирует воркфлоу с конфигурацией Cardinal (AD_CFG, RAW_AR_CFG, MAIN_CFG)."""
    cardinal = None
    try:
        cardinal = get_cardinal()
    except Exception:
        return

    if not cardinal:
        return

    nodes = workflow.get("nodes", [])
    is_enabled = workflow.get("enabled", True)

    # Ищем триггер, экшены и уведомления
    trigger_node = next((n for n in nodes if n.get("type") == "trigger"), None)
    action_nodes = [n for n in nodes if n.get("type") == "action"]
    notif_nodes = [n for n in nodes if n.get("type") == "notification"]

    ev_type = trigger_node.get("event_type") if trigger_node else None

    # 1. Автовыдача (order_created -> deliver_product)
    delivery_action = next((a for a in action_nodes if a.get("action") == "deliver_product"), None)
    if delivery_action or ev_type == "order_created":
        params = (delivery_action.get("params") if delivery_action else None) or {}
        lot_name = params.get("lot_name") or (trigger_node.get("params", {}).get("lot_name") if trigger_node else None) or workflow.get("name", "New Lot")
        response_text = params.get("response", "Спасибо за покупку!")
        p_file = params.get("productsFileName") or ""

        ad_cfg = getattr(cardinal, "AD_CFG", None)
        if ad_cfg and hasattr(ad_cfg, "sections"):
            with _AD_LOCK:
                if lot_name not in ad_cfg.sections():
                    ad_cfg.add_section(lot_name)
                ad_cfg.set(lot_name, "response", response_text)
                if p_file:
                    ad_cfg.set(lot_name, "productsFileName", _sanitize_filename(p_file))
                elif ad_cfg.has_option(lot_name, "productsFileName"):
                    ad_cfg.remove_option(lot_name, "productsFileName")
                ad_cfg.set(lot_name, "disable", "0" if is_enabled else "1")

                os.makedirs("configs", exist_ok=True)
                if hasattr(cardinal, "save_config"):
                    cardinal.save_config(ad_cfg, "configs/auto_delivery.cfg")

    # 2. Автоответчик (command_received / message_received -> send_response)
    response_action = next((a for a in action_nodes if a.get("action") == "send_response"), None)
    if response_action or ev_type in ("command_received", "message_received"):
        params = (response_action.get("params") if response_action else None) or {}
        cmd_name = (
            (trigger_node.get("params", {}).get("command") if trigger_node else None)
            or params.get("command")
            or workflow.get("name", "!cmd")
        )
        resp_text = params.get("response", "Команда принята")

        has_tg_notif = bool(notif_nodes or any(a.get("action") == "send_notification" for a in action_nodes))
        notif_text = ""
        if notif_nodes:
            notif_text = notif_nodes[0].get("params", {}).get("text", "")

        raw_ar = getattr(cardinal, "RAW_AR_CFG", None)
        if raw_ar and hasattr(raw_ar, "sections"):
            with _AR_LOCK:
                if cmd_name not in raw_ar.sections():
                    raw_ar.add_section(cmd_name)
                raw_ar.set(cmd_name, "response", resp_text)
                raw_ar.set(cmd_name, "telegramNotification", "1" if has_tg_notif else "0")
                raw_ar.set(cmd_name, "enabled", "1" if is_enabled else "0")
                if notif_text:
                    raw_ar.set(cmd_name, "notificationText", notif_text)
                elif raw_ar.has_option(cmd_name, "notificationText"):
                    raw_ar.remove_option(cmd_name, "notificationText")

                os.makedirs("configs", exist_ok=True)
                if hasattr(cardinal, "save_config"):
                    cardinal.save_config(raw_ar, "configs/auto_response.cfg")
                if os.path.exists("configs/auto_response.cfg"):
                    try:
                        cardinal.AR_CFG = cfg_loader.load_auto_response_config("configs/auto_response.cfg")
                        cardinal.RAW_AR_CFG = cfg_loader.load_raw_auto_response_config("configs/auto_response.cfg")
                    except Exception:
                        pass

    # 3. Поднятие лотов (raise_lots)
    if any(a.get("action") == "raise_lots" for a in action_nodes):
        main_cfg = getattr(cardinal, "MAIN_CFG", None)
        if main_cfg and hasattr(main_cfg, "sections"):
            if not main_cfg.has_section("FunPay"):
                main_cfg.add_section("FunPay")
            main_cfg.set("FunPay", "autoRaise", "1" if is_enabled else "0")
            if hasattr(cardinal, "save_config"):
                cardinal.save_config(main_cfg, "configs/_main.cfg")


def save_workflow(workflow_data: dict[str, Any]) -> dict[str, Any]:
    """Сохраняет или обновляет воркфлоу и синхронизирует его с Cardinal."""
    wf_name = (workflow_data.get("name") or "New Workflow").strip()
    nodes = workflow_data.get("nodes", [])

    if not nodes:
        raise ValueError("Воркфлоу должен содержать хотя бы один узел")

    # Валидация структуры
    has_trigger = any(n.get("type") == "trigger" for n in nodes)
    has_action = any(n.get("type") in ("action", "notification") for n in nodes)
    if not has_trigger:
        raise ValueError("Воркфлоу должен содержать начальный триггер (Trigger)")
    if not has_action:
        raise ValueError("Воркфлоу должен содержать хотя бы одно действие (Action)")

    wf_id = workflow_data.get("id") or ("wf_" + str(uuid.uuid4())[:8])
    workflow = {
        "id": wf_id,
        "name": wf_name,
        "enabled": workflow_data.get("enabled", True),
        "category": workflow_data.get("category") or "custom",
        "nodes": nodes,
        "updated_at": time.time(),
    }

    with _WORKFLOWS_LOCK:
        workflows = _load_workflows_raw()
        if not workflows:
            workflows = _synthesize_default_workflows()

        idx = next((i for i, w in enumerate(workflows) if str(w.get("id")) == str(wf_id)), -1)
        if idx >= 0:
            workflows[idx] = workflow
        else:
            workflows.append(workflow)

        _save_workflows_raw(workflows)

    # Синхронизация с конфигами Cardinal
    _sync_workflow_to_cardinal(workflow)
    return workflow


def update_workflow(workflow_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Обновляет статус активности, имя или узлы существующего воркфлоу."""
    with _WORKFLOWS_LOCK:
        workflows = _load_workflows_raw()
        if not workflows:
            workflows = _synthesize_default_workflows()

        idx = next((i for i, w in enumerate(workflows) if str(w.get("id")) == str(workflow_id)), -1)
        if idx < 0:
            raise IndexError(f"Workflow {workflow_id} not found")

        wf = workflows[idx]
        for k, v in updates.items():
            if v is not None:
                wf[k] = v
        wf["updated_at"] = time.time()
        workflows[idx] = wf
        _save_workflows_raw(workflows)

    _sync_workflow_to_cardinal(wf)
    return wf


def delete_workflow(workflow_id: str) -> bool:
    """Удаляет воркфлоу."""
    with _WORKFLOWS_LOCK:
        workflows = _load_workflows_raw()
        if not workflows:
            workflows = _synthesize_default_workflows()

        new_list = [w for w in workflows if str(w.get("id")) != str(workflow_id)]
        if len(new_list) == len(workflows):
            return False

        _save_workflows_raw(new_list)
        return True


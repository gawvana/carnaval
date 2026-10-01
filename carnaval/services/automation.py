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
import asyncio
import threading
from typing import Any, Optional

from carnaval.deps import get_cardinal
from Utils import cardinal_tools
from Utils import config_loader as cfg_loader
from tg_bot import utils as tg_utils

_AD_LOCK = threading.Lock()
_AR_LOCK = threading.Lock()
_TEMPLATES_LOCK = threading.Lock()

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

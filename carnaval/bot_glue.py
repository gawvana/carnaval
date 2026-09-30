"""
carnaval/bot_glue.py — интеграция Telegram-бота с Carnaval Mini App.

- Читает CARNAVAL_PUBLIC_URL из окружения или MAIN_CFG.
- Генерирует WebApp-кнопки «Открыть Carnaval» с иконкой Приложения (5778672437122045013).
- Настраивает MenuButtonWebApp через set_chat_menu_button.
- Добавляет deep-link кнопки в уведомления (order_<id>, chat_<id>).
- Если CARNAVAL_PUBLIC_URL не задан — бот работает в классическом режиме.
"""

from __future__ import annotations

import logging
import os
from typing import Optional, TYPE_CHECKING

from telebot import types
from telebot.apihelper import ApiTelegramException

if TYPE_CHECKING:
    from cardinal import Cardinal

logger = logging.getLogger("Carnaval.BotGlue")

APP_EMOJI_ID = "5778672437122045013"
CLASSIC_MENU_CBT = "carnaval_classic_menu"


def get_public_url(cardinal: Optional["Cardinal"] = None) -> str:
    """
    Возвращает публичный HTTPS URL фронтенда Mini App (на Vercel).
    Приоритет: env CARNAVAL_PUBLIC_URL -> MAIN_CFG[Carnaval][publicUrl].
    """
    env_url = os.getenv("CARNAVAL_PUBLIC_URL", "").strip()
    if env_url:
        return env_url.rstrip("/")

    if cardinal and hasattr(cardinal, "MAIN_CFG") and cardinal.MAIN_CFG.has_section("Carnaval"):
        cfg_url = cardinal.MAIN_CFG.get("Carnaval", "publicUrl", fallback="").strip()
        if cfg_url:
            return cfg_url.rstrip("/")

    return ""


def create_menu_keyboard(public_url: str) -> types.InlineKeyboardMarkup:
    """
    Клавиатура для команд /menu и /start:
    1. Кнопка «Открыть Carnaval» (WebApp).
    2. Кнопка «Классическое меню» (переход в стандартную панель Cardinal).
    """
    kb = types.InlineKeyboardMarkup()
    web_app = types.WebAppInfo(url=public_url)

    btn_app = types.InlineKeyboardButton(
        text="Открыть Carnaval",
        web_app=web_app,
        icon_custom_emoji_id=APP_EMOJI_ID,
    )
    btn_classic = types.InlineKeyboardButton(
        text="Классическое меню",
        callback_data=CLASSIC_MENU_CBT,
        icon_custom_emoji_id="5870982283724328568",  # ⚙
    )

    kb.row(btn_app)
    kb.row(btn_classic)
    return kb


def setup_chat_menu_button(bot: types.TeleBot, chat_id: int, public_url: str) -> None:
    """
    Устанавливает кнопку MenuButtonWebApp для авторизованного чата.
    """
    if not public_url.startswith("https://"):
        return

    try:
        menu_btn = types.MenuButtonWebApp(
            type="web_app",
            text="Carnaval",
            web_app=types.WebAppInfo(url=public_url),
        )
        bot.set_chat_menu_button(chat_id=chat_id, menu_button=menu_btn)
    except ApiTelegramException as e:
        logger.debug(f"Не удалось установить MenuButtonWebApp для чата {chat_id}: {e}")
    except Exception as e:
        logger.debug(f"Ошибка setup_chat_menu_button: {e}")


def add_order_webapp_button(
    keyboard: Optional[types.InlineKeyboardMarkup],
    public_url: str,
    order_id: str,
) -> Optional[types.InlineKeyboardMarkup]:
    """Добавляет кнопку перехода в заказ Mini App (deep link)."""
    if not public_url.startswith("https://") or not order_id:
        return keyboard

    target_url = f"{public_url}?startapp=order_{order_id}"
    btn = types.InlineKeyboardButton(
        text="Заказ в Carnaval",
        web_app=types.WebAppInfo(url=target_url),
        icon_custom_emoji_id=APP_EMOJI_ID,
    )

    if keyboard is None:
        keyboard = types.InlineKeyboardMarkup()
    keyboard.row(btn)
    return keyboard


def add_chat_webapp_button(
    keyboard: Optional[types.InlineKeyboardMarkup],
    public_url: str,
    chat_id: int,
) -> Optional[types.InlineKeyboardMarkup]:
    """Добавляет кнопку перехода в чат Mini App (deep link)."""
    if not public_url.startswith("https://") or not chat_id:
        return keyboard

    target_url = f"{public_url}?startapp=chat_{chat_id}"
    btn = types.InlineKeyboardButton(
        text="Чат в Carnaval",
        web_app=types.WebAppInfo(url=target_url),
        icon_custom_emoji_id=APP_EMOJI_ID,
    )

    if keyboard is None:
        keyboard = types.InlineKeyboardMarkup()
    keyboard.row(btn)
    return keyboard

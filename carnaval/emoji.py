"""
carnaval/emoji.py — поддержка премиум-эмодзи в Telegram-боте.

1. PREMIUM: таблица соответствия эмодзи -> icon_custom_emoji_id.
2. tge(key, fallback): обёртка <tg-emoji emoji-id="...">{fallback}</tg-emoji>.
3. icon(key): ID кастомного эмодзи для InlineKeyboardButton.
4. replace_emojis_with_tg_emoji(text): замена эмодзи в HTML сообщениях (без порчи code/pre/a).
5. patch_telebot_for_premium_emojis(): глобальный патчинг telebot для бесшовной работы
   всех клавиатур и сообщений без ручной переписки сотен файлов панели.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger("Carnaval.Emoji")

# Таблица премиум-эмодзи (строго по спецификации)
PREMIUM: dict[str, str] = {
    # Основные иконки интерфейса
    "⚙️": "5870982283724328568",
    "⚙": "5870982283724328568",
    "👤": "5870994129244131212",
    "👥": "5870772616305839506",
    "📁": "5870528606328852614",
    "💾": "5870528606328852614",
    "🙂": "5870764288364252592",
    "👋": "5870764288364252592",
    "📊": "5870921681735781843",
    "🏘": "5873147866364514353",
    "🔒": "6037249452824072506",
    "🔓": "6037496202990194718",
    "📣": "6039422865189638057",
    "✅": "5870633910337015697",
    "🟢": "5870633910337015697",
    "❌": "5870657884844462243",
    "🔴": "5870657884844462243",
    "🚫": "5870657884844462243",
    "✏️": "5870676941614354370",
    "✏": "5870676941614354370",
    "🖋️": "5870676941614354370",
    "🖋": "5870676941614354370",
    "📝": "5870753782874246579",
    "✍️": "5870753782874246579",
    "✍": "5870753782874246579",
    "🗑️": "5870875489362513438",
    "🗑": "5870875489362513438",
    "📰": "5893057118545646106",
    "📎": "6039451237743595514",
    "🔗": "5769289093221454192",
    "🌐": "5769289093221454192",
    "ℹ️": "6028435952299413210",
    "ℹ": "6028435952299413210",
    "⚠️": "6028435952299413210",
    "❔": "6028435952299413210",
    "❓": "6028435952299413210",
    "🤖": "6030400221232501136",
    "👁️": "6037397706505195857",
    "👁": "6037397706505195857",
    "⚪": "6037243349675544634",
    "⬆️": "5963103826075456248",
    "⬆": "5963103826075456248",
    "▶️": "5963103826075456248",
    "▶": "5963103826075456248",
    "⬇️": "6039802767931871481",
    "⬇": "6039802767931871481",
    "🔔": "6039486778597970865",
    "🔕": "6039486778597970865",
    "✉️": "6039486778597970865",
    "✉": "6039486778597970865",
    "🎁": "6032644646587338669",
    "⭐": "6032644646587338669",
    "⏰": "5983150113483134607",
    "⏱️": "5983150113483134607",
    "🎉": "6041731551845159060",
    "🖼️": "6035128606563241721",
    "🖼": "6035128606563241721",
    "📍": "6042011682497106307",
    "👛": "5769126056262898415",
    "💰": "5904462880941545555",
    "🪙": "5904462880941545555",
    "🏧": "5879814368572478751",
    "📦": "5884479287171485878",
    "🧩": "5778672437122045013",
    "app": "5778672437122045013",
    "👾": "5260752406890711732",
    "📅": "5890937706803894250",
    "🏷️": "5886285355279193209",
    "🏷": "5886285355279193209",
    "🕓": "5775896410780079073",
    "🖌️": "6050679691004612757",
    "🖌": "6050679691004612757",
    "🔡": "5771851822897566479",
    "🗣️": "5771851822897566479",
    "🗣": "5771851822897566479",
    "↔️": "5778479949572738874",
    "↔": "5778479949572738874",
    "🔨": "5940433880585605708",
    "🔄": "5345906554510012647",
}

# Регулярка для поиска эмодзи в начале строки
_LEADING_EMOJI_RE = re.compile(
    r"^([\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff\u2b50\u2b55\u200d\ufe0f]+)\s*"
)


def tge(key: str, fallback: Optional[str] = None) -> str:
    """Возвращает <tg-emoji emoji-id="...">fallback</tg-emoji>."""
    eid = PREMIUM.get(key)
    fb = fallback or key
    if not eid:
        return fb
    return f'<tg-emoji emoji-id="{eid}">{fb}</tg-emoji>'


def icon(key: str) -> Optional[str]:
    """Возвращает ID кастомного эмодзи для icon_custom_emoji_id."""
    return PREMIUM.get(key)


def strip_leading_emoji_for_button(text: str) -> tuple[str, Optional[str]]:
    """
    Анализирует текст кнопки:
    1. Если это кнопка «Назад» (◀️ Назад, Назад и т.п.) -> возвращает ('◁ Назад', None).
    2. Извлекает ведущий эмодзи, находит его ID в PREMIUM, убирает эмодзи из текста кнопки.
    3. Возвращает (clean_text, custom_emoji_id).
    """
    if not text:
        return text, None

    cleaned_text = text.strip()

    # Специфическое правило для кнопки «Назад»:
    # «Кнопка «Назад» — просто текст ◁ Назад, без ID.»
    if "назад" in cleaned_text.lower():
        # Заменяем стрелку на ◁
        clean = re.sub(r"^[◀️◀\s]*", "", cleaned_text).strip()
        if not clean.startswith("◁"):
            clean = f"◁ {clean}"
        return clean, None

    m = _LEADING_EMOJI_RE.match(cleaned_text)
    if not m:
        return cleaned_text, None

    raw_emoji = m.group(1)
    clean_text = cleaned_text[m.end():].strip()

    # Подбираем кастомный ID
    eid = PREMIUM.get(raw_emoji)
    if not eid:
        # Проверяем без селектора стиля \ufe0f
        normalized = raw_emoji.replace("\ufe0f", "")
        eid = PREMIUM.get(normalized)

    # Если всё равно нет точного совпадения — берём ближайший общий инфо/действие
    if not eid:
        eid = "6028435952299413210"  # Инфо по умолчанию

    return clean_text, eid


def replace_emojis_with_tg_emoji(text: str) -> str:
    """
    Заменяет известные эмодзи в тексте сообщения на <tg-emoji>.
    Не затрагивает содержимое внутри <code>, <pre>, <a> и уже существующих <tg-emoji>.
    """
    if not text:
        return text

    # Защищаем защищенные теги плейсхолдерами
    placeholders: list[str] = []

    def _save_tag(m: re.Match) -> str:
        idx = len(placeholders)
        placeholders.append(m.group(0))
        return f"___PROTECTED_TAG_{idx}___"

    protected_pattern = re.compile(
        r"(<code.*?>.*?</code>|<pre.*?>.*?</pre>|<a\s+.*?>.*?</a>|<tg-emoji.*?>.*?</tg-emoji>)",
        flags=re.DOTALL | re.IGNORECASE,
    )
    processed = protected_pattern.sub(_save_tag, text)

    # Заменяем эмодзи в оставшемся тексте
    # Сортируем ключи по убыванию длины, чтобы длинные последовательности заменялись первыми
    sorted_emojis = sorted(PREMIUM.keys(), key=lambda k: len(k), reverse=True)
    for em in sorted_emojis:
        if em in processed and not em.isalnum():
            eid = PREMIUM[em]
            replacement = f'<tg-emoji emoji-id="{eid}">{em}</tg-emoji>'
            processed = processed.replace(em, replacement)

    # Восстанавливаем защищённые теги
    for i, tag in enumerate(placeholders):
        processed = processed.replace(f"___PROTECTED_TAG_{i}___", tag)

    return processed


_telebot_patched = False


def patch_telebot_for_premium_emojis() -> None:
    """
    Применяет глобальные патчи к библиотеке pytelegrambotapi:
    1. InlineKeyboardButton: извлечение ведущего эмодзи в icon_custom_emoji_id.
    2. InlineKeyboardButton.to_dict(): передача icon_custom_emoji_id в Telegram Bot API.
    3. TeleBot.send_message / edit_message_text: замена эмодзи на <tg-emoji>
       и fallback при ApiTelegramException.
    """
    global _telebot_patched
    if _telebot_patched:
        return

    import telebot
    from telebot import types
    from telebot.apihelper import ApiTelegramException

    # --- 1. Патч InlineKeyboardButton ---
    orig_button_init = types.InlineKeyboardButton.__init__
    orig_button_to_dict = types.InlineKeyboardButton.to_dict

    def patched_button_init(self, text, *args, **kwargs):
        icon_id = kwargs.pop("icon_custom_emoji_id", None)
        clean_text, detected_icon = strip_leading_emoji_for_button(str(text))
        final_icon = icon_id or detected_icon
        orig_button_init(self, clean_text, *args, **kwargs)
        self.icon_custom_emoji_id = final_icon

    def patched_button_to_dict(self):
        d = orig_button_to_dict(self)
        if getattr(self, "icon_custom_emoji_id", None):
            d["icon_custom_emoji_id"] = str(self.icon_custom_emoji_id)
        return d

    types.InlineKeyboardButton.__init__ = patched_button_init
    types.InlineKeyboardButton.to_dict = patched_button_to_dict

    # --- 2. Патч TeleBot методов отправки сообщений ---
    orig_send_message = telebot.TeleBot.send_message
    orig_edit_message = telebot.TeleBot.edit_message_text

    def patched_send_message(self, chat_id, text, *args, **kwargs):
        parse_mode = kwargs.get("parse_mode") or getattr(self, "parse_mode", None) or "HTML"
        formatted_text = text
        if parse_mode == "HTML" and isinstance(text, str):
            formatted_text = replace_emojis_with_tg_emoji(text)
        try:
            return orig_send_message(self, chat_id, formatted_text, *args, **kwargs)
        except ApiTelegramException as e:
            # Fallback: если Telegram отклонил кастомные эмодзи — повторяем с исходным текстом
            logger.debug(f"TeleBot send_message fallback: {e}")
            if formatted_text != text:
                return orig_send_message(self, chat_id, text, *args, **kwargs)
            raise

    def patched_edit_message_text(self, text, *args, **kwargs):
        parse_mode = kwargs.get("parse_mode") or getattr(self, "parse_mode", None) or "HTML"
        formatted_text = text
        if parse_mode == "HTML" and isinstance(text, str):
            formatted_text = replace_emojis_with_tg_emoji(text)
        try:
            return orig_edit_message(self, formatted_text, *args, **kwargs)
        except ApiTelegramException as e:
            logger.debug(f"TeleBot edit_message fallback: {e}")
            if formatted_text != text:
                return orig_edit_message(self, text, *args, **kwargs)
            raise

    telebot.TeleBot.send_message = patched_send_message
    telebot.TeleBot.edit_message_text = patched_edit_message_text

    _telebot_patched = True
    logger.info("Carnaval: TeleBot успешно пропатчен для поддержки премиум-эмодзи")


# Автоматически активируем патч при импорте
try:
    patch_telebot_for_premium_emojis()
except Exception as _ex:
    logger.warning(f"Не удалось инициализировать патчи telebot: {_ex}")

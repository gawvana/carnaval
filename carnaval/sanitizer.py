"""
carnaval/sanitizer.py — централизованный фильтр и санитайзер логов.

Удаляет из вывода:
- Telegram Bot Tokens
- FunPay Golden Keys
- Пароли (в JSON и URL параметрах)
- Bearer токены и куки сессий
- Мастер-ключи и хеши
"""

from __future__ import annotations

import re
import logging

# Регулярные выражения для поиска конфиденциальных данных
_PATTERNS = [
    # Telegram Bot Token (напр. 123456789:ABCdefGHIjklMNOpqrSTUvwxYZ)
    (re.compile(r"\b\d{8,10}:[a-zA-Z0-9_-]{35}\b"), "***TG_BOT_TOKEN***"),
    # Bearer токен в заголовках
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/-]{16,}", re.IGNORECASE), r"\1***BEARER_TOKEN***"),
    # Кука сессии
    (re.compile(r"(carnaval_session=)[A-Za-z0-9._~+/-]{16,}", re.IGNORECASE), r"\1***SESSION_COOKIE***"),
    # Golden key (32 hex символа)
    (re.compile(r"(golden_key[\"'\s:=]+)[a-fA-F0-9]{32}\b", re.IGNORECASE), r"\1***GOLDEN_KEY***"),
    # Пароли в JSON ("password": "...")
    (re.compile(r'("(?:password|new_password|old_password|tg_password)"\s*:\s*")[^"]+(")', re.IGNORECASE), r'\1***REDACTED***\2'),
    # Пароли в query string (password=...)
    (re.compile(r'((?:password|secret)=)[^&\s]+', re.IGNORECASE), r'\1***REDACTED***'),
]


def sanitize_log_message(text: str) -> str:
    """Очищает строку от известных секретов и токенов."""
    if not isinstance(text, str):
        text = str(text)
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class SensitiveDataLogFilter(logging.Filter):
    """Logging фильтр для предотвращения утечки секретов в логи приложения."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = sanitize_log_message(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: sanitize_log_message(v) if isinstance(v, str) else v for k, v in record.args.items()}
                elif isinstance(record.args, tuple):
                    record.args = tuple(sanitize_log_message(v) if isinstance(v, str) else v for v in record.args)
        except Exception:
            pass
        return True


def install_log_sanitizer() -> None:
    """Устанавливает фильтр на корневой логгер."""
    root = logging.getLogger()
    filt = SensitiveDataLogFilter()
    for h in root.handlers:
        h.addFilter(filt)
    root.addFilter(filt)

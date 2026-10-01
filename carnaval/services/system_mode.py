"""
carnaval/services/system_mode.py — управление режимами работы системы:
- Safe Mode (безопасный режим): пропуск сторонних плагинов.
- Maintenance Mode (режим обслуживания): пауза автовыдачи + рассылка оповещений.

Состояния персистентны, хранятся в таблице system_state SQLite (потокобезопасно, идемпотентно).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from carnaval import bridge
from carnaval.db import get_state, set_state, log_audit

logger = logging.getLogger("Carnaval.SystemMode")

_lock = threading.RLock()

STATE_SAFE_MODE = "safe_mode"
STATE_MAINTENANCE_MODE = "maintenance_mode"
STATE_MAINTENANCE_REASON = "maintenance_reason"


def is_safe_mode() -> bool:
    """Возвращает True, если активирован безопасный режим (Safe Mode)."""
    with _lock:
        val = get_state(STATE_SAFE_MODE, "0")
        return str(val).strip().lower() in ("1", "true", "yes", "on")


def is_maintenance_mode() -> bool:
    """Возвращает True, если активирован режим обслуживания (Maintenance Mode)."""
    with _lock:
        val = get_state(STATE_MAINTENANCE_MODE, "0")
        return str(val).strip().lower() in ("1", "true", "yes", "on")


def get_maintenance_reason() -> str:
    """Возвращает причину активации режима обслуживания."""
    with _lock:
        return get_state(STATE_MAINTENANCE_REASON, "") or ""


def set_safe_mode(enabled: bool) -> None:
    """
    Включает или выключает безопасный режим.
    Идемпотентно и потокобезопасно.
    В безопасном режиме опциональные сторонние плагины обходятся (bypassed).
    """
    with _lock:
        val = "1" if enabled else "0"
        set_state(STATE_SAFE_MODE, val)

        action = "safe_mode_enabled" if enabled else "safe_mode_disabled"
        log_audit(action, None, details=f"Safe mode set to {enabled}")
        logger.info(f"Carnaval.SystemMode: Safe mode set to {enabled}")

        try:
            bridge.emit("system.mode", {
                "safe_mode": enabled,
                "maintenance_mode": is_maintenance_mode(),
                "maintenance_reason": get_maintenance_reason(),
                "timestamp": int(time.time()),
            })
        except Exception as e:
            logger.debug(f"Carnaval.SystemMode: bridge emit failed: {e}")


def set_maintenance_mode(enabled: bool, reason: str = "") -> None:
    """
    Включает или выключает режим обслуживания.
    Идемпотентно и потокобезопасно.
    В режиме обслуживания автовыдача приостанавливается ради безопасности,
    и рассылается оповещение (SSE + Telegram notification, если бот активен).
    """
    with _lock:
        val = "1" if enabled else "0"
        clean_reason = (reason or "").strip()
        set_state(STATE_MAINTENANCE_MODE, val)
        if enabled:
            set_state(STATE_MAINTENANCE_REASON, clean_reason)
        else:
            set_state(STATE_MAINTENANCE_REASON, "")

        action = "maintenance_mode_enabled" if enabled else "maintenance_mode_disabled"
        log_audit(action, None, details=clean_reason if enabled else "Disabled")
        logger.info(f"Carnaval.SystemMode: Maintenance mode set to {enabled} (reason='{clean_reason}')")

        # 1. Оповещение через SSE bridge
        alert_payload = {
            "type": "maintenance_mode",
            "enabled": enabled,
            "reason": clean_reason,
            "timestamp": int(time.time()),
        }
        try:
            bridge.emit("system.alert", alert_payload)
            bridge.emit("system.mode", {
                "safe_mode": is_safe_mode(),
                "maintenance_mode": enabled,
                "maintenance_reason": clean_reason if enabled else "",
                "timestamp": int(time.time()),
            })
        except Exception as e:
            logger.debug(f"Carnaval.SystemMode: bridge emit failed: {e}")

        # 2. Рассылка Telegram-оповещения администраторам (если доступен Cardinal)
        try:
            from carnaval.deps import get_cardinal
            cardinal = get_cardinal()
            tg = getattr(cardinal, "telegram", None)
            if tg and hasattr(tg, "send_notification"):
                if enabled:
                    msg = "⚠️ <b>Внимание: активирован режим обслуживания!</b>"
                    if clean_reason:
                        msg += f"\nПричина: <i>{clean_reason}</i>"
                    msg += "\nАвтовыдача временно приостановлена для безопасности."
                else:
                    msg = "✅ <b>Режим обслуживания отключен.</b>\nРабота системы и автовыдача возобновлены."
                tg.send_notification(msg)
        except Exception:
            # Cardinal может быть не инициализирован в изолированных тестах
            pass


def should_bypass_plugin(plugin_uuid: Optional[str] = None) -> bool:
    """
    Проверяет, должен ли плагин быть обойден.
    В безопасном режиме сторонние плагины (любые плагины с UUID) пропускаются.
    """
    if not is_safe_mode():
        return False
    # В safe mode все опциональные плагины обходятся
    return plugin_uuid is not None


def is_autodelivery_allowed() -> bool:
    """
    Проверяет, разрешена ли автовыдача.
    В режиме обслуживания автовыдача приостановлена ради безопасности.
    """
    return not is_maintenance_mode()

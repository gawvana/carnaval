"""
carnaval/services/live.py — Сервис оперативного мониторинга Live Control Center.

Содержит:
1. Авторитетный сбор живой телеметрии:
   - FunPay статус: состояние подключения, пользователь, баланс, валюта, последний ping.
   - Runner статус: статус цикла, размер очереди, количество попыток.
   - Системные метрики: CPU %, Память (MB), Аптайм, Размер базы данных, Активные SSE клиенты.
   - Операционные метрики: непрочитанные чаты, заказы за сегодня, активные автоматизации, работающие плагины.
2. Провайдер топологии системы (DAG):
   - Узлы: Telegram Bot, Backend, SSE Bridge, Cardinal Core, FunPay Runner, Automation Engine, Plugins, FunPay API.
   - Статусы узлов: healthy, warning, error, inactive с точной причиной, последним событием и кнопкой восстановления.
3. Кольцевой буфер ленты активности (Activity Timeline):
   - Потокобезопасный буфер на последние 100 событий.
   - Формат события: id, timestamp, category (order, chat, system, automation, update), title, description, details, replay_supported.
4. Сервис симуляции повтора событий (Event Replay):
   - Запуск событий через движок правил автоответа и автовыдачи без реальных побочных эффектов в продакшне.
"""

from __future__ import annotations

import collections
import datetime
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from carnaval import bridge
from carnaval.paths import DB_PATH
from carnaval.secrets_manager import SecretManager

logger = logging.getLogger("Carnaval.Live")

# Время старта сервиса телеметрии
_SERVICE_START_TIME = time.time()
_LAST_FUNPAY_PING: float = 0.0


def _safe_get_cardinal() -> Any:
    """Безопасное получение экземпляра Cardinal без выброса исключений."""
    try:
        from carnaval.deps import get_cardinal
        return get_cardinal()
    except Exception:
        return None


def record_funpay_ping() -> None:
    """Обновляет отметку времени успешного взаимодействия с FunPay."""
    global _LAST_FUNPAY_PING
    _LAST_FUNPAY_PING = time.time()


# ─────────────────────────────────────────────────────────────
# 1. Потокобезопасный кольцевой буфер ленты активности (Timeline)
# ─────────────────────────────────────────────────────────────

VALID_CATEGORIES = {"order", "chat", "system", "automation", "update"}


class TimelineEvent:
    """Модель единичного события ленты активности."""

    def __init__(
        self,
        event_id: str,
        timestamp: float,
        category: str,
        title: str,
        description: str,
        details: Optional[Dict[str, Any]] = None,
        replay_supported: bool = False,
    ):
        if category not in VALID_CATEGORIES:
            category = "system"
        self.id = event_id
        self.timestamp = timestamp
        self.category = category
        self.title = title
        self.description = description
        self.details = details or {}
        self.replay_supported = replay_supported

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "details": self.details,
            "replay_supported": self.replay_supported,
        }


class ActivityTimeline:
    """
    Потокобезопасный кольцевой буфер последних 100 событий ленты активности.
    """

    def __init__(self, maxlen: int = 100):
        self._maxlen = maxlen
        self._buffer: collections.deque[TimelineEvent] = collections.deque(maxlen=maxlen)
        self._lock = threading.RLock()
        self._counter: int = 0
        self._last_event_by_node: Dict[str, Dict[str, Any]] = {}

    def record_event(
        self,
        category: str,
        title: str,
        description: str,
        details: Optional[Dict[str, Any]] = None,
        replay_supported: bool = False,
        broadcast_sse: bool = True,
        node_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Записывает событие в кольцевой буфер и опционально транслирует его в SSE.
        """
        with self._lock:
            self._counter += 1
            event_id = f"evt_{self._counter}"
            event = TimelineEvent(
                event_id=event_id,
                timestamp=time.time(),
                category=category,
                title=title,
                description=description,
                details=details,
                replay_supported=replay_supported,
            )
            self._buffer.append(event)
            event_dict = event.to_dict()

            if node_id:
                self._last_event_by_node[node_id] = {
                    "id": event_id,
                    "title": title,
                    "timestamp": event.timestamp,
                }

        if broadcast_sse:
            try:
                bridge.emit("timeline.event", event_dict)
            except Exception as e:
                logger.debug(f"Timeline: ошибка трансляции SSE: {e}")

        return event_dict

    def get_events(
        self, limit: int = 100, category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Возвращает события в обратном хронологическом порядке (сначала новые).
        """
        with self._lock:
            events = list(self._buffer)

        if category and category in VALID_CATEGORIES:
            events = [e for e in events if e.category == category]

        events = list(reversed(events))
        return [e.to_dict() for e in events[:limit]]

    def get_event_by_id(self, event_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for e in self._buffer:
                if e.id == event_id:
                    return e.to_dict()
        return None

    def get_last_node_event(self, node_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._last_event_by_node.get(node_id)

    def set_last_node_event(self, node_id: str, title: str, timestamp: Optional[float] = None) -> None:
        with self._lock:
            self._last_event_by_node[node_id] = {
                "title": title,
                "timestamp": timestamp or time.time(),
            }

    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()
            self._counter = 0
            self._last_event_by_node.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._buffer)


# Глобальный синглтон ленты активности
timeline = ActivityTimeline(maxlen=100)

# Начальное системное событие
timeline.record_event(
    category="system",
    title="Live Control Center Initialized",
    description="Система оперативного контроля Carnaval запущена и ведет сбор телеметрии.",
    details={"subsystem": "live_control_center"},
    replay_supported=False,
    broadcast_sse=False,
    node_id="backend",
)


# ─────────────────────────────────────────────────────────────
# 2. Сбор авторитетной телеметрии (Live Telemetry)
# ─────────────────────────────────────────────────────────────

def _get_system_cpu_memory() -> Tuple[float, float]:
    """Возвращает CPU % и RSS память в MB с безопасным fallback."""
    cpu = 0.0
    mem_mb = 0.0
    try:
        import psutil
        cpu = float(psutil.cpu_percent(interval=None))
        mem_bytes = psutil.Process().memory_info().rss
        mem_mb = round(mem_bytes / (1024 * 1024), 2)
    except Exception as e:
        logger.debug(f"Telemetry: ошибка получения метрик процесса: {e}")
    return cpu, mem_mb


def _get_database_size() -> Tuple[int, str]:
    """Возвращает размер SQLite базы данных в байтах и форматированную строку."""
    size_bytes = 0
    try:
        if os.path.exists(DB_PATH):
            size_bytes += os.path.getsize(DB_PATH)
        wal_path = f"{DB_PATH}-wal"
        if os.path.exists(wal_path):
            size_bytes += os.path.getsize(wal_path)
    except Exception:
        pass

    if size_bytes >= 1024 * 1024:
        formatted = f"{round(size_bytes / (1024 * 1024), 2)} MB"
    elif size_bytes >= 1024:
        formatted = f"{round(size_bytes / 1024, 2)} KB"
    else:
        formatted = f"{size_bytes} B"

    return size_bytes, formatted


def _get_active_automations_count(cardinal: Any) -> int:
    """Подсчитывает суммарное количество активных правил автоматизации."""
    count = 0
    try:
        from carnaval.services import automation as auto_svc
        lots = auto_svc.list_delivery_lots()
        count += sum(1 for l in lots if not l.get("disable"))
        cmds = auto_svc.list_auto_response_commands()
        count += sum(1 for c in cmds if c.get("enabled", True))
    except Exception:
        if cardinal:
            ad_cfg = getattr(cardinal, "AD_CFG", None)
            if ad_cfg:
                for sec in ad_cfg.sections():
                    if not ad_cfg[sec].getboolean("disable", fallback=False):
                        count += 1
            raw_ar = getattr(cardinal, "RAW_AR_CFG", None)
            if raw_ar:
                for sec in raw_ar.sections():
                    if raw_ar[sec].getboolean("enabled", fallback=True):
                        count += 1
    return count


def _get_running_plugins_count(cardinal: Any) -> int:
    """Подсчитывает количество запущенных плагинов."""
    if not cardinal:
        return 0
    plugins = getattr(cardinal, "plugins", {})
    if not plugins:
        return 0
    disabled = getattr(cardinal, "disabled_plugins", [])
    count = 0
    for p_id, p_data in plugins.items():
        if getattr(p_data, "enabled", True) and p_id not in disabled:
            count += 1
    return count


def _get_today_orders_count(cardinal: Any) -> int:
    """Подсчитывает заказы за сегодняшний день."""
    if not cardinal:
        return 0
    today = datetime.date.today()
    runner = getattr(cardinal, "runner", None)
    if runner and getattr(runner, "saved_orders", None):
        saved = runner.saved_orders
        if isinstance(saved, dict):
            c = 0
            for o in saved.values():
                odate = getattr(o, "date", None)
                if odate and hasattr(odate, "date") and odate.date() == today:
                    c += 1
            return c
    return 0


def _get_unread_chats_count(cardinal: Any) -> int:
    """Подсчитывает количество непрочитанных чатов."""
    if not cardinal:
        return 0
    acc = getattr(cardinal, "account", None)
    if not acc:
        return 0
    # Проверка сохранённых чатов аккаунта
    saved_chats = getattr(acc, "_Account__saved_chats", None) or getattr(acc, "saved_chats", None)
    if isinstance(saved_chats, dict):
        return sum(1 for c in saved_chats.values() if getattr(c, "unread", False))
    return 0


def get_live_telemetry() -> Dict[str, Any]:
    """
    Собирает полную, авторитетную телеметрию в реальном времени.
    """
    cardinal = _safe_get_cardinal()
    acc = getattr(cardinal, "account", None) if cardinal else None

    # 1. FunPay статус
    fp_connection_state = "disconnected"
    fp_user: Dict[str, Any] = {"id": None, "username": None}
    fp_balance = 0.0
    fp_currency = "RUB"
    last_ping = _LAST_FUNPAY_PING

    has_key = (
        SecretManager.has_secret("golden_key")
        or bool(os.getenv("FUNPAY_GOLDEN_KEY", "").strip())
        or bool(os.getenv("GOLDEN_KEY", "").strip())
        or (cardinal and getattr(cardinal, "MAIN_CFG", None) and cardinal.MAIN_CFG.get("FunPay", "golden_key", fallback="").strip())
    )

    if acc and (getattr(acc, "is_initiated", False) or getattr(acc, "id", None)):
        fp_connection_state = "ready"
        fp_user = {
            "id": getattr(acc, "id", None),
            "username": getattr(acc, "username", None) or "Seller",
        }
        raw_bal = getattr(acc, "total_balance", 0.0)
        try:
            fp_balance = float(raw_bal) if raw_bal is not None else 0.0
        except (ValueError, TypeError):
            fp_balance = 0.0

        if cardinal and getattr(cardinal, "balance", None):
            try:
                b = cardinal.balance
                fp_balance = float(getattr(b, "total_rub", fp_balance) or fp_balance)
            except Exception:
                pass

        curr = getattr(acc, "currency", "RUB")
        fp_currency = getattr(curr, "name", str(curr or "RUB"))

        acc_last_upd = getattr(acc, "last_update", None)
        if acc_last_upd and isinstance(acc_last_upd, (int, float)):
            last_ping = max(last_ping, float(acc_last_upd))
        elif last_ping == 0.0:
            last_ping = time.time()
    elif has_key:
        from carnaval.services.account_lifecycle import lifecycle_manager, AccountState
        st = lifecycle_manager.get_status()
        if st.get("state") == AccountState.FAILED.value:
            fp_connection_state = "failed"
        elif st.get("state") in (AccountState.AUTHENTICATING.value, AccountState.CONNECTING.value):
            fp_connection_state = "connecting"
        else:
            fp_connection_state = "disconnected"
    else:
        fp_connection_state = "no_key"

    # 2. Runner статус
    from carnaval.services.supervisor import supervisor, LoopState
    runner_loop = supervisor.loops.get("RunnerLoop")
    runner_loop_status = "stopped"
    runner_attempts = 0

    if runner_loop and runner_loop.state in (LoopState.FAILED, LoopState.RESTARTING):
        runner_loop_status = runner_loop.state.value.lower()
        runner_attempts = runner_loop.retry_count
    elif cardinal and getattr(cardinal, "running", False) and getattr(cardinal, "runner", None):
        runner_loop_status = "running"
        runner_attempts = runner_loop.retry_count if runner_loop else 0
    elif runner_loop:
        runner_loop_status = runner_loop.state.value.lower() if isinstance(runner_loop.state, LoopState) else str(runner_loop.state).lower()
        runner_attempts = runner_loop.retry_count

    runner_queue_size = 0
    if cardinal and getattr(cardinal, "runner", None):
        queue = getattr(cardinal.runner, "payload_queue", None)
        if isinstance(queue, dict):
            runner_queue_size = len(queue)

    # 3. Системные метрики
    cpu_percent, memory_mb = _get_system_cpu_memory()
    uptime_sec = 0
    if cardinal and hasattr(cardinal, "start_time") and isinstance(cardinal.start_time, (int, float)):
        uptime_sec = int(time.time() - cardinal.start_time)
    else:
        uptime_sec = int(time.time() - _SERVICE_START_TIME)

    db_bytes, db_formatted = _get_database_size()
    sse_clients = bridge.get_queue_size()

    # 4. Операционные метрики
    unread_chats = _get_unread_chats_count(cardinal)
    today_orders = _get_today_orders_count(cardinal)
    active_automations = _get_active_automations_count(cardinal)
    running_plugins = _get_running_plugins_count(cardinal)

    return {
        "ok": True,
        "timestamp": time.time(),
        "funpay": {
            "connection_state": fp_connection_state,
            "user": fp_user,
            "balance": fp_balance,
            "currency": fp_currency,
            "last_ping": last_ping,
        },
        "runner": {
            "loop_status": runner_loop_status,
            "queue_size": runner_queue_size,
            "attempts": runner_attempts,
        },
        "system": {
            "cpu_percent": cpu_percent,
            "memory_mb": memory_mb,
            "uptime_seconds": uptime_sec,
            "database_size_bytes": db_bytes,
            "database_size_formatted": db_formatted,
            "sse_connected_clients": sse_clients,
        },
        "operational": {
            "unread_chats": unread_chats,
            "today_orders_count": today_orders,
            "active_automations": active_automations,
            "running_plugins_count": running_plugins,
        },
    }


# ─────────────────────────────────────────────────────────────
# 3. Провайдер живой топологии системы (DAG)
# ─────────────────────────────────────────────────────────────

def get_live_topology() -> Dict[str, Any]:
    """
    Генерирует граф топологии подсистем Carnaval и Cardinal.
    Узлы:
      - Telegram Bot
      - Backend
      - SSE Bridge
      - Cardinal Core
      - FunPay Runner
      - Automation Engine
      - Plugins
      - FunPay API
    Статусы: healthy, warning, error, inactive с точной причиной, последним событием и действием восстановления.
    """
    cardinal = _safe_get_cardinal()
    acc = getattr(cardinal, "account", None) if cardinal else None
    telemetry = get_live_telemetry()
    nodes: List[Dict[str, Any]] = []

    # 1. Backend
    b_last = timeline.get_last_node_event("backend") or {"title": "HTTP server active", "timestamp": time.time()}
    nodes.append({
        "id": "backend",
        "name": "Backend",
        "status": "healthy",
        "exact_reason": "FastAPI сервер активен, обрабатывает REST API запросы",
        "last_event": b_last,
        "recovery_action": None,
    })

    # 2. SSE Bridge
    sse_clients = telemetry["system"]["sse_connected_clients"]
    sse_status = "healthy"
    sse_reason = f"SSE мост активен, подключено клиентов: {sse_clients}"
    if sse_clients == 0:
        sse_reason = "SSE мост готов, ожидает подключения клиентов Mini App"
    nodes.append({
        "id": "sse_bridge",
        "name": "SSE Bridge",
        "status": sse_status,
        "exact_reason": sse_reason,
        "last_event": timeline.get_last_node_event("sse_bridge") or {"title": "Bridge alive", "timestamp": time.time()},
        "recovery_action": None,
    })

    # 3. FunPay API
    fp_state = telemetry["funpay"]["connection_state"]
    fp_node_status = "inactive"
    fp_reason = "Golden Key не настроен"
    fp_recovery = {"id": "config_key", "label": "Ввести Golden Key", "action": "open_settings", "endpoint": "/api/settings"}

    if fp_state == "ready":
        fp_node_status = "healthy"
        fp_reason = f"Авторизован как {telemetry['funpay']['user']['username'] or 'Seller'}, соединение стабильно"
        fp_recovery = None
    elif fp_state == "connecting":
        fp_node_status = "warning"
        fp_reason = "Выполняется проверка и подключение ключа к FunPay..."
        fp_recovery = None
    elif fp_state == "failed":
        fp_node_status = "error"
        from carnaval.services.account_lifecycle import lifecycle_manager
        st = lifecycle_manager.get_status()
        err_msg = st.get("error", {}).get("message") if st.get("error") else "Сбой авторизации Golden Key"
        fp_reason = f"Ошибка FunPay API: {err_msg}"
        fp_recovery = {"id": "reconnect_funpay", "label": "Повторить подключение", "action": "reconnect", "endpoint": "/api/auth/reconnect"}
    elif fp_state == "disconnected":
        fp_node_status = "warning"
        fp_reason = "Golden Key сохранен, но аккаунт еще не подключен"
        fp_recovery = {"id": "connect_funpay", "label": "Подключить аккаунт", "action": "connect", "endpoint": "/api/auth/reconnect"}

    nodes.append({
        "id": "funpay_api",
        "name": "FunPay API",
        "status": fp_node_status,
        "exact_reason": fp_reason,
        "last_event": timeline.get_last_node_event("funpay_api") or {
            "title": f"FunPay API state: {fp_state}",
            "timestamp": telemetry["funpay"]["last_ping"] or time.time(),
        },
        "recovery_action": fp_recovery,
    })

    # 4. FunPay Runner
    r_state = telemetry["runner"]["loop_status"]
    r_queue = telemetry["runner"]["queue_size"]
    r_attempts = telemetry["runner"]["attempts"]
    r_node_status = "inactive"
    r_reason = "Runner остановлен (ожидает запуска Cardinal/FunPay)"
    r_recovery = {"id": "start_runner", "label": "Запустить Runner", "action": "start_loop", "endpoint": "/api/more/system/runner/start"}

    if r_state == "running":
        if r_queue > 20:
            r_node_status = "warning"
            r_reason = f"Runner работает, но наблюдается очередь запросов: {r_queue}"
            r_recovery = {"id": "restart_runner", "label": "Перезапустить Runner", "action": "restart_loop", "endpoint": "/api/more/system/runner/restart"}
        else:
            r_node_status = "healthy"
            r_reason = f"Поток опроса Runner активен, очередь: {r_queue}"
            r_recovery = None
    elif r_state in ("restarting", "starting"):
        r_node_status = "warning"
        r_reason = f"Runner перезапускается (попытка {r_attempts})"
        r_recovery = None
    elif r_state == "failed":
        r_node_status = "error"
        from carnaval.services.supervisor import supervisor
        rloop = supervisor.loops.get("RunnerLoop")
        lerr = rloop.last_error if rloop else "Превышен лимит ошибок"
        r_reason = f"Runner переведен в статус сбоя: {lerr}"
        r_recovery = {"id": "restart_runner", "label": "Сбросить ошибку и перезапустить", "action": "restart_loop", "endpoint": "/api/more/system/runner/restart"}

    nodes.append({
        "id": "funpay_runner",
        "name": "FunPay Runner",
        "status": r_node_status,
        "exact_reason": r_reason,
        "last_event": timeline.get_last_node_event("funpay_runner") or {
            "title": f"Runner status: {r_state}",
            "timestamp": time.time(),
        },
        "recovery_action": r_recovery,
    })

    # 5. Cardinal Core
    core_status = "inactive"
    core_reason = "Ядро Cardinal не инициализировано"
    core_recovery = {"id": "start_core", "label": "Инициализировать ядро", "action": "init_core", "endpoint": "/api/more/system/restart"}

    if cardinal:
        if getattr(cardinal, "running", False):
            core_status = "healthy"
            core_reason = f"Ядро активно, версия {getattr(cardinal, 'VERSION', '0.1.0')}"
            core_recovery = None
        else:
            core_status = "warning"
            core_reason = "Ядро Cardinal загружено, но флаг running = False"
            core_recovery = {"id": "start_cardinal", "label": "Запустить ядро", "action": "run_core", "endpoint": "/api/more/system/restart"}

    nodes.append({
        "id": "cardinal_core",
        "name": "Cardinal Core",
        "status": core_status,
        "exact_reason": core_reason,
        "last_event": timeline.get_last_node_event("cardinal_core") or {
            "title": f"Core status: {core_status}",
            "timestamp": time.time(),
        },
        "recovery_action": core_recovery,
    })

    # 6. Telegram Bot
    tg_connected = False
    tg_enabled = False
    tg_reason = "Telegram бот отключен в настройках"
    tg_status = "inactive"
    tg_recovery = {"id": "setup_telegram", "label": "Настроить Telegram токен", "action": "open_settings", "endpoint": "/api/settings"}

    if cardinal and getattr(cardinal, "MAIN_CFG", None):
        tg_enabled = cardinal.MAIN_CFG.getboolean("Telegram", "enabled", fallback=False) or bool(os.getenv("TG_BOT_TOKEN", "").strip())

    if cardinal and getattr(cardinal, "telegram", None):
        is_alive_fn = getattr(cardinal.telegram, "is_alive", None)
        if callable(is_alive_fn):
            tg_connected = bool(is_alive_fn())
        else:
            tg_connected = bool(getattr(cardinal.telegram, "bot", None))

    if tg_connected:
        tg_status = "healthy"
        tg_reason = "Telegram бот подключен и готов к рассылке уведомлений"
        tg_recovery = None
    elif tg_enabled:
        tg_status = "warning"
        tg_reason = "Telegram включен в конфигурации, но соединение с ботом отсутствует"
        tg_recovery = {"id": "reconnect_tg", "label": "Переподключить бота", "action": "reconnect_tg", "endpoint": "/api/settings"}

    nodes.append({
        "id": "telegram_bot",
        "name": "Telegram Bot",
        "status": tg_status,
        "exact_reason": tg_reason,
        "last_event": timeline.get_last_node_event("telegram_bot") or {
            "title": f"Telegram status: {tg_status}",
            "timestamp": time.time(),
        },
        "recovery_action": tg_recovery,
    })

    # 7. Automation Engine
    auto_count = telemetry["operational"]["active_automations"]
    auto_status = "healthy"
    auto_reason = f"Активно правил автоматизации: {auto_count}"
    auto_recovery = None

    if auto_count == 0:
        auto_status = "inactive"
        auto_reason = "Правила автовыдачи и автоответа не настроены или отключены"
        auto_recovery = {"id": "setup_auto", "label": "Настроить правила", "action": "open_automation", "endpoint": "/api/automation/lots"}

    nodes.append({
        "id": "automation_engine",
        "name": "Automation Engine",
        "status": auto_status,
        "exact_reason": auto_reason,
        "last_event": timeline.get_last_node_event("automation_engine") or {
            "title": f"Rules active: {auto_count}",
            "timestamp": time.time(),
        },
        "recovery_action": auto_recovery,
    })

    # 8. Plugins
    plugins_count = telemetry["operational"]["running_plugins_count"]
    total_plugins = len(getattr(cardinal, "plugins", {})) if cardinal else 0
    p_status = "healthy"
    p_reason = f"Запущено плагинов: {plugins_count}/{total_plugins}"
    p_recovery = None

    if total_plugins == 0:
        p_status = "inactive"
        p_reason = "Плагины не установлены"
    elif plugins_count < total_plugins:
        p_status = "warning"
        p_reason = f"Часть плагинов отключена ({plugins_count} из {total_plugins} активно)"
        p_recovery = {"id": "open_plugins", "label": "Управление плагинами", "action": "open_plugins", "endpoint": "/api/more/plugins"}

    nodes.append({
        "id": "plugins",
        "name": "Plugins",
        "status": p_status,
        "exact_reason": p_reason,
        "last_event": timeline.get_last_node_event("plugins") or {
            "title": f"Plugins active: {plugins_count}",
            "timestamp": time.time(),
        },
        "recovery_action": p_recovery,
    })

    # Определение общего статуса топологии
    statuses = [n["status"] for n in nodes]
    if "error" in statuses:
        overall_status = "error"
    elif "warning" in statuses:
        overall_status = "warning"
    elif cardinal and getattr(cardinal, "running", False):
        overall_status = "healthy"
    elif all(s == "inactive" for s in [fp_node_status, r_node_status, core_status]):
        overall_status = "inactive"
    else:
        overall_status = "healthy"

    # Ребра ориентированного ациклического графа (DAG)
    edges = [
        {"from": "funpay_api", "to": "funpay_runner", "label": "polling updates"},
        {"from": "funpay_runner", "to": "cardinal_core", "label": "event stream"},
        {"from": "cardinal_core", "to": "automation_engine", "label": "order & chat triggers"},
        {"from": "cardinal_core", "to": "plugins", "label": "hooks execution"},
        {"from": "cardinal_core", "to": "backend", "label": "state synchronization"},
        {"from": "backend", "to": "sse_bridge", "label": "real-time events"},
        {"from": "cardinal_core", "to": "telegram_bot", "label": "push notifications"},
    ]

    return {
        "ok": True,
        "overall_status": overall_status,
        "nodes": nodes,
        "edges": edges,
        "timestamp": time.time(),
    }


# ─────────────────────────────────────────────────────────────
# 4. Сервис симуляции повтора событий (Event Replay)
# ─────────────────────────────────────────────────────────────

def replay_event(
    event_id: Optional[str] = None,
    category: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Симулирует прохождение события через движок правил автоответа и автовыдачи
    без каких-либо реальных побочных эффектов (без отправки сообщений на FunPay,
    без выдачи товара со склада и без спама в Telegram).
    """
    cardinal = _safe_get_cardinal()
    resolved_category = category
    resolved_payload = dict(payload or {})

    # 1. Если передан event_id, подгружаем параметры из ленты активности
    if event_id:
        src_event = timeline.get_event_by_id(event_id)
        if not src_event:
            raise ValueError(f"Событие с ID '{event_id}' не найдено в ленте активности")
        if not resolved_category:
            resolved_category = src_event.get("category")
        if not resolved_payload and src_event.get("details"):
            resolved_payload = dict(src_event.get("details", {}))

    if not resolved_category:
        resolved_category = "chat"

    simulated_actions: List[Dict[str, Any]] = []
    side_effects_prevented: List[str] = []
    matched_rule: Optional[str] = None
    rendered_output: Optional[str] = None
    rule_type: str = resolved_category

    # ─────────────────────────────────────────────────────────
    # Симуляция события чата (Chat / Message Event)
    # ─────────────────────────────────────────────────────────
    if resolved_category == "chat":
        text = str(resolved_payload.get("text", "") or "").strip()
        author = str(resolved_payload.get("author", "SimulationBuyer") or "SimulationBuyer")
        chat_id = resolved_payload.get("chat_id", 12345678)

        side_effects_prevented.extend([
            "FunPay API send_message bypassed (Dry Run)",
            "Telegram notification send bypassed (Dry Run)",
            "Blacklist state updates bypassed (Dry Run)",
        ])

        # Проверяем соответствие правилам автоответчика
        ar_cfg = getattr(cardinal, "AR_CFG", None) if cardinal else None
        raw_ar_cfg = getattr(cardinal, "RAW_AR_CFG", None) if cardinal else None

        clean_cmd = text.replace("\n", "").strip().lower()
        target_sec = None

        if ar_cfg and clean_cmd in ar_cfg:
            target_sec = ar_cfg[clean_cmd]
            matched_rule = clean_cmd
        elif raw_ar_cfg and clean_cmd in raw_ar_cfg:
            target_sec = raw_ar_cfg[clean_cmd]
            matched_rule = clean_cmd

        if target_sec and target_sec.getboolean("enabled", fallback=True):
            resp_template = target_sec.get("response", "")
            rendered_output = resp_template.replace("$username", author).replace("$chat_id", str(chat_id))
            simulated_actions.append({
                "action": "send_chat_message",
                "target_chat_id": chat_id,
                "recipient": author,
                "content": rendered_output,
                "rule_matched": matched_rule,
            })
            if target_sec.getboolean("telegramNotification", fallback=False):
                ntfc_text = target_sec.get("notificationText", "") or f"Команда {clean_cmd} вызвана пользователем {author}"
                simulated_actions.append({
                    "action": "send_telegram_notification",
                    "content": ntfc_text,
                })
        else:
            rendered_output = None

    # ─────────────────────────────────────────────────────────
    # Симуляция события заказа (Order Event)
    # ─────────────────────────────────────────────────────────
    elif resolved_category == "order":
        desc = str(resolved_payload.get("description", "") or "").strip()
        buyer = str(resolved_payload.get("buyer_username", "SimulationBuyer") or "SimulationBuyer")
        price = resolved_payload.get("price", 100.0)
        currency = resolved_payload.get("currency", "RUB")
        subcat = resolved_payload.get("subcategory_name", "Test Category")
        order_id = str(resolved_payload.get("id", "SIMULATED_ORDER") or "SIMULATED_ORDER")
        amount = int(resolved_payload.get("amount", 1) or 1)

        side_effects_prevented.extend([
            "Products storage file modification bypassed (Dry Run)",
            "FunPay goods delivery message bypassed (Dry Run)",
            "Telegram order notification bypassed (Dry Run)",
        ])

        ad_cfg = getattr(cardinal, "AD_CFG", None) if cardinal else None
        if ad_cfg:
            matched_lots: List[str] = []
            for lot_name in ad_cfg.sections():
                # Проверка вхождения или префикса
                if lot_name in desc or desc.startswith(lot_name):
                    matched_lots.append(lot_name)

            if matched_lots:
                # Берём наиболее специфичное совпадение (наибольшей длины)
                matched_rule = max(matched_lots, key=len)
                sec = ad_cfg[matched_rule]
                is_disabled = sec.getboolean("disable", fallback=False)

                if not is_disabled:
                    resp_template = sec.get("response", "")
                    products_file = sec.get("productsFileName", "")
                    sample_product = "[SIMULATED_PRODUCT_KEY_12345]"

                    # Если указан файл товаров, безопасно считываем образец БЕЗ удаления
                    if products_file:
                        try:
                            from carnaval.services import automation as auto_svc
                            goods = auto_svc.get_products_file_goods(products_file, limit=1)
                            if goods:
                                sample_product = goods[0]
                        except Exception:
                            pass

                    rendered_output = resp_template.replace("$product", sample_product)
                    rendered_output = rendered_output.replace("$username", buyer)
                    rendered_output = rendered_output.replace("$order_id", order_id)

                    simulated_actions.append({
                        "action": "deliver_goods",
                        "order_id": order_id,
                        "recipient": buyer,
                        "lot_matched": matched_rule,
                        "products_file": products_file,
                        "sample_delivered_item": sample_product,
                        "delivery_message": rendered_output,
                    })

                    simulated_actions.append({
                        "action": "send_telegram_notification",
                        "content": f"Новый заказ #{order_id}: {desc} ({price} {currency}) от {buyer}. Выдача товаров смоделирована.",
                    })
        else:
            rendered_output = None

    else:
        side_effects_prevented.append("General event processing bypassed (Dry Run)")
        rendered_output = f"Событие категории '{resolved_category}' обработано без побочных эффектов"

    # Записываем событие в Timeline для наглядного аудита симуляции
    timeline.record_event(
        category="automation",
        title=f"Replay Simulation: {resolved_category}",
        description=f"Выполнен dry-run симуляции события '{resolved_category}'. Правило: {matched_rule or 'не найдено'}.",
        details={
            "dry_run": True,
            "category": resolved_category,
            "matched_rule": matched_rule,
            "simulated_actions_count": len(simulated_actions),
        },
        replay_supported=False,
        broadcast_sse=True,
        node_id="automation_engine",
    )

    return {
        "ok": True,
        "dry_run": True,
        "category": resolved_category,
        "matched_rule": matched_rule,
        "rendered_output": rendered_output,
        "simulated_actions": simulated_actions,
        "side_effects_prevented": side_effects_prevented,
        "timestamp": time.time(),
    }

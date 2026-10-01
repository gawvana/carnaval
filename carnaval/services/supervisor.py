"""
carnaval/services/supervisor.py — Background Loop Supervisor.

Управляет жизненным циклом и отказоустойчивостью фоновых циклов:
- RunnerLoop (FunPayAPI.Runner.loop)
- LotsRaise (cardinal.lots_raise_loop)
- SessionLoop (cardinal.update_session_loop)

Отслеживает состояния:
- STARTING
- RUNNING
- FAILED
- RESTARTING
- STOPPED

Предотвращает tight-loop сбои при непредвиденных исключениях с помощью
экспоненциального backoff (5s, 10s, 30s) и ограничения max retries.
"""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger("Carnaval.Supervisor")


class LoopState(str, Enum):
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    FAILED = "FAILED"
    RESTARTING = "RESTARTING"
    STOPPED = "STOPPED"


class SupervisedLoop:
    """
    Класс-обёртка для одного контролируемого фонового цикла.
    """

    def __init__(
        self,
        name: str,
        target_fn: Callable[[], Any],
        max_retries: int = 5,
        backoff_delays: Tuple[float, ...] = (5.0, 10.0, 30.0),
        cardinal_getter: Optional[Callable[[], Any]] = None,
    ):
        self.name = name
        self.target_fn = target_fn
        self.max_retries = max_retries
        self.backoff_delays = backoff_delays
        self.cardinal_getter = cardinal_getter

        self.state: LoopState = LoopState.STOPPED
        self.retry_count: int = 0
        self.last_error: Optional[str] = None
        self.last_error_time: Optional[float] = None
        self.start_time: Optional[float] = None

        self._thread: Optional[threading.Thread] = None
        self._stop_event: threading.Event = threading.Event()
        self._lock: threading.RLock = threading.RLock()

    def _should_stop(self) -> bool:
        if self._stop_event.is_set():
            return True
        if self.cardinal_getter:
            try:
                cardinal = self.cardinal_getter()
                if cardinal and not getattr(cardinal, "running", True):
                    return True
            except Exception:
                pass
        return False

    def _before_run(self) -> None:
        """Специальные подготовительные действия перед запуском целевой функции."""
        if self.name == "RunnerLoop" and self.cardinal_getter:
            try:
                cardinal = self.cardinal_getter()
                runner = getattr(cardinal, "runner", None)
                if runner and hasattr(runner, "_Runner__is_running"):
                    runner._Runner__is_running = False
            except Exception:
                pass

    def _run(self) -> None:
        self.state = LoopState.STARTING
        self.start_time = time.time()

        while not self._stop_event.is_set():
            if self._should_stop():
                break

            run_start = time.time()
            try:
                self.state = LoopState.RUNNING
                logger.info(f"LoopSupervisor: [{self.name}] запущен в состоянии RUNNING.")

                self._before_run()
                self.target_fn()

                if self._stop_event.is_set() or self._should_stop():
                    break

                logger.info(f"LoopSupervisor: [{self.name}] завершил выполнение штатно.")
                break

            except Exception as exc:
                if self._stop_event.is_set() or self._should_stop():
                    break

                self.last_error = str(exc)
                self.last_error_time = time.time()
                logger.error(
                    f"LoopSupervisor: [{self.name}] непредвиденная ошибка: {exc}",
                    exc_info=True,
                )

                # Сбрасываем счётчик ретраев, если цикл стабильно отработал более 60 секунд
                if time.time() - run_start >= 60.0:
                    self.retry_count = 0

                self.retry_count += 1
                if self.retry_count > self.max_retries:
                    self.state = LoopState.FAILED
                    logger.critical(
                        f"LoopSupervisor: [{self.name}] превысил max_retries ({self.max_retries}) и переведён в FAILED!"
                    )
                    return

                self.state = LoopState.RESTARTING
                delay_idx = min(self.retry_count - 1, len(self.backoff_delays) - 1)
                delay = self.backoff_delays[delay_idx]
                logger.warning(
                    f"LoopSupervisor: [{self.name}] перезапуск через {delay:.1f}s "
                    f"(попытка {self.retry_count}/{self.max_retries})..."
                )

                if self._stop_event.wait(delay):
                    break

                self.state = LoopState.STARTING

        self.state = LoopState.STOPPED
        logger.info(f"LoopSupervisor: [{self.name}] остановлен (STOPPED).")

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                logger.debug(f"LoopSupervisor: [{self.name}] поток уже активен.")
                return

            self._stop_event.clear()
            self.state = LoopState.STARTING
            self.retry_count = 0
            self.last_error = None
            self.last_error_time = None
            self.start_time = time.time()

            self._thread = threading.Thread(
                target=self._run,
                name=f"Carnaval-{self.name}",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        with self._lock:
            self._stop_event.set()
            self.state = LoopState.STOPPED
            if self._thread and self._thread.is_alive() and self._thread != threading.current_thread():
                self._thread.join(timeout=timeout)
            self._thread = None

    def restart(self) -> None:
        self.stop(timeout=1.0)
        self.start()

    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def to_dict(self) -> dict:
        uptime = 0.0
        if self.state == LoopState.RUNNING and self.start_time:
            uptime = round(time.time() - self.start_time, 2)
        return {
            "name": self.name,
            "state": self.state.value if isinstance(self.state, LoopState) else str(self.state),
            "retries": self.retry_count,
            "max_retries": self.max_retries,
            "uptime": uptime,
            "last_error": self.last_error,
            "last_error_time": self.last_error_time,
        }


class BackgroundLoopSupervisor:
    """
    Супервизор фоновых циклов Carnaval и FunPay Cardinal.
    """

    def __init__(
        self,
        backoff_delays: Tuple[float, ...] = (5.0, 10.0, 30.0),
        max_retries: int = 5,
    ):
        self.backoff_delays = backoff_delays
        self.max_retries = max_retries
        self.loops: Dict[str, SupervisedLoop] = {}
        self._cardinal = None
        self._lock = threading.RLock()

    def set_cardinal(self, cardinal: Any) -> None:
        with self._lock:
            self._cardinal = cardinal
            self._ensure_default_loops()

    def _get_cardinal(self) -> Any:
        if self._cardinal is not None:
            return self._cardinal
        try:
            from carnaval.deps import get_cardinal
            return get_cardinal()
        except Exception:
            return None

    def _ensure_default_loops(self) -> None:
        """Регистрирует стандартные циклы: RunnerLoop, LotsRaise, SessionLoop."""
        if "RunnerLoop" not in self.loops:
            self.register_loop(
                "RunnerLoop",
                self._run_runner_loop,
                self.max_retries,
                self.backoff_delays,
            )
        if "LotsRaise" not in self.loops:
            self.register_loop(
                "LotsRaise",
                self._run_lots_raise_loop,
                self.max_retries,
                self.backoff_delays,
            )
        if "SessionLoop" not in self.loops:
            self.register_loop(
                "SessionLoop",
                self._run_session_loop,
                self.max_retries,
                self.backoff_delays,
            )

    def _run_runner_loop(self) -> None:
        cardinal = self._get_cardinal()
        if not cardinal or not getattr(cardinal, "runner", None):
            logger.warning("LoopSupervisor: RunnerLoop вызван, но cardinal.runner отсутствует.")
            return
        if hasattr(cardinal.runner, "_Runner__is_running"):
            cardinal.runner._Runner__is_running = False
        cardinal.runner.loop()

    def _run_lots_raise_loop(self) -> None:
        cardinal = self._get_cardinal()
        if not cardinal:
            return
        cardinal.lots_raise_loop()

    def _run_session_loop(self) -> None:
        cardinal = self._get_cardinal()
        if not cardinal:
            return
        cardinal.update_session_loop()

    def register_loop(
        self,
        name: str,
        target_fn: Callable[[], Any],
        max_retries: Optional[int] = None,
        backoff_delays: Optional[Tuple[float, ...]] = None,
    ) -> SupervisedLoop:
        with self._lock:
            loop = SupervisedLoop(
                name=name,
                target_fn=target_fn,
                max_retries=max_retries if max_retries is not None else self.max_retries,
                backoff_delays=backoff_delays if backoff_delays is not None else self.backoff_delays,
                cardinal_getter=self._get_cardinal,
            )
            self.loops[name] = loop
            return loop

    def start_all(self, cardinal: Optional[Any] = None) -> None:
        """Запустить все зарегистрированные циклы под управлением супервизора."""
        if cardinal is not None:
            self.set_cardinal(cardinal)
        else:
            self._ensure_default_loops()

        for name, loop in list(self.loops.items()):
            loop.start()

    def stop_all(self, timeout: float = 2.0) -> None:
        """Остановить все циклы."""
        for name, loop in list(self.loops.items()):
            loop.stop(timeout=timeout)

    def start_loop(self, name: str) -> bool:
        self._ensure_default_loops()
        if name in self.loops:
            self.loops[name].start()
            return True
        return False

    def stop_loop(self, name: str, timeout: float = 2.0) -> bool:
        if name in self.loops:
            self.loops[name].stop(timeout=timeout)
            return True
        return False

    def restart_loop(self, name: str) -> bool:
        if name in self.loops:
            self.loops[name].restart()
            return True
        return False

    def get_status(self) -> Dict[str, dict]:
        self._ensure_default_loops()
        return {name: loop.to_dict() for name, loop in self.loops.items()}

    def get_state(self, name: str) -> Optional[LoopState]:
        self._ensure_default_loops()
        loop = self.loops.get(name)
        return loop.state if loop else None

    def is_healthy(self) -> bool:
        self._ensure_default_loops()
        return all(loop.state != LoopState.FAILED for loop in self.loops.values())


# Singleton instances
supervisor = BackgroundLoopSupervisor()
loop_supervisor = supervisor

__all__ = [
    "LoopState",
    "SupervisedLoop",
    "BackgroundLoopSupervisor",
    "supervisor",
    "loop_supervisor",
]

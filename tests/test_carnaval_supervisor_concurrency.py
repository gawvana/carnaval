"""
Tests for Background Loop Supervisor and Concurrency Enhancements:
- cardinal.py: No UnboundLocalError in lots_raise_loop and update_session_loop
- supervisor.py: BackgroundLoopSupervisor state transitions, backoff, and max retries
- server.py: Single port resolution and no fallback port thread
"""

import os
import time
import threading
from unittest.mock import MagicMock, patch
import pytest

from carnaval.services.supervisor import (
    BackgroundLoopSupervisor,
    LoopState,
    SupervisedLoop,
    supervisor,
)


def test_cardinal_loop_variable_no_unbound_local_error():
    """Проверяет отсутствие UnboundLocalError в lots_raise_loop и update_session_loop."""
    from cardinal import Cardinal

    # Проверяем байткод/переменные функций: '_' не должен входить в co_varnames
    assert "_" not in Cardinal.lots_raise_loop.__code__.co_varnames
    assert "_" not in Cardinal.update_session_loop.__code__.co_varnames
    assert "_step" in Cardinal.lots_raise_loop.__code__.co_varnames
    assert "_step" in Cardinal.update_session_loop.__code__.co_varnames


def test_supervisor_initial_state():
    """Начальное состояние супервизора и регистрация циклов."""
    sup = BackgroundLoopSupervisor()
    status = sup.get_status()
    assert "RunnerLoop" in status
    assert "LotsRaise" in status
    assert "SessionLoop" in status
    assert status["RunnerLoop"]["state"] == LoopState.STOPPED.value
    assert status["LotsRaise"]["state"] == LoopState.STOPPED.value
    assert status["SessionLoop"]["state"] == LoopState.STOPPED.value
    assert sup.is_healthy() is True


def test_supervised_loop_clean_run_and_stop():
    """Тест штатного запуска и остановки цикла."""
    call_count = 0
    stop_flag = threading.Event()

    def dummy_task():
        nonlocal call_count
        call_count += 1
        stop_flag.wait(0.5)

    sup = BackgroundLoopSupervisor()
    loop = sup.register_loop("TestLoop", dummy_task, max_retries=3, backoff_delays=(0.05, 0.1))
    loop.start()

    for _ in range(20):
        if loop.state == LoopState.RUNNING:
            break
        time.sleep(0.05)
    assert loop.state == LoopState.RUNNING
    status = loop.to_dict()
    assert status["state"] == "RUNNING"
    assert status["retries"] == 0

    stop_flag.set()
    loop.stop(timeout=1.0)
    assert loop.state == LoopState.STOPPED
    assert call_count >= 1


def test_supervised_loop_exponential_backoff_and_failed_state():
    """Тест перехода в RESTARTING с экспоненциальным backoff и FAILED при превышении max_retries."""
    attempts = 0
    delays_recorded = []
    last_call_time = [0.0]

    def failing_task():
        nonlocal attempts
        attempts += 1
        now = time.time()
        if last_call_time[0] > 0:
            delays_recorded.append(round(now - last_call_time[0], 2))
        last_call_time[0] = now
        raise ValueError(f"Simulated failure {attempts}")

    backoff = (0.05, 0.1, 0.2)
    sup = BackgroundLoopSupervisor(backoff_delays=backoff, max_retries=3)
    loop = sup.register_loop("FailLoop", failing_task, max_retries=3, backoff_delays=backoff)

    loop.start()
    # Ждём завершения попыток: 3 ретрая + задержки (0.05 + 0.1 + 0.2 ~ 0.35s)
    time.sleep(0.7)

    assert loop.state == LoopState.FAILED
    assert loop.retry_count == 4  # 1 начальный + 3 ретрая
    assert "Simulated failure" in (loop.last_error or "")
    assert sup.is_healthy() is False

    status = loop.to_dict()
    assert status["state"] == "FAILED"
    assert status["retries"] == 4
    assert status["max_retries"] == 3


def test_supervised_loop_recovery():
    """Тест успешного восстановления после временной ошибки."""
    attempts = 0

    def recovering_task():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("Transient network failure")
        time.sleep(0.3)

    sup = BackgroundLoopSupervisor(backoff_delays=(0.05, 0.1), max_retries=3)
    loop = sup.register_loop("RecoverLoop", recovering_task, max_retries=3, backoff_delays=(0.05, 0.1))

    loop.start()
    # Первая попытка упадет, супервизор подождет 0.05s и перезапустит
    time.sleep(0.15)
    assert loop.state == LoopState.RUNNING
    assert loop.retry_count == 1  # 1 ошибка зафиксирована

    loop.stop(timeout=1.0)
    assert loop.state == LoopState.STOPPED


def test_supervisor_cardinal_integration():
    """Интеграция супервизора с экземпляром Cardinal."""
    mock_runner = MagicMock()
    mock_cardinal = MagicMock()
    mock_cardinal.runner = mock_runner
    mock_cardinal.running = True

    sup = BackgroundLoopSupervisor()
    sup.start_all(mock_cardinal)

    # Даем немного времени потокам запуститься
    time.sleep(0.1)

    assert mock_cardinal.lots_raise_loop.called or mock_cardinal.update_session_loop.called
    sup.stop_all(timeout=1.0)


def test_server_single_port_resolution(monkeypatch):
    """Проверяет строго один порт в carnaval.server.start."""
    from carnaval import server

    captured_ports = []

    def mock_run_server(bind_host, bind_port):
        captured_ports.append((bind_host, bind_port))

    # Перехватываем Thread.start чтобы не стартовать реальный uvicorn
    with patch("threading.Thread") as mock_thread_cls:
        mock_instance = MagicMock()
        mock_thread_cls.return_value = mock_instance

        mock_cardinal = MagicMock()
        mock_cardinal.MAIN_CFG.get.side_effect = lambda sec, opt, fallback=None: "127.0.0.1" if opt == "host" else "5000"

        # 1. По умолчанию
        server.start(mock_cardinal, host="127.0.0.1", port=5000)
        # Должен быть создан ровно 1 поток
        assert mock_thread_cls.call_count == 1
        call_kwargs = mock_thread_cls.call_args[1]
        assert call_kwargs["name"] == "Carnaval-5000"
        assert call_kwargs["args"] == ("127.0.0.1", 5000)

        # 2. Через переменную окружения PORT
        mock_thread_cls.reset_mock()
        monkeypatch.setenv("PORT", "7777")
        monkeypatch.setenv("CARNAVAL_HOST", "0.0.0.0")
        server.start(mock_cardinal, host="0.0.0.0", port=5000)
        assert mock_thread_cls.call_count == 1
        call_kwargs = mock_thread_cls.call_args[1]
        assert call_kwargs["name"] == "Carnaval-7777"
        assert call_kwargs["args"] == ("0.0.0.0", 7777)

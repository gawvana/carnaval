"""
tests/test_carnaval_lifecycle.py
Тесты для сервиса управления жизненным циклом аккаунта FunPay (AccountLifecycleManager)
и конечного автомата состояний (State Machine).
"""

import pytest
import asyncio
from unittest.mock import MagicMock, patch

from carnaval.services.account_lifecycle import (
    AccountLifecycleManager,
    AccountState,
    ErrorCode,
)
import FunPayAPI
from FunPayAPI.common import exceptions as fp_exceptions


@pytest.fixture
def lifecycle_mgr():
    """Тестовый экземпляр менеджера с чистым состоянием."""
    from carnaval import deps
    deps.set_cardinal(None)
    mgr = AccountLifecycleManager()
    mgr._init_state()
    return mgr


def test_initial_state_no_key(lifecycle_mgr):
    """При отсутствии ключа начальное состояние должно быть NO_KEY."""
    status = lifecycle_mgr.get_status()
    assert status["state"] in (AccountState.NO_KEY.value, AccountState.KEY_SAVED.value)
    assert status["is_ready"] is False
    assert status["profile"] is None


@pytest.mark.asyncio
async def test_invalid_golden_key_format(lifecycle_mgr):
    """Ключ некорректной длины должен переводить в FAILED с кодом INVALID_KEY_FORMAT."""
    res = await lifecycle_mgr.connect_account("short_key")
    assert res["ok"] is False
    assert res["status"]["state"] == AccountState.FAILED.value
    assert res["status"]["error"]["code"] == ErrorCode.INVALID_KEY_FORMAT.value


@pytest.mark.asyncio
async def test_unauthorized_error_handling(lifecycle_mgr, monkeypatch):
    """UnauthorizedError от FunPay должен давать ошибку UNAUTHORIZED."""
    fake_key = "0123456789abcdef0123456789abcdef"

    class StubAccount:
        golden_key = fake_key
        phpsessid = None
        is_initiated = False

        def get(self, update_phpsessid=False):
            raise fp_exceptions.UnauthorizedError(MagicMock())

    class StubCardinal:
        account = StubAccount()

    from carnaval import deps
    monkeypatch.setattr(deps, "get_cardinal", lambda: StubCardinal())

    res = await lifecycle_mgr.connect_account(fake_key)
    assert res["ok"] is False
    assert res["status"]["state"] == AccountState.FAILED.value
    assert res["status"]["error"]["code"] == ErrorCode.UNAUTHORIZED.value


@pytest.mark.asyncio
async def test_successful_connection_lifecycle(lifecycle_mgr, monkeypatch):
    """Успешная авторизация переводит в состояние READY."""
    fake_key = "0123456789abcdef0123456789abcdef"

    class FakeCurrency:
        name = "RUB"

    class StubAccount:
        golden_key = fake_key
        phpsessid = "sess123"
        is_initiated = True
        id = 999888
        username = "CarnavalMaster"
        total_balance = 1500
        currency = FakeCurrency()
        active_sales = 3
        active_purchases = 1
        runner = None

        def get(self, update_phpsessid=False):
            self.is_initiated = True
            return self

    class StubCardinal:
        account = StubAccount()
        runner = None
        old_mode_enabled = False
        running = False
        balance = None

        def get_balance(self):
            return 1500

        def _Cardinal__update_profile(self, **kwargs):
            return True

        def lots_raise_loop(self):
            pass

        def update_session_loop(self):
            pass

    from carnaval import deps
    monkeypatch.setattr(deps, "get_cardinal", lambda: StubCardinal())

    # Патчим FunPayAPI.Runner чтобы не запускать реальные циклы
    with patch("FunPayAPI.Runner"):
        res = await lifecycle_mgr.connect_account(fake_key)
        assert res["ok"] is True
        assert res["status"]["state"] == AccountState.READY.value
        assert res["status"]["is_ready"] is True
        assert res["status"]["profile"]["username"] == "CarnavalMaster"
        assert res["status"]["profile"]["balance"] == 1500


@pytest.mark.asyncio
async def test_disconnect_lifecycle(lifecycle_mgr, monkeypatch):
    """Отключение сбрасывает состояние и очищает профиль."""
    class StubAccount:
        golden_key = "abc"
        phpsessid = "sess"
        _Account__initiated = True
        id = 123
        username = "Test"
        runner = None

    class StubCardinal:
        account = StubAccount()
        running = True
        runner = MagicMock()

    from carnaval import deps
    monkeypatch.setattr(deps, "get_cardinal", lambda: StubCardinal())

    res = await lifecycle_mgr.disconnect_account()
    assert res["ok"] is True
    assert res["status"]["state"] == AccountState.DISCONNECTED.value
    assert res["status"]["profile"] is None
    assert res["status"]["is_connected"] is False


@pytest.mark.asyncio
async def test_setup_configure_golden_key_lifecycle(monkeypatch):
    """configure_golden_key валидирует через lifecycle_manager и возвращает реальный статус."""
    from carnaval.services import setup as setup_svc
    from carnaval.db import set_state

    set_state("owner_telegram_id", "777")

    # 1. Неверный формат ключа
    ok, err, st = await setup_svc.configure_golden_key(777, "short_key")
    assert ok is False
    assert st["state"] == AccountState.FAILED.value
    assert st["error"]["code"] == ErrorCode.INVALID_KEY_FORMAT.value

    # 2. Не владелец
    ok, err, st = await setup_svc.configure_golden_key(999, "0123456789abcdef0123456789abcdef")
    assert ok is False
    assert "Только владелец" in err


@pytest.mark.asyncio
async def test_more_change_and_delete_golden_key(monkeypatch):
    """Смена и удаление ключа в more.py обращаются напрямую к AccountLifecycleManager."""
    from carnaval.services import more as more_svc

    # 1. Без confirm=True
    ok, err, st = await more_svc.change_golden_key("0123456789abcdef0123456789abcdef", confirm=False)
    assert ok is False
    assert "confirm" in err.lower()

    # 2. Удаление без confirm
    ok, err, st = await more_svc.delete_golden_key(confirm=False)
    assert ok is False
    assert "confirm" in err.lower()

    # 3. Успешное удаление
    class StubCardinal:
        account = MagicMock()
        running = False
        runner = None
    monkeypatch.setattr("carnaval.deps.get_cardinal", lambda: StubCardinal())

    ok, err, st = await more_svc.delete_golden_key(confirm=True)
    assert ok is True
    assert st["state"] == AccountState.DISCONNECTED.value


def test_health_detailed_states(monkeypatch):
    """Проверка всех состояний /health: healthy, degraded, unhealthy."""
    from carnaval.server import build_app
    from fastapi.testclient import TestClient
    from carnaval.secrets_manager import SecretManager
    from carnaval.deps import set_cardinal

    app = build_app()
    client = TestClient(app)

    # 1. Unhealthy: ничего не запущено, ключей нет
    monkeypatch.delenv("GOLDEN_KEY", raising=False)
    monkeypatch.delenv("FUNPAY_GOLDEN_KEY", raising=False)
    monkeypatch.delenv("TG_BOT_TOKEN", raising=False)
    SecretManager.delete_secret("golden_key")
    set_cardinal(None)

    mgr = AccountLifecycleManager()
    mgr.state = AccountState.NO_KEY
    mgr.last_error = None
    mgr.profile = None

    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "unhealthy"
    assert data["status"] != "ok"
    assert data["funpay"] == "disconnected"
    assert data["telegram"] == "disconnected"
    assert data["backend"] == "healthy"

    # 2. Degraded: Telegram подключен, FunPay отключен
    monkeypatch.setenv("TG_BOT_TOKEN", "123:ABC")
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "degraded"
    assert data["status"] != "ok"
    assert data["telegram"] == "connected"
    assert data["funpay"] == "disconnected"

    # 3. Healthy: оба подключены и раннер запущен
    c = MagicMock()
    c.running = True
    c.start_time = 1000
    c.runner = MagicMock()
    c.telegram = MagicMock()
    c.telegram.is_alive = lambda: True
    c.account = MagicMock()
    c.account.id = 888
    c.account.golden_key = "0123456789abcdef0123456789abcdef"
    c.account.is_initiated = True
    set_cardinal(c)
    SecretManager.set_secret("golden_key", "0123456789abcdef0123456789abcdef")
    mgr.state = AccountState.READY

    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["funpay"] == "connected"
    assert data["telegram"] == "connected"
    assert data["account"] == "ready"
    assert data["runner"] == "running"
    assert data["backend"] == "healthy"


def test_tg_bot_lock_and_409_handler():
    """Тестирование single instance lock и обработки ошибки 409."""
    import os
    from tg_bot.bot import (
        acquire_tg_bot_lock,
        release_tg_bot_lock,
        TG_LOCK_FILE,
        TelegramPollingExceptionHandler,
        ApiTelegramException,
    )

    # 1. Захват lock-файла
    acquire_tg_bot_lock()
    assert os.path.exists(TG_LOCK_FILE)
    with open(TG_LOCK_FILE, "r", encoding="utf-8") as f:
        pid = int(f.read().strip())
    assert pid == os.getpid()

    # 2. Обработчик 409 Conflict
    handler = TelegramPollingExceptionHandler()
    fake_result = MagicMock()
    fake_result.status_code = 409
    fake_result.text = '{"error_code": 409, "description": "Conflict: terminated by other getUpdates request"}'
    fake_409 = ApiTelegramException("polling", fake_result, {"error_code": 409, "description": "Conflict"})

    # Мокаем time.sleep чтобы тест не ждал 5 секунд
    with patch("time.sleep") as mock_sleep:
        handled = handler.handle(fake_409)
        assert handled is True
        mock_sleep.assert_called_once_with(5)

    # Обычное исключение не должно перехватываться как 409
    other_exc = Exception("something else")
    assert handler.handle(other_exc) is False

    # 3. Освобождение lock-файла
    release_tg_bot_lock()
    assert not os.path.exists(TG_LOCK_FILE)

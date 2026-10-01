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

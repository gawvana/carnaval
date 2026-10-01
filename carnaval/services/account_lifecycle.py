"""
carnaval/services/account_lifecycle.py
Единый сервис управления жизненным циклом аккаунта FunPay и Golden Key.
Реализует строгую конечную машину состояний (State Machine), потокобезопасность (RLock),
синхронную валидацию через funpay.com, предотвращение гонок условий и SSE-бродкаст.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup

import FunPayAPI
from FunPayAPI.common import exceptions as fp_exceptions
from carnaval import bridge
from carnaval.secrets_manager import SecretManager

logger = logging.getLogger("Carnaval.Lifecycle")


def _safe_get_cardinal():
    """Безопасное получение экземпляра Cardinal без выброса исключений."""
    try:
        from carnaval.deps import get_cardinal
        return get_cardinal()
    except Exception:
        return None


class AccountState(str, enum.Enum):
    NO_KEY = "NO_KEY"
    KEY_SAVED = "KEY_SAVED"
    CONNECTING = "CONNECTING"
    AUTHENTICATING = "AUTHENTICATING"
    CONNECTED = "CONNECTED"
    RUNNER_STARTING = "RUNNER_STARTING"
    READY = "READY"
    FAILED = "FAILED"
    DISCONNECTING = "DISCONNECTING"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTING = "RECONNECTING"


class ErrorCode(str, enum.Enum):
    INVALID_KEY_FORMAT = "INVALID_KEY_FORMAT"
    UNAUTHORIZED = "UNAUTHORIZED"
    CLOUDFLARE_BLOCKED = "CLOUDFLARE_BLOCKED"
    RATE_LIMITED = "RATE_LIMITED"
    PROXY_ERROR = "PROXY_ERROR"
    TIMEOUT = "TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"
    RUNNER_ERROR = "RUNNER_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass
class AccountErrorDetail:
    code: ErrorCode
    message: str
    http_status: Optional[int] = None
    timestamp: float = 0.0
    raw_details: Optional[str] = None


@dataclass
class AccountProfileDetail:
    user_id: int
    username: str
    total_balance: float
    currency: str
    active_sales: int
    active_purchases: int
    avatar_url: Optional[str] = None
    last_synced: float = 0.0


class AccountLifecycleManager:
    """
    Singleton-менеджер жизненного цикла аккаунта FunPay.
    Обеспечивает единственную точку входа для:
    - connect_account(golden_key)
    - reconnect_account()
    - disconnect_account()
    - change_golden_key(new_key)
    - get_status()
    """

    _instance: Optional[AccountLifecycleManager] = None
    _thread_lock = threading.RLock()

    @property
    def _lock(self) -> asyncio.Lock:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.Lock()
        if not hasattr(self, "_loop_locks"):
            self._loop_locks = {}
        if loop not in self._loop_locks:
            self._loop_locks[loop] = asyncio.Lock()
        return self._loop_locks[loop]

    def __new__(cls) -> AccountLifecycleManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_state()
        return cls._instance

    def _init_state(self):
        self.state: AccountState = AccountState.NO_KEY
        self.last_error: Optional[AccountErrorDetail] = None
        self.profile: Optional[AccountProfileDetail] = None
        self._initial_check_done = False

    def _set_error(self, code: ErrorCode, message: str, http_status: Optional[int] = None, raw_details: Optional[str] = None):
        self.state = AccountState.FAILED
        self.last_error = AccountErrorDetail(
            code=code,
            message=message,
            http_status=http_status,
            timestamp=time.time(),
            raw_details=raw_details,
        )
        logger.error(f"Carnaval.Lifecycle: [State -> FAILED] {code.value}: {message}")
        self._broadcast_state()

    def _broadcast_state(self):
        try:
            status = self.get_status()
            bridge.emit("account.state", status)
        except Exception as e:
            logger.debug(f"Carnaval.Lifecycle: ошибка SSE broadcast: {e}")

    def get_status(self) -> dict[str, Any]:
        """Возвращает актуальный статус для API и фронтенда."""
        with self._thread_lock:
            # Синхронизация состояния при старте (только когда Cardinal доступен)
            if not self._initial_check_done:
                cardinal = _safe_get_cardinal()
                if cardinal is not None:
                    self._initial_check_done = True
                    acc = getattr(cardinal, "account", None)
                    if acc and getattr(acc, "is_initiated", False):
                        self.state = AccountState.READY
                        curr = getattr(acc, "currency", None)
                        curr_str = curr.name if curr and hasattr(curr, "name") else str(curr or "RUB")
                        self.profile = AccountProfileDetail(
                            user_id=getattr(acc, "id", 0) or 0,
                            username=getattr(acc, "username", "") or "",
                            total_balance=float(getattr(acc, "total_balance", 0) or 0),
                            currency=curr_str,
                            active_sales=getattr(acc, "active_sales", 0) or 0,
                            active_purchases=getattr(acc, "active_purchases", 0) or 0,
                            last_synced=time.time(),
                        )
                    else:
                        has_key = (
                            SecretManager.has_secret("golden_key")
                            or bool(os.getenv("FUNPAY_GOLDEN_KEY", "").strip())
                            or bool(os.getenv("GOLDEN_KEY", "").strip())
                        )
                        self.state = AccountState.KEY_SAVED if has_key else AccountState.NO_KEY

            return {
                "state": self.state.value,
                "is_ready": self.state == AccountState.READY,
                "is_connected": self.state in (AccountState.CONNECTED, AccountState.RUNNER_STARTING, AccountState.READY),
                "has_key": (
                    SecretManager.has_secret("golden_key")
                    or bool(os.getenv("FUNPAY_GOLDEN_KEY", "").strip())
                    or bool(os.getenv("GOLDEN_KEY", "").strip())
                ),
                "profile": {
                    "id": self.profile.user_id,
                    "username": self.profile.username,
                    "balance": self.profile.total_balance,
                    "currency": self.profile.currency,
                    "sales": self.profile.active_sales,
                    "purchases": self.profile.active_purchases,
                } if self.profile else None,
                "error": {
                    "code": self.last_error.code.value,
                    "message": self.last_error.message,
                    "http_status": self.last_error.http_status,
                    "timestamp": self.last_error.timestamp,
                } if self.last_error else None,
            }

    async def connect_account(self, golden_key: str, timeout: float = 20.0) -> dict[str, Any]:
        """
        СИНХРОННАЯ авторизация на FunPay:
        Валидация -> Сохранение -> Подключение -> Account.get() -> Запуск Runner.
        Возвращает успех ТОЛЬКО после реального ответа FunPay!
        """
        async with self._lock:
            clean_key = golden_key.strip()
            if len(clean_key) != 32:
                self._set_error(ErrorCode.INVALID_KEY_FORMAT, f"Golden Key должен состоять ровно из 32 символов (получено {len(clean_key)})")
                return {"ok": False, "status": self.get_status()}

            # 1. Сохранение ключа
            self.state = AccountState.KEY_SAVED
            self.last_error = None
            SecretManager.set_secret("golden_key", clean_key)
            self._broadcast_state()

            # 2. Аутентификация на FunPay
            self.state = AccountState.AUTHENTICATING
            self._broadcast_state()
            try:
                profile_detail = await asyncio.wait_for(
                    asyncio.to_thread(self._sync_authenticate, clean_key),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                self._set_error(ErrorCode.TIMEOUT, "Таймаут соединения с funpay.com (сервер не ответил за 20 сек)")
                return {"ok": False, "status": self.get_status()}
            except asyncio.CancelledError:
                self._set_error(ErrorCode.TIMEOUT, "Запрос авторизации был отменен")
                raise
            except Exception as e:
                if self.state != AccountState.FAILED:
                    self._set_error(ErrorCode.NETWORK_ERROR, f"Ошибка при проверке ключа FunPay: {e}")
                return {"ok": False, "status": self.get_status()}

            # 3. Аккаунт верифицирован
            self.state = AccountState.CONNECTED
            self.profile = profile_detail
            self._broadcast_state()

            # 4. Запуск раннера Cardinal
            self.state = AccountState.RUNNER_STARTING
            self._broadcast_state()
            try:
                await asyncio.to_thread(self._sync_start_runner)
                self.state = AccountState.READY
                self._broadcast_state()
            except Exception as e:
                logger.error(f"Carnaval.Lifecycle: ошибка запуска раннера: {e}")
                self._set_error(ErrorCode.RUNNER_ERROR, f"Аккаунт авторизован, но фоновый процесс завершился ошибкой: {e}")
                return {"ok": False, "status": self.get_status()}

            logger.info(f"Carnaval.Lifecycle: Аккаунт {self.profile.username} (ID: {self.profile.user_id}) успешно подключен и готов к работе!")
            return {"ok": True, "status": self.get_status()}

    async def reconnect_account(self, force: bool = False, timeout: float = 20.0) -> dict[str, Any]:
        """
        Переподключение существующего аккаунта по сохраненному ключу.
        Потокобезопасно: исключает дублирующие запросы.
        """
        async with self._lock:
            with self._thread_lock:
                if self.state == AccountState.READY and not force:
                    return {"ok": True, "status": self.get_status()}

            g_key = (
                SecretManager.get_secret("golden_key")
                or os.getenv("FUNPAY_GOLDEN_KEY", "").strip()
                or os.getenv("GOLDEN_KEY", "").strip()
            )
            cardinal = _safe_get_cardinal()
            if not g_key and cardinal and hasattr(cardinal, "MAIN_CFG"):
                g_key = cardinal.MAIN_CFG["FunPay"].get("golden_key", "").strip()

            if not g_key:
                self.state = AccountState.NO_KEY
                self._broadcast_state()
                return {"ok": False, "error": "Golden Key не найден", "status": self.get_status()}

            self.state = AccountState.RECONNECTING
            self._broadcast_state()

            try:
                profile_detail = await asyncio.wait_for(
                    asyncio.to_thread(self._sync_authenticate, g_key.strip()),
                    timeout=timeout
                )
                self.profile = profile_detail
                self.state = AccountState.CONNECTED
                await asyncio.to_thread(self._sync_start_runner)
                self.state = AccountState.READY
                self.last_error = None
                self._broadcast_state()
                return {"ok": True, "status": self.get_status()}
            except asyncio.CancelledError:
                self._set_error(ErrorCode.TIMEOUT, "Запрос переподключения был отменен")
                raise
            except Exception as e:
                self._set_error(ErrorCode.NETWORK_ERROR, f"Ошибка переподключения FunPay: {e}")
                return {"ok": False, "error": str(e), "status": self.get_status()}

    async def disconnect_account(self) -> dict[str, Any]:
        """Безопасный разрыв соединения, остановка циклов и очистка секретов."""
        async with self._lock:
            self.state = AccountState.DISCONNECTING
            self._broadcast_state()

            await asyncio.to_thread(self._sync_stop_runner)
            SecretManager.delete_secret("golden_key")

            cardinal = _safe_get_cardinal()
            if cardinal and hasattr(cardinal, "account") and cardinal.account:
                cardinal.account.golden_key = ""
                cardinal.account.phpsessid = None
                cardinal.account._Account__initiated = False
                cardinal.account.id = None
                cardinal.account.username = None
                if hasattr(cardinal.account, "runner"):
                    cardinal.account.runner = None
            if cardinal:
                cardinal.running = False
                cardinal.runner = None
                if hasattr(cardinal, "MAIN_CFG") and "FunPay" in cardinal.MAIN_CFG:
                    cardinal.MAIN_CFG["FunPay"]["golden_key"] = ""
                    try:
                        cardinal.save_config(cardinal.MAIN_CFG, "configs/_main.cfg")
                    except Exception:
                        pass

            self.profile = None
            self.last_error = None
            self.state = AccountState.DISCONNECTED
            self._broadcast_state()
            logger.info("Carnaval.Lifecycle: Аккаунт FunPay успешно отключен.")
            return {"ok": True, "status": self.get_status()}

    async def change_golden_key(self, new_key: str, timeout: float = 20.0) -> dict[str, Any]:
        """Атомарная ротация Golden Key под единым мьютексом."""
        clean_key = new_key.strip()
        if len(clean_key) != 32:
            self._set_error(ErrorCode.INVALID_KEY_FORMAT, f"Golden Key должен состоять ровно из 32 символов (получено {len(clean_key)})")
            return {"ok": False, "status": self.get_status()}

        async with self._lock:
            # 1. Отключаем старый аккаунт
            self.state = AccountState.DISCONNECTING
            self._broadcast_state()
            await asyncio.to_thread(self._sync_stop_runner)

            # 2. Подключаем новый аккаунт
            self.state = AccountState.KEY_SAVED
            self.last_error = None
            SecretManager.set_secret("golden_key", clean_key)
            self._broadcast_state()

            self.state = AccountState.AUTHENTICATING
            self._broadcast_state()
            try:
                profile_detail = await asyncio.wait_for(
                    asyncio.to_thread(self._sync_authenticate, clean_key),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                self._set_error(ErrorCode.TIMEOUT, "Таймаут соединения с funpay.com (сервер не ответил за 20 сек)")
                return {"ok": False, "status": self.get_status()}
            except asyncio.CancelledError:
                self._set_error(ErrorCode.TIMEOUT, "Запрос авторизации был отменен")
                raise
            except Exception as e:
                if self.state != AccountState.FAILED:
                    self._set_error(ErrorCode.NETWORK_ERROR, f"Ошибка при проверке нового ключа FunPay: {e}")
                return {"ok": False, "status": self.get_status()}

            self.state = AccountState.CONNECTED
            self.profile = profile_detail
            self._broadcast_state()

            self.state = AccountState.RUNNER_STARTING
            self._broadcast_state()
            try:
                await asyncio.to_thread(self._sync_start_runner)
                self.state = AccountState.READY
                self._broadcast_state()
            except Exception as e:
                logger.error(f"Carnaval.Lifecycle: ошибка запуска раннера при ротации ключа: {e}")
                self._set_error(ErrorCode.RUNNER_ERROR, f"Новый аккаунт авторизован, но раннер завершился ошибкой: {e}")
                return {"ok": False, "status": self.get_status()}

            logger.info(f"Carnaval.Lifecycle: Ключ успешно обновлен для аккаунта {self.profile.username}")
            return {"ok": True, "status": self.get_status()}

    # ─────────────────────────────────────────────────────────────────────────
    # Синхронные методы (выполняются в отдельном пуле потоков через to_thread)
    # ─────────────────────────────────────────────────────────────────────────

    def _sync_authenticate(self, clean_key: str) -> AccountProfileDetail:
        cardinal = _safe_get_cardinal()
        with self._thread_lock:
            account = getattr(cardinal, "account", None) if cardinal else None
            if not account:
                account = FunPayAPI.Account(clean_key)
                if cardinal:
                    cardinal.account = account
            else:
                account.golden_key = clean_key
                account.phpsessid = None

        logger.info("Carnaval.Lifecycle: обращение к funpay.com через Account.get(update_phpsessid=True)...")
        try:
            # Сетевой вызов БЕЗ блокировки _thread_lock, предотвращая зависание asyncio event loop
            account.get(update_phpsessid=True)
        except fp_exceptions.UnauthorizedError as e:
            # Проверка на Cloudflare
            text = ""
            if hasattr(e, "response") and e.response is not None:
                text = getattr(e.response, "text", "")
            if "cloudflare" in text.lower() or "challenge" in text.lower() or "turnstile" in text.lower():
                self._set_error(
                    ErrorCode.CLOUDFLARE_BLOCKED,
                    "FunPay отклонил запрос защитой Cloudflare (403). Требуется прокси.",
                    http_status=403,
                    raw_details=text[:300]
                )
            else:
                self._set_error(
                    ErrorCode.UNAUTHORIZED,
                    "Неверный или устаревший Golden Key. Проверьте актуальность куки golden_key.",
                    http_status=401
                )
            raise
        except requests.exceptions.ProxyError as e:
            self._set_error(ErrorCode.PROXY_ERROR, f"Ошибка подключения к прокси-серверу: {e}")
            raise
        except requests.exceptions.Timeout as e:
            self._set_error(ErrorCode.TIMEOUT, "Сервер FunPay не ответил вовремя (превышен таймаут)")
            raise
        except Exception as e:
            self._set_error(ErrorCode.NETWORK_ERROR, f"Сетевая ошибка при проверке FunPay: {e}")
            raise

        with self._thread_lock:
            if cardinal and hasattr(cardinal, "MAIN_CFG") and "FunPay" in cardinal.MAIN_CFG:
                cardinal.MAIN_CFG["FunPay"]["golden_key"] = clean_key
                try:
                    cardinal.save_config(cardinal.MAIN_CFG, "configs/_main.cfg")
                except Exception:
                    pass

            # Безопасное чтение баланса (fallback)
            total_bal = getattr(account, "total_balance", 0) or 0
            curr = getattr(account, "currency", None)
            curr_str = curr.name if curr and hasattr(curr, "name") else str(curr or "RUB")

            return AccountProfileDetail(
                user_id=getattr(account, "id", 0) or 0,
                username=getattr(account, "username", "") or "",
                total_balance=float(total_bal),
                currency=curr_str,
                active_sales=getattr(account, "active_sales", 0) or 0,
                active_purchases=getattr(account, "active_purchases", 0) or 0,
                last_synced=time.time(),
            )

    def _sync_start_runner(self):
        with self._thread_lock:
            cardinal = _safe_get_cardinal()
            if not cardinal or not getattr(cardinal, "account", None):
                return

            # Безопасное получение детального баланса
            try:
                cardinal.balance = cardinal.get_balance()
            except Exception as e:
                logger.warning(f"Carnaval.Lifecycle: не удалось распарсить баланс по лотам ({e}), используем базовый.")
                cardinal.balance = getattr(cardinal.account, "total_balance", 0)

            # Безопасное обновление профиля (2 попытки, без зависания)
            try:
                if hasattr(cardinal, "_Cardinal__update_profile"):
                    cardinal._Cardinal__update_profile(infinite_polling=False, attempts=2)
            except Exception as e:
                logger.warning(f"Carnaval.Lifecycle: предупреждение при обновлении профиля: {e}")

            # Запуск циклов раннера
            if cardinal.runner is None:
                cardinal.account.runner = None
                cardinal.runner = FunPayAPI.Runner(cardinal.account, cardinal.old_mode_enabled)
                cardinal.running = True
                try:
                    from carnaval.services.supervisor import supervisor
                    supervisor.start_all(cardinal)
                except Exception:
                    threading.Thread(target=cardinal.runner.loop, daemon=True, name="Carnaval-RunnerLoop").start()
                    threading.Thread(target=cardinal.lots_raise_loop, daemon=True, name="Carnaval-LotsRaise").start()
                    threading.Thread(target=cardinal.update_session_loop, daemon=True, name="Carnaval-SessionLoop").start()

            cardinal.running = True

    def _sync_stop_runner(self):
        with self._thread_lock:
            cardinal = _safe_get_cardinal()
            if cardinal:
                cardinal.running = False
                try:
                    from carnaval.services.supervisor import supervisor
                    supervisor.stop_all()
                except Exception:
                    pass
                if cardinal.runner:
                    try:
                        # Сбрасываем очередь полезной нагрузки
                        if hasattr(cardinal.runner, "payload_queue"):
                            cardinal.runner.payload_queue.clear()
                    except Exception:
                        pass
                cardinal.runner = None
                if hasattr(cardinal, "account") and cardinal.account:
                    cardinal.account.runner = None


# Экземпляр-одиночка для всего приложения
lifecycle_manager = AccountLifecycleManager()

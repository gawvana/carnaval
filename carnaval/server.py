"""
carnaval/server.py — FastAPI приложение + запуск в daemon-потоке.

Запуск: carnaval.server.start(cardinal, host, port)
Останавливается автоматически вместе с процессом (daemon=True).
"""

from __future__ import annotations

import asyncio
import collections
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from carnaval import auth, bridge
from carnaval.deps import set_cardinal, get_cardinal
from carnaval.routers import api_router

if TYPE_CHECKING:
    from cardinal import Cardinal

logger = logging.getLogger("Carnaval")

# Текущий список разрешённых CORS-origins (обновляется при старте)
_ALLOWED_ORIGINS: list[str] = ["*"]

# In-memory rate limiting для мутирующих запросов (POST, PATCH, DELETE)
_MUTATING_LIMIT = 60  # запросов в минуту
_MUTATING_WINDOW = 60
_mutating_requests: dict[str, list[float]] = collections.defaultdict(list)


def set_allowed_origins(raw: str) -> None:
    """Парсит строку 'origin1,origin2' и обновляет глобальный список."""
    global _ALLOWED_ORIGINS
    if not raw or raw.strip() == "*":
        _ALLOWED_ORIGINS = ["*"]
    else:
        _ALLOWED_ORIGINS = [o.strip() for o in raw.split(",") if o.strip()]


def get_allowed_origins() -> list[str]:
    return list(_ALLOWED_ORIGINS)


def _get_client_ip(request: Request) -> str:
    """Извлекает IP клиента с учётом CARNAVAL_TRUST_PROXY."""
    if os.getenv("CARNAVAL_TRUST_PROXY", "0") == "1":
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация базы данных, персистентных папок и моста SSE."""
    from carnaval.paths import init_persistent_dirs
    from carnaval.db import init_db
    from carnaval.sanitizer import install_log_sanitizer

    init_persistent_dirs()
    init_db()
    install_log_sanitizer()

    from carnaval.secrets_manager import SecretManager
    SecretManager.migrate_legacy_env_secrets()

    bridge.set_loop(asyncio.get_event_loop())
    logger.info("Carnaval: SSE bridge ready, security systems initialized")
    yield
    logger.info("Carnaval: shutdown")


def build_app(allowed_origins: list[str] | None = None, serve_static: bool | None = None) -> FastAPI:
    app = FastAPI(
        title="Carnaval",
        version="0.1.0",
        docs_url=None,        # не светим /docs в продакшне
        redoc_url=None,
        lifespan=lifespan,
    )

    origins = allowed_origins if allowed_origins is not None else get_allowed_origins()

    # CORS middleware (для кросс-доменных вызовов при необходимости)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Last-Event-ID", "X-Requested-With", "X-CSRF-Token"],
        allow_credentials=True if origins != ["*"] else False,
        max_age=600,
    )

    # Безопасные заголовки на все ответы
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        # Rate limit для мутирующих запросов (POST, PATCH, DELETE) кроме /api/auth
        if request.method in ("POST", "PATCH", "DELETE") and not request.url.path.startswith("/api/auth"):
            ip = _get_client_ip(request)
            now = time.time()
            hits = [t for t in _mutating_requests[ip] if now - t < _MUTATING_WINDOW]
            _mutating_requests[ip] = hits
            if len(hits) >= _MUTATING_LIMIT:
                logger.warning(f"Carnaval: rate limit превышен для IP {ip} на {request.method} {request.url.path}")
                return JSONResponse({"error": "rate_limited", "message": "Слишком много запросов"}, status_code=429)
            _mutating_requests[ip].append(now)

        response: Response = await call_next(request)

        # Безопасные заголовки
        if request.url.path.startswith("/api/"):
            # API ответы: без кэша + запрет встраивания во фреймы
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        else:
            # Ответы фронтенда (HTML/JS/CSS): разрешено встраивание в Telegram WebApp
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://telegram.org; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; "
                "img-src 'self' data: https:; "
                "connect-src 'self'; "
                "frame-ancestors https://web.telegram.org https://*.telegram.org telegram:;"
            )

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response

    # Эндпоинт проверки работоспособности (Section 41)
    @app.get("/health")
    @app.get("/api/health")
    async def health() -> JSONResponse:
        """Реальный health check с авторитетным состоянием подсистем."""
        uptime_sec = 0
        fp_connected = False
        tg_connected = False
        runner_running = False
        account_status = "not_initialized"

        try:
            try:
                c = get_cardinal()
            except Exception:
                c = None

            if c and hasattr(c, "start_time") and isinstance(c.start_time, (int, float)):
                uptime_sec = int(time.time() - c.start_time)

            if c and hasattr(c, "telegram") and c.telegram:
                is_alive_fn = getattr(c.telegram, "is_alive", None)
                if callable(is_alive_fn):
                    tg_connected = bool(is_alive_fn())
                else:
                    tg_connected = bool(getattr(c.telegram, "bot", None))
            elif os.getenv("TG_BOT_TOKEN", "").strip():
                tg_connected = True

            from carnaval.secrets_manager import SecretManager
            from carnaval.services.account_lifecycle import lifecycle_manager, AccountState
            st = lifecycle_manager.get_status()

            has_golden_key = (
                SecretManager.has_secret("golden_key")
                or bool(os.getenv("FUNPAY_GOLDEN_KEY", "").strip())
                or bool(os.getenv("GOLDEN_KEY", "").strip())
            )
            cardinal_acc = getattr(c, "account", None) if c else None
            cardinal_key = bool(cardinal_acc and getattr(cardinal_acc, "golden_key", None))

            cardinal_acc_ready = bool(
                cardinal_acc and (getattr(cardinal_acc, "is_initiated", False) or getattr(cardinal_acc, "id", None))
            )

            # FunPay подключен ТОЛЬКО если есть ключ и подтвержденная сессия
            if (has_golden_key or cardinal_key) and (st.get("is_connected") or cardinal_acc_ready):
                fp_connected = True
            else:
                fp_connected = False

            if fp_connected and (st.get("is_ready") or (cardinal_acc_ready and getattr(c, "running", False))):
                account_status = "ready"
            elif st.get("state") == AccountState.FAILED.value or (st.get("error") is not None):
                account_status = "failed"
            else:
                account_status = "not_initialized"

            if fp_connected and ((c and getattr(c, "running", False) and getattr(c, "runner", None) is not None) or st.get("is_ready")):
                runner_running = True
        except Exception as e:
            logger.debug(f"Carnaval: health check error: {e}")

        # Авторитетный расчет общего статуса
        if tg_connected and fp_connected and runner_running:
            status = "healthy"
        elif tg_connected:
            status = "degraded"
        elif fp_connected:
            status = "degraded"
        else:
            status = "unhealthy"

        return JSONResponse({
            "status": status,
            "backend": "healthy",
            "telegram": "connected" if tg_connected else "disconnected",
            "funpay": "connected" if fp_connected else "disconnected",
            "account": account_status,
            "runner": "running" if runner_running else "stopped",
            "uptime_sec": uptime_sec,
            "app": "Carnaval",
            "sse": "active",
        })

    # Публичный endpoint — метаинформация
    @app.get("/api/meta")
    async def meta() -> JSONResponse:
        try:
            cardinal = get_cardinal()
            version = getattr(cardinal, "VERSION", "0.1.0") or "0.1.0"
        except Exception:
            version = "0.1.0"
        return JSONResponse({
            "app": "Carnaval",
            "version": version,
        })

    # API роутеры
    app.include_router(api_router, prefix="/api")

    # Статика Mini App (единый origin)
    serve_static_flag = serve_static if serve_static is not None else True
    if serve_static_flag:
        web_dir = os.path.join(os.path.dirname(__file__), "web")
        if os.path.isdir(web_dir):
            from fastapi.staticfiles import StaticFiles
            app.mount("/", StaticFiles(directory=web_dir, html=True), name="static")

    return app


def start(cardinal: "Cardinal", host: str = "0.0.0.0", port: int = 5000) -> None:
    """
    Запустить Carnaval сервер в daemon-потоке.
    Вызывать из cardinal.py ПОСЛЕ инициализации аккаунта.
    """
    set_cardinal(cardinal)

    # Инициализировать модуль авторизации секретом из конфига (или безопасная генерация)
    secret = cardinal.MAIN_CFG.get("Carnaval", "secretKey", fallback="")
    auth.init(secret)

    # Настроить разрешённые CORS-origins
    raw_origins = cardinal.MAIN_CFG.get("Carnaval", "allowedOrigins", fallback="*")
    if not raw_origins or raw_origins.strip() == "*":
        logger.info("Carnaval: allowedOrigins = '*' (разрешены все origins)")
        raw_origins = "*"
    set_allowed_origins(raw_origins)

    app = build_app()

    def _run_server(bind_host: str, bind_port: int, is_primary: bool = True):
        try:
            config = uvicorn.Config(
                app,
                host=bind_host,
                port=bind_port,
                log_level="warning",
                access_log=False,
            )
            srv = uvicorn.Server(config)
            logger.info(f"Carnaval: запуск на http://{bind_host}:{bind_port}")
            srv.run()
        except Exception as e:
            if is_primary:
                logger.error(f"Carnaval: ошибка запуска на {bind_host}:{bind_port}: {e}")
            else:
                logger.debug(f"Carnaval: резервный порт {bind_port} не запущен: {e}")

    # Основной сервер
    t = threading.Thread(target=_run_server, args=(host, port, True), name=f"Carnaval-{port}", daemon=True)
    t.start()
    logger.info(f"Carnaval: основной поток запущен на http://{host}:{port}")

    # Резервный порт: обеспечивает доступность как по порту 5000, так и по 8000
    fallback_port = 8000 if port == 5000 else 5000
    try:
        t_fallback = threading.Thread(target=_run_server, args=(host, fallback_port, False), name=f"Carnaval-{fallback_port}", daemon=True)
        t_fallback.start()
        logger.info(f"Carnaval: резервный поток запущен на порту {fallback_port}")
    except Exception as e:
        logger.debug(f"Carnaval: резервный поток не создан: {e}")

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
    """Устанавливает event loop для SSE-моста при старте."""
    bridge.set_loop(asyncio.get_event_loop())
    logger.info("Carnaval: SSE bridge ready")
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

    # CORS middleware:
    # - allow_credentials=False (Bearer-токены в Authorization, не cookies)
    # - preflight кэш: max_age=600 сек (10 минут)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Last-Event-ID", "X-Requested-With"],
        allow_credentials=False,
        max_age=600,
    )

    # Безопасные заголовки на все ответы
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        # Rate limit для мутирующих запросов (POST, PATCH, DELETE) кроме /api/auth (у него свой лимитер)
        if request.method in ("POST", "PATCH", "DELETE") and request.url.path != "/api/auth":
            ip = _get_client_ip(request)
            now = time.time()
            hits = [t for t in _mutating_requests[ip] if now - t < _MUTATING_WINDOW]
            _mutating_requests[ip] = hits
            if len(hits) >= _MUTATING_LIMIT:
                logger.warning(f"Carnaval: rate limit превышен для IP {ip} на {request.method} {request.url.path}")
                return JSONResponse({"error": "rate_limited", "message": "Слишком много запросов"}, status_code=429)
            _mutating_requests[ip].append(now)

        response: Response = await call_next(request)

        # API ответы: без кэша + запрет встраивания во фреймы (frame-ancestors 'none')
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    # Публичный endpoint — возвращает метаинформацию (без списка origins в проде)
    @app.get("/api/meta")
    async def meta() -> JSONResponse:
        """Публичный эндпоинт: версия приложения. Не требует авторизации."""
        cardinal = get_cardinal()
        return JSONResponse({
            "app": "Carnaval",
            "version": getattr(cardinal, "VERSION", "0.0.0"),
        })

    # Наблюдаемость: GET /api/health
    @app.get("/api/health")
    async def health() -> JSONResponse:
        """Проверка работоспособности системы (для Infrlo healthcheck и мониторинга)."""
        cardinal = get_cardinal()
        acc = getattr(cardinal, "account", None)
        tg = getattr(cardinal, "telegram", None)
        uptime = int(time.time()) - cardinal.start_time if getattr(cardinal, "start_time", None) else 0

        return JSONResponse({
            "status": "ok",
            "app": "Carnaval",
            "version": getattr(cardinal, "VERSION", "0.0.0"),
            "uptime_sec": uptime,
            "funpay": {
                "authorized": bool(acc and getattr(acc, "id", None)),
                "username": getattr(acc, "username", None) if acc else None,
            },
            "telegram": {
                "active": bool(tg and getattr(tg, "is_alive", lambda: True)()),
                "authorized_users_count": len(getattr(tg, "authorized_users", [])) if tg else 0,
            },
            "sse": {
                "active_subscribers": bridge.get_queue_size(),
            }
        })

    # API роутеры
    app.include_router(api_router, prefix="/api")

    # Статика (SPA) — монтируется локально и в тестах; отключается в Docker prod через CARNAVAL_SERVE_STATIC=0
    serve_static_flag = serve_static if serve_static is not None else (os.getenv("CARNAVAL_SERVE_STATIC", "1") != "0")
    if serve_static_flag:
        web_dir = os.path.join(os.path.dirname(__file__), "web")
        if os.path.isdir(web_dir):
            from fastapi.staticfiles import StaticFiles
            app.mount("/", StaticFiles(directory=web_dir, html=True), name="static")

    return app


def start(cardinal: "Cardinal", host: str = "127.0.0.1", port: int = 8765) -> None:
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
    if raw_origins == "*" and os.getenv("CARNAVAL_ALLOW_ANY_ORIGIN", "0") != "1":
        logger.error(
            "Carnaval: [Carnaval] allowedOrigins = '*' запрещено в продакшене! "
            "Укажите точный домен Vercel в конфиге/переменной CARNAVAL_ALLOWED_ORIGINS, "
            "или установите CARNAVAL_ALLOW_ANY_ORIGIN=1 для разработки."
        )
        return

    set_allowed_origins(raw_origins)

    app = build_app()
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)

    def _run():
        logger.info(f"Carnaval: запуск на http://{host}:{port}")
        server.run()

    t = threading.Thread(target=_run, name="Carnaval", daemon=True)
    t.start()
    logger.info("Carnaval: поток запущен")

"""
carnaval/routers/system_info.py — Public version / build identity endpoint.

GET /api/system/version
  No auth required.
  Cache-Control: no-store (never cached — must always be fresh).
  Returns current backend version, git SHA, build ID, environment, and API contract.
"""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["system"])

APP_VERSION = "2.1.0"
CARDINAL_VERSION = "0.4.0"
API_CONTRACT = 5


@lru_cache(maxsize=1)
def _resolve_git_sha() -> str:
    """Resolves git SHA once at startup (cached). Prefers env var, falls back to subprocess."""
    env_sha = os.environ.get("CARNAVAL_GIT_SHA", "").strip()
    if env_sha and env_sha != "unknown":
        return env_sha[:7]
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).decode().strip()
        os.environ["CARNAVAL_GIT_SHA"] = sha
        return sha
    except Exception:
        return "unknown"


@router.get("/api/system/version")
async def system_version() -> JSONResponse:
    """
    Public build identity endpoint.
    Used by frontend to detect stale deployments.
    Always returns fresh data — never cached by CDN or browser.
    """
    git_sha = _resolve_git_sha()
    build_id = os.environ.get("CARNAVAL_BUILD_ID", git_sha)
    build_time = os.environ.get("CARNAVAL_BUILD_TIME", "unknown")
    environment = os.environ.get("CARNAVAL_ENV", "production")
    app_version = os.environ.get("CARNAVAL_APP_VERSION", APP_VERSION)

    return JSONResponse(
        content={
            "ok": True,
            "app_version": app_version,
            "backend_version": app_version,
            "cardinal_version": CARDINAL_VERSION,
            "git_sha": git_sha,
            "build_id": build_id,
            "build_time": build_time,
            "environment": environment,
            "api_contract": API_CONTRACT,
        },
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )

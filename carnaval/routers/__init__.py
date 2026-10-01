"""
carnaval/routers/__init__.py — агрегирует все роутеры в один api_router.
"""

from fastapi import APIRouter

from .auth import router as auth_router
from .dashboard import router as dashboard_router
from .events import router as events_router
from .settings import router as settings_router
from .orders import router as orders_router
from .chats import router as chats_router
from .automation import router as automation_router
from .more import router as more_router
from .setup import router as setup_router
from .search import router as search_router
from .update import router as update_router
from .live import router as live_router

api_router = APIRouter()
api_router.include_router(auth_router, tags=["auth"])
api_router.include_router(setup_router, tags=["setup"])
api_router.include_router(dashboard_router, tags=["dashboard"])
api_router.include_router(events_router, tags=["events"])
api_router.include_router(settings_router, tags=["settings"])
api_router.include_router(orders_router, tags=["orders"])
api_router.include_router(chats_router, tags=["chats"])
api_router.include_router(automation_router, tags=["automation"])
api_router.include_router(more_router, tags=["more"])
api_router.include_router(search_router, tags=["search"])
api_router.include_router(update_router, tags=["update"])
api_router.include_router(live_router, tags=["live"])

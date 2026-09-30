"""
carnaval/paths.py — централизованное управление путями персистентного хранилища.

Поддерживает единую директорию персистентности (/data или ./data),
что обеспечивает сохранность данных на Infrlo, в Docker и при локальном запуске.
"""

from __future__ import annotations

import os
import shutil
import logging

logger = logging.getLogger("Carnaval.Paths")


def get_data_dir() -> str:
    """
    Определяет корневую директорию данных:
    1. Переменная окружения DATA_DIR
    2. /data (если существует или доступна для создания в контейнере)
    3. ./data (локальный fallback в корне проекта)
    """
    env_dir = os.getenv("DATA_DIR")
    if env_dir:
        return os.path.abspath(env_dir)

    # В Linux контейнерах проверяем /data
    if os.name != "nt" and os.path.isdir("/data"):
        return "/data"

    # Иначе локальная папка data в корне проекта
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(base, "data")


DATA_DIR = get_data_dir()
DB_PATH = os.path.join(DATA_DIR, "app.db")
SECRETS_DIR = os.path.join(DATA_DIR, "secrets")
MASTER_KEY_PATH = os.path.join(SECRETS_DIR, "master.key")
CONFIGS_DIR = os.path.join(DATA_DIR, "configs")
STORAGE_DIR = os.path.join(DATA_DIR, "storage")
PRODUCTS_DIR = os.path.join(STORAGE_DIR, "products")
LOGS_DIR = os.path.join(DATA_DIR, "logs")
BACKUPS_DIR = os.path.join(DATA_DIR, "backups")
PLUGINS_DIR = os.path.join(DATA_DIR, "plugins")


def init_persistent_dirs() -> None:
    """Создает все необходимые директории с безопасными правами."""
    dirs = [
        DATA_DIR,
        SECRETS_DIR,
        CONFIGS_DIR,
        STORAGE_DIR,
        PRODUCTS_DIR,
        LOGS_DIR,
        BACKUPS_DIR,
        PLUGINS_DIR,
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        if os.name != "nt":
            try:
                # Ограничиваем доступ только текущему пользователю
                os.chmod(d, 0o700)
            except Exception:
                pass

    # Миграция: если в корне проекта есть configs/_main.cfg, а в DATA_DIR нет
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    root_cfg = os.path.join(base, "configs", "_main.cfg")
    target_cfg = os.path.join(CONFIGS_DIR, "_main.cfg")
    if os.path.isfile(root_cfg) and not os.path.isfile(target_cfg):
        try:
            shutil.copy2(root_cfg, target_cfg)
            logger.info("Carnaval.Paths: configs/_main.cfg мигрирован в персистентное хранилище")
        except Exception as e:
            logger.warning(f"Carnaval.Paths: не удалось скопировать _main.cfg: {e}")

"""
carnaval/services/backup.py — создание и восстановление резервных копий.
Используется перед обновлениями и для ручного бэкапа конфигурации и данных.
"""

from __future__ import annotations

import io
import os
import time
import zipfile
import logging
from typing import Any, Optional

from carnaval.paths import BACKUPS_DIR, init_persistent_dirs
from carnaval.services.more import create_configs_backup, restore_backup as _restore_zip

logger = logging.getLogger("Carnaval.Backup")

_last_backup_bytes: Optional[bytes] = None
_last_backup_path: Optional[str] = None


def create_backup(target: Any = None) -> tuple[bool, str] | bytes:
    """
    Создает резервную копию конфигураций и данных без секретов.
    Автоматически сохраняет копию в BACKUPS_DIR с временной меткой.
    Если target предоставлен (file-like объект): записывает в него и возвращает (True, path).
    Иначе возвращает bytes.
    """
    global _last_backup_bytes, _last_backup_path
    init_persistent_dirs()
    try:
        data = create_configs_backup()
        _last_backup_bytes = data

        ts = int(time.time())
        filename = f"pre_update_{ts}.zip"
        path = os.path.join(BACKUPS_DIR, filename)
        try:
            with open(path, "wb") as f:
                f.write(data)
            _last_backup_path = path
            logger.info(f"Carnaval.Backup: создан бэкап {path} ({len(data)} байт)")
            _rotate_backups(max_backups=5)
        except Exception as e:
            logger.warning(f"Carnaval.Backup: не удалось сохранить файл бэкапа {path}: {e}")

        if target is not None:
            if hasattr(target, "write"):
                target.write(data)
            return True, _last_backup_path or filename
        return data
    except Exception as e:
        logger.error(f"Carnaval.Backup: ошибка создания бэкапа: {e}")
        if target is not None:
            return False, str(e)
        raise


def restore_backup(source: bytes | str | None = None) -> tuple[bool, str]:
    """
    Безопасно восстанавливает систему из бэкапа с валидацией архива против Zip Slip и атак.
    source: bytes или путь к .zip файлу, либо None (последний созданный бэкап).
    """
    global _last_backup_bytes, _last_backup_path
    try:
        if source is None:
            if _last_backup_bytes:
                zip_bytes = _last_backup_bytes
            elif _last_backup_path and os.path.isfile(_last_backup_path):
                with open(_last_backup_path, "rb") as f:
                    zip_bytes = f.read()
            else:
                return False, "Резервная копия для восстановления не найдена"
        elif isinstance(source, bytes):
            zip_bytes = source
        elif isinstance(source, str):
            if not os.path.isfile(source):
                return False, f"Файл бэкапа {source} не найден"
            with open(source, "rb") as f:
                zip_bytes = f.read()
        else:
            return False, f"Неподдерживаемый тип источника бэкапа: {type(source)}"

        ok, err = _restore_zip(zip_bytes)
        if ok:
            logger.info("Carnaval.Backup: резервная копия успешно восстановлена")
        else:
            logger.error(f"Carnaval.Backup: ошибка восстановления: {err}")
        return ok, err
    except Exception as e:
        logger.error(f"Carnaval.Backup: ошибка при восстановлении: {e}")
        return False, str(e)


def get_last_backup() -> Optional[bytes]:
    """Возвращает байты последнего созданного бэкапа."""
    return _last_backup_bytes


def get_last_backup_path() -> Optional[str]:
    """Возвращает путь к последнему сохраненному файлу бэкапа."""
    return _last_backup_path


def _rotate_backups(max_backups: int = 5) -> None:
    """Удаляет старые резервные копии, оставляя не более max_backups самых свежих."""
    try:
        if not os.path.isdir(BACKUPS_DIR):
            return
        files = [
            os.path.join(BACKUPS_DIR, f)
            for f in os.listdir(BACKUPS_DIR)
            if f.endswith(".zip") and os.path.isfile(os.path.join(BACKUPS_DIR, f))
        ]
        files.sort(key=os.path.getmtime, reverse=True)
        if len(files) > max_backups:
            for old_file in files[max_backups:]:
                try:
                    os.remove(old_file)
                    logger.debug(f"Carnaval.Backup: ротация удалила старый бэкап {old_file}")
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"Carnaval.Backup: ошибка ротации бэкапов: {e}")


def list_backups() -> list[dict[str, Any]]:
    """Возвращает список сохраненных резервных копий."""
    init_persistent_dirs()
    backups = []
    if os.path.isdir(BACKUPS_DIR):
        for fname in sorted(os.listdir(BACKUPS_DIR), reverse=True):
            if fname.endswith(".zip"):
                fpath = os.path.join(BACKUPS_DIR, fname)
                try:
                    stat = os.stat(fpath)
                    backups.append({
                        "filename": fname,
                        "path": fpath,
                        "size": stat.st_size,
                        "created_at": int(stat.st_mtime),
                    })
                except Exception:
                    continue
    return backups

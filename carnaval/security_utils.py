"""
carnaval/security_utils.py — криптографические утилиты, хеширование паролей, защита от SSRF и Path Traversal.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import zipfile
import io
import tempfile
import logging
from urllib.parse import urlparse
from typing import Optional, Tuple, Any

logger = logging.getLogger("Carnaval.SecurityUtils")

# Инициализация Argon2id хешера с безопасными параметрами
try:
    from argon2 import PasswordHasher, Type
    from argon2.exceptions import VerifyMismatchError, VerificationError
    _hasher = PasswordHasher(
        time_cost=2,
        memory_cost=65536,  # 64 MB
        parallelism=1,
        hash_len=32,
        type=Type.ID
    )
except ImportError:
    _hasher = None


def hash_password(password: str) -> str:
    """Хеширует пароль с использованием Argon2id (или bcrypt fallback)."""
    if not password or len(password) < 6:
        raise ValueError("Пароль должен быть длиной не менее 6 символов")

    if _hasher is not None:
        return _hasher.hash(password)
    
    # Fallback на bcrypt
    import bcrypt
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Проверяет пароль против сохраненного хеша."""
    if not password or not hashed:
        return False

    # 1. Пробуем Argon2id
    if _hasher is not None and hashed.startswith("$argon2"):
        try:
            return _hasher.verify(hashed, password)
        except (VerifyMismatchError, VerificationError):
            return False
        except Exception:
            return False

    # 2. Пробуем bcrypt
    if hashed.startswith("$2b$") or hashed.startswith("$2a$") or hashed.startswith("$2y$"):
        try:
            import bcrypt
            return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
        except Exception:
            return False

    return False


# ─────────────────────────────────────────────────────────────
# Защита от Path Traversal
# ─────────────────────────────────────────────────────────────

def validate_safe_path(base_dir: str, filename: str) -> str:
    """
    Проверяет, что filename находится строго внутри base_dir.
    Защищает от ../, абсолютных путей и спецсимволов.
    Возвращает безопасный канонический путь или выбрасывает ValueError.
    """
    clean_name = os.path.basename(filename.strip().replace("\\", "/"))
    if not clean_name or clean_name in (".", ".."):
        raise ValueError("Недопустимое имя файла")

    base_real = os.path.realpath(base_dir)
    target_real = os.path.realpath(os.path.join(base_real, clean_name))

    if os.path.commonpath([base_real, target_real]) != base_real:
        raise ValueError("Path traversal попытка заблокирована")

    return target_real


# ─────────────────────────────────────────────────────────────
# Защита от SSRF (Server-Side Request Forgery)
# ─────────────────────────────────────────────────────────────

_BLOCKED_HOSTNAMES = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def is_safe_url(url: str) -> Tuple[bool, str]:
    """
    Проверяет URL перед выполнением исходящих запросов.
    Блокирует:
    - Не-HTTP(S) протоколы
    - Localhost и loopback адреса (127.0.0.0/8, ::1)
    - Приватные IP диапазоны (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
    - Облачные метаданные (169.254.169.254)
    - Link-local и multicast
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False, "Разрешены только протоколы http и https"

        hostname = parsed.hostname
        if not hostname:
            return False, "Отсутствует имя хоста"

        hostname_clean = hostname.lower().strip()
        if hostname_clean in _BLOCKED_HOSTNAMES:
            return False, "Обращение к локальному хосту запрещено"

        # Резолвим DNS и проверяем полученные IP-адреса
        try:
            addr_info = socket.getaddrinfo(hostname_clean, parsed.port or (443 if parsed.scheme == "https" else 80))
        except socket.gaierror:
            return False, f"Не удалось разрешить хост '{hostname_clean}'"

        for _, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            ip = ipaddress.ip_address(ip_str)

            if ip.is_loopback:
                return False, "Loopback IP адрес заблокирован"
            if ip.is_private:
                return False, "Приватный IP диапазон заблокирован"
            if ip.is_link_local:
                return False, "Link-local IP адрес заблокирован"
            if ip.is_multicast:
                return False, "Multicast IP адрес заблокирован"
            if ip.is_reserved:
                return False, "Зарезервированный IP адрес заблокирован"
            # Облачные метаданные (AWS, GCP, Azure, DigitalOcean)
            if str(ip) == "169.254.169.254":
                return False, "Обращение к cloud metadata заблокировано"

        return True, ""
    except Exception as e:
        return False, f"Ошибка проверки URL: {e}"


# ─────────────────────────────────────────────────────────────
# Безопасная работа с ZIP архивами (защита от Zip Slip и Zip Bomb)
# ─────────────────────────────────────────────────────────────

MAX_ZIP_FILES = 500
MAX_ZIP_UNCOMPRESSED_SIZE = 50 * 1024 * 1024  # 50 MB


class ZipValidationError(ValueError):
    """Ошибка валидации содержимого ZIP архива (Zip Slip, Zip Bomb, симлинки)."""
    pass


def validate_zip_archive(archive: Any, dest_dir: str = "", max_uncompressed_bytes: int = MAX_ZIP_UNCOMPRESSED_SIZE) -> None:
    """
    Проверяет ZIP-архив перед распаковкой:
    - Защита от Zip Slip (../ или абсолютные пути)
    - Защита от Zip Bomb (превышение макс. числа файлов или размера)
    - Запрет симлинков
    """
    if isinstance(archive, bytes):
        zf = zipfile.ZipFile(io.BytesIO(archive), "r")
    elif isinstance(archive, io.BytesIO):
        zf = zipfile.ZipFile(archive, "r")
    else:
        zf = archive

    dest_real = os.path.realpath(dest_dir or tempfile.gettempdir())
    infolist = zf.infolist()

    if len(infolist) > MAX_ZIP_FILES:
        raise ZipValidationError(f"Архив содержит слишком много файлов (макс. {MAX_ZIP_FILES})")

    total_size = 0
    for info in infolist:
        total_size += info.file_size
        if total_size > max_uncompressed_bytes:
            raise ZipValidationError(f"Общий распакованный размер превышает лимит {max_uncompressed_bytes // 1024 // 1024}MB")

        # Проверка пути
        target = os.path.realpath(os.path.join(dest_real, info.filename))
        if os.path.commonpath([dest_real, target]) != dest_real:
            raise ZipValidationError(f"Опасный путь в архиве: {info.filename}")

        # Проверка симлинка (Unix permission bits)
        if (info.external_attr >> 16) & 0o120000 == 0o120000:
            raise ZipValidationError(f"Симлинки в архивах запрещены: {info.filename}")

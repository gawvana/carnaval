"""
bootstrap_env.py — инициализация и синхронизация конфигурации из переменных окружения.

Используется для headless/PaaS деплоев (Infrlo, Docker, Kubernetes),
где интерактивная консоль first_setup.py недоступна.
"""

from __future__ import annotations

import logging
import os
import secrets
from configparser import ConfigParser

from Utils.cardinal_tools import hash_password

logger = logging.getLogger("BootstrapEnv")

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36"
)

DEFAULT_ALLOWED_ORIGINS = [
    "https://web.telegram.org",
    "https://carnaval-cardinal.vercel.app",
    "https://amazing-babbage-tau.vercel.app",
    "http://localhost:5000",
    "http://127.0.0.1:5000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]


def resolve_allowed_origins_string() -> str:
    """
    Формирует строку разрешённых CORS-origins для конфигурации:
    - '*' только если явно задано CARNAVAL_ALLOW_ANY_ORIGIN=1
    - иначе строгий allowlist по умолчанию плюс любые кастомные origins из CARNAVAL_ALLOWED_ORIGINS
    """
    if os.getenv("CARNAVAL_ALLOW_ANY_ORIGIN", "0").strip() == "1":
        return "*"

    origins = list(DEFAULT_ALLOWED_ORIGINS)
    custom = os.getenv("CARNAVAL_ALLOWED_ORIGINS", "").strip()
    if custom:
        for c in custom.split(","):
            c = c.strip()
            if c and c != "*" and c not in origins:
                origins.append(c)
    return ",".join(origins)


def bootstrap() -> bool:
    """
    Вызывается при старте Cardinal до загрузки конфигурации.
    
    1. Если configs/_main.cfg отсутствует и заданы переменные среды
       (FUNPAY_GOLDEN_KEY или TG_BOT_TOKEN) — создаёт конфиг без интерактивных вопросов.
    2. Если configs/_main.cfg уже есть — обновляет только переменные CARNAVAL_* и PORT.
    
    Возвращает True если файл создан/обновлен, False если переменных нет.
    """
    from carnaval.paths import init_persistent_dirs
    from carnaval.db import init_db
    init_persistent_dirs()
    init_db()

    config_path = "configs/_main.cfg"
    os.makedirs("configs", exist_ok=True)
    os.makedirs("storage/cache", exist_ok=True)
    os.makedirs("storage/products", exist_ok=True)
    os.makedirs("plugins", exist_ok=True)
    os.makedirs("logs", exist_ok=True)

    # 1. Если файл уже существует — синхронизируем секцию [Carnaval] из env
    if os.path.exists(config_path):
        return _sync_existing_config(config_path)

    # 2. Если файла нет — проверяем, переданы ли переменные для авто-инициализации
    golden_key = (os.getenv("FUNPAY_GOLDEN_KEY") or os.getenv("GOLDEN_KEY", "")).strip()
    tg_token = (os.getenv("TG_BOT_TOKEN") or os.getenv("TG_TOKEN", "")).strip()

    if not golden_key and not tg_token:
        # Переменных нет — позволяем main.py запустить first_setup()
        return False

    logger.info("BootstrapEnv: создание конфигурации _main.cfg из переменных окружения...")

    user_agent = os.getenv("FUNPAY_USER_AGENT", DEFAULT_UA).strip()
    tg_password = os.getenv("TG_PANEL_PASSWORD", "").strip()
    if not tg_password:
        tg_password = secrets.token_urlsafe(16)
        logger.info("BootstrapEnv: TG_PANEL_PASSWORD не указан. Сгенерирован безопасный случайный пароль для Telegram ПУ.")
    secret_hash = hash_password(tg_password)

    port = os.getenv("PORT") or os.getenv("CARNAVAL_PORT", "5000")
    host = os.getenv("CARNAVAL_HOST", "0.0.0.0")
    carnaval_enabled = os.getenv("CARNAVAL_ENABLED", "1")
    carnaval_secret = os.getenv("CARNAVAL_SECRET", "").strip() or secrets.token_hex(32)
    allowed_origins = resolve_allowed_origins_string()
    public_url = os.getenv("CARNAVAL_PUBLIC_URL", "").strip()
    locale = os.getenv("LOCALE", "ru").strip()
    proxy = os.getenv("FUNPAY_PROXY", "").strip()

    cfg = ConfigParser(delimiters=(":",), interpolation=None)
    cfg.optionxform = str

    cfg["FunPay"] = {
        "golden_key": golden_key,
        "user_agent": user_agent,
        "autoRaise": "0",
        "autoResponse": "0",
        "autoDelivery": "0",
        "multiDelivery": "0",
        "autoRestore": "0",
        "autoDisable": "0",
        "oldMsgGetMode": "0",
        "keepSentMessagesUnread": "0",
        "locale": locale,
    }

    cfg["Telegram"] = {
        "enabled": "1" if tg_token else "0",
        "token": tg_token,
        "secretKeyHash": secret_hash,
        "blockLogin": "0",
        "proxy": "",
    }

    cfg["BlockList"] = {
        "blockDelivery": "0",
        "blockResponse": "0",
        "blockNewMessageNotification": "0",
        "blockNewOrderNotification": "0",
        "blockCommandNotification": "0",
    }

    cfg["NewMessageView"] = {
        "includeMyMessages": "1",
        "includeFPMessages": "1",
        "includeBotMessages": "0",
        "notifyOnlyMyMessages": "0",
        "notifyOnlyFPMessages": "0",
        "notifyOnlyBotMessages": "0",
        "showImageName": "1",
    }

    cfg["Greetings"] = {
        "ignoreSystemMessages": "0",
        "onlyNewChats": "0",
        "sendGreetings": "0",
        "greetingsText": "Привет, $chat_name!",
        "greetingsCooldown": "2",
    }

    cfg["OrderConfirm"] = {
        "watermark": "1",
        "sendReply": "0",
        "replyText": "$username, спасибо за подтверждение заказа $order_id!\nЕсли не сложно, оставь, пожалуйста, отзыв!",
    }

    cfg["ReviewReply"] = {
        "star1Reply": "0",
        "star2Reply": "0",
        "star3Reply": "0",
        "star4Reply": "0",
        "star5Reply": "0",
        "star1ReplyText": "",
        "star2ReplyText": "",
        "star3ReplyText": "",
        "star4ReplyText": "",
        "star5ReplyText": "",
    }

    cfg["Proxy"] = {
        "enable": "1" if proxy else "0",
        "proxy": proxy,
        "check": "0",
    }

    cfg["Other"] = {
        "watermark": "🐦",
        "requestsDelay": "4",
        "language": locale,
    }

    cfg["Carnaval"] = {
        "enabled": carnaval_enabled,
        "host": host,
        "port": str(port),
        "secretKey": carnaval_secret,
        "allowedOrigins": allowed_origins,
        "publicUrl": public_url,
    }

    with open(config_path, "w", encoding="utf-8") as f:
        cfg.write(f)

    # Создаём вспомогательные файлы если их нет
    for fname in ("configs/auto_response.cfg", "configs/auto_delivery.cfg"):
        if not os.path.exists(fname):
            with open(fname, "w", encoding="utf-8") as f:
                pass

    logger.info(f"BootstrapEnv: конфигурация {config_path} успешно создана.")
    return True


def _sync_existing_config(config_path: str) -> bool:
    """Обновляет параметры [Carnaval] в существующем конфиге из переменных среды."""
    try:
        cfg = ConfigParser(delimiters=(":",), interpolation=None)
        cfg.optionxform = str
        cfg.read(config_path, encoding="utf-8")

        if not cfg.has_section("Carnaval"):
            cfg.add_section("Carnaval")

        changed = False

        # Синхронизация порта ($PORT от PaaS платформы имеет наивысший приоритет)
        port = os.getenv("PORT") or os.getenv("CARNAVAL_PORT", "5000")
        if cfg.get("Carnaval", "port", fallback=None) != str(port):
            cfg.set("Carnaval", "port", str(port))
            changed = True

        host = os.getenv("CARNAVAL_HOST", "0.0.0.0")
        if cfg.get("Carnaval", "host", fallback=None) != host:
            cfg.set("Carnaval", "host", host)
            changed = True

        enabled = os.getenv("CARNAVAL_ENABLED", "1")
        if cfg.get("Carnaval", "enabled", fallback=None) != enabled:
            cfg.set("Carnaval", "enabled", enabled)
            changed = True

        # Синхронизация CORS origins: строгий allowlist по умолчанию, '*' только при CARNAVAL_ALLOW_ANY_ORIGIN=1
        allow_any = os.getenv("CARNAVAL_ALLOW_ANY_ORIGIN", "0").strip() == "1"
        current_origins = cfg.get("Carnaval", "allowedOrigins", fallback=None)
        if allow_any:
            target_origins = "*"
        else:
            env_origins = os.getenv("CARNAVAL_ALLOWED_ORIGINS", "").strip()
            if env_origins:
                target_origins = resolve_allowed_origins_string()
            elif current_origins == "*" or current_origins is None or not current_origins.strip():
                # Заменяем небезопасный дефолт '*' на строгий allowlist
                target_origins = resolve_allowed_origins_string()
            else:
                target_origins = current_origins

        if current_origins != target_origins:
            cfg.set("Carnaval", "allowedOrigins", target_origins)
            changed = True

        public_url = os.getenv("CARNAVAL_PUBLIC_URL")
        if public_url and cfg.get("Carnaval", "publicUrl", fallback=None) != public_url:
            cfg.set("Carnaval", "publicUrl", public_url)
            changed = True

        secret = os.getenv("CARNAVAL_SECRET")
        if secret and cfg.get("Carnaval", "secretKey", fallback=None) != secret:
            cfg.set("Carnaval", "secretKey", secret)
            changed = True

        # Синхронизация Telegram токена если передан через env
        tg_token = (os.getenv("TG_BOT_TOKEN") or os.getenv("TG_TOKEN", "")).strip()
        if tg_token:
            if not cfg.has_section("Telegram"):
                cfg.add_section("Telegram")
            if cfg.get("Telegram", "token", fallback=None) != tg_token:
                cfg.set("Telegram", "token", tg_token)
                changed = True
            if cfg.get("Telegram", "enabled", fallback="0") != "1":
                cfg.set("Telegram", "enabled", "1")
                changed = True

        if changed:
            with open(config_path, "w", encoding="utf-8") as f:
                cfg.write(f)
            logger.info("BootstrapEnv: конфигурация синхронизирована с переменными среды.")

        return True
    except Exception as e:
        logger.warning(f"BootstrapEnv: ошибка синхронизации конфига: {e}")
        return False

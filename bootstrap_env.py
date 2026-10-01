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
    tg_password = (
        os.getenv("TG_PANEL_PASSWORD")
        or os.getenv("PANEL_PASSWORD")
        or os.getenv("TG_PASSWORD")
        or ""
    ).strip()
    password_source = "из переменной окружения TG_PANEL_PASSWORD"
    if not tg_password:
        tg_password = secrets.token_urlsafe(24)
        password_source = "сгенерирован автоматически (задайте TG_PANEL_PASSWORD чтобы зафиксировать)"

    # Сохраняем пароль в файл для отображения при последующих стартах
    os.makedirs("storage/cache", exist_ok=True)
    try:
        with open("storage/cache/tg_password.txt", "w", encoding="utf-8") as _pf:
            _pf.write(tg_password)
    except Exception:
        pass

    # Всегда печатаем пароль в stdout — sanitizer логов не трогает print()
    _sep = "=" * 60
    print(f"\n{_sep}", flush=True)
    print(f"[CARNAVAL] ПАРОЛЬ TELEGRAM БОТА ({password_source}):", flush=True)
    print(f"           {tg_password}", flush=True)
    print(f"Отправьте этот пароль боту в Telegram для авторизации.", flush=True)
    print(f"{_sep}\n", flush=True)

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
        cfg = ConfigParser(delimiters=(":", "="), interpolation=None)
        cfg.optionxform = str
        cfg.read(config_path, encoding="utf-8")

        if not cfg.has_section("Carnaval"):
            cfg.add_section("Carnaval")

        changed = False

        # Нормализация ключей секции [Telegram] к каноническому регистру Cardinal
        if cfg.has_section("Telegram"):
            for canon in ("secretKeyHash", "blockLogin", "enabled", "token", "proxy"):
                for existing in list(cfg.options("Telegram")):
                    if existing.lower() == canon.lower() and existing != canon:
                        cfg.set("Telegram", canon, cfg.get("Telegram", existing))
                        cfg.remove_option("Telegram", existing)
                        changed = True

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

        # Синхронизация пароля Telegram бота из переменной окружения
        tg_pass_env = (
            os.getenv("TG_PANEL_PASSWORD")
            or os.getenv("PANEL_PASSWORD")
            or os.getenv("TG_PASSWORD")
            or ""
        ).strip()
        from Utils.cardinal_tools import hash_password, check_password

        if tg_pass_env:
            if not cfg.has_section("Telegram"):
                cfg.add_section("Telegram")
            cur_hash = cfg.get("Telegram", "secretKeyHash", fallback="")
            if not cur_hash or not check_password(tg_pass_env, cur_hash):
                cfg.set("Telegram", "secretKeyHash", hash_password(tg_pass_env))
                changed = True
                logger.info("BootstrapEnv: пароль Telegram бота обновлен из переменной окружения.")
        elif os.getenv("RESET_TG_PASSWORD", "0").strip() == "1":
            new_pass = secrets.token_urlsafe(24)
            if not cfg.has_section("Telegram"):
                cfg.add_section("Telegram")
            cfg.set("Telegram", "secretKeyHash", hash_password(new_pass))
            changed = True
            logger.warning("BootstrapEnv: сброшен пароль Telegram бота по запросу RESET_TG_PASSWORD=1.")

        # Синхронизация обязательного владельца системы (TG_OWNER_ID)
        owner_id = (
            os.getenv("TG_OWNER_ID")
            or os.getenv("OWNER_ID")
            or os.getenv("OWNER_TELEGRAM_ID")
            or ""
        ).strip()
        if owner_id and owner_id.isdigit():
            from carnaval.db import set_state
            set_state("owner_telegram_id", owner_id)
            set_state("state", "INITIALIZED")
            try:
                from tg_bot.utils import load_authorized_users, save_authorized_users
                auth_users = load_authorized_users()
                oid = int(owner_id)
                if oid not in auth_users or auth_users[oid].get("role") != "owner":
                    auth_users[oid] = {"role": "owner", "username": "owner"}
                    save_authorized_users(auth_users)
                    logger.info(f"BootstrapEnv: назначен владелец системы Telegram ID {owner_id}")
            except Exception as e:
                logger.warning(f"BootstrapEnv: не удалось назначить владельца: {e}")

        # Синхронизация дополнительных администраторов по ID из переменных окружения
        admin_ids = (os.getenv("TG_ADMIN_ID") or os.getenv("ADMIN_ID") or "").strip()
        if admin_ids:
            try:
                from tg_bot.utils import load_authorized_users, save_authorized_users
                auth_users = load_authorized_users()
                users_updated = False
                for aid in admin_ids.split(","):
                    aid = aid.strip()
                    if aid and aid.isdigit() and int(aid) not in auth_users:
                        auth_users[int(aid)] = {"role": "admin", "username": f"admin_{aid}"}
                        users_updated = True
                        logger.info(f"BootstrapEnv: Telegram ID {aid} добавлен в список администраторов.")
                if users_updated:
                    save_authorized_users(auth_users)
            except Exception as e:
                logger.warning(f"BootstrapEnv: не удалось синхронизировать список администраторов: {e}")

        # Устраняем MASKED_IN_BACKUP в рабочем конфиге если они остались от старых бэкапов
        if cfg.has_section("FunPay") and cfg.get("FunPay", "golden_key", fallback="") == "MASKED_IN_BACKUP":
            from carnaval.secrets_manager import SecretManager
            real_key = SecretManager.get_secret("golden_key") or os.getenv("FUNPAY_GOLDEN_KEY", "") or os.getenv("GOLDEN_KEY", "")
            if real_key:
                cfg.set("FunPay", "golden_key", real_key)
                changed = True
        if cfg.has_section("Telegram") and cfg.get("Telegram", "token", fallback="") == "MASKED_IN_BACKUP":
            real_token = os.getenv("TG_BOT_TOKEN", "") or os.getenv("TG_TOKEN", "")
            if real_token:
                cfg.set("Telegram", "token", real_token)
                changed = True
        if cfg.has_section("Carnaval") and cfg.get("Carnaval", "secretKey", fallback="") == "MASKED_IN_BACKUP":
            real_sec = os.getenv("CARNAVAL_SECRET", "")
            if real_sec:
                cfg.set("Carnaval", "secretKey", real_sec)
                changed = True

        if changed:
            with open(config_path, "w", encoding="utf-8") as f:
                cfg.write(f)
            logger.info("BootstrapEnv: конфигурация синхронизирована с переменными среды.")

        # Показываем пароль Telegram бота при каждом старте
        _print_tg_password_banner()

        return True
    except Exception as e:
        logger.warning(f"BootstrapEnv: ошибка синхронизации конфига: {e}")
        return False


def _print_tg_password_banner() -> None:
    """
    Выводит в stdout текущий пароль Telegram бота при каждом старте сервера.
    Использует print() намеренно — sanitizer логов фильтрует logger.*,
    но не трогает stdout, поэтому пароль гарантированно виден в логах контейнера.
    """
    _sep = "=" * 60

    # 1. Пароль из переменной окружения (наивысший приоритет)
    env_pass = (
        os.getenv("TG_PANEL_PASSWORD")
        or os.getenv("PANEL_PASSWORD")
        or os.getenv("TG_PASSWORD")
        or ""
    ).strip()
    if env_pass:
        print(f"\n{_sep}", flush=True)
        print("[CARNAVAL] ПАРОЛЬ TELEGRAM БОТА (из переменной окружения):", flush=True)
        print(f"           {env_pass}", flush=True)
        print(f"{_sep}\n", flush=True)
        return

    # 2. Пароль из сохранённого файла
    pass_file = "storage/cache/tg_password.txt"
    if os.path.exists(pass_file):
        try:
            saved = open(pass_file, encoding="utf-8").read().strip()
            if saved:
                print(f"\n{_sep}", flush=True)
                print("[CARNAVAL] ПАРОЛЬ TELEGRAM БОТА (сохранён при первом запуске):", flush=True)
                print(f"           {saved}", flush=True)
                print("Чтобы сменить пароль — задайте переменную окружения TG_PANEL_PASSWORD.", flush=True)
                print(f"{_sep}\n", flush=True)
                return
        except Exception:
            pass

    # 3. Пароль неизвестен — инструкция
    print(f"\n{_sep}", flush=True)
    print("[CARNAVAL] ПАРОЛЬ TELEGRAM БОТА НЕИЗВЕСТЕН.", flush=True)
    print("Задайте переменную окружения TG_PANEL_PASSWORD и перезапустите сервер.", flush=True)
    print(f"{_sep}\n", flush=True)

"""
dev_server.py — запуск Carnaval Mini App в dev-режиме с мок-данными.

Поднимает локальный сервер на http://127.0.0.1:8765.
Предоставляет реалистичные мок-данные для всех 5 вкладок:
- Главная (аккаунт, баланс, переключатели, таймеры)
- Заказы (список, статусы, детализация заказа)
- Чаты (список чатов, история сообщений, отправка)
- Авто (автовыдача, склад/файлы, команды автоответа, шаблоны)
- Ещё (настройки, уведомления, плагины, прокси, ЧС, логи, бэкап)

Использование:
    python dev_server.py
"""

import configparser
import datetime
import logging
import sys
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("DevServer")

# ---------------------------------------------------------------------------
# Мок-классы данных FunPay
# ---------------------------------------------------------------------------

class MockOrderShortcut:
    def __init__(self, oid, desc, price, buyer, status="PAID", subcat="Telegram Stars"):
        self.id = oid
        self.description = desc
        self.price = price
        self.currency = "RUB"
        self.buyer_username = buyer
        self.buyer_id = 458921
        self.chat_id = 98765
        self.status = type("Status", (), {"name": status})()
        self.date = datetime.datetime.now() - datetime.timedelta(minutes=15)
        self.subcategory_name = subcat
        self.amount = 1


class MockOrderDetail:
    def __init__(self, oid):
        self.id = oid
        self.status = type("Status", (), {"name": "PAID"})()
        self.subcategory = type("SubCat", (), {"name": "Telegram Stars"})()
        self.sum = 350.00
        self.currency = "RUB"
        self.amount = 100
        self.buyer_id = 458921
        self.buyer_username = "durov_fan"
        self.buyer_open_orders_count = 0
        self.chat_id = 98765
        self.chat_name = "durov_fan"
        self.secrets = ["TG-STARS-KEY-9988-AAXX-ZZ77"]
        self.params = "100 звёзд"
        self.review = type("Review", (), {
            "stars": 5,
            "text": "Быстро и чётко! Спасибо!",
            "reply": "Обращайтесь ещё!",
            "anonymous": False,
        })()
        self.fields = {
            "Количество": type("Field", (), {"name": "Количество", "value": "100"})(),
            "Получатель": type("Field", (), {"name": "Получатель", "value": "@durov_fan"})(),
        }


class MockChat:
    def __init__(self, cid, name, last_msg, unread=False):
        self.id = cid
        self.name = name
        self.last_message_text = last_msg
        self.unread = unread
        self.node_msg_id = 502
        self.user_msg_id = 501
        self.last_by_bot = False


class MockMessage:
    def __init__(self, mid, text, cid, author, author_id):
        self.id = mid
        self.text = text
        self.chat_id = cid
        self.chat_name = author
        self.author = author
        self.author_id = author_id
        self.image_link = None
        self.image_name = None
        self.badge_text = None


class StubAccount:
    username = "carnaval_seller"
    id = 777000
    golden_key = "devkey_abcdef123456_devkey"
    user_agent = "Mozilla/5.0"
    proxy = {}
    active_sales = 3
    active_purchases = 0

    def __init__(self):
        self._orders = [
            MockOrderShortcut("ORDER-9812", "100 Telegram Stars", 350.0, "durov_fan", "PAID"),
            MockOrderShortcut("ORDER-9811", "Discord Nitro 1 месяц", 299.0, "gamer_pro", "CLOSED"),
            MockOrderShortcut("ORDER-9810", "Steam Пополнение 500 RUB", 550.0, "alex_steam", "CLOSED"),
            MockOrderShortcut("ORDER-9809", "Spotify Premium 3 мес", 450.0, "music_lover", "REFUNDED"),
        ]
        self._chats = {
            98765: MockChat(98765, "durov_fan", "Звёзды пришли, спасибо!", False),
            98766: MockChat(98766, "gamer_pro", "Привет, когда будет код?", True),
            98767: MockChat(98767, "alex_steam", "Спасибо за быструю выдачу 👍", False),
        }
        self._history = {
            98765: [
                MockMessage(1, "Здравствуйте, оплатил заказ", 98765, "durov_fan", 458921),
                MockMessage(2, "Привет! Ваш заказ выдан автоматически: TG-STARS-KEY-9988-AAXX-ZZ77", 98765, "carnaval_seller", 777000),
                MockMessage(3, "Звёзды пришли, спасибо!", 98765, "durov_fan", 458921),
            ],
            98766: [
                MockMessage(10, "Привет, когда будет код?", 98766, "gamer_pro", 458922),
            ]
        }

    def get_sales(self, start_from=None, include_paid=True, include_closed=True, include_refunded=True, **kwargs):
        filtered = []
        for o in self._orders:
            st = getattr(o.status, "name", str(o.status))
            if st == "PAID" and include_paid:
                filtered.append(o)
            elif st == "CLOSED" and include_closed:
                filtered.append(o)
            elif st == "REFUNDED" and include_refunded:
                filtered.append(o)
        return None, filtered, "ru", {}

    def get_order(self, order_id):
        return MockOrderDetail(order_id)

    def get_chats(self, update=False):
        return self._chats

    def get_chat_history(self, chat_id, last_message_id=None):
        return self._history.get(int(chat_id), [])

    def refund(self, order_id):
        logger.info(f"[stub] refund order {order_id}")
        return True

    def send_review_reply(self, order_id, text):
        logger.info(f"[stub] send_review_reply {order_id}: {text}")
        return True

    def delete_review_reply(self, order_id):
        logger.info(f"[stub] delete_review_reply {order_id}")
        return True


class StubPluginData:
    def __init__(self, name, uuid, desc, enabled=True):
        self.name = name
        self.version = "1.2.0"
        self.description = desc
        self.credits = "Carnaval Community"
        self.uuid = uuid
        self.path = f"plugins/{name}.py"
        self.enabled = enabled
        self.pinned = False
        self.settings_page = False


class StubTelegram:
    authorized_users = [777000, 123456789]
    answer_templates = [
        "Здравствуйте! Товар выдаётся автоматически в течение 1 минуты.",
        "Спасибо за покупку! Буду благодарен за положительный отзыв ⭐",
        "Уточните, пожалуйста, данные для активации.",
    ]


class StubBalance:
    total_rub = 4850.50
    available_rub = 3200.00
    total_usd = 45.75
    available_usd = 32.00
    total_eur = 38.30
    available_eur = 27.50


class MockLotShortcut:
    def __init__(self, lid, title, price, subcat_name):
        self.id = lid
        self.description = title
        self.price = price
        self.currency = "RUB"
        self.subcategory = type("Sub", (), {"name": subcat_name, "fullname": subcat_name})()


class MockProfile:
    def get_sorted_lots(self, mode=1):
        return {
            101: MockLotShortcut(101, "100 Telegram Stars", 350.0, "Telegram"),
            102: MockLotShortcut(102, "Discord Nitro 1 месяц", 299.0, "Discord"),
            103: MockLotShortcut(103, "Steam 500 RUB Пополнение", 550.0, "Steam"),
        }


class StubCardinal:
    VERSION = "3.13.1"
    start_time = int(__import__("time").time()) - 7200
    running = True
    raise_time = int(__import__("time").time()) + 900
    raised_time = int(__import__("time").time()) - 1500

    blacklist = ["scammer1", "baduser42"]
    delivery_tests = {}
    balance = StubBalance()
    profile = MockProfile()

    plugins = {
        "11111111-1111-1111-1111-111111111111": StubPluginData(
            "AutoBump", "11111111-1111-1111-1111-111111111111", "Автоматическое поднятие лотов по расписанию", True),
        "22222222-2222-2222-2222-222222222222": StubPluginData(
            "SmartReply", "22222222-2222-2222-2222-222222222222", "Умные ответы на частые вопросы покупателей", True),
        "33333333-3333-3333-3333-333333333333": StubPluginData(
            "WatermarkPro", "33333333-3333-3333-3333-333333333333", "Наложение водяных знаков на скриншоты", False),
    }
    proxy_dict = {
        0: "http://proxy.example.com:8080",
        1: "socks5h://user:secret@fastproxy.net:1080",
    }
    telegram = StubTelegram()
    account = StubAccount()

    def __init__(self):
        # MAIN_CFG
        cfg = configparser.ConfigParser()
        cfg.read_string("""
[FunPay]
golden_key = devkey_abcdef123456_devkey
user_agent = Mozilla/5.0
autoRaise = 1
autoResponse = 1
autoDelivery = 1
multiDelivery = 0
autoRestore = 1
autoDisable = 0
oldMsgGetMode = 0
keepSentMessagesUnread = 0
locale = ru

[Telegram]
enabled = 1
token = 123456:ABC-DEF
secretKeyHash =
proxy =
blockLogin = 0

[BlockList]
blockDelivery = 0
blockResponse = 0
blockNewMessageNotification = 0
blockNewOrderNotification = 0
blockCommandNotification = 0

[NewMessageView]
includeMyMessages = 1
includeFPMessages = 0
includeBotMessages = 0
notifyOnlyMyMessages = 0
notifyOnlyFPMessages = 0
notifyOnlyBotMessages = 0
showImageName = 1

[Greetings]
ignoreSystemMessages = 0
onlyNewChats = 0
sendGreetings = 1
greetingsText = Привет! Чем могу помочь?
greetingsCooldown = 86400

[OrderConfirm]
watermark = 1
sendReply = 1
replyText = Спасибо за заказ! Выдача товара выполнена автоматически.

[ReviewReply]
star1Reply = 0
star1ReplyText =
star2Reply = 0
star2ReplyText =
star3Reply = 0
star3ReplyText =
star4Reply = 1
star4ReplyText = Спасибо за оценку! Рады стараться.
star5Reply = 1
star5ReplyText = Огромное спасибо за 5 звёзд! Ждём вас снова!

[Proxy]
enable = 0
proxy =
check = 0

[Other]
watermark = 🤖 Carnaval Bot
requestsDelay = 2
language = ru

[Carnaval]
enabled = 1
host = 127.0.0.1
port = 8765
secretKey =
""")
        self.MAIN_CFG = cfg

        # AD_CFG
        ad_cfg = configparser.ConfigParser()
        ad_cfg.read_string("""
[100 Telegram Stars]
response = Ваш ключ: $product
telegramNotification = 1
notificationText = Выдан товар: 100 Telegram Stars

[Discord Nitro 1 месяц]
response = Ваша ссылка активации: $product
telegramNotification = 1
notificationText = Выдан Discord Nitro
""")
        self.AD_CFG = ad_cfg

        # AR_CFG
        ar_cfg = configparser.ConfigParser()
        ar_cfg.read_string("""
[!help|!помощь]
response = Доступные команды: !help, !status, !stock
telegramNotification = 0

[!stock|!наличие]
response = Все товары в наличии и выдаются автоматически!
telegramNotification = 0
""")
        self.AR_CFG = ar_cfg
        self.RAW_AR_CFG = ar_cfg

    @staticmethod
    def save_config(config, path):
        logger.info(f"[stub] save_config → {path} (сохранение пропущено в dev-режиме)")

    def toggle_plugin(self, uuid: str):
        if uuid in self.plugins:
            self.plugins[uuid].enabled = not self.plugins[uuid].enabled
            logger.info(f"[stub] toggle_plugin {uuid} → {self.plugins[uuid].enabled}")

    def send_message(self, chat_id, message_text, chat_name=None, interlocutor_id=None, watermark=True):
        logger.info(f"[stub] send_message to chat {chat_id}: {message_text}")
        msg = MockMessage(999, message_text, chat_id, self.account.username, self.account.id)
        if chat_id in self.account._history:
            self.account._history[chat_id].append(msg)
        return [msg]


# ---------------------------------------------------------------------------
# Запуск FastAPI
# ---------------------------------------------------------------------------

def main():
    stub = StubCardinal()

    # 1. Задаем Singleton кардинала
    from carnaval.deps import set_cardinal
    set_cardinal(stub)

    # 2. Инициализируем auth
    from carnaval import auth
    auth.init("")
    auth.verify_token = lambda tok: {"sub": "dev_user", "uid": 777000} if tok else None

    # 3. Отключаем требование Telegram-авторизации во всех роутерах
    import carnaval.routers.dashboard  as _r_dash
    import carnaval.routers.settings   as _r_settings
    import carnaval.routers.orders     as _r_orders
    import carnaval.routers.chats      as _r_chats
    import carnaval.routers.automation as _r_auto
    import carnaval.routers.more       as _r_more

    _always_auth = lambda request: True
    for mod in [_r_dash, _r_settings, _r_orders, _r_chats, _r_auto, _r_more]:
        if hasattr(mod, "_check_auth"):
            mod._check_auth = _always_auth

    # 4. Собираем FastAPI приложение
    from carnaval.server import build_app
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from starlette.middleware.base import BaseHTTPMiddleware

    os.environ["CARNAVAL_ALLOW_ANY_ORIGIN"] = "1"
    app = build_app(allowed_origins=["*"])
    from fastapi.staticfiles import StaticFiles
    web_dir = os.path.join(os.path.dirname(__file__), "carnaval", "web")
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="static")

    # 5. Middleware для перехвата авторизации (выдаёт токен при входе)
    class DevAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if request.method == "POST" and request.url.path == "/api/auth":
                logger.info("[dev] POST /api/auth → выдаём dev-токен")
                tok = auth.create_token(777000)
                return JSONResponse({"token": tok, "expires_in": 14400})
            return await call_next(request)

    app.add_middleware(DevAuthMiddleware)

    # 6. Создаём тестовые файлы склада, если их нет
    os.makedirs("storage/products", exist_ok=True)
    stars_file = "storage/products/telegram_stars.txt"
    if not os.path.exists(stars_file):
        with open(stars_file, "w", encoding="utf-8") as f:
            f.write("TG-STARS-KEY-0001-AA\nTG-STARS-KEY-0002-BB\nTG-STARS-KEY-0003-CC\n")

    nitro_file = "storage/products/discord_nitro.txt"
    if not os.path.exists(nitro_file):
        with open(nitro_file, "w", encoding="utf-8") as f:
            f.write("https://discord.gift/mock1\nhttps://discord.gift/mock2\n")

    # 7. Запуск Uvicorn
    import uvicorn

    print()
    print("=" * 65)
    print("   [+] CARNAVAL TELEGRAM MINI APP - DEV SERVER STARTED")
    print("=" * 65)
    print("   Local URL:    http://127.0.0.1:8765")
    print("   Mode:         Browser / Telegram WebApp")
    print("   Auth:         Automatic (dev bypass)")
    print("   Tabs:")
    print("      * Dashboard  (balance, toggles, lot bump timers)")
    print("      * Orders     (list, filter, details, refund)")
    print("      * Chats      (list, history, send message)")
    print("      * Auto       (delivery, storage files, auto-response, templates)")
    print("      * More       (notifications, plugins, proxy, blacklist, logs)")
    print("=" * 65)
    print()

    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")


if __name__ == "__main__":
    main()

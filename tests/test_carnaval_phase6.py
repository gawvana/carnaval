"""
tests/test_carnaval_phase6.py — Этап 6: CORS, /api/meta, config.js, Vercel proxy.

4 теста:
  1. test_cors_headers         — CORS заголовки присутствуют в ответах
  2. test_meta_endpoint        — GET /api/meta возвращает app/version
  3. test_set_allowed_origins  — set_allowed_origins() + get_allowed_origins()
  4. test_config_js_exists     — config.js и apiUrl export присутствуют в web/js
"""

import os
import pytest
from fastapi.testclient import TestClient


# ── Fixtures ────────────────────────────────────────────────────────────────

def _make_cardinal_stub(allowed_origins="*"):
    """Создаёт stub Cardinal для тестов."""
    import configparser

    class StubAccount:
        username = "test_user"
        id = 1
        golden_key = "key"
        user_agent = ""
        proxy = {}
        active_sales = 0
        active_purchases = 0

    class StubCardinal:
        VERSION = "3.13.1"
        start_time = 0
        running = True
        raise_time = None
        raised_time = None
        blacklist = []
        balance = None
        plugins = {}
        proxy_dict = {}
        account = StubAccount()

        class _tg:
            authorized_users = []

        telegram = _tg()

        def __init__(self):
            cfg = configparser.ConfigParser()
            cfg.read_string(f"""
[FunPay]
golden_key = test
user_agent =
autoRaise = 0
autoResponse = 0
autoDelivery = 0
multiDelivery = 0
autoRestore = 0
autoDisable = 0
oldMsgGetMode = 0
keepSentMessagesUnread = 0
locale = ru

[Telegram]
enabled = 0
token =
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
includeMyMessages = 0
includeFPMessages = 0
includeBotMessages = 0
notifyOnlyMyMessages = 0
notifyOnlyFPMessages = 0
notifyOnlyBotMessages = 0
showImageName = 0

[Greetings]
ignoreSystemMessages = 0
onlyNewChats = 0
sendGreetings = 0
greetingsText = hi
greetingsCooldown = 3600

[OrderConfirm]
watermark = 0
sendReply = 0
replyText = thanks

[ReviewReply]
star1Reply = 0
star1ReplyText =
star2Reply = 0
star2ReplyText =
star3Reply = 0
star3ReplyText =
star4Reply = 0
star4ReplyText =
star5Reply = 0
star5ReplyText =

[Proxy]
enable = 0
proxy =
check = 0

[Other]
watermark = test
requestsDelay = 2
language = ru

[Carnaval]
enabled = 1
host = 127.0.0.1
port = 8765
secretKey =
allowedOrigins = {allowed_origins}
""")
            self.MAIN_CFG = cfg

    return StubCardinal()


def _build_test_client(allowed_origins="*"):
    """Строит TestClient с заданными CORS origins."""
    from carnaval.deps import set_cardinal
    from carnaval import auth
    from carnaval.server import build_app, set_allowed_origins

    stub = _make_cardinal_stub(allowed_origins)
    set_cardinal(stub)
    set_allowed_origins(allowed_origins)
    app = build_app(allowed_origins=["*"] if allowed_origins == "*" else [o.strip() for o in allowed_origins.split(",")])
    return TestClient(app, raise_server_exceptions=True)


# ── Tests ────────────────────────────────────────────────────────────────────

def test_cors_headers_wildcard():
    """CORS заголовки присутствуют при allowedOrigins = *."""
    client = _build_test_client("*")

    # Preflight OPTIONS запрос
    r = client.options(
        "/api/meta",
        headers={
            "Origin": "https://my-app.vercel.app",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    # Starlette возвращает 200 для OPTIONS с CORS
    assert r.status_code in (200, 204), f"OPTIONS failed: {r.status_code}"

    # GET запрос должен содержать Access-Control-Allow-Origin
    r = client.get("/api/meta", headers={"Origin": "https://my-app.vercel.app"})
    assert r.status_code == 200
    assert "access-control-allow-origin" in r.headers, (
        "Access-Control-Allow-Origin header missing in GET /api/meta"
    )


def test_meta_endpoint():
    """GET /api/meta возвращает app, version без cors_origins (Section 4.3)."""
    client = _build_test_client("*")
    r = client.get("/api/meta")
    assert r.status_code == 200

    data = r.json()
    assert data["app"] == "Carnaval", f"Expected app='Carnaval', got {data}"
    assert "version" in data, "version field missing"
    assert "cors_origins" not in data, "cors_origins must not be exposed in /api/meta"


def test_set_allowed_origins_logic():
    """set_allowed_origins парсит строку корректно для wildcard и конкретных origins."""
    from carnaval.server import set_allowed_origins, get_allowed_origins

    # Wildcard
    set_allowed_origins("*")
    assert get_allowed_origins() == ["*"]

    # Пустая строка — как wildcard
    set_allowed_origins("")
    assert get_allowed_origins() == ["*"]

    # Конкретный origin
    set_allowed_origins("https://carnaval.vercel.app")
    result = get_allowed_origins()
    assert result == ["https://carnaval.vercel.app"]

    # Несколько через запятую
    set_allowed_origins("https://a.vercel.app, https://b.vercel.app")
    result = get_allowed_origins()
    assert len(result) == 2
    assert "https://a.vercel.app" in result
    assert "https://b.vercel.app" in result

    # Сбрасываем в wildcard после теста
    set_allowed_origins("*")


def test_config_js_and_vercel_files_exist():
    """Файлы config.js, scripts/gen-config.mjs и vercel.json присутствуют; serverless proxy удален."""
    base = os.path.join(os.path.dirname(__file__), "..")

    config_js = os.path.normpath(os.path.join(base, "carnaval", "web", "js", "config.js"))
    assert os.path.exists(config_js), f"config.js not found: {config_js}"

    # Проверяем что config.js экспортирует getApiBase и apiUrl
    with open(config_js, encoding="utf-8") as f:
        content = f.read()
    assert "getApiBase" in content, "config.js must export getApiBase()"
    assert "apiUrl" in content, "config.js must export apiUrl()"

    # Проверяем, что в архитектуре Infrlo single-origin vercel.json удален
    vercel_json = os.path.normpath(os.path.join(base, "vercel.json"))
    assert not os.path.exists(vercel_json), f"vercel.json must NOT exist in single-origin setup: {vercel_json}"

    # Проверяем, что serverless proxy api/[...path].js удален
    proxy_js = os.path.normpath(os.path.join(base, "api", "[...path].js"))
    assert not os.path.exists(proxy_js), f"api/[...path].js should be deleted: {proxy_js}"

    # Проверяем, что Vercel скрипт gen-config.mjs удален
    gen_script = os.path.normpath(os.path.join(base, "scripts", "gen-config.mjs"))
    assert not os.path.exists(gen_script), f"scripts/gen-config.mjs must be deleted: {gen_script}"

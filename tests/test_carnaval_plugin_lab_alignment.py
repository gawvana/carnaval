"""
tests/test_carnaval_plugin_lab_alignment.py — Comprehensive test suite for Plugin Lab & Route Alignment.

Covers:
1. All plugin endpoints under both /api/plugins and /api/more/plugins (GET, toggle, pin, reload, reload-all, upload, delete, commands)
2. Destructive operations protected by require_panel_unlocked
3. Complete authorized users support (GET, POST with role/comment, DELETE, security guards)
4. Frontend route alignment (command_palette.js, error_center.js, plugins_lab.js fake plugins removal)
5. Backup routes (GET download & POST trigger under both /api/backup and /api/more/backup)
"""

import configparser
import os
import time
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from carnaval import auth
from carnaval.deps import set_cardinal
from carnaval.server import build_app


class MockPlugin:
    def __init__(self, uuid="test-uuid", name="Test Plugin"):
        self.uuid = uuid
        self.name = name
        self.version = "1.0.0"
        self.description = "Test description"
        self.credits = "Author"
        self.path = f"plugins/{uuid}.py"
        self.enabled = True
        self.pinned = False
        self.settings_page = False
        self.commands = {"ping": "gl_ping", "help": "gl_help"}
        self.delete_handler = None


class MockTelegram:
    def __init__(self):
        self.authorized_users = {
            12345: {"username": "admin", "full_name": "Admin User", "role": "owner"},
            67890: {"username": "moderator", "full_name": "Mod User", "role": "admin"},
        }

    def is_alive(self):
        return True


class MockCardinal:
    def __init__(self):
        self.VERSION = "3.13.1"
        self.running = True
        self.start_time = int(time.time()) - 100

        cfg = configparser.ConfigParser(delimiters=(":",), interpolation=None)
        cfg.optionxform = str
        cfg.add_section("FunPay")
        cfg.set("FunPay", "golden_key", "sec12345")
        cfg.set("FunPay", "autoRaise", "1")
        cfg.add_section("Telegram")
        cfg.set("Telegram", "enabled", "1")
        cfg.set("Telegram", "token", "123:ABC")
        cfg.set("Telegram", "authorizedUsers", "12345,67890")
        cfg.add_section("Carnaval")
        cfg.set("Carnaval", "enabled", "1")
        cfg.set("Carnaval", "secretKey", "test_secret_for_plugin_alignment")

        self.MAIN_CFG = cfg
        self.account = MagicMock()
        self.account.id = 777
        self.account.username = "seller"
        self.account.golden_key = "sec12345"
        self.account.is_initiated = True

        self.telegram = MockTelegram()
        self.plugins = {
            "test-uuid": MockPlugin("test-uuid", "Alpha Plugin"),
            "second-uuid": MockPlugin("second-uuid", "Beta Plugin"),
        }
        self.disabled_plugins = []
        self.pinned_plugins = []
        self.proxy_dict = {}
        self.handler_bind_var_names = {}

    def toggle_plugin(self, uuid: str):
        if uuid in self.plugins:
            self.plugins[uuid].enabled = not self.plugins[uuid].enabled
            if not self.plugins[uuid].enabled and uuid not in self.disabled_plugins:
                self.disabled_plugins.append(uuid)
            elif self.plugins[uuid].enabled and uuid in self.disabled_plugins:
                self.disabled_plugins.remove(uuid)

    def pin_plugin(self, uuid: str):
        if uuid in self.plugins:
            self.plugins[uuid].pinned = not self.plugins[uuid].pinned
            if self.plugins[uuid].pinned and uuid not in self.pinned_plugins:
                self.pinned_plugins.append(uuid)
            elif not self.plugins[uuid].pinned and uuid in self.pinned_plugins:
                self.pinned_plugins.remove(uuid)

    def reload_plugin(self, uuid: str):
        if uuid not in self.plugins:
            return False, f"Plugin {uuid} not found"
        self.plugins[uuid].reloaded = True
        return True, ""

    def reload_all_plugins(self):
        for p in self.plugins.values():
            p.reloaded_all = True
        return True, ""

    def save_config(self, config, path):
        pass


@pytest.fixture
def mock_cardinal(monkeypatch):
    c = MockCardinal()
    set_cardinal(c)
    auth.init("test_secret_for_plugin_alignment")

    import carnaval.services.more as svc_more
    monkeypatch.setattr(svc_more, "get_cardinal", lambda: c)

    yield c
    set_cardinal(None)


@pytest.fixture
def client_unlocked(mock_cardinal, monkeypatch):
    """Client with unlocked panel session."""
    from carnaval import auth as auth_mod
    monkeypatch.setattr(auth_mod, "get_session", lambda tok: {
        "telegram_user_id": 12345,
        "role": "owner",
        "panel_unlocked": 1,
        "session_id_hash": "mock",
    })
    app = build_app(allowed_origins=["*"])
    return TestClient(app)


@pytest.fixture
def client_locked(mock_cardinal, monkeypatch):
    """Client with locked panel session."""
    from carnaval import auth as auth_mod
    monkeypatch.setattr(auth_mod, "get_session", lambda tok: {
        "telegram_user_id": 12345,
        "role": "owner",
        "panel_unlocked": 0,
        "session_id_hash": "mock",
    })
    import carnaval.deps as deps_mod
    monkeypatch.setattr(deps_mod, "get_state", lambda key, default=None: "INITIALIZED" if key == "state" else ("some_hash" if "password" in key else default))

    app = build_app(allowed_origins=["*"])
    return TestClient(app)


# ─────────────────────────────────────────────────────────────
# 1. Plugin Endpoints Dual Route Testing (/api/plugins & /api/more/plugins)
# ─────────────────────────────────────────────────────────────

def test_plugin_list_both_routes(client_unlocked, mock_cardinal):
    headers = {"Authorization": "Bearer tok"}

    for path in ("/api/plugins", "/api/more/plugins"):
        res = client_unlocked.get(path, headers=headers)
        assert res.status_code == 200, f"Failed on {path}"
        data = res.json()
        assert "plugins" in data
        assert len(data["plugins"]) == 2
        p0 = data["plugins"][0]
        # Check compatibility fields
        assert "uuid" in p0
        assert "name" in p0
        assert "desc" in p0
        assert "description" in p0
        assert "author" in p0
        assert "credits" in p0
        assert "commands" in p0


def test_plugin_toggle_both_routes(client_unlocked, mock_cardinal):
    headers = {"Authorization": "Bearer tok"}

    # Initially enabled
    assert mock_cardinal.plugins["test-uuid"].enabled is True

    # 1. Toggle via /api/plugins
    res1 = client_unlocked.post("/api/plugins/test-uuid/toggle", headers=headers)
    assert res1.status_code == 200
    assert res1.json()["ok"] is True
    assert mock_cardinal.plugins["test-uuid"].enabled is False

    # 2. Toggle back via /api/more/plugins
    res2 = client_unlocked.post("/api/more/plugins/test-uuid/toggle", headers=headers)
    assert res2.status_code == 200
    assert res2.json()["ok"] is True
    assert mock_cardinal.plugins["test-uuid"].enabled is True


def test_plugin_pin_both_routes(client_unlocked, mock_cardinal):
    headers = {"Authorization": "Bearer tok"}

    # 1. Pin toggle via /api/plugins with JSON body
    res1 = client_unlocked.post("/api/plugins/test-uuid/pin", json={"pinned": True}, headers=headers)
    assert res1.status_code == 200
    assert mock_cardinal.plugins["test-uuid"].pinned is True

    # 2. Pin toggle via /api/more/plugins without body
    res2 = client_unlocked.post("/api/more/plugins/test-uuid/pin", headers=headers)
    assert res2.status_code == 200
    assert mock_cardinal.plugins["test-uuid"].pinned is False


def test_plugin_reload_both_routes(client_unlocked, mock_cardinal):
    headers = {"Authorization": "Bearer tok"}

    # Reload single plugin via /api/plugins
    res1 = client_unlocked.post("/api/plugins/test-uuid/reload", headers=headers)
    assert res1.status_code == 200
    assert res1.json()["ok"] is True
    assert getattr(mock_cardinal.plugins["test-uuid"], "reloaded", False) is True

    # Reload single plugin via /api/more/plugins
    res2 = client_unlocked.post("/api/more/plugins/second-uuid/reload", headers=headers)
    assert res2.status_code == 200
    assert res2.json()["ok"] is True
    assert getattr(mock_cardinal.plugins["second-uuid"], "reloaded", False) is True

    # Reload non-existent plugin -> 400
    res_err = client_unlocked.post("/api/plugins/non-existent/reload", headers=headers)
    assert res_err.status_code == 400


def test_plugin_reload_all_both_routes(client_unlocked, mock_cardinal):
    headers = {"Authorization": "Bearer tok"}

    # Reload all via /api/plugins
    res1 = client_unlocked.post("/api/plugins/reload-all", headers=headers)
    assert res1.status_code == 200
    assert res1.json()["ok"] is True
    assert getattr(mock_cardinal.plugins["test-uuid"], "reloaded_all", False) is True

    # Reload all via /api/more/plugins
    res2 = client_unlocked.post("/api/more/plugins/reload-all", headers=headers)
    assert res2.status_code == 200
    assert res2.json()["ok"] is True


def test_plugin_upload_and_delete_both_routes(client_unlocked, mock_cardinal, tmp_path, monkeypatch):
    headers = {"Authorization": "Bearer tok"}

    # Test upload via /api/plugins
    fake_plugin_code = b"# Sample plugin\nNAME = 'Sample'\nUUID = 'sample-123'\n"
    plugin_name = f"sample_{int(time.time() * 1000)}.py"
    target_path = os.path.join("plugins", plugin_name)
    try:
        res_upload = client_unlocked.post(
            "/api/plugins/upload",
            files={"file": (plugin_name, fake_plugin_code, "text/x-python")},
            headers=headers,
        )
        assert res_upload.status_code == 200
        assert res_upload.json()["ok"] is True
    finally:
        if os.path.exists(target_path):
            try:
                os.remove(target_path)
            except Exception:
                pass

    # Test delete without confirm -> 400
    res_del_no_conf = client_unlocked.delete("/api/plugins/test-uuid", headers=headers)
    assert res_del_no_conf.status_code == 400
    assert res_del_no_conf.json().get("error") == "confirm_required"

    # Test delete with confirm via /api/plugins
    res_del = client_unlocked.delete("/api/plugins/test-uuid?confirm=true", headers=headers)
    assert res_del.status_code == 200
    assert "test-uuid" not in mock_cardinal.plugins


def test_plugin_commands_both_routes(client_unlocked, mock_cardinal):
    headers = {"Authorization": "Bearer tok"}

    res1 = client_unlocked.get("/api/plugins/test-uuid/commands", headers=headers)
    assert res1.status_code == 200
    assert "ping" in res1.json()["commands"]

    res2 = client_unlocked.get("/api/more/plugins/test-uuid/commands", headers=headers)
    assert res2.status_code == 200
    assert "ping" in res2.json()["commands"]


# ─────────────────────────────────────────────────────────────
# 2. Destructive Operations Require Unlocked Panel
# ─────────────────────────────────────────────────────────────

def test_destructive_operations_blocked_when_panel_locked(client_locked, mock_cardinal):
    headers = {"Authorization": "Bearer tok"}

    # Toggle
    res_toggle = client_locked.post("/api/plugins/test-uuid/toggle", headers=headers)
    assert res_toggle.status_code == 403
    assert res_toggle.json()["detail"]["error"] == "panel_locked"

    # Reload single
    res_reload = client_locked.post("/api/plugins/test-uuid/reload", headers=headers)
    assert res_reload.status_code == 403
    assert res_reload.json()["detail"]["error"] == "panel_locked"

    # Reload all
    res_reload_all = client_locked.post("/api/plugins/reload-all", headers=headers)
    assert res_reload_all.status_code == 403
    assert res_reload_all.json()["detail"]["error"] == "panel_locked"

    # Upload
    res_upload = client_locked.post(
        "/api/plugins/upload",
        files={"file": ("test.py", b"# code", "text/x-python")},
        headers=headers,
    )
    assert res_upload.status_code == 403
    assert res_upload.json()["detail"]["error"] == "panel_locked"

    # Delete
    res_del = client_locked.delete("/api/plugins/test-uuid?confirm=true", headers=headers)
    assert res_del.status_code == 403
    assert res_del.json()["detail"]["error"] == "panel_locked"

    # Add authorized user
    res_au = client_locked.post(
        "/api/more/authorized-users",
        json={"user_id": 99999, "role": "admin"},
        headers=headers,
    )
    assert res_au.status_code == 403
    assert res_au.json()["detail"]["error"] == "panel_locked"


# ─────────────────────────────────────────────────────────────
# 3. Authorized Users Complete Support
# ─────────────────────────────────────────────────────────────

def test_authorized_users_add_get_delete(client_unlocked, mock_cardinal):
    headers = {"Authorization": "Bearer tok"}

    # 1. GET list via both routes
    res_get1 = client_unlocked.get("/api/more/authorized-users", headers=headers)
    assert res_get1.status_code == 200
    assert len(res_get1.json()["users"]) == 2

    res_get2 = client_unlocked.get("/api/authorized-users", headers=headers)
    assert res_get2.status_code == 200
    assert len(res_get2.json()["users"]) == 2

    # 2. Add new user via /api/more/authorized-users
    new_user_payload = {"user_id": 777888, "role": "support", "comment": "Junior Admin"}
    res_add = client_unlocked.post("/api/more/authorized-users", json=new_user_payload, headers=headers)
    assert res_add.status_code == 200
    assert res_add.json()["ok"] is True
    assert 777888 in mock_cardinal.telegram.authorized_users
    assert mock_cardinal.telegram.authorized_users[777888]["role"] == "support"
    assert mock_cardinal.telegram.authorized_users[777888]["comment"] == "Junior Admin"

    # 3. Duplicate addition returns 400
    res_dup = client_unlocked.post("/api/authorized-users", json=new_user_payload, headers=headers)
    assert res_dup.status_code == 400

    # 4. Self deletion blocked (user 12345 cannot delete 12345)
    res_self = client_unlocked.delete("/api/more/authorized-users/12345?confirm=true", headers=headers)
    assert res_self.status_code == 400
    assert res_self.json().get("error") == "self_deletion_forbidden"

    # 5. Delete without confirm blocked
    res_no_conf = client_unlocked.delete("/api/more/authorized-users/777888", headers=headers)
    assert res_no_conf.status_code == 400
    assert res_no_conf.json().get("error") == "confirm_required"

    # 6. Delete with confirm succeeds
    res_del = client_unlocked.delete("/api/more/authorized-users/777888?confirm=true", headers=headers)
    assert res_del.status_code == 200
    assert 777888 not in mock_cardinal.telegram.authorized_users


# ─────────────────────────────────────────────────────────────
# 4. Backup Endpoints (GET and POST)
# ─────────────────────────────────────────────────────────────

def test_backup_routes_both_prefixes(client_unlocked, mock_cardinal, monkeypatch):
    headers = {"Authorization": "Bearer tok"}

    # GET download backup
    res_get1 = client_unlocked.get("/api/more/backup", headers=headers)
    assert res_get1.status_code == 200
    assert res_get1.headers["content-type"] == "application/zip"

    res_get2 = client_unlocked.get("/api/backup", headers=headers)
    assert res_get2.status_code == 200
    assert res_get2.headers["content-type"] == "application/zip"

    # POST trigger backup
    import carnaval.services.backup as backup_mod
    monkeypatch.setattr(backup_mod, "create_backup", lambda target=None: (True, "backups/test.zip"))

    res_post1 = client_unlocked.post("/api/more/backup", headers=headers)
    assert res_post1.status_code == 200
    assert res_post1.json()["ok"] is True

    res_post2 = client_unlocked.post("/api/backup", headers=headers)
    assert res_post2.status_code == 200
    assert res_post2.json()["ok"] is True


# ─────────────────────────────────────────────────────────────
# 5. Frontend Files Route Alignment Verification
# ─────────────────────────────────────────────────────────────

def test_frontend_action_routes_alignment():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 1. command_palette.js
    cp_path = os.path.join(base_dir, "carnaval", "web", "js", "ui", "command_palette.js")
    with open(cp_path, "r", encoding="utf-8") as f:
        cp_content = f.read()
    assert "/api/setup/reconnect" in cp_content
    assert "/api/more/backup" in cp_content
    assert "/api/account/reconnect" not in cp_content
    assert "api.request('POST', '/api/backup'" not in cp_content

    # 2. error_center.js
    ec_path = os.path.join(base_dir, "carnaval", "web", "js", "ui", "error_center.js")
    with open(ec_path, "r", encoding="utf-8") as f:
        ec_content = f.read()
    assert "/api/setup/reconnect" in ec_content
    assert "/api/account/reconnect" not in ec_content

    # 3. plugins_lab.js
    pl_path = os.path.join(base_dir, "carnaval", "web", "js", "pages", "plugins_lab.js")
    with open(pl_path, "r", encoding="utf-8") as f:
        pl_content = f.read()
    assert "AutoDeliver Plus" not in pl_content
    assert "Review Bot" not in pl_content
    assert "Не удалось загрузить список плагинов" in pl_content
    assert "retry-plugins-btn" in pl_content

    # 4. api.js
    api_path = os.path.join(base_dir, "carnaval", "web", "js", "api.js")
    with open(api_path, "r", encoding="utf-8") as f:
        api_content = f.read()
    assert "export async function addAuthorizedUser" in api_content
    assert "/api/more/authorized-users" in api_content

    # 5. pages/more.js
    more_path = os.path.join(base_dir, "carnaval", "web", "js", "pages", "more.js")
    with open(more_path, "r", encoding="utf-8") as f:
        more_content = f.read()
    assert "au-add-btn" in more_content
    assert "Добавить пользователя" in more_content

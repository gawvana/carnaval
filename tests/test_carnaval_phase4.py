"""
Тесты для Этапа 4 Carnaval:
- Автовыдача (AD_CFG, создание, редактирование, удаление, тест-ключи)
- Товарные файлы (создание, пополнение, скачивание, удаление, защита от path traversal)
- Автоответчик (RAW_AR_CFG / AR_CFG, команды, уведомления)
- Шаблоны ответов (answer_templates)
- Лоты FunPay (/api/funpay/lots)
- Статика страницы automation.js
"""

import os
import shutil
import tempfile
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from carnaval.server import build_app
from carnaval.deps import set_cardinal
from carnaval import auth


@pytest.fixture
def mock_cardinal_p4(tmp_path, monkeypatch):
    import configparser
    c = MagicMock()
    c.VERSION = "0.1.17.15"
    c.delivery_tests = {}

    # Временная папка для хранения файлов товаров
    products_dir = tmp_path / "storage" / "products"
    products_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)

    # Конфиг автовыдачи
    ad_cfg = configparser.ConfigParser(delimiters=(":",), interpolation=None)
    ad_cfg.optionxform = str
    ad_cfg.add_section("Test Lot 1")
    ad_cfg.set("Test Lot 1", "response", "Привет, вот товар: $product")
    ad_cfg.set("Test Lot 1", "productsFileName", "test_goods.txt")
    ad_cfg.set("Test Lot 1", "disable", "0")

    # Конфиг автоответа
    raw_ar_cfg = configparser.ConfigParser(delimiters=(":",), interpolation=None)
    raw_ar_cfg.optionxform = str
    raw_ar_cfg.add_section("!help|помощь")
    raw_ar_cfg.set("!help|помощь", "response", "Помощь тут!")
    raw_ar_cfg.set("!help|помощь", "telegramNotification", "0")
    raw_ar_cfg.set("!help|помощь", "enabled", "1")

    ar_cfg = configparser.ConfigParser(delimiters=(":",), interpolation=None)
    ar_cfg.optionxform = str
    ar_cfg.add_section("!help")
    ar_cfg.set("!help", "response", "Помощь тут!")
    ar_cfg.add_section("помощь")
    ar_cfg.set("помощь", "response", "Помощь тут!")

    main_cfg = configparser.ConfigParser(delimiters=(":",), interpolation=None)
    main_cfg.optionxform = str
    main_cfg.add_section("Carnaval")
    main_cfg.set("Carnaval", "enabled", "1")
    main_cfg.set("Carnaval", "secretKey", "secret_p4")

    c.MAIN_CFG = main_cfg
    c.AD_CFG = ad_cfg
    c.RAW_AR_CFG = raw_ar_cfg
    c.AR_CFG = ar_cfg

    c.telegram = MagicMock()
    c.telegram.authorized_users = {12345: {}}
    c.telegram.answer_templates = ["Спасибо за покупку!", "Здравствуйте, чем помочь?"]

    # Профиль FunPay
    profile = MagicMock()
    mock_lot = MagicMock()
    mock_lot.id = 111
    mock_lot.description = "FunPay 1000 Gold"
    mock_lot.price = 250.0
    mock_lot.currency = "RUB"
    mock_lot.server = "EU"
    mock_lot.side = "Horde"
    mock_lot.subcategory_name = "WOW Gold"
    mock_lot.title = "FunPay 1000 Gold"
    profile.get_sorted_lots.return_value = {111: mock_lot}

    c.profile = profile
    c.account = MagicMock()
    c.account.id = 999
    c.save_config = MagicMock()

    set_cardinal(c)
    auth.init("secret_p4")
    return c


def test_delivery_lots_crud_and_test(mock_cardinal_p4):
    app = build_app()
    client = TestClient(app)
    token = auth.create_token(12345)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. GET /api/delivery/lots
    res = client.get("/api/delivery/lots", headers=headers)
    assert res.status_code == 200
    lots = res.json()["lots"]
    assert len(lots) == 1
    assert lots[0]["name"] == "Test Lot 1"

    # 2. POST /api/delivery/lots (создание)
    new_lot = {
        "name": "New Lot 2",
        "response": "Спасибо, $username!",
        "productsFileName": None,
        "disable": False
    }
    create_res = client.post("/api/delivery/lots", json=new_lot, headers=headers)
    assert create_res.status_code == 200
    assert create_res.json()["name"] == "New Lot 2"

    # 3. POST /api/delivery/lots/{i}/test (генерация ключа теста)
    test_res = client.post("/api/delivery/lots/0/test", headers=headers)
    assert test_res.status_code == 200
    test_key = test_res.json()["key"]
    assert len(test_key) == 50
    assert mock_cardinal_p4.delivery_tests[test_key] == "Test Lot 1"

    # 4. PATCH /api/delivery/lots/{i}
    patch_res = client.patch("/api/delivery/lots/0", json={"disable": True}, headers=headers)
    assert patch_res.status_code == 200
    assert patch_res.json()["disable"] is True

    # 5. DELETE /api/delivery/lots/{i}
    no_confirm_res = client.delete("/api/delivery/lots/1", headers=headers)
    assert no_confirm_res.status_code == 400
    assert no_confirm_res.json().get("error") == "confirm_required"

    del_res = client.delete("/api/delivery/lots/1?confirm=true", headers=headers)
    assert del_res.status_code == 200


def test_products_files_crud_and_security(mock_cardinal_p4):
    app = build_app()
    client = TestClient(app)
    token = auth.create_token(12345)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. POST /api/delivery/files (создание файла с товарами)
    create_res = client.post("/api/delivery/files", json={
        "name": "keys.txt",
        "goods": ["key123", "key456"]
    }, headers=headers)
    assert create_res.status_code == 200
    assert create_res.json()["count"] == 2

    # 2. GET /api/delivery/files
    files_res = client.get("/api/delivery/files", headers=headers)
    assert files_res.status_code == 200
    assert any(f["name"] == "keys.txt" for f in files_res.json()["files"])

    # 3. POST /api/delivery/files/{name}/goods (пополнение)
    add_res = client.post("/api/delivery/files/keys.txt/goods", json={
        "goods": ["key789"],
        "at_zero_position": False
    }, headers=headers)
    assert add_res.status_code == 200
    assert add_res.json()["count"] == 3

    # 4. GET /api/delivery/files/{name}/download
    dl_res = client.get("/api/delivery/files/keys.txt/download", headers=headers)
    assert dl_res.status_code == 200
    assert "key123" in dl_res.text
    assert "key789" in dl_res.text

    # 5. Path traversal защита
    bad_res = client.get("/api/delivery/files/..%2F..%2Fetc/passwd", headers=headers)
    assert bad_res.status_code in (400, 404)

    # 6. DELETE /api/delivery/files/{name}
    no_confirm_res = client.delete("/api/delivery/files/keys.txt", headers=headers)
    assert no_confirm_res.status_code == 400
    assert no_confirm_res.json().get("error") == "confirm_required"

    del_res = client.delete("/api/delivery/files/keys.txt?confirm=true", headers=headers)
    assert del_res.status_code == 200


def test_autoresponse_and_templates(mock_cardinal_p4):
    app = build_app()
    client = TestClient(app)
    token = auth.create_token(12345)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. GET /api/autoresponse/commands
    cmds_res = client.get("/api/autoresponse/commands", headers=headers)
    assert cmds_res.status_code == 200
    assert len(cmds_res.json()["commands"]) == 1

    # 2. POST /api/autoresponse/commands
    new_cmd_res = client.post("/api/autoresponse/commands", json={
        "command": "!status",
        "response": "Работаю штатно!",
        "telegramNotification": True,
        "enabled": True
    }, headers=headers)
    assert new_cmd_res.status_code == 200

    # 3. GET /api/templates
    tmpls_res = client.get("/api/templates", headers=headers)
    assert tmpls_res.status_code == 200
    assert len(tmpls_res.json()["templates"]) == 2

    # 4. POST /api/templates
    create_t_res = client.post("/api/templates", json={"text": "Новый шаблон"}, headers=headers)
    assert create_t_res.status_code == 200

    # 5. GET /api/funpay/lots
    lots_res = client.get("/api/funpay/lots", headers=headers)
    assert lots_res.status_code == 200
    assert len(lots_res.json()["lots"]) == 1
    assert lots_res.json()["lots"][0]["title"] == "FunPay 1000 Gold"

    # 6. Статика automation.js
    script_res = client.get("/js/pages/automation.js")
    assert script_res.status_code == 200
    assert "renderAutomation" in script_res.text

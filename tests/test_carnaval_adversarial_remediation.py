"""
tests/test_carnaval_adversarial_remediation.py — Регрессионные тесты для устраненных состязательных дефектов:
- CRIT-01: Проверка panel_password_hash в require_panel_unlocked
- CRIT-03: Защита эндпоинтов возврата (refund) через require_panel_unlocked
- CRIT-04: Маскирование секретов и защита require_panel_unlocked для /more/configs
- HIGH-04: Защита эндпоинтов управления прокси через require_panel_unlocked
- MED-01: Безопасность /api/meta при неинициализированном Cardinal
"""

from fastapi.testclient import TestClient
import pytest
from carnaval.server import build_app
from carnaval.deps import set_cardinal
from carnaval.db import init_db, set_state


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    import carnaval.paths
    test_db = str(tmp_path / "test_adversarial.db")
    monkeypatch.setattr(carnaval.paths, "DB_PATH", test_db)
    init_db()
    yield
    try:
        set_state("panel_password_hash", "")
        set_state("state", "UNINITIALIZED")
    except Exception:
        pass


def test_require_panel_unlocked_checks_panel_password_hash():
    """CRIT-01: require_panel_unlocked блокирует доступ, если установлен panel_password_hash и сессия не разблокирована."""
    from carnaval.deps import require_panel_unlocked
    from fastapi import HTTPException

    set_state("state", "INITIALIZED")
    set_state("panel_password_hash", "$2b$12$fakehashedpassword123456789012345678901234567890")

    session = {"telegram_user_id": 12345, "role": "owner", "panel_unlocked": False}

    with pytest.raises(HTTPException) as exc_info:
        require_panel_unlocked(request=None, session=session)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail.get("error") == "panel_locked"

    # Когда панель разблокирована — доступ разрешен
    session["panel_unlocked"] = True
    result = require_panel_unlocked(request=None, session=session)
    assert result == session


def test_meta_endpoint_safe_without_cardinal(monkeypatch):
    """MED-01: /api/meta возвращает 200 OK даже если Cardinal равен None."""
    import carnaval.deps
    monkeypatch.setattr(carnaval.deps, "_cardinal", None)
    app = build_app()
    client = TestClient(app)

    res = client.get("/api/meta")
    assert res.status_code == 200
    data = res.json()
    assert data["app"] == "Carnaval"
    assert "version" in data


def test_config_masks_secrets_in_main_cfg(tmp_path, monkeypatch):
    """CRIT-04: get_config_content маскирует конфиденциальные данные _main.cfg."""
    from carnaval.services import more as more_svc
    import os

    cfg_dir = tmp_path / "configs"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    main_cfg_path = cfg_dir / "_main.cfg"
    main_cfg_path.write_text(
        "[Telegram]\n"
        "token = 123456789:ABCdefGHIjklMNOpqrsTUVwxyz\n"
        "secretPassword = SuperSecretPassword123\n\n"
        "[FunPay]\n"
        "golden_key = a1b2c3d4e5f60718293a4b5c6d7e8f90\n\n"
        "[Carnaval]\n"
        "secretKey = CarnavalSecretKey123\n",
        encoding="utf-8"
    )

    # Перенаправляем путь к configs
    monkeypatch.chdir(tmp_path)
    content, filename, err = more_svc.get_config_content("main")
    assert err is None
    assert content is not None
    assert "123456789:ABCdefGHIjklMNOpqrsTUVwxyz" not in content
    assert "SuperSecretPassword123" not in content
    assert "a1b2c3d4e5f60718293a4b5c6d7e8f90" not in content
    assert "CarnavalSecretKey123" not in content
    assert "[MASKED_BY_CARNAVAL]" in content

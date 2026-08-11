import pytest
from fastapi import HTTPException

from app.api.dependencies.admin import require_admin_api_key


def test_admin_key_fails_closed_when_not_configured(monkeypatch):
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)

    with pytest.raises(HTTPException) as error:
        require_admin_api_key("anything")

    assert error.value.status_code == 503


def test_admin_key_requires_constant_time_matched_header(monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "admin-secret")

    with pytest.raises(HTTPException) as error:
        require_admin_api_key("wrong")
    assert error.value.status_code == 401
    assert require_admin_api_key("admin-secret") is None

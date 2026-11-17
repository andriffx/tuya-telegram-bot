"""Test autentikasi dashboard: API key, session cookie, logout, token rusak."""

import pytest
from fastapi.testclient import TestClient

import tuyabot.web.deps as deps
from tuyabot.web.app import app

API_KEY = "kunci-uji-fase5"


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setattr(deps, "DASHBOARD_API_KEY", API_KEY)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_request_without_credentials_is_rejected(client):
    assert client.get("/api/devices").status_code == 401


def test_api_key_header_still_works_for_scripts(client):
    response = client.get("/api/devices", headers={"X-API-Key": API_KEY})
    assert response.status_code == 200


def test_login_with_wrong_key_is_rejected(client):
    assert client.post("/api/login", json={"api_key": "salah"}).status_code == 401


def test_login_sets_hardened_cookie(client):
    response = client.post("/api/login", json={"api_key": API_KEY})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower().replace(" ", "")
    assert "httponly" in cookie, "cookie wajib HttpOnly agar tidak dibaca JavaScript"
    assert "samesite=strict" in cookie


def test_cookie_grants_access_to_api(client):
    client.post("/api/login", json={"api_key": API_KEY})
    assert client.get("/api/devices").status_code == 200
    assert client.get("/api/session").json() == {"authenticated": True}


def test_logout_clears_session(client):
    client.post("/api/login", json={"api_key": API_KEY})
    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/devices").status_code == 401
    assert client.get("/api/session").json() == {"authenticated": False}


def test_tampered_cookie_is_rejected(client):
    client.post("/api/login", json={"api_key": API_KEY})
    token = client.cookies.get("tuyabot_session")
    assert token

    payload, signature = token.split(".")
    forged = f"{payload}.{'A' * len(signature)}"
    client.cookies.set("tuyabot_session", forged)
    assert client.get("/api/devices").status_code == 401


def test_expired_token_is_rejected(client, monkeypatch):
    import tuyabot.web.auth as auth

    token = auth.create_session_token(ttl=-1)
    client.cookies.set("tuyabot_session", token)
    assert auth.verify_session_token(token) is False
    assert client.get("/api/devices").status_code == 401


def test_unconfigured_key_returns_503(client, monkeypatch):
    monkeypatch.setattr(deps, "DASHBOARD_API_KEY", "")
    assert client.post("/api/login", json={"api_key": "apa-saja"}).status_code == 503
    assert client.get("/api/devices").status_code == 503


def test_healthz_stays_open(client):
    assert client.get("/healthz").status_code == 200

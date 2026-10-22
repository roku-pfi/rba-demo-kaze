"""Kaze Labs' portal: signs in through RokuSec, authorizes by permission (U-5)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from rba_contracts import CallbackTokenResponse, SessionResponse, SessionToken, UserPublic

from rba_demo_kaze.config import Settings
from rba_demo_kaze.idp import IdpError
from rba_demo_kaze.main import create_app, login_url

# What the IdP flattens kaze-portal's roles down to (seed: admin, member, viewer).
ADMIN = ["portal:read", "projects:write", "settings:manage"]
MEMBER = ["portal:read", "projects:write"]
VIEWER = ["portal:read"]
WHEN = datetime(2026, 10, 22, tzinfo=timezone.utc)


class StubIdp:
    def __init__(self, permissions: list[str], email: str = "lucas@kazelabs.example") -> None:
        self.permissions = permissions
        self.email = email
        self.sessions = {"tok"}

    def _user(self) -> UserPublic:
        return UserPublic(tenant_id="kaze-labs", user_id="usr_kz", email=self.email, created_at=WHEN, is_admin=False)

    def exchange(self, code: str) -> CallbackTokenResponse:
        if code != "good":
            raise IdpError("bad code")
        return CallbackTokenResponse(session=SessionToken(token="tok", expires_at=WHEN), user=self._user())

    def get_session(self, token: str) -> SessionResponse:
        if token not in self.sessions:
            raise IdpError("expired")
        return SessionResponse(user=self._user(), expires_at=WHEN, application_id="kaze-portal", permissions=list(self.permissions))

    def logout(self, token: str) -> None:
        self.sessions.discard(token)


def _settings() -> Settings:
    return Settings(idp_public_url="http://idp.test", idp_internal_url="http://idp.test", public_url="http://kaze.test")


def _signed_in(permissions: list[str], email: str = "lucas@kazelabs.example") -> TestClient:
    client = TestClient(create_app(_settings(), idp_client=StubIdp(permissions, email)))
    client.get("/callback?code=good", follow_redirects=False)
    return client


def test_anonymous_goes_to_rokusec_with_the_public_client_id() -> None:
    resp = TestClient(create_app(_settings(), idp_client=StubIdp(ADMIN))).get("/", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith("http://idp.test/login?")
    assert "client_id=rk_Kz3sH8dYc5JfW1qN" in location
    assert "kaze-portal" not in location  # the internal id never travels


def test_home_greets_the_person() -> None:
    html = _signed_in(MEMBER, "martin@kazelabs.example").get("/").text
    assert "Martin" in html and "Anuncios" in html


def test_a_member_creates_projects() -> None:
    client = _signed_in(MEMBER)
    resp = client.post("/proyectos", data={"nombre": "Demo de passkeys"}, follow_redirects=True)
    assert resp.status_code == 200
    assert "Demo de passkeys" in resp.text


def test_a_viewer_reads_projects_but_cannot_change_them() -> None:
    """U-5: a page viewer cannot change: no form, and the write path refuses."""
    client = _signed_in(VIEWER, "valen@kazelabs.example")
    page = client.get("/proyectos")
    assert page.status_code == 200
    assert "Solo lectura" in page.text
    assert 'action="/proyectos"' not in page.text
    refused = client.post("/proyectos", data={"nombre": "x"})
    assert refused.status_code == 403
    assert "projects:write" in refused.text


@pytest.mark.parametrize("permissions", [MEMBER, VIEWER])
def test_only_an_admin_reaches_settings(permissions) -> None:
    """U-5: a page only admin can reach, on read and on write."""
    client = _signed_in(permissions)
    assert client.get("/configuracion").status_code == 403
    assert client.post("/configuracion", data={"nombre": "x", "horas": 2}).status_code == 403


def test_an_admin_changes_settings() -> None:
    client = _signed_in(ADMIN)
    assert client.get("/configuracion").status_code == 200
    saved = client.post("/configuracion", data={"nombre": "Kaze HQ", "horas": 12}, follow_redirects=True)
    assert "Guardado" in saved.text and "Kaze HQ" in saved.text


def test_no_portal_access_is_refused_everywhere() -> None:
    client = _signed_in([])
    assert client.get("/").status_code == 403


def test_an_expired_session_goes_back_to_login() -> None:
    client = _signed_in(ADMIN)
    client.post("/logout", follow_redirects=False)
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302 and "/login?" in resp.headers["location"]


def test_brand_files_are_served() -> None:
    client = TestClient(create_app(_settings(), idp_client=StubIdp(ADMIN)))
    for path in ("/static/kaze.css", "/static/brand/kaze-mark.svg", "/static/fonts/manrope-latin-700-normal.woff2"):
        assert client.get(path).status_code == 200, path


def test_cloud_refuses_local_urls() -> None:
    with pytest.raises(ValidationError):
        Settings(deployment="cloud")


def test_login_url_shape() -> None:
    assert login_url(_settings()) == (
        "http://idp.test/login?client_id=rk_Kz3sH8dYc5JfW1qN&redirect_uri=http%3A%2F%2Fkaze.test%2Fcallback"
    )

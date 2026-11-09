"""Administrator authentication and security behavior tests."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.router import create_initial_administrator
from app.auth.security import hash_password
from app.config import Settings
from app.database.base import Base
from app.database.models import Administrator, AdministratorSession
from app.main import create_app

ORIGIN = "http://testserver"


def build_test_app(tmp_path, *, max_attempts: int = 5):
    """Create an isolated app with a temporary SQLite database."""
    database_path = tmp_path / "auth.sqlite"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        session_security_key="test-session-security-key-with-32-bytes-minimum",
        session_cookie_name="srm_session",
        session_cookie_secure=False,
        auth_rate_limit_max_attempts=max_attempts,
        auth_rate_limit_window_seconds=60,
        auth_rate_limit_retention_seconds=86_400,
    )
    return create_app(settings)


def provision_admin(
    app, *, username: str = "admin", password: str = "secure-test-password"
):
    """Create a test administrator after application startup."""
    Base.metadata.create_all(app.state.engine)
    factory = app.state.session_factory
    with factory.begin() as session:
        create_initial_administrator(session, username, password)


def login(
    client: TestClient, username: str = "admin", password: str = "secure-test-password"
):
    """Perform a same-origin login request."""
    return client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers={"Origin": ORIGIN},
    )


def test_health_endpoints_and_security_headers(tmp_path) -> None:
    """Health checks and baseline hardening headers are available."""
    app = build_test_app(tmp_path)
    with TestClient(app) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")

    assert live.status_code == 200
    assert ready.status_code == 200
    assert live.headers["x-content-type-options"] == "nosniff"
    assert live.headers["x-frame-options"] == "DENY"
    assert live.headers["content-security-policy"].startswith("default-src 'self'")
    assert "frame-ancestors 'none'" in live.headers["content-security-policy"]
    assert not live.headers.get("strict-transport-security")


def test_browser_dashboard_and_assets_are_served_with_security_headers(tmp_path) -> None:
    """The browser UI and its static assets are available with a restrictive CSP."""
    app = build_test_app(tmp_path)
    with TestClient(app) as client:
        page = client.get("/")
        stylesheet = client.get("/static/app.css")
        script = client.get("/static/app.js")

    assert page.status_code == stylesheet.status_code == script.status_code == 200
    assert "Sign in to view monitoring activity" in page.text
    assert "text/css" in stylesheet.headers["content-type"]
    assert "text/javascript" in script.headers["content-type"]
    assert "script-src 'self'" in page.headers["content-security-policy"]


def test_secure_login_session_csrf_logout_and_revocation(tmp_path) -> None:
    """Login issues a protected cookie and logout revokes the stored session."""
    app = build_test_app(tmp_path)
    with TestClient(app) as client:
        provision_admin(app)
        response = login(client)

        assert response.status_code == 200
        assert "session" not in response.json()
        csrf_token = response.json()["csrf_token"]
        cookie = response.cookies.get("srm_session")
        assert cookie
        assert "httponly" in response.headers["set-cookie"].lower()
        assert "samesite=lax" in response.headers["set-cookie"].lower()
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/api/auth/me").json() == {
            "username": "admin",
            "role": "ADMIN",
        }
        csrf_refresh = client.post("/api/auth/csrf", headers={"Origin": ORIGIN})
        assert csrf_refresh.status_code == 200
        csrf_token = csrf_refresh.json()["csrf_token"]
        assert client.get("/api/admin/ping").json() == {"status": "ok"}

        bad_csrf = client.post(
            "/api/auth/logout",
            headers={"Origin": ORIGIN, "X-CSRF-Token": "invalid"},
        )
        assert bad_csrf.status_code == 403

        logout_response = client.post(
            "/api/auth/logout",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf_token},
        )
        assert logout_response.status_code == 204
        assert client.get("/api/auth/me").status_code == 401
        assert client.get("/api/admin/ping").status_code == 401


def test_authentication_requires_same_origin_for_login_and_logout(tmp_path) -> None:
    """Cross-origin or origin-less authentication writes are rejected."""
    app = build_test_app(tmp_path)
    with TestClient(app) as client:
        provision_admin(app)
        missing_origin = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "secure-test-password"},
        )
        wrong_origin = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "secure-test-password"},
            headers={"Origin": "https://attacker.invalid"},
        )
        successful_login = login(client)
        wrong_origin_csrf = client.post(
            "/api/auth/csrf",
            headers={"Origin": "https://attacker.invalid"},
        )
        wrong_origin_logout = client.post(
            "/api/auth/logout",
            headers={
                "Origin": "https://attacker.invalid",
                "X-CSRF-Token": successful_login.json()["csrf_token"],
            },
        )

    assert missing_origin.status_code == 403
    assert wrong_origin.status_code == 403
    assert successful_login.status_code == 200
    assert wrong_origin_csrf.status_code == 403
    assert wrong_origin_logout.status_code == 403


def test_role_authorization_denies_staff_from_admin_route(tmp_path) -> None:
    """Authenticated staff do not gain administrator-only access."""
    app = build_test_app(tmp_path)
    with TestClient(app) as client:
        Base.metadata.create_all(app.state.engine)
        factory = app.state.session_factory
        with factory.begin() as session:
            session.add(
                Administrator(
                    username="staff",
                    password_hash=hash_password("secure-staff-password"),
                    role="STAFF",
                    enabled=True,
                )
            )
        response = login(
            client,
            username="staff",
            password="secure-staff-password",
        )

        assert response.status_code == 200
        assert client.get("/api/auth/me").json()["role"] == "STAFF"
        assert client.get("/api/admin/ping").status_code == 403


def test_failed_login_is_generic_and_rate_limited_in_database(tmp_path) -> None:
    """Login failures are non-enumerable and block after the configured limit."""
    app = build_test_app(tmp_path, max_attempts=2)
    with TestClient(app) as client:
        provision_admin(app)
        first = login(client, password="wrong-password")
        second = login(client, username="unknown", password="wrong-password")
        third = login(client, password="wrong-password")
        blocked = login(client, password="secure-test-password")

    assert first.status_code == second.status_code == third.status_code == 401
    assert first.json() == second.json()
    assert blocked.status_code == 429
    assert blocked.headers.get("retry-after")


def test_invalid_stored_password_hash_fails_closed(tmp_path) -> None:
    """Corrupt hashes are treated as invalid credentials, not server errors."""
    app = build_test_app(tmp_path)
    with TestClient(app) as client:
        provision_admin(app)
        factory = app.state.session_factory
        with factory.begin() as session:
            administrator = session.scalar(select(Administrator))
            assert administrator is not None
            administrator.password_hash = "invalid-stored-hash"

        response = login(client)

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password"


def test_successful_login_clears_previous_rate_limit_failures(tmp_path) -> None:
    """A successful login resets the per-client failure bucket."""
    app = build_test_app(tmp_path, max_attempts=2)
    with TestClient(app) as client:
        provision_admin(app)
        assert login(client, password="wrong-password").status_code == 401
        success = login(client)
        assert success.status_code == 200
        client.post(
            "/api/auth/logout",
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": success.json()["csrf_token"],
            },
        )
        assert login(client, password="wrong-password").status_code == 401
        assert login(client).status_code == 200


def test_expired_session_is_rejected(tmp_path) -> None:
    """Expired server-side sessions cannot authenticate even if cookie remains."""
    app = build_test_app(tmp_path)
    with TestClient(app) as client:
        provision_admin(app)
        success = login(client)
        assert success.status_code == 200
        factory = app.state.session_factory
        with factory.begin() as session:
            stored_session = session.scalar(select(AdministratorSession))
            assert stored_session is not None
            stored_session.expires_at = datetime.now(UTC) - timedelta(minutes=1)

        assert client.get("/api/auth/me").status_code == 401


def test_initial_admin_provisioning_refuses_existing_admin(tmp_path) -> None:
    """The bootstrap helper cannot replace an existing administrator."""
    app = build_test_app(tmp_path)
    with TestClient(app):
        provision_admin(app)
        factory = app.state.session_factory
        with factory() as session, pytest.raises(ValueError, match="already exists"):
            create_initial_administrator(
                session,
                "other-admin",
                "another-secure-password",
            )


def test_settings_reject_weak_key_and_insecure_cookie_name() -> None:
    """Security-sensitive settings fail closed during startup validation."""
    with pytest.raises(ValueError, match="32 bytes"):
        Settings(
            database_url="sqlite://",
            session_security_key="short",
        )
    with pytest.raises(ValueError, match="__Host-"):
        Settings(
            database_url="sqlite://",
            session_security_key="test-session-security-key-with-32-bytes-minimum",
            session_cookie_name="srm_session",
        )
    with pytest.raises(ValueError, match="HTTPS"):
        Settings(
            database_url="sqlite://",
            session_security_key="test-session-security-key-with-32-bytes-minimum",
            public_origin="http://example.test",
        )

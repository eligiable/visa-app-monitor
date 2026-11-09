"""Dashboard API tests for the admin operational views."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.auth.router import create_initial_administrator
from app.auth.security import hash_password
from app.config import Settings
from app.database.base import Base
from app.database.models import (
    AlertEvent,
    Administrator,
    ApplicantOrigin,
    AvailabilityHistory,
    CheckResult,
    City,
    Country,
    MonitoringJob,
    NotificationOutboxItem,
    Provider,
    ProviderPermissionRecord,
    SystemError,
    VisaCategory,
    VisaCentre,
)
from app.main import create_app

ORIGIN = "http://testserver"


def build_test_app(tmp_path):
    """Create an isolated app with a temporary SQLite database."""
    database_path = tmp_path / "dashboard.sqlite"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        session_security_key="test-session-security-key-with-32-bytes-minimum",
        session_cookie_name="srm_session",
        session_cookie_secure=False,
    )
    return create_app(settings)


def provision_admin(app, *, username: str = "admin", password: str = "secure-test-password"):
    """Create a test administrator after application startup."""
    Base.metadata.create_all(app.state.engine)
    with app.state.session_factory.begin() as session:
        create_initial_administrator(session, username, password)


def login(client: TestClient, username: str = "admin", password: str = "secure-test-password"):
    """Perform a same-origin login request."""
    return client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers={"Origin": ORIGIN},
    )


def create_job_record(app) -> MonitoringJob:
    """Create a representative monitoring job and related dashboard rows."""
    with app.state.session_factory.begin() as session:
        country = Country(country_code="DE", name="Germany")
        origin = ApplicantOrigin(code="PK", name="Pakistan")
        provider = Provider(
            provider_code="dashboard_provider",
            name="Dashboard Provider",
            access_mode="AUTOMATED",
            health_status="HEALTHY",
        )
        category = VisaCategory(name="Tourist", category_code="tourist")
        session.add_all([country, origin, provider, category])
        session.flush()

        city = City(country_id=country.id, name="Berlin")
        session.add(city)
        session.flush()

        centre = VisaCentre(
            city_id=city.id,
            provider_id=provider.id,
            name="Berlin Centre",
            official_url="https://provider.example/appointments",
            access_mode="AUTOMATED",
            enabled=True,
        )
        session.add(centre)
        session.flush()

        permission = ProviderPermissionRecord(
            provider_id=provider.id,
            official_source_url=centre.official_url,
            terms_url="https://provider.example/terms",
            robots_txt_url="https://provider.example/robots.txt",
            api_documentation_url="https://provider.example/docs",
            permitted_access_method="AUTOMATED",
            request_limits={"max_requests_per_day": 5},
            verified_at=datetime.now(UTC),
            review_due_at=datetime.now(UTC),
            responsible_administrator_id=1,
            approval_status="APPROVED",
            evidence_reference="docs/internal-review-01",
        )
        session.add(permission)
        session.flush()

        job = MonitoringJob(
            origin_id=origin.id,
            destination_country_id=country.id,
            city_id=city.id,
            visa_centre_id=centre.id,
            category_id=category.id,
            provider_id=provider.id,
            appointment_type="Short Stay",
            official_source_url=centre.official_url,
            polling_interval=300,
            jitter_seconds=30,
            enabled=True,
            access_mode="AUTOMATED",
            execution_status="SUCCEEDED",
            availability_status="UNAVAILABLE",
            next_check_at=datetime.now(UTC),
        )
        session.add(job)
        session.flush()

        result = CheckResult(
            job_id=job.id,
            checked_at=datetime.now(UTC),
            execution_status="SUCCEEDED",
            availability_status="UNAVAILABLE",
            source_url=centre.official_url,
            response_code=200,
            duration_ms=100,
        )
        session.add(result)
        session.flush()

        history = AvailabilityHistory(
            job_id=job.id,
            previous_status=None,
            new_status="UNAVAILABLE",
            detected_at=datetime.now(UTC),
            source_check_result_id=result.id,
            manual_verification_id=None,
        )
        session.add(history)
        session.flush()

        alert = AlertEvent(
            job_id=job.id,
            availability_history_id=history.id,
            availability_status="AVAILABLE",
            verification_source="AUTOMATED",
            created_at=datetime.now(UTC),
            deduplication_key="dashboard-alert-1",
        )
        session.add(alert)
        session.flush()

        session.add(
            NotificationOutboxItem(
                alert_event_id=alert.id,
                channel="EMAIL",
                recipient_reference="ops@example.com",
                created_at=datetime.now(UTC),
                next_attempt_at=datetime.now(UTC),
                state="PENDING",
            )
        )
        session.add(
            SystemError(
                component="scheduler",
                provider_id=provider.id,
                severity="WARNING",
                message="Provider health degraded during polling",
                occurred_at=datetime.now(UTC),
            )
        )
        return job


def test_dashboard_overview_and_admin_views(tmp_path) -> None:
    """The admin dashboard exposes monitoring, alert, and system-state views."""
    app = build_test_app(tmp_path)
    with TestClient(app) as client:
        provision_admin(app)
        job = create_job_record(app)

        login_response = login(client)
        assert login_response.status_code == 200

        overview = client.get("/api/admin/dashboard/overview")
        assert overview.status_code == 200
        assert overview.json()["active_jobs"] >= 1
        assert overview.json()["alert_count"] >= 1
        assert overview.json()["pending_notifications"] >= 1

        jobs = client.get("/api/admin/jobs")
        assert jobs.status_code == 200
        assert any(item["id"] == job.id for item in jobs.json())

        history = client.get(f"/api/admin/jobs/{job.id}/history")
        assert history.status_code == 200
        assert len(history.json()) >= 1

        providers = client.get("/api/admin/providers")
        assert providers.status_code == 200
        assert providers.json()[0]["provider_code"] == "dashboard_provider"

        alerts = client.get("/api/admin/alerts")
        assert alerts.status_code == 200
        assert len(alerts.json()) >= 1

        notifications = client.get("/api/admin/notifications")
        assert notifications.status_code == 200
        assert len(notifications.json()) >= 1

        errors = client.get("/api/admin/system-errors")
        assert errors.status_code == 200
        assert len(errors.json()) >= 1

        manual = client.post(
            f"/api/admin/jobs/{job.id}/manual-verification",
            json={
                "recorded_status": "AVAILABLE",
                "official_source_url": "https://provider.example/manual-check",
                "manual_alert_enabled": False,
            },
        )
        assert manual.status_code == 200
        assert manual.json()["new_status"] == "AVAILABLE"

        history_after = client.get(f"/api/admin/jobs/{job.id}/history")
        assert history_after.status_code == 200
        assert any(item["new_status"] == "AVAILABLE" for item in history_after.json())


def test_staff_can_sign_in_and_use_dashboard_and_manual_verification(tmp_path) -> None:
    """Provisioned staff users can use the dashboard and record manual checks."""
    app = build_test_app(tmp_path)
    with TestClient(app) as client:
        Base.metadata.create_all(app.state.engine)
        with app.state.session_factory.begin() as session:
            session.add(
                Administrator(
                    username="staff",
                    password_hash=hash_password("secure-staff-password"),
                    role="STAFF",
                    enabled=True,
                )
            )
        job = create_job_record(app)

        response = login(
            client,
            username="staff",
            password="secure-staff-password",
        )
        assert response.status_code == 200
        csrf_token = response.json()["csrf_token"]
        assert client.get("/api/admin/dashboard/overview").status_code == 200

        manual = client.post(
            f"/api/admin/jobs/{job.id}/manual-verification",
            json={
                "recorded_status": "AVAILABLE",
                "official_source_url": "https://provider.example/manual-check",
            },
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf_token},
        )

        assert manual.status_code == 200
        assert manual.json()["new_status"] == "AVAILABLE"

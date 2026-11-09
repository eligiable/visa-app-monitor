"""Dashboard API tests for the admin operational views."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.auth.router import create_initial_administrator
from app.auth.security import hash_password
from app.config import Settings
from app.database.base import Base
from app.database.models import (
    AlertEvent,
    Administrator,
    ApplicantOrigin,
    AuditEvent,
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
        session_cookie_name="eligiable_session",
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


def test_admin_can_create_update_and_duplicate_check_monitoring_jobs(tmp_path) -> None:
    """Job management validates references and cannot weaken manual-only access."""
    app = build_test_app(tmp_path)
    with TestClient(app) as client:
        provision_admin(app)
        create_job_record(app)
        with app.state.session_factory.begin() as session:
            origin = session.query(ApplicantOrigin).filter_by(code="PK").one()
            country = session.query(Country).filter_by(country_code="DE").one()
            provider = Provider(
                provider_code="manual_provider",
                name="Manual provider",
                access_mode="MANUAL_CHECK_REQUIRED",
                health_status="UNKNOWN",
            )
            session.add(provider)
            session.flush()
            provider_id = provider.id
            origin_id = origin.id
            country_id = country.id

        csrf_token = login(client).json()["csrf_token"]
        options = client.get("/api/admin/job-options")
        assert options.status_code == 200
        assert any(
            item["provider_code"] == "manual_provider"
            for item in options.json()["providers"]
        )

        payload = {
            "origin_id": origin_id,
            "destination_country_id": country_id,
            "provider_id": provider_id,
            "city_name": "Toronto",
            "visa_centre_name": "Toronto Centre",
            "category_name": "Business",
            "category_code": "business",
            "appointment_type": "Short Stay",
            "official_source_url": "https://manual.example/appointments",
            "polling_interval": 3600,
            "jitter_seconds": 30,
            "enabled": False,
        }
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf_token}
        created = client.post("/api/admin/jobs", json=payload, headers=headers)
        assert created.status_code == 201
        created_job = created.json()
        assert created_job["access_mode"] == "MANUAL_CHECK_REQUIRED"
        assert created_job["enabled"] is False
        assert created_job["city_name"] == "Toronto"
        assert created_job["visa_centre_name"] == "Toronto Centre"

        updated = client.patch(
            f"/api/admin/jobs/{created_job['id']}",
            json={"enabled": True, "polling_interval": 7200},
            headers=headers,
        )
        assert updated.status_code == 200
        assert updated.json()["enabled"] is True
        assert updated.json()["access_mode"] == "MANUAL_CHECK_REQUIRED"
        assert updated.json()["polling_interval"] == 7200

        duplicate = client.post("/api/admin/jobs", json=payload, headers=headers)
        invalid_source = client.patch(
            f"/api/admin/jobs/{created_job['id']}",
            json={"official_source_url": "http://manual.example/appointments"},
            headers=headers,
        )
        null_update = client.patch(
            f"/api/admin/jobs/{created_job['id']}",
            json={"enabled": None},
            headers=headers,
        )

    assert duplicate.status_code == 409, duplicate.text
    assert invalid_source.status_code == 422
    assert null_update.status_code == 422


def test_staff_cannot_create_or_update_monitoring_jobs(tmp_path) -> None:
    """Staff may view and verify jobs but cannot change job configuration."""
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
        csrf_token = login(
            client,
            username="staff",
            password="secure-staff-password",
        ).json()["csrf_token"]
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf_token}

        denied_create = client.post(
            "/api/admin/jobs",
            json={
                "origin_id": 1,
                "destination_country_id": 1,
                "provider_id": 1,
                "city_name": "Toronto",
                "visa_centre_name": "Toronto Centre",
                "category_name": "Business",
                "category_code": "business",
                "appointment_type": "Short Stay",
                "official_source_url": "https://manual.example/appointments",
                "polling_interval": 3600,
            },
            headers=headers,
        )
        denied_update = client.patch(
            f"/api/admin/jobs/{job.id}",
            json={"enabled": False},
            headers=headers,
        )

    assert denied_create.status_code == 403
    assert denied_update.status_code == 403


def test_admin_can_manage_provider_permission_reviews_without_changing_provider_mode(
    tmp_path,
) -> None:
    """Provider reviews are editable while seeded access modes stay untouched."""
    app = build_test_app(tmp_path)
    with TestClient(app) as client:
        provision_admin(app)
        with app.state.session_factory.begin() as session:
            provider = Provider(
                provider_code="review_provider",
                name="Review Provider",
                access_mode="MANUAL_CHECK_REQUIRED",
                health_status="UNKNOWN",
            )
            session.add(provider)
            session.flush()
            provider_id = provider.id

        csrf_token = login(client).json()["csrf_token"]
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf_token}
        payload = {
            "official_source_url": "https://provider.example/appointments",
            "terms_url": "https://provider.example/terms",
            "robots_txt_url": "https://provider.example/robots.txt",
            "api_documentation_url": "https://provider.example/docs",
            "permitted_access_method": "Official documented API",
            "request_limits": {"requests_per_day": 10},
            "evidence_reference": "compliance/review-2026-01",
        }

        created = client.post(
            f"/api/admin/providers/{provider_id}/permissions",
            json=payload,
            headers=headers,
        )
        assert created.status_code == 201, created.text
        permission_id = created.json()["id"]
        assert created.json()["approval_status"] == "PENDING"

        updated_payload = {**payload, "permitted_access_method": "Official API v2"}
        updated = client.patch(
            f"/api/admin/provider-permissions/{permission_id}",
            json=updated_payload,
            headers=headers,
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["permitted_access_method"] == "Official API v2"
        assert updated.json()["approval_status"] == "PENDING"

        approved = client.post(
            f"/api/admin/provider-permissions/{permission_id}/approve",
            json={"review_due_at": (datetime.now(UTC) + timedelta(days=180)).isoformat()},
            headers=headers,
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["approval_status"] == "APPROVED"
        assert approved.json()["responsible_administrator_id"] == 1

        provider_view = client.get("/api/admin/providers").json()[0]
        assert provider_view["access_mode"] == "MANUAL_CHECK_REQUIRED"
        assert provider_view["permission_status"] == "APPROVED"
        assert provider_view["permission"]["id"] == permission_id
        assert provider_view["permission"]["request_limits"] == {"requests_per_day": 10}

        edited_after_approval = client.patch(
            f"/api/admin/provider-permissions/{permission_id}",
            json={**updated_payload, "evidence_reference": "compliance/review-2026-02"},
            headers=headers,
        )
        assert edited_after_approval.status_code == 200
        assert edited_after_approval.json()["approval_status"] == "PENDING"
        assert edited_after_approval.json()["verified_at"] is None

        reapproved = client.post(
            f"/api/admin/provider-permissions/{permission_id}/approve",
            json={"review_due_at": (datetime.now(UTC) + timedelta(days=180)).isoformat()},
            headers=headers,
        )
        assert reapproved.status_code == 200, reapproved.text
        assert reapproved.json()["approval_status"] == "APPROVED"

        revoked = client.post(
            f"/api/admin/provider-permissions/{permission_id}/revoke",
            headers=headers,
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["approval_status"] == "REVOKED"
        assert revoked.json()["revoked_at"] is not None

        with app.state.session_factory() as session:
            stored_provider = session.get(Provider, provider_id)
            actions = {
                event.action
                for event in session.query(AuditEvent).all()
            }
        assert stored_provider.access_mode == "MANUAL_CHECK_REQUIRED"
        assert {
            "provider_permission.created",
            "provider_permission.updated",
            "provider_permission.approved",
            "provider_permission.revoked",
        } <= actions


def test_staff_cannot_manage_provider_permission_reviews(tmp_path) -> None:
    """Only administrators may change provider compliance configuration."""
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
            provider = Provider(
                provider_code="staff_provider",
                name="Staff Provider",
                access_mode="MANUAL_CHECK_REQUIRED",
                health_status="UNKNOWN",
            )
            session.add(provider)
            session.flush()
            provider_id = provider.id

        csrf_token = login(
            client,
            username="staff",
            password="secure-staff-password",
        ).json()["csrf_token"]
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf_token}
        denied = client.post(
            f"/api/admin/providers/{provider_id}/permissions",
            json={
                "official_source_url": "https://provider.example/appointments",
                "permitted_access_method": "Manual verification",
            },
            headers=headers,
        )

    assert denied.status_code == 403

"""Database constraint and schema behavior tests."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.models import (
    Administrator,
    ApplicantOrigin,
    CheckResult,
    City,
    Country,
    MonitoringJob,
    Provider,
    ProviderPermissionRecord,
    VisaCategory,
    VisaCentre,
)


def create_valid_job(session: Session) -> MonitoringJob:
    """Insert a complete valid set of job references for constraint tests."""
    country = Country(country_code="DE", name="Germany")
    origin = ApplicantOrigin(code="PK", name="Pakistan")
    provider = Provider(
        provider_code="test_provider",
        name="Test Provider",
        access_mode="MANUAL_CHECK_REQUIRED",
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
        official_url="https://provider.invalid/appointments",
        access_mode="MANUAL_CHECK_REQUIRED",
    )
    session.add(centre)
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
        polling_interval=3600,
    )
    session.add(job)
    session.flush()
    return job


def test_schema_creates_all_entities(database_session: Session) -> None:
    """The metadata includes the records required by the approved design."""
    expected_tables = {
        "countries",
        "applicant_origins",
        "cities",
        "visa_centres",
        "visa_categories",
        "providers",
        "provider_permission_records",
        "administrators",
        "administrator_sessions",
        "monitoring_jobs",
        "check_results",
        "availability_history",
        "manual_verifications",
        "audit_events",
        "alert_events",
        "notification_outbox_items",
        "notification_integrations",
        "notification_delivery_attempts",
        "system_errors",
    }

    assert expected_tables <= set(
        inspect(database_session.connection()).get_table_names()
    )


def test_job_cannot_mismatch_city_and_destination(database_session: Session) -> None:
    """Composite foreign keys keep job dimensions internally consistent."""
    job = create_valid_job(database_session)
    database_session.flush()
    database_session.add(Country(country_code="US", name="United States"))
    database_session.flush()

    invalid_job = MonitoringJob(
        origin_id=job.origin_id,
        destination_country_id=database_session.scalar(
            select(Country.id).where(Country.country_code == "US"),
        ),
        city_id=job.city_id,
        visa_centre_id=job.visa_centre_id,
        category_id=job.category_id,
        provider_id=job.provider_id,
        appointment_type="Long Stay",
        official_source_url=job.official_source_url,
        polling_interval=3600,
    )
    database_session.add(invalid_job)

    with pytest.raises(IntegrityError):
        database_session.flush()


def test_failed_check_cannot_claim_availability(database_session: Session) -> None:
    """Errors and restricted checks cannot store appointment availability."""
    job = create_valid_job(database_session)
    database_session.add(
        CheckResult(
            job_id=job.id,
            checked_at=datetime.now(UTC),
            execution_status="SOURCE_ERROR",
            availability_status="AVAILABLE",
            source_url=job.official_source_url,
        )
    )

    with pytest.raises(IntegrityError):
        database_session.flush()


def test_job_lock_owner_and_expiry_must_be_paired(database_session: Session) -> None:
    """A partial job lease cannot be persisted."""
    job = create_valid_job(database_session)
    job.lock_owner = "worker-1"

    with pytest.raises(IntegrityError):
        database_session.flush()


def test_approved_permission_requires_review_deadline(
    database_session: Session,
) -> None:
    """Approval cannot be recorded without a reviewer and review deadline."""
    administrator = Administrator(
        username="admin",
        password_hash="test-hash",
        role="ADMIN",
    )
    provider = Provider(
        provider_code="test_provider",
        name="Test Provider",
    )
    database_session.add_all([administrator, provider])
    database_session.flush()
    database_session.add(
        ProviderPermissionRecord(
            provider_id=provider.id,
            official_source_url="https://provider.invalid",
            permitted_access_method="Official documented interface",
            verified_at=datetime.now(UTC),
            responsible_administrator_id=administrator.id,
            approval_status="APPROVED",
        )
    )

    with pytest.raises(IntegrityError):
        database_session.flush()

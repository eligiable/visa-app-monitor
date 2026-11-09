"""Availability detection and alerting tests for Phase 6."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from app.database.models import (
    Administrator,
    AlertEvent,
    CheckResult,
    Country,
    ApplicantOrigin,
    MonitoringJob,
    NotificationOutboxItem,
    Provider,
    VisaCategory,
    VisaCentre,
    City,
)
from app.monitoring.availability import AvailabilityDetectionService

NOW = datetime(2026, 11, 9, 9, 0, tzinfo=UTC)
SOURCE_URL = "https://provider.example/appointments"


def _create_job(
    session: Session,
    *,
    initial_policy: bool = False,
    country_code: str | None = None,
    origin_code: str | None = None,
    provider_code: str | None = None,
    category_code: str | None = None,
) -> MonitoringJob:
    country_code = country_code or uuid4().hex[:2].upper()
    origin_code = origin_code or uuid4().hex[:2].upper()
    provider_code = provider_code or f"provider_{uuid4().hex[:6]}"
    category_code = category_code or f"cat_{uuid4().hex[:6]}"

    country = Country(country_code=country_code, name="Germany")
    origin = ApplicantOrigin(code=origin_code, name="Pakistan")
    provider = Provider(provider_code=provider_code, name="Test Provider", access_mode="AUTOMATED")
    category = VisaCategory(name="Tourist", category_code=category_code)
    session.add_all([country, origin, provider, category])
    session.flush()

    city = City(country_id=country.id, name="Berlin")
    session.add(city)
    session.flush()

    centre = VisaCentre(
        city_id=city.id,
        provider_id=provider.id,
        name="Berlin Centre",
        official_url=SOURCE_URL,
        access_mode="AUTOMATED",
        enabled=True,
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
        official_source_url=SOURCE_URL,
        polling_interval=300,
        jitter_seconds=30,
        enabled=True,
        access_mode="AUTOMATED",
        execution_status="SUCCEEDED",
        availability_status=None,
        initial_available_alert_policy=initial_policy,
        next_check_at=NOW,
    )
    session.add(job)
    session.flush()
    return job


def _create_check_result(session: Session, job: MonitoringJob, *, status: str) -> CheckResult:
    result = CheckResult(
        job_id=job.id,
        checked_at=NOW,
        execution_status="SUCCEEDED",
        availability_status=status,
        source_url=SOURCE_URL,
        response_code=200,
        duration_ms=100,
        error_message=None,
    )
    session.add(result)
    session.flush()
    return result


def test_first_available_result_creates_no_alert_by_default(database_session: Session) -> None:
    job = _create_job(database_session, initial_policy=False)
    result = _create_check_result(database_session, job, status="AVAILABLE")

    service = AvailabilityDetectionService()
    history = service.process_check_result(database_session, job.id, result.id, now=NOW)

    assert history is not None
    assert job.availability_status == "AVAILABLE"
    assert database_session.query(AlertEvent).count() == 0
    assert database_session.query(NotificationOutboxItem).count() == 0


def test_available_transition_creates_alert_and_history(database_session: Session) -> None:
    job = _create_job(database_session, initial_policy=True)
    job.availability_status = "UNAVAILABLE"
    database_session.flush()
    result = _create_check_result(database_session, job, status="AVAILABLE")

    service = AvailabilityDetectionService()
    history = service.process_check_result(database_session, job.id, result.id, now=NOW)

    assert history is not None
    assert history.previous_status == "UNAVAILABLE"
    assert history.new_status == "AVAILABLE"
    assert database_session.query(AlertEvent).count() == 1
    assert database_session.query(AlertEvent).one().verification_source == "AUTOMATED"


def test_available_transition_queues_configured_recipients(database_session: Session) -> None:
    """An alert passing transition policy creates outbox entries for recipients."""
    job = _create_job(database_session, initial_policy=True)
    job.availability_status = "UNAVAILABLE"
    database_session.flush()
    result = _create_check_result(database_session, job, status="AVAILABLE")

    history = AvailabilityDetectionService().process_check_result(
        database_session,
        job.id,
        result.id,
        now=NOW,
        notification_recipients={"TELEGRAM": ["-10012345"], "EMAIL": []},
    )

    assert history is not None
    queued = database_session.query(NotificationOutboxItem).all()
    assert [(item.channel, item.recipient_reference) for item in queued] == [
        ("TELEGRAM", "-10012345"),
    ]


def test_unavailable_result_does_not_create_alert(database_session: Session) -> None:
    job = _create_job(database_session, initial_policy=False)
    result = _create_check_result(database_session, job, status="UNAVAILABLE")

    service = AvailabilityDetectionService()
    history = service.process_check_result(database_session, job.id, result.id, now=NOW)

    assert history is not None
    assert history.new_status == "UNAVAILABLE"
    assert database_session.query(AlertEvent).count() == 0


def test_cooldown_prevents_duplicate_available_alerts(database_session: Session) -> None:
    job = _create_job(database_session, initial_policy=True)
    job.availability_status = "UNAVAILABLE"
    database_session.flush()
    first_result = _create_check_result(database_session, job, status="AVAILABLE")

    service = AvailabilityDetectionService(cooldown_seconds=3600)
    service.process_check_result(database_session, job.id, first_result.id, now=NOW)

    job.availability_status = "UNAVAILABLE"
    database_session.flush()
    second_result = _create_check_result(database_session, job, status="AVAILABLE")
    second = service.process_check_result(database_session, job.id, second_result.id, now=NOW + timedelta(minutes=5))

    assert second is not None
    assert database_session.query(AlertEvent).count() == 1


def test_manual_verification_available_can_create_manual_alert(database_session: Session) -> None:
    admin = Administrator(
        username="manual-operator",
        password_hash="hash",
        role="STAFF",
        enabled=True,
    )
    database_session.add(admin)
    database_session.flush()

    job = _create_job(database_session, initial_policy=False)
    service = AvailabilityDetectionService()

    history = service.record_manual_verification(
        database_session,
        job_id=job.id,
        operator_administrator_id=admin.id,
        recorded_status="AVAILABLE",
        official_source_url=SOURCE_URL,
        verified_at=NOW,
        manual_alert_enabled=True,
    )

    assert history is not None
    assert database_session.query(AlertEvent).filter(AlertEvent.verification_source == "MANUAL").count() == 1

    job2 = _create_job(
        database_session,
        initial_policy=True,
        origin_code="AE",
        provider_code="manual_alert_provider",
        category_code="business",
    )
    job2.availability_status = "UNAVAILABLE"
    database_session.flush()
    history2 = service.record_manual_verification(
        database_session,
        job_id=job2.id,
        operator_administrator_id=admin.id,
        recorded_status="AVAILABLE",
        official_source_url=SOURCE_URL,
        verified_at=NOW + timedelta(minutes=10),
        manual_alert_enabled=True,
    )

    assert history2 is not None
    assert database_session.query(AlertEvent).filter(AlertEvent.verification_source == "MANUAL").count() == 2

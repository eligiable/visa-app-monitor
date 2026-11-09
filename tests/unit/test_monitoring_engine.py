"""Phase 5 monitoring-engine tests."""

from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import (
    Administrator,
    ApplicantOrigin,
    City,
    Country,
    MonitoringJob,
    NotificationIntegration,
    NotificationOutboxItem,
    Provider,
    ProviderPermissionRecord,
    VisaCategory,
    VisaCentre,
)
from app.monitoring.engine import CircuitBreaker, JobExecutionPolicy, MonitoringEngine
from app.notifications.configuration import encrypt_configuration
from app.providers.base import BaseProvider
from app.providers.models import (
    AvailabilityStatus,
    CheckExecutionStatus,
    ProviderAccessMode,
    ProviderCheckContext,
    ProviderCheckResult,
    ProviderHealthResult,
    ProviderHealthStatus,
)
from app.providers.registry import ProviderRegistry

NOW = datetime(2026, 11, 9, 8, 0, tzinfo=UTC)
SOURCE_URL = "https://provider.example/appointments"
METHOD = "documented_test_interface_v1"


class _AuthorizedStubAdapter(BaseProvider):
    provider_code = "monitoring_test_provider"
    permitted_access_method = METHOD
    default_access_mode = ProviderAccessMode.AUTOMATED

    async def check_availability(self, context: ProviderCheckContext) -> ProviderCheckResult:
        return ProviderCheckResult(
            provider_code=self.provider_code,
            access_mode=ProviderAccessMode.AUTOMATED,
            execution_status=CheckExecutionStatus.SUCCEEDED,
            availability_status=AvailabilityStatus.AVAILABLE,
            verification_source="AUTHORIZED_AUTOMATION",
            permission_record_id=context.permission_record_id,
            checked_at=context.checked_at,
            source_url=context.source_url,
        )

    async def health_check(self) -> ProviderHealthResult:
        return ProviderHealthResult(
            provider_code=self.provider_code,
            status=ProviderHealthStatus.HEALTHY,
            checked_at=NOW,
        )


def _create_permission(session: Session, provider: Provider) -> ProviderPermissionRecord:
    admin = Administrator(
        username=f"reviewer-{provider.id}",
        password_hash="test-hash",
        role="ADMIN",
        enabled=True,
    )
    session.add(admin)
    session.flush()
    record = ProviderPermissionRecord(
        provider_id=provider.id,
        official_source_url=SOURCE_URL,
        permitted_access_method=METHOD,
        terms_url="https://provider.example/terms",
        request_limits={"minimum_interval_seconds": 3600},
        evidence_reference="documented-authorization",
        verified_at=NOW - timedelta(days=1),
        review_due_at=NOW + timedelta(days=30),
        responsible_administrator_id=admin.id,
        approval_status="APPROVED",
    )
    session.add(record)
    session.flush()
    return record


def _create_job(session: Session) -> MonitoringJob:
    country = Country(country_code="DE", name="Germany")
    origin = ApplicantOrigin(code="PK", name="Pakistan")
    provider = Provider(
        provider_code=_AuthorizedStubAdapter.provider_code,
        name="Monitoring Test Provider",
        access_mode="AUTOMATED",
        enabled=True,
    )
    category = VisaCategory(name="Tourist", category_code="tourist", enabled=True)
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
        execution_status="NOT_RUN",
        next_check_at=NOW - timedelta(minutes=5),
    )
    session.add(job)
    session.flush()
    return job


def test_monitoring_engine_claims_and_executes_a_due_job(database_session: Session) -> None:
    job = _create_job(database_session)
    provider = database_session.get(Provider, job.provider_id)
    _create_permission(database_session, provider)
    registry = ProviderRegistry((_AuthorizedStubAdapter(),))
    engine = MonitoringEngine(registry=registry, owner="unit-test-scheduler")

    result = engine.run_job(database_session, job, now=NOW)

    assert result.claimed is True
    assert result.executed is True
    assert result.status == "SUCCEEDED"
    assert job.lock_owner is None
    assert job.execution_status == "SUCCEEDED"
    assert job.availability_status == "AVAILABLE"
    assert job.next_check_at is not None


def test_monitoring_engine_queues_alert_for_configured_recipient(
    database_session: Session,
) -> None:
    """The worker engine connects authorized transitions to the notification outbox."""
    job = _create_job(database_session)
    job.availability_status = "UNAVAILABLE"
    job.initial_available_alert_policy = True
    provider = database_session.get(Provider, job.provider_id)
    permission = _create_permission(database_session, provider)
    encryption_key = Fernet.generate_key().decode("ascii")
    database_session.add(
        NotificationIntegration(
            channel="TELEGRAM",
            enabled=True,
            encrypted_configuration=encrypt_configuration(
                {"bot_token": "test-token", "recipients": ["-10012345"]},
                encryption_key,
            ),
            updated_by_administrator_id=permission.responsible_administrator_id,
        )
    )
    database_session.flush()
    engine = MonitoringEngine(
        registry=ProviderRegistry((_AuthorizedStubAdapter(),)),
        owner="unit-test-scheduler",
        notification_encryption_key=encryption_key,
    )

    result = engine.run_job(database_session, job, now=NOW)

    assert result.executed is True
    assert database_session.query(NotificationOutboxItem).count() == 1
    queued = database_session.query(NotificationOutboxItem).one()
    assert queued.channel == "TELEGRAM"
    assert queued.recipient_reference == "-10012345"


def test_monitoring_engine_recovers_expired_leases(database_session: Session) -> None:
    job = _create_job(database_session)
    job.enabled = True
    job.lock_owner = "stale-worker"
    job.lock_expires_at = NOW - timedelta(minutes=5)
    job.next_check_at = NOW - timedelta(minutes=1)
    database_session.flush()

    engine = MonitoringEngine(owner="unit-test-scheduler")
    recovered = engine.recover_abandoned_jobs(database_session, now=NOW)

    assert recovered == 1
    assert job.lock_owner is None
    assert job.lock_expires_at is None
    assert job.next_check_at == NOW


def test_circuit_breaker_trips_after_failures() -> None:
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=60)
    assert breaker.is_open() is False

    breaker.record_failure(now=NOW)
    assert breaker.is_open(now=NOW) is False

    breaker.record_failure(now=NOW)
    assert breaker.is_open(now=NOW) is True

    breaker.record_success()
    assert breaker.is_open(now=NOW) is False


def test_monitoring_engine_keeps_jobs_under_concurrency_limit(database_session: Session) -> None:
    job = _create_job(database_session)
    job.lock_owner = "locked-worker"
    job.lock_expires_at = NOW + timedelta(hours=1)
    job.next_check_at = NOW - timedelta(minutes=1)
    database_session.flush()

    engine = MonitoringEngine(
        registry=ProviderRegistry((_AuthorizedStubAdapter(),)),
        policy=JobExecutionPolicy(max_concurrent_jobs=1),
    )
    results = engine.run_due_jobs(database_session, now=NOW)

    assert results == []
    assert database_session.scalar(
        select(MonitoringJob.id).where(MonitoringJob.lock_owner == "locked-worker")
    ) == job.id

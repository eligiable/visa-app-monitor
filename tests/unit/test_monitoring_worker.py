"""Tests for the dedicated, transaction-owning scheduler worker."""

import asyncio
from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet
from sqlalchemy import select

from app.database.base import Base
from app.database.models import (
    Administrator,
    AlertEvent,
    ApplicantOrigin,
    AvailabilityHistory,
    CheckResult,
    City,
    Country,
    MonitoringJob,
    NotificationDeliveryAttempt,
    NotificationIntegration,
    NotificationOutboxItem,
    Provider,
    VisaCategory,
    VisaCentre,
)
from app.database.session import create_database_engine, create_session_factory
from app.monitoring.engine import MonitoringEngine
from app.monitoring.worker import MonitoringWorker
from app.notifications.configuration import encrypt_configuration
from app.notifications.providers import TelegramNotificationProvider
from app.providers.registry import create_default_registry


def test_worker_commits_restricted_job_result_from_its_poll_thread(tmp_path) -> None:
    """Worker poll persists results without nesting asyncio event loops."""
    database_path = tmp_path / "worker.sqlite"
    database_engine = create_database_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(database_engine)
    session_factory = create_session_factory(database_engine)
    now = datetime.now(UTC)

    with session_factory.begin() as session:
        origin = ApplicantOrigin(code="PK", name="Pakistan")
        country = Country(country_code="DE", name="Germany")
        provider = Provider(
            provider_code="vfs_global",
            name="VFS Global",
            access_mode="MANUAL_CHECK_REQUIRED",
        )
        category = VisaCategory(name="Tourist", category_code="tourist")
        session.add_all([origin, country, provider, category])
        session.flush()
        city = City(country_id=country.id, name="Berlin")
        session.add(city)
        session.flush()
        centre = VisaCentre(
            city_id=city.id,
            provider_id=provider.id,
            name="Berlin Centre",
            official_url="https://official.example/appointments",
            access_mode="MANUAL_CHECK_REQUIRED",
        )
        session.add(centre)
        session.flush()
        session.add(
            MonitoringJob(
                origin_id=origin.id,
                destination_country_id=country.id,
                city_id=city.id,
                visa_centre_id=centre.id,
                category_id=category.id,
                provider_id=provider.id,
                appointment_type="Short Stay",
                official_source_url=centre.official_url,
                polling_interval=3600,
                jitter_seconds=0,
                enabled=True,
                access_mode="MANUAL_CHECK_REQUIRED",
                next_check_at=now - timedelta(seconds=1),
            )
        )

    worker = MonitoringWorker(
        engine=MonitoringEngine(registry=create_default_registry()),
        session_factory=session_factory,
    )
    results = asyncio.run(worker.run_once(now=now))

    assert len(results) == 1
    assert results[0].status == "SKIPPED_RESTRICTED"
    with session_factory() as session:
        check_result = session.scalar(select(CheckResult))
        job = session.scalar(select(MonitoringJob))
        assert check_result is not None
        assert check_result.availability_status is None
        assert job is not None
        assert job.execution_status == "SKIPPED_RESTRICTED"
        assert job.next_check_at is not None
    database_engine.dispose()


def test_worker_delivers_pending_telegram_outbox_item(tmp_path, monkeypatch) -> None:
    """The worker decrypts enabled channel settings and records delivery attempts."""
    database_path = tmp_path / "worker-notifications.sqlite"
    database_engine = create_database_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(database_engine)
    session_factory = create_session_factory(database_engine)
    now = datetime.now(UTC)
    encryption_key = Fernet.generate_key().decode("ascii")
    sent: list[tuple[str, str]] = []

    def fake_send(self, *, message: str, recipient: str) -> str:
        sent.append((message, recipient))
        return "telegram:42"

    monkeypatch.setattr(TelegramNotificationProvider, "send", fake_send)
    with session_factory.begin() as session:
        admin = Administrator(
            username="integration-admin",
            password_hash="hash",
            role="ADMIN",
        )
        origin = ApplicantOrigin(code="PK", name="Pakistan")
        country = Country(country_code="DE", name="Germany")
        provider = Provider(
            provider_code="notify_provider",
            name="Notify Provider",
            access_mode="MANUAL_CHECK_REQUIRED",
        )
        category = VisaCategory(name="Tourist", category_code="notify_tourist")
        session.add_all([admin, origin, country, provider, category])
        session.flush()
        city = City(country_id=country.id, name="Berlin")
        session.add(city)
        session.flush()
        centre = VisaCentre(
            city_id=city.id,
            provider_id=provider.id,
            name="Berlin Centre",
            official_url="https://provider.example/appointments",
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
            jitter_seconds=0,
            enabled=False,
            access_mode="MANUAL_CHECK_REQUIRED",
            availability_status="AVAILABLE",
        )
        session.add(job)
        session.flush()
        check_result = CheckResult(
            job_id=job.id,
            checked_at=now,
            execution_status="SUCCEEDED",
            availability_status="AVAILABLE",
            source_url=centre.official_url,
        )
        session.add(check_result)
        session.flush()
        history = AvailabilityHistory(
            job_id=job.id,
            previous_status="UNAVAILABLE",
            new_status="AVAILABLE",
            detected_at=now,
            source_check_result_id=check_result.id,
        )
        session.add(history)
        session.flush()
        alert = AlertEvent(
            job_id=job.id,
            availability_history_id=history.id,
            availability_status="AVAILABLE",
            verification_source="AUTOMATED",
            created_at=now,
            deduplication_key="worker-notification-alert",
        )
        session.add(alert)
        session.flush()
        outbox = NotificationOutboxItem(
            alert_event_id=alert.id,
            channel="TELEGRAM",
            recipient_reference="-10012345",
            created_at=now,
            next_attempt_at=now,
            state="PENDING",
        )
        session.add(outbox)
        session.flush()
        session.add(
            NotificationIntegration(
                channel="TELEGRAM",
                enabled=True,
                encrypted_configuration=encrypt_configuration(
                    {"bot_token": "secret-token", "recipients": ["-10012345"]},
                    encryption_key,
                ),
                updated_by_administrator_id=admin.id,
            )
        )
        outbox_id = outbox.id

    worker = MonitoringWorker(
        engine=MonitoringEngine(registry=create_default_registry()),
        session_factory=session_factory,
        notification_encryption_key=encryption_key,
    )
    asyncio.run(worker.run_once(now=now))

    with session_factory() as session:
        stored_outbox = session.get(NotificationOutboxItem, outbox_id)
        attempts = session.scalars(select(NotificationDeliveryAttempt)).all()
    assert stored_outbox is not None
    assert stored_outbox.state == "DELIVERED"
    assert len(attempts) == 1
    assert attempts[0].delivery_status == "SUCCEEDED"
    assert attempts[0].provider_message_reference == "telegram:42"
    assert sent[0][1] == "-10012345"
    assert "available appointment" in sent[0][0]
    database_engine.dispose()

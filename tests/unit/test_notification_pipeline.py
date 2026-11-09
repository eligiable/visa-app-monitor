"""Tests for the notification outbox and channel delivery pipeline."""

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.orm import Session

from app.database.models import (
    AlertEvent,
    ApplicantOrigin,
    AvailabilityHistory,
    CheckResult,
    City,
    Country,
    MonitoringJob,
    NotificationDeliveryAttempt,
    NotificationOutboxItem,
    Provider,
    SystemError,
    VisaCategory,
    VisaCentre,
)
from app.notifications.service import NotificationOutboxService
from app.notifications.providers import TelegramNotificationProvider

NOW = datetime(2026, 11, 9, 9, 0, tzinfo=UTC)
SOURCE_URL = "https://provider.example/appointments"


def _create_alert(session: Session) -> AlertEvent:
    country = Country(country_code="DE", name="Germany")
    origin = ApplicantOrigin(code="PK", name="Pakistan")
    provider = Provider(provider_code="notify_provider", name="Notify Provider", access_mode="AUTOMATED")
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
        availability_status="UNAVAILABLE",
        initial_available_alert_policy=True,
        next_check_at=NOW,
    )
    session.add(job)
    session.flush()

    result = CheckResult(
        job_id=job.id,
        checked_at=NOW,
        execution_status="SUCCEEDED",
        availability_status="AVAILABLE",
        source_url=SOURCE_URL,
        response_code=200,
        duration_ms=100,
    )
    session.add(result)
    session.flush()

    history = AvailabilityHistory(
        job_id=job.id,
        previous_status="UNAVAILABLE",
        new_status="AVAILABLE",
        detected_at=NOW,
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
        created_at=NOW,
        deduplication_key="alert-test-1",
    )
    session.add(alert)
    session.flush()
    return alert


class SuccessProvider:
    channel = "TELEGRAM"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def send(self, *, message: str, recipient: str) -> str:
        self.calls.append((message, recipient))
        return "telegram:42"


class FailProvider:
    channel = "EMAIL"

    def send(self, *, message: str, recipient: str) -> str:
        raise RuntimeError("SMTP temporary failure")


def test_alert_notifications_are_queued_once_per_channel_recipient(database_session: Session) -> None:
    alert = _create_alert(database_session)
    service = NotificationOutboxService()

    first = service.queue_alert_notifications(
        database_session,
        alert.id,
        recipients={"EMAIL": ["ops@example.com"], "TELEGRAM": ["-10012345"]},
        channels=["EMAIL", "TELEGRAM"],
        now=NOW,
    )
    second = service.queue_alert_notifications(
        database_session,
        alert.id,
        recipients={"EMAIL": ["ops@example.com"], "TELEGRAM": ["-10012345"]},
        channels=["EMAIL", "TELEGRAM"],
        now=NOW,
    )

    assert len(first) == 2
    assert len(second) == 0
    assert database_session.query(NotificationOutboxItem).count() == 2


def test_outbox_delivery_records_successful_attempts(database_session: Session) -> None:
    alert = _create_alert(database_session)
    service = NotificationOutboxService()
    success_telegram = SuccessProvider()
    success_email = SuccessProvider()
    success_email.channel = "EMAIL"

    service.queue_alert_notifications(
        database_session,
        alert.id,
        recipients={"EMAIL": ["ops@example.com"], "TELEGRAM": ["-10012345"]},
        channels=["EMAIL", "TELEGRAM"],
        now=NOW,
    )

    processed = service.process_due_notifications(
        database_session,
        providers={"EMAIL": success_email, "TELEGRAM": success_telegram},
        now=NOW,
    )

    assert len(processed) == 2
    assert database_session.query(NotificationOutboxItem).filter(NotificationOutboxItem.state == "DELIVERED").count() == 2
    assert database_session.query(NotificationDeliveryAttempt).count() == 2


def test_disabled_channel_leaves_pending_items_queued(database_session: Session) -> None:
    """Disabling a channel pauses its outbox items without failing them."""
    alert = _create_alert(database_session)
    service = NotificationOutboxService()
    queued = service.queue_alert_notifications(
        database_session,
        alert.id,
        recipients={"TELEGRAM": ["-10012345"]},
        now=NOW,
    )

    processed = service.process_due_notifications(
        database_session,
        providers={},
        channels=[],
        now=NOW,
    )

    assert len(queued) == 1
    assert processed == []
    assert queued[0].state == "PENDING"
    assert database_session.query(NotificationDeliveryAttempt).count() == 0


def test_delivery_failure_is_logged_without_erase_other_channel_outcomes(database_session: Session) -> None:
    alert = _create_alert(database_session)
    service = NotificationOutboxService(max_attempts=1)
    telegram = SuccessProvider()
    telegram.channel = "TELEGRAM"

    service.queue_alert_notifications(
        database_session,
        alert.id,
        recipients={"EMAIL": ["ops@example.com"], "TELEGRAM": ["-10012345"]},
        channels=["EMAIL", "TELEGRAM"],
        now=NOW,
    )

    processed = service.process_due_notifications(
        database_session,
        providers={"EMAIL": FailProvider(), "TELEGRAM": telegram},
        now=NOW,
    )

    assert len(processed) == 2
    assert database_session.query(NotificationOutboxItem).filter(NotificationOutboxItem.channel == "EMAIL").one().state == "FAILED"
    assert database_session.query(NotificationOutboxItem).filter(NotificationOutboxItem.channel == "TELEGRAM").one().state == "DELIVERED"
    assert database_session.query(NotificationDeliveryAttempt).filter(NotificationDeliveryAttempt.delivery_status == "FAILED").count() == 1
    assert database_session.query(SystemError).count() == 1


def test_telegram_api_error_does_not_expose_bot_token(monkeypatch) -> None:
    """Telegram error bodies and request URLs must not leak the bot token."""
    token = "sensitive-bot-token"

    class FailedResponse:
        status_code = 401
        text = f"error from https://api.telegram.org/bot{token}/sendMessage"

    monkeypatch.setattr(
        "app.notifications.providers.httpx.post",
        lambda *args, **kwargs: FailedResponse(),
    )
    with pytest.raises(RuntimeError) as failure:
        TelegramNotificationProvider(bot_token=token).send(
            message="test",
            recipient="-10012345",
        )
    assert token not in str(failure.value)


def test_telegram_transport_error_does_not_expose_bot_token(monkeypatch) -> None:
    """HTTP request exception strings can contain the token-bearing URL."""
    token = "sensitive-bot-token"
    request = httpx.Request(
        "POST",
        f"https://api.telegram.org/bot{token}/sendMessage",
    )

    def fail_request(*args, **kwargs):
        raise httpx.RequestError(f"request failed for {request.url}", request=request)

    monkeypatch.setattr("app.notifications.providers.httpx.post", fail_request)
    with pytest.raises(RuntimeError) as failure:
        TelegramNotificationProvider(bot_token=token).send(
            message="test",
            recipient="-10012345",
        )
    assert token not in str(failure.value)

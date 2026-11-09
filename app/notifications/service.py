"""Notification outbox processing and delivery scheduling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import (
    AlertEvent,
    MonitoringJob,
    NotificationDeliveryAttempt,
    NotificationOutboxItem,
    SystemError,
)
from app.notifications.templates import NotificationTemplateRenderer


class NotificationOutboxService:
    """Queue alerts for delivery and process pending outbox items."""

    def __init__(self, *, retry_backoff_seconds: int = 300, max_attempts: int = 3) -> None:
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be non-negative")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.retry_backoff_seconds = retry_backoff_seconds
        self.max_attempts = max_attempts

    def queue_alert_notifications(
        self,
        session: Session,
        alert_event_id: int,
        *,
        recipients: dict[str, Iterable[str]] | None = None,
        channels: Iterable[str] | None = None,
        now: datetime | None = None,
    ) -> list[NotificationOutboxItem]:
        """Create one outbox entry per recipient/channel combination."""
        alert = session.get(AlertEvent, alert_event_id)
        if alert is None:
            return []

        recipients = recipients or {}
        channels = list(channels or recipients.keys())
        created: list[NotificationOutboxItem] = []
        for channel in channels:
            configured = list(recipients.get(channel, ()))
            if not configured:
                continue
            for recipient in configured:
                existing = session.execute(
                    select(NotificationOutboxItem).where(
                        NotificationOutboxItem.alert_event_id == alert_event_id,
                    ).where(NotificationOutboxItem.channel == channel).where(
                        NotificationOutboxItem.recipient_reference == recipient,
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    continue

                item = NotificationOutboxItem(
                    alert_event_id=alert_event_id,
                    channel=channel,
                    recipient_reference=recipient,
                    created_at=now or datetime.now(UTC),
                    next_attempt_at=now or datetime.now(UTC),
                    state="PENDING",
                )
                session.add(item)
                created.append(item)
        session.flush()
        return created

    def process_due_notifications(
        self,
        session: Session,
        *,
        providers: dict[str, object] | None = None,
        now: datetime | None = None,
    ) -> list[NotificationOutboxItem]:
        """Deliver pending outbox items using the configured channel providers."""
        providers = providers or {}
        now = now or datetime.now(UTC)
        cutoff = now
        pending = session.execute(
            select(NotificationOutboxItem)
            .where(NotificationOutboxItem.state == "PENDING")
            .where(
                (NotificationOutboxItem.next_attempt_at.is_(None))
                | (NotificationOutboxItem.next_attempt_at <= cutoff)
            )
            .order_by(NotificationOutboxItem.created_at.asc())
        ).scalars().all()

        processed: list[NotificationOutboxItem] = []
        for item in pending:
            provider = providers.get(item.channel)
            if provider is None:
                self._record_failure(
                    session,
                    item=item,
                    now=now,
                    error_detail=f"No notification provider configured for {item.channel}",
                    status="FAILED",
                    finish_outbox=True,
                )
                processed.append(item)
                continue

            attempt_number = (
                session.query(NotificationDeliveryAttempt)
                .filter(NotificationDeliveryAttempt.outbox_item_id == item.id)
                .count()
                + 1
            )
            attempt = NotificationDeliveryAttempt(
                outbox_item_id=item.id,
                attempt_number=attempt_number,
                attempted_at=now,
                delivery_status="FAILED",
            )
            session.add(attempt)
            session.flush()

            try:
                alert = session.get(AlertEvent, item.alert_event_id)
                job = session.get(MonitoringJob, alert.job_id) if alert else None
                message = (
                    NotificationTemplateRenderer.render_alert_message(alert, job)
                    if alert else "eligiable Visa notification"
                )
                provider_ref = provider.send(message=message, recipient=item.recipient_reference)
                attempt.delivery_status = "SUCCEEDED"
                attempt.provider_message_reference = provider_ref
                item.state = "DELIVERED"
                item.next_attempt_at = None
                processed.append(item)
            except Exception as exc:  # pragma: no cover - defensive path
                detail = str(exc)[:1000]
                attempt.delivery_status = "FAILED"
                attempt.safe_error_detail = detail
                if attempt_number >= self.max_attempts:
                    item.state = "FAILED"
                    item.next_attempt_at = None
                    self._record_failure(
                        session,
                        item=item,
                        now=now,
                        error_detail=detail,
                        status="FAILED",
                        finish_outbox=True,
                    )
                else:
                    item.state = "PENDING"
                    delay = timedelta(seconds=self.retry_backoff_seconds * attempt_number)
                    item.next_attempt_at = now + delay
                    self._record_failure(
                        session,
                        item=item,
                        now=now,
                        error_detail=detail,
                        status="FAILED",
                        finish_outbox=False,
                    )
                processed.append(item)
            session.flush()
        return processed

    def _record_failure(
        self,
        session: Session,
        *,
        item: NotificationOutboxItem,
        now: datetime,
        error_detail: str,
        status: str,
        finish_outbox: bool,
    ) -> None:
        """Persist a system-error record when delivery fails."""
        alert = session.get(AlertEvent, item.alert_event_id)
        session.add(
            SystemError(
                component="notification_service",
                provider_id=None,
                severity="ERROR",
                message=(
                    f"Notification delivery failed for channel={item.channel} "
                    f"recipient={item.recipient_reference}: {error_detail}"
                ),
                occurred_at=now,
            )
        )
        if finish_outbox:
            item.state = status
            item.next_attempt_at = None

"""Availability transition detection and alert handling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import (
    AlertEvent,
    AvailabilityHistory,
    CheckResult,
    ManualVerification,
    MonitoringJob,
)


class AvailabilityDetectionService:
    """Evaluate provider results and persist availability transitions."""

    def __init__(self, *, cooldown_seconds: int = 3600) -> None:
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be non-negative")
        self.cooldown_seconds = cooldown_seconds

    def process_check_result(
        self,
        session: Session,
        job_id: int,
        check_result_id: int,
        *,
        now: datetime | None = None,
    ) -> AvailabilityHistory | None:
        """Persist availability history and alert events for a successful check."""
        result = session.get(CheckResult, check_result_id)
        if result is None or result.job_id != job_id:
            return None

        job = session.get(MonitoringJob, job_id)
        if job is None:
            return None

        status = result.availability_status
        if result.execution_status != "SUCCEEDED" or status not in {"AVAILABLE", "UNAVAILABLE"}:
            return None

        previous_status = job.availability_status
        if previous_status == status:
            return None

        history = AvailabilityHistory(
            job_id=job.id,
            previous_status=previous_status,
            new_status=status,
            detected_at=now or datetime.now(UTC),
            source_check_result_id=result.id,
            manual_verification_id=None,
        )
        session.add(history)
        session.flush()

        job.availability_status = status
        job.last_check_at = now or datetime.now(UTC)

        if status == "AVAILABLE":
            self._emit_available_alert(
                session,
                job=job,
                availability_history_id=history.id,
                verification_source="AUTOMATED",
                now=now or datetime.now(UTC),
            )

        return history

    def record_manual_verification(
        self,
        session: Session,
        *,
        job_id: int,
        operator_administrator_id: int,
        recorded_status: str,
        official_source_url: str,
        internal_notes: str | None = None,
        verified_at: datetime | None = None,
        manual_alert_enabled: bool = False,
    ) -> AvailabilityHistory | None:
        """Persist a manual verification and alert when enabled by policy."""
        if recorded_status not in {"AVAILABLE", "UNAVAILABLE"}:
            return None
        job = session.get(MonitoringJob, job_id)
        if job is None:
            return None

        previous_status = job.availability_status
        if previous_status == recorded_status:
            return None

        verification = ManualVerification(
            job_id=job.id,
            operator_administrator_id=operator_administrator_id,
            recorded_status=recorded_status,
            verified_at=verified_at or datetime.now(UTC),
            official_source_url=official_source_url,
            internal_notes=internal_notes,
        )
        session.add(verification)
        session.flush()

        history = AvailabilityHistory(
            job_id=job.id,
            previous_status=previous_status,
            new_status=recorded_status,
            detected_at=verification.verified_at,
            source_check_result_id=None,
            manual_verification_id=verification.id,
        )
        session.add(history)
        session.flush()

        job.availability_status = recorded_status
        job.last_check_at = verification.verified_at

        if recorded_status == "AVAILABLE" and manual_alert_enabled:
            self._emit_available_alert(
                session,
                job=job,
                availability_history_id=history.id,
                verification_source="MANUAL",
                now=verification.verified_at,
            )

        return history

    def _emit_available_alert(
        self,
        session: Session,
        *,
        job: MonitoringJob,
        availability_history_id: int,
        verification_source: str,
        now: datetime,
    ) -> AlertEvent | None:
        """Create a unique availability alert, applying initial-available and cooldown policy."""
        if verification_source not in {"AUTOMATED", "MANUAL"}:
            return None

        previous_status = session.get(AvailabilityHistory, availability_history_id).previous_status
        if verification_source == "AUTOMATED" and previous_status is None and not job.initial_available_alert_policy:
            return None

        if self._alert_in_cooldown(session, job_id=job.id, now=now):
            return None

        deduplication_key = (
            f"job:{job.id}:status:AVAILABLE:source:{verification_source}:"
            f"previous:{previous_status or 'none'}:history:{availability_history_id}"
        )
        existing = session.execute(
            select(AlertEvent).where(AlertEvent.deduplication_key == deduplication_key)
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        alert = AlertEvent(
            job_id=job.id,
            availability_history_id=availability_history_id,
            availability_status="AVAILABLE",
            verification_source=verification_source,
            created_at=now,
            deduplication_key=deduplication_key,
        )
        session.add(alert)
        session.flush()
        return alert

    def _alert_in_cooldown(
        self,
        session: Session,
        *,
        job_id: int,
        now: datetime,
    ) -> bool:
        """Skip alert emission when an earlier alert for the same job is still cooling down."""
        if self.cooldown_seconds <= 0:
            return False
        cutoff = now - timedelta(seconds=self.cooldown_seconds)
        existing = session.execute(
            select(AlertEvent)
            .where(AlertEvent.job_id == job_id)
            .where(AlertEvent.created_at >= cutoff)
            .order_by(AlertEvent.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        return existing is not None


__all__ = ["AvailabilityDetectionService"]

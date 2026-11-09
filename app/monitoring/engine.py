"""Monitoring-engine primitives for scheduled provider checks."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
import random

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.database.models import CheckResult, MonitoringJob, Provider
from app.monitoring.availability import AvailabilityDetectionService
from app.notifications.configuration import (
    NotificationConfigurationError,
    load_notification_recipients,
)
from app.providers.models import CheckExecutionStatus
from app.providers.registry import ProviderRegistry
from app.providers.service import execute_provider_check

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class JobExecutionPolicy:
    """Runtime policy for scheduler cadence, retries and lease handling."""

    polling_interval_seconds: int = 300
    jitter_seconds: int = 30
    max_retries: int = 3
    base_backoff_seconds: int = 30
    max_concurrent_jobs: int = 1
    lease_seconds: int = 300
    circuit_breaker_threshold: int = 3
    circuit_breaker_cooldown_seconds: int = 300

    def __post_init__(self) -> None:
        if self.polling_interval_seconds <= 0:
            raise ValueError("polling_interval_seconds must be positive")
        if self.jitter_seconds < 0:
            raise ValueError("jitter_seconds must be non-negative")
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.base_backoff_seconds <= 0:
            raise ValueError("base_backoff_seconds must be positive")
        if self.max_concurrent_jobs <= 0:
            raise ValueError("max_concurrent_jobs must be positive")
        if self.lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if self.circuit_breaker_threshold <= 0:
            raise ValueError("circuit_breaker_threshold must be positive")
        if self.circuit_breaker_cooldown_seconds <= 0:
            raise ValueError("circuit_breaker_cooldown_seconds must be positive")

    def jitter_for(self, job: MonitoringJob) -> int:
        """Return a bounded jitter value for the given monitoring job."""
        base = max(0, int(job.jitter_seconds or self.jitter_seconds))
        if base == 0:
            return 0
        return random.randint(0, min(base, self.polling_interval_seconds))

    def backoff_seconds(self, attempt_number: int) -> int:
        """Return the exponential-backoff delay for retry attempts."""
        attempt = max(1, attempt_number)
        return self.base_backoff_seconds * (2 ** (attempt - 1))


@dataclass(slots=True)
class MonitoringCycleResult:
    """Outcome from a single scheduler cycle on one job."""

    job_id: int
    owner: str
    claimed: bool
    executed: bool
    status: str
    next_check_at: datetime | None
    reason: str | None = None


@dataclass(slots=True)
class CircuitBreaker:
    """Simple per-provider failure circuit breaker used by the scheduler."""

    failure_threshold: int = 3
    cooldown_seconds: int = 300
    failure_count: int = 0
    opened_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.failure_threshold <= 0:
            raise ValueError("failure_threshold must be positive")
        if self.cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be positive")

    def is_open(self, *, now: datetime | None = None) -> bool:
        """Return true when the circuit remains in its cooldown window."""
        current_time = now or datetime.now(UTC)
        if self.opened_at is None:
            return False
        return current_time < self.opened_at + timedelta(seconds=self.cooldown_seconds)

    def record_success(self) -> None:
        """Reset the breaker after a successful execution."""
        self.failure_count = 0
        self.opened_at = None

    def record_failure(self, *, now: datetime | None = None) -> None:
        """Advance the breaker after a failed execution attempt."""
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.opened_at = now or datetime.now(UTC)


class MonitoringEngine:
    """Scheduler logic for due jobs, lock leasing, retries and circuit breakers."""

    def __init__(
        self,
        *,
        registry: ProviderRegistry | None = None,
        owner: str = "scheduler-default",
        policy: JobExecutionPolicy | None = None,
        notification_encryption_key: str | None = None,
    ) -> None:
        self.registry = registry or ProviderRegistry(())
        self.owner = owner
        self.policy = policy or JobExecutionPolicy()
        self.notification_encryption_key = notification_encryption_key
        self._circuit_breakers: dict[str, CircuitBreaker] = {}

    def get_circuit_breaker(self, provider_code: str) -> CircuitBreaker:
        """Return the in-memory breaker for a provider, creating one on demand."""
        breaker = self._circuit_breakers.get(provider_code)
        if breaker is None:
            breaker = CircuitBreaker(
                failure_threshold=self.policy.circuit_breaker_threshold,
                cooldown_seconds=self.policy.circuit_breaker_cooldown_seconds,
            )
            self._circuit_breakers[provider_code] = breaker
        return breaker

    def compute_next_run(self, job: MonitoringJob, *, now: datetime | None = None) -> datetime:
        """Calculate the next schedule time using the polling interval and jitter."""
        scheduled_now = now or datetime.now(UTC)
        delay_seconds = max(0, int(job.polling_interval)) + self.policy.jitter_for(job)
        return scheduled_now + timedelta(seconds=delay_seconds)

    def get_due_jobs(
        self,
        session: Session,
        *,
        now: datetime | None = None,
        limit: int | None = None,
    ) -> list[MonitoringJob]:
        """Return due jobs eligible for claiming by the scheduler."""
        if limit is not None and limit <= 0:
            return []
        self.recover_abandoned_jobs(session, now=now)
        scheduled_now = now or datetime.now(UTC)
        query = (
            select(MonitoringJob)
            .where(MonitoringJob.enabled.is_(True))
            .where((MonitoringJob.next_check_at.is_(None)) | (MonitoringJob.next_check_at <= scheduled_now))
            .where((MonitoringJob.lock_owner.is_(None)) | (MonitoringJob.lock_expires_at.is_(None)) | (MonitoringJob.lock_expires_at <= scheduled_now))
            .order_by(MonitoringJob.next_check_at.asc().nulls_first(), MonitoringJob.id.asc())
        )
        if limit is not None:
            query = query.limit(limit)
        return list(session.execute(query).scalars().all())

    def recover_abandoned_jobs(self, session: Session, *, now: datetime | None = None) -> int:
        """Release expired leases so a worker crash does not stall a job forever."""
        scheduled_now = now or datetime.now(UTC)
        result = session.execute(
            update(MonitoringJob)
            .where(MonitoringJob.enabled.is_(True))
            .where(MonitoringJob.lock_owner.is_not(None))
            .where(MonitoringJob.lock_expires_at.is_not(None))
            .where(MonitoringJob.lock_expires_at <= scheduled_now)
            .values(
                lock_owner=None,
                lock_expires_at=None,
                next_check_at=scheduled_now,
            )
        )
        session.flush()
        return result.rowcount or 0

    def claim_job(
        self,
        session: Session,
        job: MonitoringJob,
        *,
        owner: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Claim a job with a database-backed lease to prevent duplicate execution."""
        if not job.enabled:
            return False
        lease_owner = owner or self.owner
        lease_time = now or datetime.now(UTC)
        expires_at = lease_time + timedelta(seconds=self.policy.lease_seconds)
        result = session.execute(
            update(MonitoringJob)
            .where(MonitoringJob.id == job.id)
            .where(MonitoringJob.enabled.is_(True))
            .where(
                (MonitoringJob.lock_owner.is_(None))
                | (MonitoringJob.lock_expires_at.is_(None))
                | (MonitoringJob.lock_expires_at <= lease_time)
            )
            .values(
                lock_owner=lease_owner,
                lock_expires_at=expires_at,
            )
        )
        session.flush()
        if result.rowcount == 0:
            return False
        job.lock_owner = lease_owner
        job.lock_expires_at = expires_at
        return True

    def release_job(
        self,
        session: Session,
        job: MonitoringJob,
        *,
        now: datetime | None = None,
        next_check_at: datetime | None = None,
        status: str | None = None,
        availability_status: str | None = None,
    ) -> None:
        """Clear the job lease and schedule the next run."""
        scheduled_now = now or datetime.now(UTC)
        final_status = status or job.execution_status or "NOT_RUN"
        job.execution_status = final_status
        if availability_status is not None:
            job.availability_status = availability_status
        job.last_check_at = scheduled_now
        job.lock_owner = None
        job.lock_expires_at = None
        job.next_check_at = next_check_at or self.compute_next_run(job, now=scheduled_now)
        session.execute(
            update(MonitoringJob)
            .where(MonitoringJob.id == job.id)
            .values(
                execution_status=final_status,
                availability_status=availability_status,
                last_check_at=scheduled_now,
                lock_owner=None,
                lock_expires_at=None,
                next_check_at=job.next_check_at,
            )
        )
        session.flush()

    def _provider_breaker_key(self, session: Session, job: MonitoringJob) -> str:
        provider = session.get(Provider, job.provider_id)
        if provider is None:
            return f"job:{job.id}"
        return provider.provider_code

    def run_job(
        self,
        session: Session,
        job: MonitoringJob,
        *,
        now: datetime | None = None,
        registry: ProviderRegistry | None = None,
    ) -> MonitoringCycleResult:
        """Execute one due job under a lease and persist the result."""
        scheduled_now = now or datetime.now(UTC)
        if not job.enabled:
            return MonitoringCycleResult(
                job_id=job.id,
                owner=self.owner,
                claimed=False,
                executed=False,
                status="NOT_RUN",
                next_check_at=job.next_check_at,
                reason="job disabled",
            )

        if not self.claim_job(session, job, owner=self.owner, now=scheduled_now):
            return MonitoringCycleResult(
                job_id=job.id,
                owner=self.owner,
                claimed=False,
                executed=False,
                status=job.execution_status or "NOT_RUN",
                next_check_at=job.next_check_at,
                reason="already locked",
            )

        breaker = self.get_circuit_breaker(self._provider_breaker_key(session, job))
        if breaker.is_open(now=scheduled_now):
            self.release_job(
                session,
                job,
                now=scheduled_now,
                next_check_at=scheduled_now + timedelta(seconds=self.policy.polling_interval_seconds),
                status="NOT_RUN",
            )
            return MonitoringCycleResult(
                job_id=job.id,
                owner=self.owner,
                claimed=True,
                executed=False,
                status="NOT_RUN",
                next_check_at=scheduled_now + timedelta(seconds=self.policy.polling_interval_seconds),
                reason="circuit open",
            )

        provider_registry = registry or self.registry
        try:
            result = asyncio.run(
                execute_provider_check(session, job.id, provider_registry, now=scheduled_now)
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            breaker.record_failure(now=scheduled_now)
            self.release_job(
                session,
                job,
                now=scheduled_now,
                next_check_at=scheduled_now + timedelta(seconds=self.policy.base_backoff_seconds),
                status="SOURCE_ERROR",
            )
            return MonitoringCycleResult(
                job_id=job.id,
                owner=self.owner,
                claimed=True,
                executed=False,
                status="SOURCE_ERROR",
                next_check_at=scheduled_now + timedelta(seconds=self.policy.base_backoff_seconds),
                reason=str(exc),
            )

        if result.execution_status == CheckExecutionStatus.SUCCEEDED:
            breaker.record_success()
            next_check_at = self.compute_next_run(job, now=scheduled_now)
            status_value = "SUCCEEDED"
            availability_value = result.availability_status.value if result.availability_status else None
        elif result.execution_status == CheckExecutionStatus.SKIPPED_RESTRICTED:
            breaker.record_failure(now=scheduled_now)
            next_check_at = scheduled_now + timedelta(seconds=self.policy.base_backoff_seconds)
            status_value = "SKIPPED_RESTRICTED"
            availability_value = None
        else:
            breaker.record_failure(now=scheduled_now)
            next_check_at = scheduled_now + timedelta(seconds=self.policy.base_backoff_seconds)
            status_value = "SOURCE_ERROR"
            availability_value = None

        check_record = CheckResult(
            job_id=job.id,
            provider_permission_record_id=result.permission_record_id,
            checked_at=result.checked_at,
            execution_status=result.execution_status.value,
            availability_status=availability_value,
            source_url=str(result.source_url),
            response_code=None,
            duration_ms=None,
            error_message=result.diagnostic_code.value if result.diagnostic_code else None,
        )
        session.add(check_record)
        session.flush()
        try:
            notification_recipients = load_notification_recipients(
                session,
                self.notification_encryption_key,
            )
        except NotificationConfigurationError:
            notification_recipients = {}
            logger.warning(
                "Notification settings could not be decrypted; delivery was skipped",
            )
        AvailabilityDetectionService().process_check_result(
            session,
            job.id,
            check_record.id,
            now=scheduled_now,
            notification_recipients=notification_recipients,
        )

        self.release_job(
            session,
            job,
            now=scheduled_now,
            next_check_at=next_check_at,
            status=status_value,
            availability_status=availability_value,
        )

        return MonitoringCycleResult(
            job_id=job.id,
            owner=self.owner,
            claimed=True,
            executed=True,
            status=status_value,
            next_check_at=next_check_at,
            reason=result.diagnostic_code.value if result.diagnostic_code else None,
        )

    def run_due_jobs(
        self,
        session: Session,
        *,
        now: datetime | None = None,
        limit: int | None = None,
        registry: ProviderRegistry | None = None,
    ) -> list[MonitoringCycleResult]:
        """Claim and run all due jobs within the configured maximum concurrency."""
        scheduled_now = now or datetime.now(UTC)
        jobs = self.get_due_jobs(session, now=scheduled_now, limit=limit)
        results: list[MonitoringCycleResult] = []
        for job in jobs:
            active_count = session.scalar(
                select(func.count(MonitoringJob.id)).where(
                    MonitoringJob.enabled.is_(True),
                    MonitoringJob.lock_owner.is_not(None),
                    MonitoringJob.lock_expires_at.is_not(None),
                    MonitoringJob.lock_expires_at > scheduled_now,
                )
            ) or 0
            if active_count >= self.policy.max_concurrent_jobs:
                break
            results.append(self.run_job(session, job, now=scheduled_now, registry=registry))
        return results


__all__ = [
    "CircuitBreaker",
    "JobExecutionPolicy",
    "MonitoringCycleResult",
    "MonitoringEngine",
]

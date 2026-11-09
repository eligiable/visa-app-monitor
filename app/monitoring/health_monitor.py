"""Health and heartbeat helpers for the dedicated monitoring process."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.database.models import SystemError


@dataclass(slots=True)
class SchedulerHealth:
    """Simple monitoring-process health snapshot."""

    owner: str
    status: str = "ok"
    checked_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.checked_at is None:
            self.checked_at = datetime.now(UTC)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe payload for heartbeat publication."""
        return {
            "owner": self.owner,
            "status": self.status,
            "checked_at": self.checked_at.isoformat(),
        }


class SchedulerHeartbeat:
    """Record a scheduler heartbeat without depending on an external monitoring system."""

    def __init__(self, *, owner: str = "scheduler-default") -> None:
        self.owner = owner
        self.last_heartbeat: datetime | None = None

    def publish(self, *, now: datetime | None = None) -> SchedulerHealth:
        """Return the current scheduler heartbeat and remember the most recent timestamp."""
        current_time = now or datetime.now(UTC)
        self.last_heartbeat = current_time
        return SchedulerHealth(owner=self.owner, checked_at=current_time)

    def is_stale(self, *, now: datetime | None = None, max_age_seconds: int = 120) -> bool:
        """Return true when the scheduler has not reported in time."""
        if self.last_heartbeat is None:
            return True
        current_time = now or datetime.now(UTC)
        return (current_time - self.last_heartbeat).total_seconds() > max_age_seconds


class SchedulerHealthMonitor:
    """Persist and evaluate scheduler heartbeat health and operational failures."""

    def __init__(
        self,
        *,
        heartbeat: SchedulerHeartbeat | None = None,
        owner: str = "scheduler-default",
        max_age_seconds: int = 120,
        severity: str = "ERROR",
    ) -> None:
        self.heartbeat = heartbeat or SchedulerHeartbeat(owner=owner)
        self.owner = owner
        self.max_age_seconds = max_age_seconds
        self.severity = severity

    def publish(self, *, now: datetime | None = None) -> SchedulerHealth:
        """Publish a fresh scheduler heartbeat."""
        return self.heartbeat.publish(now=now)

    def check(self, *, session: Session | None = None, now: datetime | None = None) -> bool:
        """Return whether the scheduler heartbeat is stale and optionally log a system failure."""
        stale = self.heartbeat.is_stale(now=now, max_age_seconds=self.max_age_seconds)
        if stale and session is not None:
            session.add(
                SystemError(
                    component="scheduler_heartbeat",
                    provider_id=None,
                    severity=self.severity,
                    message=(
                        f"Scheduler heartbeat for {self.heartbeat.owner} is stale "
                        f"after {self.max_age_seconds} seconds."
                    ),
                    occurred_at=now or datetime.now(UTC),
                )
            )
            session.flush()
        return stale


__all__ = ["SchedulerHealth", "SchedulerHeartbeat", "SchedulerHealthMonitor"]

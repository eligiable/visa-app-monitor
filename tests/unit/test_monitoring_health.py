"""Health-monitor tests for a dedicated scheduler heartbeat path."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.database.models import SystemError
from app.monitoring import SchedulerHealthMonitor, SchedulerHeartbeat


def test_scheduler_heartbeat_tracks_staleness() -> None:
    heartbeat = SchedulerHeartbeat(owner="unit-test-scheduler")
    now = datetime(2026, 11, 9, 8, 0, tzinfo=UTC)

    assert heartbeat.is_stale(now=now, max_age_seconds=120) is True

    heartbeat.publish(now=now)
    assert heartbeat.is_stale(now=now + timedelta(seconds=10), max_age_seconds=120) is False
    assert heartbeat.is_stale(now=now + timedelta(seconds=121), max_age_seconds=120) is True


def test_scheduler_health_monitor_writes_system_error_when_stale(database_session: Session) -> None:
    heartbeat = SchedulerHeartbeat(owner="unit-test-scheduler")
    monitor = SchedulerHealthMonitor(heartbeat=heartbeat, max_age_seconds=120)
    now = datetime(2026, 11, 9, 8, 0, tzinfo=UTC)
    heartbeat.publish(now=now - timedelta(minutes=5))

    assert monitor.check(session=database_session, now=now) is True

    error = database_session.query(SystemError).one()
    assert error.component == "scheduler_heartbeat"
    assert error.severity == "ERROR"
    assert "stale" in error.message.lower()

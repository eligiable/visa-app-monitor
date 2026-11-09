"""Async and synchronous orchestrators for the dedicated monitoring worker."""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.monitoring.engine import MonitoringEngine
from app.notifications.configuration import (
    NotificationConfigurationError,
    load_notification_runtime,
)
from app.notifications.service import NotificationOutboxService

logger = logging.getLogger(__name__)


class MonitoringWorker:
    """Small dedicated worker loop that polls for due jobs on a fixed cadence."""

    def __init__(
        self,
        *,
        engine: MonitoringEngine,
        session_factory: Any,
        poll_interval_seconds: float = 1.0,
        owner: str | None = None,
        notification_encryption_key: str | None = None,
    ) -> None:
        self.engine = engine
        self.session_factory = session_factory
        self.poll_interval_seconds = poll_interval_seconds
        self.owner = owner or engine.owner
        self.notification_encryption_key = notification_encryption_key
        self._stopped = False

    def stop(self) -> None:
        """Request a graceful stop for the worker loop."""
        self._stopped = True

    def _run_once_sync(self, now: datetime | None) -> list[Any]:
        """Run one scheduler poll within a committed database transaction."""
        with self.session_factory.begin() as session:
            results = self.engine.run_due_jobs(session, now=now)
        if self.notification_encryption_key:
            with self.session_factory.begin() as session:
                try:
                    providers, _ = load_notification_runtime(
                        session,
                        self.notification_encryption_key,
                    )
                except NotificationConfigurationError:
                    logger.error(
                        "Notification settings could not be loaded; delivery was skipped",
                    )
                else:
                    NotificationOutboxService().process_due_notifications(
                        session,
                        providers=providers,
                        channels=providers.keys(),
                        now=now,
                    )
        return results

    async def run_once(self, *, now: datetime | None = None) -> list[Any]:
        """Execute one scheduler poll and return the job cycle outputs."""
        return await asyncio.to_thread(self._run_once_sync, now)

    async def run_forever(self, *, max_cycles: int | None = None) -> list[Any]:
        """Poll until stop() is called or the maximum cycle count is reached."""
        results: list[Any] = []
        cycles = 0
        while not self._stopped:
            if max_cycles is not None and cycles >= max_cycles:
                break
            poll_result = await self.run_once()
            if max_cycles is not None:
                results.extend(poll_result)
            cycles += 1
            await asyncio.sleep(self.poll_interval_seconds)
        return results


__all__ = ["MonitoringWorker"]

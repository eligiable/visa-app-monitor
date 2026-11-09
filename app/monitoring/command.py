"""Command-line entry point for the dedicated monitoring worker."""

import asyncio
import logging
import os
import signal
import socket

from app.config import Settings
from app.database.session import create_database_engine, create_session_factory
from app.monitoring.engine import MonitoringEngine
from app.monitoring.worker import MonitoringWorker
from app.providers.registry import create_default_registry


def main() -> None:
    """Run the database-backed monitoring loop until the process is stopped."""
    settings = Settings()
    logging.basicConfig(level=settings.log_level)
    database_engine = create_database_engine(
        settings.database_url.get_secret_value(),
        engine_options={"pool_pre_ping": True},
    )
    owner = f"{socket.gethostname()}:{os.getpid()}"
    worker = MonitoringWorker(
        engine=MonitoringEngine(
            registry=create_default_registry(),
            owner=owner,
            notification_encryption_key=(
                settings.integration_encryption_key.get_secret_value()
                if settings.integration_encryption_key
                else None
            ),
        ),
        session_factory=create_session_factory(database_engine),
        notification_encryption_key=(
            settings.integration_encryption_key.get_secret_value()
            if settings.integration_encryption_key
            else None
        ),
    )

    async def run() -> None:
        loop = asyncio.get_running_loop()
        for stop_signal in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(stop_signal, worker.stop)
        await worker.run_forever()

    try:
        asyncio.run(run())
    finally:
        database_engine.dispose()

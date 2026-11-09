"""Tests for the dedicated, transaction-owning scheduler worker."""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.database.base import Base
from app.database.models import (
    ApplicantOrigin,
    CheckResult,
    City,
    Country,
    MonitoringJob,
    Provider,
    VisaCategory,
    VisaCentre,
)
from app.database.session import create_database_engine, create_session_factory
from app.monitoring.engine import MonitoringEngine
from app.monitoring.worker import MonitoringWorker
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

"""Initial YAML validation and non-destructive seed tests."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.configuration.seeds import (
    SeedConfiguration,
    load_seed_configuration,
    seed_reference_data,
)
from app.configuration.command import _default_seed_file
from app.database.models import ApplicantOrigin, Provider

ROOT = Path(__file__).parents[2]


def test_default_seed_file_uses_working_directory(monkeypatch, tmp_path: Path) -> None:
    """Installed commands use the seed copied into the container working dir."""
    seed_file = tmp_path / "configs" / "seed.yaml"
    seed_file.parent.mkdir()
    seed_file.touch()
    monkeypatch.chdir(tmp_path)

    assert _default_seed_file() == seed_file


def test_project_seed_contains_initial_origins_countries_and_manual_providers(
    database_session: Session,
) -> None:
    """Initial configuration loads without enabling unverified automation."""
    configuration = load_seed_configuration(ROOT / "configs" / "seed.yaml")
    result = seed_reference_data(database_session, configuration)
    database_session.commit()

    assert result.inserted == {
        "origins": 2,
        "countries": 18,
        "providers": 3,
    }
    assert (
        database_session.scalar(
            select(Provider).where(Provider.provider_code == "vfs_global")
        ).access_mode
        == "MANUAL_CHECK_REQUIRED"
    )
    assert (
        database_session.scalar(
            select(Provider).where(Provider.provider_code == "bls_international")
        ).access_mode
        == "MANUAL_CHECK_REQUIRED"
    )
    assert (
        database_session.scalar(
            select(Provider).where(Provider.provider_code == "tlscontact")
        ).access_mode
        == "MANUAL_CHECK_REQUIRED"
    )


def test_seed_is_idempotent_and_preserves_existing_database_edits(
    database_session: Session,
) -> None:
    """A later seed run skips existing codes instead of overwriting records."""
    configuration = load_seed_configuration(ROOT / "configs" / "seed.yaml")
    seed_reference_data(database_session, configuration)
    database_session.flush()

    pakistan = database_session.scalar(
        select(ApplicantOrigin).where(ApplicantOrigin.code == "PK")
    )
    assert pakistan is not None
    pakistan.name = "Administrator-managed name"
    database_session.flush()

    second_result = seed_reference_data(database_session, configuration)

    assert second_result.inserted == {
        "origins": 0,
        "countries": 0,
        "providers": 0,
    }
    assert second_result.skipped == {
        "origins": 2,
        "countries": 18,
        "providers": 3,
    }
    assert pakistan.name == "Administrator-managed name"


def test_invalid_seed_shape_fails_explicitly() -> None:
    """Unexpected or missing seed fields are validation errors."""
    with pytest.raises(ValidationError):
        SeedConfiguration.model_validate(
            {
                "origins": [{"code": "PK"}],
                "countries": [],
                "providers": [],
            }
        )


def test_seed_country_code_rejects_non_iso_width() -> None:
    """Malformed country identifiers are rejected before database access."""
    with pytest.raises(ValidationError):
        SeedConfiguration.model_validate(
            {
                "origins": [],
                "countries": [{"code": "USA", "name": "United States"}],
                "providers": [],
            }
        )


def test_seed_rejects_duplicate_codes() -> None:
    """Duplicate YAML identifiers fail validation instead of causing inserts."""
    with pytest.raises(ValidationError, match="duplicate codes"):
        SeedConfiguration.model_validate(
            {
                "origins": [
                    {"code": "PK", "name": "Pakistan"},
                    {"code": "PK", "name": "Duplicate"},
                ],
                "countries": [],
                "providers": [],
            }
        )

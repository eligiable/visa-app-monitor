"""Validated, non-destructive loading of initial reference data."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import ApplicantOrigin, Country, Provider


class SeedEntry(BaseModel):
    """A stable-code/name record used for initial reference data."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[A-Z]{2}$")
    name: str = Field(min_length=1, max_length=160)


class ProviderSeedEntry(BaseModel):
    """A provider seed that defaults to a non-automated access mode."""

    model_config = ConfigDict(extra="forbid")

    provider_code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    access_mode: Literal[
        "AUTOMATED",
        "MANUAL_CHECK_REQUIRED",
        "DISABLED",
        "MAINTENANCE",
    ] = "MANUAL_CHECK_REQUIRED"
    enabled: bool = True


class SeedConfiguration(BaseModel):
    """The supported shape of the initial seed YAML document."""

    model_config = ConfigDict(extra="forbid")

    origins: list[SeedEntry]
    countries: list[SeedEntry]
    providers: list[ProviderSeedEntry]

    @model_validator(mode="after")
    def reject_duplicate_codes(self) -> "SeedConfiguration":
        """Reject ambiguous entries before attempting database writes."""
        collections = (
            ("origins", [entry.code for entry in self.origins]),
            ("countries", [entry.code for entry in self.countries]),
            ("providers", [entry.provider_code for entry in self.providers]),
        )
        for collection_name, codes in collections:
            if len(codes) != len(set(codes)):
                raise ValueError(f"{collection_name} contains duplicate codes")
        return self


@dataclass(frozen=True)
class SeedResult:
    """Counts of newly created and already-present seed records."""

    inserted: dict[str, int]
    skipped: dict[str, int]


def load_seed_configuration(path: str | Path) -> SeedConfiguration:
    """Load and validate seed YAML; malformed input raises an explicit error."""
    with Path(path).open("r", encoding="utf-8") as seed_file:
        raw_configuration = yaml.safe_load(seed_file)
    return SeedConfiguration.model_validate(raw_configuration)


def seed_reference_data(
    session: Session,
    configuration: SeedConfiguration,
) -> SeedResult:
    """Insert missing reference records without changing existing database data.

    The caller owns the transaction and must commit or roll it back.
    """
    inserted = {"origins": 0, "countries": 0, "providers": 0}
    skipped = {"origins": 0, "countries": 0, "providers": 0}

    for entry in configuration.origins:
        if (
            session.scalar(
                select(ApplicantOrigin.id).where(ApplicantOrigin.code == entry.code)
            )
            is None
        ):
            session.add(ApplicantOrigin(code=entry.code, name=entry.name))
            inserted["origins"] += 1
        else:
            skipped["origins"] += 1

    for entry in configuration.countries:
        if (
            session.scalar(select(Country.id).where(Country.country_code == entry.code))
            is None
        ):
            session.add(
                Country(country_code=entry.code, name=entry.name),
            )
            inserted["countries"] += 1
        else:
            skipped["countries"] += 1

    for entry in configuration.providers:
        if (
            session.scalar(
                select(Provider.id).where(
                    Provider.provider_code == entry.provider_code,
                )
            )
            is None
        ):
            session.add(
                Provider(
                    provider_code=entry.provider_code,
                    name=entry.name,
                    access_mode=entry.access_mode,
                    enabled=entry.enabled,
                ),
            )
            inserted["providers"] += 1
        else:
            skipped["providers"] += 1

    session.flush()
    return SeedResult(inserted=inserted, skipped=skipped)

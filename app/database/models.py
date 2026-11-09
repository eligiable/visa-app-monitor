"""Relational schema for reference data, monitoring, audit, and delivery."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


def utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware value."""
    return datetime.now(UTC)


class TimestampMixin:
    """Common creation and modification timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class Country(TimestampMixin, Base):
    __tablename__ = "countries"
    __table_args__ = (
        CheckConstraint("length(country_code) = 2", name="country_code_length"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ApplicantOrigin(TimestampMixin, Base):
    __tablename__ = "applicant_origins"
    __table_args__ = (CheckConstraint("length(code) = 2", name="origin_code_length"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(2), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class City(TimestampMixin, Base):
    __tablename__ = "cities"
    __table_args__ = (
        UniqueConstraint("country_id", "name"),
        UniqueConstraint("id", "country_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Provider(TimestampMixin, Base):
    __tablename__ = "providers"
    __table_args__ = (
        CheckConstraint(
            "access_mode IN ('AUTOMATED', 'MANUAL_CHECK_REQUIRED', "
            "'DISABLED', 'MAINTENANCE')",
            name="access_mode",
        ),
        CheckConstraint(
            "health_status IN ('HEALTHY', 'DEGRADED', 'UNHEALTHY', 'UNKNOWN')",
            name="health_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    provider_code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    access_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="MANUAL_CHECK_REQUIRED",
    )
    terms_url: Mapped[str | None] = mapped_column(String(2048))
    documentation_url: Mapped[str | None] = mapped_column(String(2048))
    health_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="UNKNOWN",
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class VisaCentre(TimestampMixin, Base):
    __tablename__ = "visa_centres"
    __table_args__ = (
        UniqueConstraint("city_id", "provider_id", "name"),
        UniqueConstraint("id", "city_id", "provider_id"),
        CheckConstraint(
            "access_mode IN ('AUTOMATED', 'MANUAL_CHECK_REQUIRED', "
            "'DISABLED', 'MAINTENANCE')",
            name="access_mode",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    city_id: Mapped[int] = mapped_column(
        ForeignKey("cities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("providers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    official_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    access_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="MANUAL_CHECK_REQUIRED",
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class VisaCategory(TimestampMixin, Base):
    __tablename__ = "visa_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    category_code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Administrator(TimestampMixin, Base):
    __tablename__ = "administrators"
    __table_args__ = (CheckConstraint("role IN ('ADMIN', 'STAFF')", name="role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="STAFF")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdministratorSession(Base):
    __tablename__ = "administrator_sessions"
    __table_args__ = (Index("ix_administrator_sessions_expires_at", "expires_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    administrator_id: Mapped[int] = mapped_column(
        ForeignKey("administrators.id", ondelete="RESTRICT"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    csrf_token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthRateLimit(TimestampMixin, Base):
    __tablename__ = "auth_rate_limits"
    __table_args__ = (
        CheckConstraint("failure_count >= 0", name="nonnegative_failure_count"),
        Index("ix_auth_rate_limits_updated_at", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderPermissionRecord(TimestampMixin, Base):
    __tablename__ = "provider_permission_records"
    __table_args__ = (
        CheckConstraint(
            "approval_status IN ('PENDING', 'APPROVED', 'REVOKED', 'EXPIRED')",
            name="approval_status",
        ),
        CheckConstraint(
            "approval_status != 'APPROVED' OR "
            "(verified_at IS NOT NULL AND review_due_at IS NOT NULL AND "
            "responsible_administrator_id IS NOT NULL)",
            name="approved_record_has_reviewer",
        ),
        Index(
            "ix_provider_permission_records_provider_review_due",
            "provider_id",
            "approval_status",
            "review_due_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("providers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    official_source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    terms_url: Mapped[str | None] = mapped_column(String(2048))
    robots_txt_url: Mapped[str | None] = mapped_column(String(2048))
    api_documentation_url: Mapped[str | None] = mapped_column(String(2048))
    permitted_access_method: Mapped[str] = mapped_column(String(500), nullable=False)
    request_limits: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responsible_administrator_id: Mapped[int | None] = mapped_column(
        ForeignKey("administrators.id", ondelete="RESTRICT"),
    )
    approval_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="PENDING",
    )
    evidence_reference: Mapped[str | None] = mapped_column(String(2048))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MonitoringJob(TimestampMixin, Base):
    __tablename__ = "monitoring_jobs"
    __table_args__ = (
        UniqueConstraint(
            "origin_id",
            "destination_country_id",
            "city_id",
            "visa_centre_id",
            "category_id",
            "appointment_type",
        ),
        ForeignKeyConstraint(
            ["city_id", "destination_country_id"],
            ["cities.id", "cities.country_id"],
            name="fk_monitoring_jobs_city_country",
        ),
        ForeignKeyConstraint(
            ["visa_centre_id", "city_id", "provider_id"],
            ["visa_centres.id", "visa_centres.city_id", "visa_centres.provider_id"],
            name="fk_monitoring_jobs_visa_centre_city_provider",
        ),
        CheckConstraint(
            "access_mode IN ('AUTOMATED', 'MANUAL_CHECK_REQUIRED', "
            "'DISABLED', 'MAINTENANCE')",
            name="access_mode",
        ),
        CheckConstraint(
            "execution_status IN ('NOT_RUN', 'SUCCEEDED', 'SOURCE_ERROR', "
            "'SKIPPED_RESTRICTED')",
            name="execution_status",
        ),
        CheckConstraint(
            "availability_status IS NULL OR "
            "availability_status IN ('AVAILABLE', 'UNAVAILABLE', 'UNKNOWN')",
            name="availability_status",
        ),
        CheckConstraint("polling_interval > 0", name="positive_polling_interval"),
        CheckConstraint("jitter_seconds >= 0", name="nonnegative_jitter"),
        CheckConstraint(
            "(lock_owner IS NULL AND lock_expires_at IS NULL) OR "
            "(lock_owner IS NOT NULL AND lock_expires_at IS NOT NULL)",
            name="lock_owner_expiry_pair",
        ),
        Index("ix_monitoring_jobs_due", "enabled", "next_check_at"),
        Index("ix_monitoring_jobs_lock_expiry", "lock_expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    origin_id: Mapped[int] = mapped_column(
        ForeignKey("applicant_origins.id", ondelete="RESTRICT"),
        nullable=False,
    )
    destination_country_id: Mapped[int] = mapped_column(Integer, nullable=False)
    city_id: Mapped[int] = mapped_column(Integer, nullable=False)
    visa_centre_id: Mapped[int] = mapped_column(Integer, nullable=False)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("visa_categories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("providers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    appointment_type: Mapped[str] = mapped_column(String(120), nullable=False)
    official_source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    polling_interval: Mapped[int] = mapped_column(Integer, nullable=False)
    jitter_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    access_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="MANUAL_CHECK_REQUIRED",
    )
    execution_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="NOT_RUN",
    )
    availability_status: Mapped[str | None] = mapped_column(String(16))
    initial_available_alert_policy: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lock_owner: Mapped[str | None] = mapped_column(String(160))
    lock_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CheckResult(Base):
    __tablename__ = "check_results"
    __table_args__ = (
        CheckConstraint(
            "execution_status IN ('SUCCEEDED', 'SOURCE_ERROR', 'SKIPPED_RESTRICTED')",
            name="execution_status",
        ),
        CheckConstraint(
            "availability_status IS NULL OR "
            "availability_status IN ('AVAILABLE', 'UNAVAILABLE', 'UNKNOWN')",
            name="availability_status",
        ),
        CheckConstraint(
            "execution_status = 'SUCCEEDED' OR availability_status IS NULL",
            name="failed_execution_has_no_availability",
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="duration_nonnegative"
        ),
        Index("ix_check_results_job_checked_at", "job_id", "checked_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("monitoring_jobs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider_permission_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("provider_permission_records.id", ondelete="RESTRICT"),
    )
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    execution_status: Mapped[str] = mapped_column(String(24), nullable=False)
    availability_status: Mapped[str | None] = mapped_column(String(16))
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    response_code: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(String(1000))


class ManualVerification(Base):
    __tablename__ = "manual_verifications"
    __table_args__ = (
        CheckConstraint(
            "recorded_status IN ('AVAILABLE', 'UNAVAILABLE')",
            name="verified_availability_status",
        ),
        Index("ix_manual_verifications_job_verified_at", "job_id", "verified_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("monitoring_jobs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    operator_administrator_id: Mapped[int] = mapped_column(
        ForeignKey("administrators.id", ondelete="RESTRICT"),
        nullable=False,
    )
    recorded_status: Mapped[str] = mapped_column(String(16), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    official_source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    internal_notes: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class AvailabilityHistory(Base):
    __tablename__ = "availability_history"
    __table_args__ = (
        CheckConstraint(
            "previous_status IS NULL OR previous_status IN "
            "('AVAILABLE', 'UNAVAILABLE', 'UNKNOWN')",
            name="previous_status",
        ),
        CheckConstraint(
            "new_status IN ('AVAILABLE', 'UNAVAILABLE')",
            name="new_status",
        ),
        CheckConstraint(
            "(source_check_result_id IS NOT NULL AND manual_verification_id IS NULL) "
            "OR (source_check_result_id IS NULL AND manual_verification_id IS NOT NULL)",
            name="one_source_reference",
        ),
        UniqueConstraint("source_check_result_id"),
        UniqueConstraint("manual_verification_id"),
        Index("ix_availability_history_job_detected_at", "job_id", "detected_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("monitoring_jobs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    previous_status: Mapped[str | None] = mapped_column(String(16))
    new_status: Mapped[str] = mapped_column(String(16), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    source_check_result_id: Mapped[int | None] = mapped_column(
        ForeignKey("check_results.id", ondelete="RESTRICT"),
    )
    manual_verification_id: Mapped[int | None] = mapped_column(
        ForeignKey("manual_verifications.id", ondelete="RESTRICT"),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_occurred_at", "occurred_at"),
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    administrator_id: Mapped[int | None] = mapped_column(
        ForeignKey("administrators.id", ondelete="RESTRICT"),
    )
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(120))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    safe_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class AlertEvent(Base):
    __tablename__ = "alert_events"
    __table_args__ = (
        CheckConstraint(
            "availability_status = 'AVAILABLE'",
            name="alert_requires_available",
        ),
        CheckConstraint(
            "verification_source IN ('AUTOMATED', 'MANUAL')",
            name="verification_source",
        ),
        UniqueConstraint("availability_history_id"),
        UniqueConstraint("deduplication_key"),
        Index("ix_alert_events_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("monitoring_jobs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    availability_history_id: Mapped[int] = mapped_column(
        ForeignKey("availability_history.id", ondelete="RESTRICT"),
        nullable=False,
    )
    availability_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="AVAILABLE",
    )
    verification_source: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    deduplication_key: Mapped[str] = mapped_column(String(255), nullable=False)


class NotificationOutboxItem(Base):
    __tablename__ = "notification_outbox_items"
    __table_args__ = (
        CheckConstraint(
            "channel IN ('TELEGRAM', 'EMAIL')",
            name="channel",
        ),
        CheckConstraint(
            "state IN ('PENDING', 'PROCESSING', 'DELIVERED', 'FAILED')",
            name="state",
        ),
        UniqueConstraint("alert_event_id", "channel", "recipient_reference"),
        Index("ix_notification_outbox_state_next_attempt", "state", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_event_id: Mapped[int] = mapped_column(
        ForeignKey("alert_events.id", ondelete="RESTRICT"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    recipient_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")


class NotificationIntegration(TimestampMixin, Base):
    __tablename__ = "notification_integrations"
    __table_args__ = (
        CheckConstraint(
            "channel IN ('TELEGRAM', 'EMAIL')",
            name="channel",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    encrypted_configuration: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by_administrator_id: Mapped[int] = mapped_column(
        ForeignKey("administrators.id", ondelete="RESTRICT"),
        nullable=False,
    )


class NotificationDeliveryAttempt(Base):
    __tablename__ = "notification_delivery_attempts"
    __table_args__ = (
        CheckConstraint(
            "delivery_status IN ('SUCCEEDED', 'FAILED')",
            name="delivery_status",
        ),
        CheckConstraint("attempt_number > 0", name="positive_attempt_number"),
        UniqueConstraint("outbox_item_id", "attempt_number"),
        Index("ix_notification_delivery_attempts_attempted_at", "attempted_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    outbox_item_id: Mapped[int] = mapped_column(
        ForeignKey("notification_outbox_items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    delivery_status: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_message_reference: Mapped[str | None] = mapped_column(String(255))
    safe_error_detail: Mapped[str | None] = mapped_column(String(1000))


class SystemError(Base):
    __tablename__ = "system_errors"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('INFO', 'WARNING', 'ERROR', 'CRITICAL')",
            name="severity",
        ),
        Index("ix_system_errors_occurred_at", "occurred_at"),
        Index("ix_system_errors_provider_occurred_at", "provider_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    component: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_id: Mapped[int | None] = mapped_column(
        ForeignKey("providers.id", ondelete="RESTRICT"),
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

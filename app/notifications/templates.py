"""Notification message templates for alert delivery."""

from __future__ import annotations

from app.database.models import AlertEvent, MonitoringJob


class NotificationTemplateRenderer:
    """Render staff-facing alert notifications from alert metadata."""

    @staticmethod
    def render_alert_message(alert: AlertEvent, job: MonitoringJob | None = None) -> str:
        """Build a plain-text message for appointment availability alerts."""
        job = job or MonitoringJob()
        lines = [
            "SRM Visa Appointment Alert",
            "",
            f"Status: {alert.availability_status}",
            f"Job ID: {alert.job_id}",
            f"Appointment type: {job.appointment_type or 'N/A'}",
            f"Official source: {job.official_source_url or 'N/A'}",
            f"Verification source: {alert.verification_source}",
            "",
            "This alert indicates an available appointment has been verified.",
        ]
        return "\n".join(lines)

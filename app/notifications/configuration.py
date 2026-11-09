"""Encrypted notification integration configuration helpers."""

from __future__ import annotations

import json
import logging
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import NotificationIntegration
from app.notifications.providers import SMTPEmailProvider, TelegramNotificationProvider

logger = logging.getLogger(__name__)


class NotificationConfigurationError(ValueError):
    """Raised when integration configuration cannot be safely loaded."""


def _fernet(encryption_key: str | None) -> Fernet:
    if not encryption_key:
        raise NotificationConfigurationError(
            "INTEGRATION_ENCRYPTION_KEY is not configured",
        )
    try:
        return Fernet(encryption_key.encode("ascii"))
    except (UnicodeEncodeError, ValueError) as error:
        raise NotificationConfigurationError(
            "INTEGRATION_ENCRYPTION_KEY is invalid",
        ) from error


def encrypt_configuration(
    configuration: dict[str, Any],
    encryption_key: str | None,
) -> str:
    """Serialize and encrypt configuration before database persistence."""
    payload = json.dumps(configuration, sort_keys=True, separators=(",", ":"))
    return _fernet(encryption_key).encrypt(payload.encode("utf-8")).decode("ascii")


def decrypt_configuration(
    encrypted_configuration: str,
    encryption_key: str | None,
) -> dict[str, Any]:
    """Decrypt one settings blob without exposing cryptography errors to callers."""
    try:
        payload = _fernet(encryption_key).decrypt(
            encrypted_configuration.encode("ascii"),
        )
        configuration = json.loads(payload)
    except (InvalidToken, UnicodeEncodeError, json.JSONDecodeError) as error:
        raise NotificationConfigurationError(
            "Integration settings cannot be decrypted; verify the encryption key",
        ) from error
    if not isinstance(configuration, dict):
        raise NotificationConfigurationError("Integration settings are invalid")
    return configuration


def get_integration_configuration(
    session: Session,
    channel: str,
    encryption_key: str | None,
) -> tuple[NotificationIntegration | None, dict[str, Any] | None]:
    """Load a channel record and decrypt it when one exists."""
    integration = session.scalar(
        select(NotificationIntegration).where(
            NotificationIntegration.channel == channel,
        )
    )
    if integration is None:
        return None, None
    return integration, decrypt_configuration(
        integration.encrypted_configuration,
        encryption_key,
    )


def load_notification_runtime(
    session: Session,
    encryption_key: str | None,
) -> tuple[dict[str, object], dict[str, list[str]]]:
    """Build enabled sender clients and recipients for worker processing."""
    providers: dict[str, object] = {}
    configurations = load_enabled_configurations(session, encryption_key)
    recipients: dict[str, list[str]] = {}
    for channel, configuration in configurations.items():
        channel_recipients = configuration.get("recipients", [])
        if not isinstance(channel_recipients, list):
            logger.error(
                "Invalid recipients for notification channel=%s; channel skipped",
                channel,
            )
            continue
        recipients[channel] = [str(recipient) for recipient in channel_recipients]
        if channel == "TELEGRAM":
            providers[channel] = TelegramNotificationProvider(
                bot_token=configuration.get("bot_token"),
            )
        elif channel == "EMAIL":
            providers[channel] = SMTPEmailProvider(
                host=configuration.get("smtp_host"),
                port=configuration.get("smtp_port", 587),
                username=configuration.get("smtp_username"),
                password=configuration.get("smtp_password"),
                from_email=configuration.get("smtp_from_email"),
                use_tls=configuration.get("smtp_use_tls", True),
            )
        else:
            raise NotificationConfigurationError(
                f"Unsupported notification channel {channel}",
            )
    return providers, recipients


def load_enabled_configurations(
    session: Session,
    encryption_key: str | None,
) -> dict[str, dict[str, Any]]:
    """Decrypt configuration for enabled channels, or return none if unkeyed."""
    if not encryption_key:
        return {}
    integrations = session.scalars(
        select(NotificationIntegration).where(
            NotificationIntegration.enabled.is_(True),
        )
    ).all()
    configurations = {}
    for integration in integrations:
        try:
            configurations[integration.channel] = decrypt_configuration(
                integration.encrypted_configuration,
                encryption_key,
            )
        except NotificationConfigurationError:
            logger.error(
                "Integration settings could not be decrypted for channel=%s; channel skipped",
                integration.channel,
            )
    return configurations


def load_notification_recipients(
    session: Session,
    encryption_key: str | None,
) -> dict[str, list[str]]:
    """Return recipients for currently enabled and decryptable channels."""
    recipients: dict[str, list[str]] = {}
    for channel, configuration in load_enabled_configurations(
        session,
        encryption_key,
    ).items():
        channel_recipients = configuration.get("recipients", [])
        if not isinstance(channel_recipients, list):
            logger.error(
                "Invalid recipients for notification channel=%s; channel skipped",
                channel,
            )
            continue
        recipients[channel] = [str(recipient) for recipient in channel_recipients]
    return recipients
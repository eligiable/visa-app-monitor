"""Validated application settings loaded from environment variables."""

from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings; secrets are never read from YAML files."""

    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
        case_sensitive=False,
    )

    database_url: SecretStr
    session_security_key: SecretStr
    public_origin: str | None = None
    session_cookie_name: str = "__Host-srm_session"
    session_cookie_secure: bool = True
    session_max_age_seconds: int = 43_200
    auth_rate_limit_max_attempts: int = 5
    auth_rate_limit_window_seconds: int = 900
    auth_rate_limit_retention_seconds: int = 172_800
    telegram_bot_token: SecretStr | None = None
    telegram_default_chat_id: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from_email: str | None = None
    smtp_use_tls: bool = True
    notification_default_channels: list[str] = ["EMAIL"]
    log_level: str = "INFO"

    @field_validator("session_security_key")
    @classmethod
    def require_long_session_security_key(cls, value: SecretStr) -> SecretStr:
        """Require enough key material for HMAC-based identity hashing."""
        if len(value.get_secret_value().encode("utf-8")) < 32:
            raise ValueError("SESSION_SECURITY_KEY must contain at least 32 bytes")
        return value

    @field_validator("session_cookie_name")
    @classmethod
    def validate_cookie_name(cls, value: str) -> str:
        """Use the secure __Host- cookie prefix whenever cookies are secure."""
        if not value or any(character in value for character in " ;,\r\n\t"):
            raise ValueError("SESSION_COOKIE_NAME contains invalid characters")
        return value

    @field_validator("smtp_port")
    @classmethod
    def validate_smtp_port(cls, value: int) -> int:
        """Keep SMTP ports within the standard TCP range."""
        if not 1 <= value <= 65535:
            raise ValueError("SMTP_PORT must be between 1 and 65535")
        return value

    @field_validator("notification_default_channels")
    @classmethod
    def validate_notification_default_channels(cls, value: list[str]) -> list[str]:
        """Restrict notification channels to known delivery methods."""
        allowed = {"EMAIL", "TELEGRAM"}
        normalized = []
        for channel in value:
            candidate = channel.strip().upper()
            if candidate not in allowed:
                raise ValueError("unsupported notification channel")
            normalized.append(candidate)
        return normalized

    @model_validator(mode="after")
    def require_host_cookie_prefix_when_secure(self) -> "Settings":
        """Enforce browser __Host- cookie protections in secure deployments."""
        if self.session_cookie_secure and not self.session_cookie_name.startswith(
            "__Host-",
        ):
            raise ValueError(
                "secure session cookies must use the __Host- cookie prefix",
            )
        if (
            self.session_cookie_secure
            and self.public_origin
            and urlsplit(self.public_origin).scheme.lower() != "https"
        ):
            raise ValueError(
                "PUBLIC_ORIGIN must use HTTPS when session cookies are secure"
            )
        return self

    @field_validator("public_origin")
    @classmethod
    def validate_public_origin(cls, value: str | None) -> str | None:
        """Accept only a bare HTTP(S) origin for reverse-proxy deployments."""
        if value is None:
            return None
        try:
            parts = urlsplit(value)
            _ = parts.port
        except ValueError as error:
            raise ValueError("PUBLIC_ORIGIN must be a valid HTTP(S) origin") from error
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.path not in {"", "/"}
            or parts.query
            or parts.fragment
            or parts.username
            or parts.password
        ):
            raise ValueError("PUBLIC_ORIGIN must be a bare HTTP(S) origin")
        return value.rstrip("/")

    @field_validator("session_max_age_seconds")
    @classmethod
    def validate_session_lifetime(cls, value: int) -> int:
        """Reject unusable or excessively long administrator sessions."""
        if not 60 <= value <= 86_400:
            raise ValueError("SESSION_MAX_AGE_SECONDS must be between 60 and 86400")
        return value

    @field_validator("auth_rate_limit_max_attempts")
    @classmethod
    def validate_login_attempt_limit(cls, value: int) -> int:
        """Require a positive attempt limit."""
        if value < 1:
            raise ValueError("AUTH_RATE_LIMIT_MAX_ATTEMPTS must be positive")
        return value

    @field_validator("auth_rate_limit_window_seconds")
    @classmethod
    def validate_rate_limit_window(cls, value: int) -> int:
        """Keep the login rate-limit window bounded."""
        if not 60 <= value <= 86_400:
            raise ValueError(
                "AUTH_RATE_LIMIT_WINDOW_SECONDS must be between 60 and 86400",
            )
        return value

    @field_validator("auth_rate_limit_retention_seconds")
    @classmethod
    def validate_rate_limit_retention(cls, value: int) -> int:
        """Require enough retention to cover the configured rate window."""
        if value < 86_400:
            raise ValueError("AUTH_RATE_LIMIT_RETENTION_SECONDS must be at least 86400")
        return value

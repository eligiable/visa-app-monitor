"""Telegram and SMTP providers used by the notification outbox."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

import httpx


class TelegramNotificationProvider:
    """Send text messages via the Telegram Bot API."""

    channel = "TELEGRAM"

    def __init__(self, *, bot_token: str | None, timeout: float = 10.0) -> None:
        self.bot_token = bot_token
        self.timeout = timeout

    def send(self, *, message: str, recipient: str) -> str:
        """Send a message to a Telegram chat ID."""
        if not self.bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not configured")

        response = httpx.post(
            f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
            json={
                "chat_id": recipient,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Telegram API failure: {response.text[:500]}")

        payload = response.json()
        result = payload.get("result", {}) if isinstance(payload, dict) else {}
        message_id = result.get("message_id")
        if message_id is None:
            return f"telegram:{response.status_code}"
        return f"telegram:{message_id}"


class SMTPEmailProvider:
    """Send text email notifications using SMTP."""

    channel = "EMAIL"

    def __init__(
        self,
        *,
        host: str | None,
        port: int = 587,
        username: str | None = None,
        password: str | None = None,
        from_email: str | None = None,
        use_tls: bool = True,
        timeout: float = 10.0,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_email = from_email
        self.use_tls = use_tls
        self.timeout = timeout

    def send(self, *, message: str, recipient: str) -> str:
        """Send a plain-text SMTP email to a recipient."""
        if not self.host or not self.from_email:
            raise ValueError("SMTP host and sender address must be configured")

        email = EmailMessage()
        email["Subject"] = "SRM Visa Appointment Alert"
        email["From"] = self.from_email
        email["To"] = recipient
        email.set_content(message)

        with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as server:
            if self.use_tls:
                server.starttls()
            if self.username and self.password:
                server.login(self.username, self.password)
            server.send_message(email)

        return f"smtp:{recipient}"

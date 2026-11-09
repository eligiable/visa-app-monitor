"""Structured JSON logging with no implicit request or secret fields."""

import json
import logging
from datetime import UTC, datetime


class JsonLogFormatter(logging.Formatter):
    """Serialize standard log records as compact JSON."""

    def format(self, record: logging.LogRecord) -> str:
        """Render only timestamp, severity, logger name, and safe message."""
        return json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            },
            ensure_ascii=True,
        )


def configure_logging(level: str) -> None:
    """Configure one JSON stream handler for application logs."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level.upper())
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

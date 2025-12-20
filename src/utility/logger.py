import logging
import sys
from datetime import datetime


class SimpleFormatter(logging.Formatter):
    """Simple log formatter: timestamp | level | logger | message"""

    def format(self, record):
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')
        formatted = f"{timestamp} | {record.levelname} | {record.name} | {record.getMessage()}"

        if record.exc_info:
            formatted += "\n" + self.formatException(record.exc_info)

        return formatted


class SimpleLogger:
    """Simple logger wrapper."""

    def __init__(self, name: str):
        self.name = name
        self._logger = logging.getLogger(name)
        self._is_configured = False

    def _ensure_configured(self):
        """Configure logger on first use."""
        if self._is_configured:
            return

        self._logger.setLevel(logging.INFO)
        self._logger.handlers.clear()

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(SimpleFormatter())
        self._logger.addHandler(console_handler)

        self._is_configured = True

    def debug(self, message: str):
        self._ensure_configured()
        self._logger.debug(message)

    def info(self, message: str):
        self._ensure_configured()
        self._logger.info(message)

    def warning(self, message: str):
        self._ensure_configured()
        self._logger.warning(message)

    def error(self, message: str):
        self._ensure_configured()
        self._logger.error(message)

    def exception(self, message: str):
        self._ensure_configured()
        self._logger.exception(message)


def get_logger(name: str) -> SimpleLogger:
    """Get a logger instance by name."""
    return SimpleLogger(name)

"""Structured-ish logging. Request bodies are never logged anywhere in this project."""

from __future__ import annotations

import json
import logging
import sys


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"), "level": record.levelname,
                   "logger": record.name, "message": record.getMessage()}
        if record.exc_info:
            payload["exception"] = record.exc_info[0].__name__ if record.exc_info[0] else None  # type only: no values
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

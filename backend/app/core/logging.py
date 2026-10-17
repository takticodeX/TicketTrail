"""JSON logging with secret scrubbing (spec section 10).

Every record passes through SecretScrubber before it is written: Authorization
headers, credentials inside URLs, and values of known secret fields are masked.
"""

import json
import logging
import re
from datetime import UTC, datetime

MASK = "***"

_PATTERNS = [
    # Authorization: Basic xxx / Bearer xxx (headers, curl-style dumps, reprs)
    re.compile(r"(?i)(authorization['\"]?\s*[:=]\s*['\"]?(?:basic|bearer|token)\s+)[^\s'\",}]+"),
    re.compile(r"(?i)\b((?:basic|bearer)\s+)[A-Za-z0-9+/=._~-]{16,}"),
    # https://user:password@host and https://token@host
    re.compile(r"(?i)(\bhttps?://)[^/\s:@]+(?::[^/\s@]*)?@"),
    # "secret": "...", pat=..., password: ... (JSON, kwargs, query strings)
    re.compile(
        r"(?i)([\"']?\b(?:secret|secret_enc|pat|pat_enc|password|new_password|current_password|"
        r"token|access_token|refresh_token|tt_refresh|api_key|jwt_secret|encryption_key)\b[\"']?"
        r"\s*[:=]\s*[\"']?)[^\s\"'&,}]+"
    ),
]


def scrub(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(lambda m: m.group(1) + MASK, text)
    return text


class SecretScrubber(logging.Filter):
    """Masks secrets in the final message and in exception text."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = scrub(message)
        if cleaned != message:
            record.msg, record.args = cleaned, None
        if record.exc_info:
            record.exc_text = scrub(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_text:
            entry["exc_info"] = record.exc_text
        elif record.exc_info:
            entry["exc_info"] = scrub(self.formatException(record.exc_info))
        return json.dumps(entry, ensure_ascii=False)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(SecretScrubber())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # Route uvicorn's and Celery's own loggers through the JSON handler on the root.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "celery"):
        named = logging.getLogger(name)
        named.handlers = []
        named.propagate = True

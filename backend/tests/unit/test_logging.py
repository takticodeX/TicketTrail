import json
import logging

import pytest

from app.core.logging import JsonFormatter, SecretScrubber, scrub


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("Authorization: Basic cGF0OnMzY3IzdC10b2tlbg==", "cGF0OnMzY3IzdC10b2tlbg=="),
        (
            "headers={'Authorization': 'Bearer eyJhbGciOiJIUzI1NiJ9.abc.def'}",
            "eyJhbGciOiJIUzI1NiJ9",
        ),
        ("fatal: unable to access 'https://user:hunter2@git.example.com/r.git'", "hunter2"),
        ("cloning https://ghp_abcdef123456@github.com/acme/app", "ghp_abcdef123456"),
        ('{"secret": "ghp_supersecret", "name": "x"}', "ghp_supersecret"),
        ("pat=azure-pat-value&x=1", "azure-pat-value"),
        ("password: correct-horse-battery", "correct-horse-battery"),
        ("tt_refresh=eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9", "eyJ0eXAiOiJKV1Qi"),
    ],
)
def test_scrub_masks_secrets(text: str, secret: str) -> None:
    cleaned = scrub(text)
    assert secret not in cleaned
    assert "***" in cleaned


def test_scrub_leaves_ordinary_text_alone() -> None:
    text = "Started run 1234 for project abc: 677 commits, AB#12 posted"
    assert scrub(text) == text


def _render(record: logging.LogRecord) -> dict[str, str]:
    SecretScrubber().filter(record)
    result: dict[str, str] = json.loads(JsonFormatter().format(record))
    return result


def test_filter_scrubs_formatted_arguments() -> None:
    record = logging.LogRecord(
        "x",
        logging.INFO,
        __file__,
        1,
        "Calling %s with %s",
        ("https://u:p4ss@h/x", "pat=s3cr3t"),
        None,
    )
    message = _render(record)["message"]
    assert "p4ss" not in message
    assert "s3cr3t" not in message


def test_filter_scrubs_exception_text() -> None:
    try:
        raise RuntimeError("Authorization: Basic c2VjcmV0LXZhbHVlLTEyMzQ1Ng==")
    except RuntimeError:
        import sys

        record = logging.LogRecord("x", logging.ERROR, __file__, 1, "failed", None, sys.exc_info())
    rendered = _render(record)
    assert "c2VjcmV0LXZhbHVlLTEyMzQ1Ng==" not in rendered["exc_info"]
    assert "RuntimeError" in rendered["exc_info"]

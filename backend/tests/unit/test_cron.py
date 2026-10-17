import pytest

from app.core.cron import InvalidCronError, validate_cron


@pytest.mark.parametrize(
    "expression",
    [
        "*/15 * * * *",  # UI preset: every 15 minutes
        "0 * * * *",  # hourly
        "0 8 * * *",  # daily at 08:00
        "0 8 * * 1-5",  # weekdays at 08:00
        "*/5 * * * *",  # exactly the minimum
        "30 2 1 * *",
    ],
)
def test_valid_expressions(expression: str) -> None:
    assert validate_cron(expression, min_interval_minutes=5) == expression


def test_whitespace_is_normalised() -> None:
    assert validate_cron("  0   8 * *  1-5 ", min_interval_minutes=5) == "0 8 * * 1-5"


@pytest.mark.parametrize(
    "expression", ["* * * *", "0 0 * * * *", "@hourly", "", "0 8 * * MON-FRI extra"]
)
def test_needs_five_fields(expression: str) -> None:
    with pytest.raises(InvalidCronError, match="5 fields"):
        validate_cron(expression, min_interval_minutes=5)


@pytest.mark.parametrize("expression", ["61 * * * *", "0 25 * * *", "a b c d e"])
def test_invalid_values(expression: str) -> None:
    with pytest.raises(InvalidCronError, match="not a valid"):
        validate_cron(expression, min_interval_minutes=5)


@pytest.mark.parametrize(
    "expression",
    [
        "* * * * *",
        "*/4 * * * *",
        "0,1 8 * * *",  # two runs a minute apart once a day
        "0,2 0 1 * *",  # ...or once a month
    ],
)
def test_minimum_interval(expression: str) -> None:
    with pytest.raises(InvalidCronError, match="every 5 minutes"):
        validate_cron(expression, min_interval_minutes=5)


def test_minimum_interval_is_configurable() -> None:
    validate_cron("* * * * *", min_interval_minutes=1)
    with pytest.raises(InvalidCronError):
        validate_cron("*/15 * * * *", min_interval_minutes=30)

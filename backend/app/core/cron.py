"""Cron schedules: 5-field expressions with a minimum interval (spec section 7).

The frontend mirrors these rules in frontend/src/lib/schedule.ts.
"""

from datetime import UTC, datetime, timedelta

from croniter import croniter

# How far ahead the minimum-interval check looks.
_CHECK_RUNS = 1000
_CHECK_HORIZON = timedelta(days=400)


class InvalidCronError(ValueError):
    pass


def validate_cron(expression: str, *, min_interval_minutes: int) -> str:
    """Return the normalised expression, or raise InvalidCronError."""
    fields = expression.split()
    if len(fields) != 5:
        raise InvalidCronError("must have 5 fields: minute hour day-of-month month day-of-week")
    normalised = " ".join(fields)
    if not croniter.is_valid(normalised):
        raise InvalidCronError("is not a valid cron expression")

    start = datetime(2026, 1, 1, tzinfo=UTC)
    runs = croniter(normalised, start)
    previous: datetime = runs.get_next(datetime)
    minimum = timedelta(minutes=min_interval_minutes)
    for _ in range(_CHECK_RUNS):
        current: datetime = runs.get_next(datetime)
        if current - previous < minimum:
            raise InvalidCronError(
                f"must not run more often than every {min_interval_minutes} minutes"
            )
        if current - start > _CHECK_HORIZON:
            break
        previous = current
    return normalised

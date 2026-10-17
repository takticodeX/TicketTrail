from datetime import UTC, datetime

from app.core.cron import latest_slot, next_slot


def test_latest_slot_is_in_the_users_time_zone() -> None:
    # 08:00 in Rome is 06:00 UTC in October (summer time).
    now = datetime(2026, 10, 16, 6, 30, tzinfo=UTC)
    assert latest_slot("0 8 * * *", "Europe/Rome", now) == datetime(2026, 10, 16, 6, 0, tzinfo=UTC)
    assert latest_slot("0 8 * * *", "UTC", now) == datetime(2026, 10, 15, 8, 0, tzinfo=UTC)


def test_an_exact_hit_counts_as_due() -> None:
    now = datetime(2026, 10, 16, 6, 0, tzinfo=UTC)
    assert latest_slot("0 8 * * *", "Europe/Rome", now) == now


def test_next_slot_follows_daylight_saving_changes() -> None:
    # Rome leaves summer time on Sunday 25 October 2026: 08:00 becomes 07:00 UTC.
    before = next_slot("0 8 * * *", "Europe/Rome", datetime(2026, 10, 24, 12, 0, tzinfo=UTC))
    after = next_slot("0 8 * * *", "Europe/Rome", datetime(2026, 10, 25, 12, 0, tzinfo=UTC))
    assert before == datetime(2026, 10, 25, 7, 0, tzinfo=UTC)
    assert after == datetime(2026, 10, 26, 7, 0, tzinfo=UTC)


def test_every_five_minutes() -> None:
    now = datetime(2026, 10, 16, 6, 7, 30, tzinfo=UTC)
    assert latest_slot("*/5 * * * *", "UTC", now) == datetime(2026, 10, 16, 6, 5, tzinfo=UTC)
    assert next_slot("*/5 * * * *", "UTC", now) == datetime(2026, 10, 16, 6, 10, tzinfo=UTC)

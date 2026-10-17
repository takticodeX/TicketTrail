import pytest

from app.sync.parser import (
    DEFAULT_TICKET_PATTERN,
    InvalidPatternError,
    PatternTimeoutError,
    compile_ticket_pattern,
)


def ids(pattern: str, message: str) -> list[int]:
    return compile_ticket_pattern(pattern).extract(message)


def test_default_pattern() -> None:
    assert DEFAULT_TICKET_PATTERN == r"AB#(\d+)"
    assert ids(DEFAULT_TICKET_PATTERN, "Fix login AB#123") == [123]


def test_matching_is_case_insensitive() -> None:
    assert ids(DEFAULT_TICKET_PATTERN, "fix ab#7") == [7]


def test_searches_subject_and_body() -> None:
    message = "Refactor parser AB#1\n\nAlso touches AB#2 and AB#3."
    assert ids(DEFAULT_TICKET_PATTERN, message) == [1, 2, 3]


def test_ids_are_unique_in_first_seen_order() -> None:
    assert ids(DEFAULT_TICKET_PATTERN, "AB#5 AB#2 AB#5 ab#2") == [5, 2]


def test_no_match() -> None:
    assert ids(DEFAULT_TICKET_PATTERN, "chore: bump deps") == []


def test_zero_is_not_a_work_item() -> None:
    assert ids(DEFAULT_TICKET_PATTERN, "AB#0 AB#00 AB#9") == [9]


@pytest.mark.parametrize(
    ("pattern", "message", "expected"),
    [
        (r"#(\d+)", "closes #42, see #7", [42, 7]),
        (r"(?:fixes|refs)\s+#(\d+)", "Fixes #10, refs  #11, mentions #12", [10, 11]),
        (r"PROJ-(\d+)", "PROJ-99 proj-100", [99, 100]),
        (r"(?P<id>\d+)@(\w+)", "123@team", [123]),
        (r"(?<id>[0-9]{1,6})!", "45!", [45]),
        (r"(?i:task)\s*(\d+)", "TASK 8", [8]),
        (r"\[(\d+)\]", "[31] fix", [31]),
        (r"(?:[(]x[)])?#(\d+)", "(x)#5", [5]),
    ],
)
def test_spec_examples_and_other_valid_patterns(
    pattern: str, message: str, expected: list[int]
) -> None:
    assert ids(pattern, message) == expected


@pytest.mark.parametrize(
    ("pattern", "reason"),
    [
        ("", "empty"),
        (r"AB#\d+", "needs one capture group"),
        (r"(AB)#(\d+)", "exactly one capture group"),
        (r"AB#(\w+)", "digits only"),
        (r"AB#(\d+[a-z])", "digits only"),
        (r"AB#(.+)", "digits only"),
        (r"(?P<ticket>\d+)-(\d+)", "exactly one capture group"),
        (r"AB#(\d+", "not a valid regular expression"),
        ("a" * 501, "at most 500"),
    ],
)
def test_invalid_patterns(pattern: str, reason: str) -> None:
    with pytest.raises(InvalidPatternError, match=reason):
        compile_ticket_pattern(pattern)


def test_named_id_group_may_sit_next_to_other_groups() -> None:
    assert ids(r"(\w+)-(?P<id>\d+)", "PROJ-12") == [12]


# Catastrophic backtracking that the `regex` engine does not optimise away.
SLOW_PATTERN = r"(?:a|a)+#(\d+)"
SLOW_MESSAGE = "a" * 40 + "!"


def test_slow_matching_times_out_after_100_ms() -> None:
    pattern = compile_ticket_pattern(SLOW_PATTERN)
    with pytest.raises(PatternTimeoutError):
        pattern.extract(SLOW_MESSAGE)


def test_unicode_digits_are_ignored() -> None:
    assert ids(r"AB#(\d+)", "AB#١٢") == []

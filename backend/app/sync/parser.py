"""Ticket-reference patterns: validation and ID extraction (spec section 5).

A pattern is a Python regex with exactly one capture group, or a named group
(?P<id>...), and that group must capture digits only. It runs with the `regex`
package and a per-message timeout, case-insensitively, over the whole message.
The frontend mirrors the structural rules in frontend/src/lib/ticketPattern.ts.
"""

import re
from dataclasses import dataclass

import regex

DEFAULT_TICKET_PATTERN = r"AB#(\d+)"
MAX_PATTERN_LENGTH = 500
MATCH_TIMEOUT_SECONDS = 0.1
ID_GROUP_NAME = "id"

# The body of the ID group: \d or [0-9], optionally quantified.
_DIGITS_ONLY = re.compile(r"(?:\\d|\[0-9\]|\[\\d\])(?:\+|\*|\?|\{\d+(?:,\d*)?\})?\??")


class InvalidPatternError(ValueError):
    pass


class PatternTimeoutError(Exception):
    """Matching took longer than the timeout (likely catastrophic backtracking)."""


@dataclass(frozen=True)
class _Group:
    name: str | None
    body: str


def _skip_class(pattern: str, index: int) -> int:
    """Return the index just past the character class that starts at pattern[index] == '['."""
    i = index + 1
    if i < len(pattern) and pattern[i] == "^":
        i += 1
    if i < len(pattern) and pattern[i] == "]":
        i += 1  # a leading ] is a literal
    while i < len(pattern):
        if pattern[i] == "\\":
            i += 2
            continue
        if pattern[i] == "]":
            return i + 1
        i += 1
    return i


def _capturing_groups(pattern: str) -> list[_Group]:
    groups: list[_Group] = []
    stack: list[tuple[int, str | None, bool]] = []  # (body start, name, capturing)
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == "\\":
            i += 2
            continue
        if char == "[":
            i = _skip_class(pattern, i)
            continue
        if char == "(":
            rest = pattern[i + 1 :]
            named = re.match(r"\?P?<([A-Za-z_]\w*)>", rest)
            if named:
                stack.append((i + 1 + named.end(), named.group(1), True))
                i += 1 + named.end()
                continue
            stack.append((i + 1, None, not rest.startswith("?")))
            i += 1
            continue
        if char == ")" and stack:
            start, name, capturing = stack.pop()
            if capturing:
                groups.append(_Group(name, pattern[start:i]))
        i += 1
    return groups


@dataclass(frozen=True)
class TicketPattern:
    source: str
    compiled: "regex.Pattern[str]"
    group: int | str

    def extract(self, message: str, *, timeout: float = MATCH_TIMEOUT_SECONDS) -> list[int]:
        """Unique work-item IDs in the order they first appear."""
        ids: list[int] = []
        try:
            for match in self.compiled.finditer(message, timeout=timeout):
                value = match.group(self.group)
                if value and value.isascii() and value.isdigit():
                    work_item_id = int(value)
                    if work_item_id > 0 and work_item_id not in ids:
                        ids.append(work_item_id)
        except TimeoutError as exc:
            raise PatternTimeoutError("pattern took too long on this message") from exc
        return ids


def compile_ticket_pattern(pattern: str) -> TicketPattern:
    """Validate a pattern and compile it. Raises InvalidPatternError with a readable reason."""
    if not pattern:
        raise InvalidPatternError("must not be empty")
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise InvalidPatternError(f"must be at most {MAX_PATTERN_LENGTH} characters")
    try:
        compiled = regex.compile(pattern, flags=regex.IGNORECASE | regex.VERSION0)
    except regex.error as exc:
        raise InvalidPatternError(f"is not a valid regular expression: {exc}") from exc

    groups = _capturing_groups(pattern)
    if len(groups) != compiled.groups:
        raise InvalidPatternError("uses group syntax that is not supported")

    named = [g for g in groups if g.name == ID_GROUP_NAME]
    group_ref: int | str
    if named:
        target, group_ref = named[0], ID_GROUP_NAME
    elif len(groups) == 1:
        target, group_ref = groups[0], 1
    elif not groups:
        raise InvalidPatternError(r"needs one capture group for the ID, e.g. AB#(\d+)")
    else:
        raise InvalidPatternError(
            r"must have exactly one capture group, or name the ID group (?P<id>\d+)"
        )
    if not _DIGITS_ONLY.fullmatch(target.body):
        raise InvalidPatternError(r"the ID group must capture digits only, e.g. (\d+)")
    return TicketPattern(source=pattern, compiled=compiled, group=group_ref)

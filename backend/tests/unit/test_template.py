from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.sync.template import (
    DEFAULT_COMMENT_TEMPLATE,
    TEMPLATE_VARIABLES,
    CommentContext,
    InvalidTemplateError,
    escape_markdown,
    render_comment,
    truncate,
    validate_comment_template,
)

SHA = "3f9a1c27b4e85d60a1b2c3d4e5f60718293a4b5c"


def context(**overrides: object) -> CommentContext:
    values: dict[str, object] = {
        "sha": SHA,
        "message": "Fix login AB#123\n\nThe session cookie was dropped.",
        "subject": "Fix login AB#123",
        "body": "The session cookie was dropped.",
        "author_name": "Ada Lovelace",
        "author_email": "ada@example.com",
        "author_date": datetime(2026, 10, 17, 16, 32, tzinfo=timezone(timedelta(hours=2))),
        "branch": "main",
        "repo_name": "web-app",
        "commit_url": f"https://github.com/acme/web-app/commit/{SHA}",
    }
    values.update(overrides)
    return CommentContext(**values)  # type: ignore[arg-type]


def test_default_template_renders() -> None:
    assert render_comment(DEFAULT_COMMENT_TEMPLATE, context()) == (
        f"**Commit** [`3f9a1c2`](https://github.com/acme/web-app/commit/{SHA}) "
        "on `main` by Ada Lovelace, 2026-10-17 14:32 UTC\n"
        "\n"
        "Fix login AB#123\n"
        "\n"
        "The session cookie was dropped.\n"
        "\n"
        f"<sub>Posted by TicketTrail · tt:{SHA}</sub>"
    )


def test_marker_is_added_when_the_template_drops_it() -> None:
    rendered = render_comment("{subject}", context())
    assert rendered == f"Fix login AB#123\n\n<sub>tt:{SHA}</sub>"


def test_marker_is_not_added_twice() -> None:
    assert render_comment("{subject} tt:{sha}", context()).count("tt:") == 1


def test_markdown_in_the_message_is_shown_as_written() -> None:
    message = "# Not a heading\n- not a list\n1. not ordered\n> not a quote\n*bold* _it_ `code`"
    rendered = render_comment("{message}", context(message=message))
    assert rendered.startswith(
        "\\# Not a heading  \n"
        "\\- not a list  \n"
        "1\\. not ordered  \n"
        "\\> not a quote  \n"
        "\\*bold\\* \\_it\\_ \\`code\\`"
    )


def test_html_and_links_in_the_message_are_neutralised() -> None:
    escaped = escape_markdown("<img src=x onerror=alert(1)> [click](https://evil.example)")
    assert escaped == ("\\<img src=x onerror=alert\\(1\\)\\> \\[click\\]\\(https://evil.example\\)")


def test_ticket_references_stay_readable() -> None:
    assert escape_markdown("Fix AB#123 and #45") == "Fix AB#123 and #45"


def test_line_breaks_and_paragraphs_are_kept() -> None:
    assert escape_markdown("one\ntwo\n\n\n   three\r\nfour") == "one  \ntwo\n\nthree  \nfour"


def test_long_messages_are_truncated_to_10000_characters() -> None:
    rendered = render_comment("{message}", context(message="x" * 20_000))
    assert len(rendered.split("\n\n")[0]) == 10_000
    assert rendered.split("\n\n")[0].endswith("…")
    assert truncate("short") == "short"


def test_branch_with_a_backtick_cannot_break_the_code_span() -> None:
    rendered = render_comment("`{branch}`", context(branch="feat`x"))
    assert rendered.startswith("`feat'x`")


def test_link_target_is_url_safe() -> None:
    rendered = render_comment("({commit_url})", context(commit_url="https://x.example/a b)c"))
    assert rendered.startswith("(https://x.example/a%20b%29c)")


def test_unknown_host_drops_the_link_target() -> None:
    assert render_comment("[{short_sha}]({commit_url})", context(commit_url="")).startswith(
        "[3f9a1c2]()"
    )


def test_author_date_is_shown_in_utc() -> None:
    rendered = render_comment(
        "{author_date}", context(author_date=datetime(2026, 1, 1, tzinfo=UTC))
    )
    assert rendered.startswith("2026-01-01 00:00 UTC")


def test_default_template_is_valid_and_carries_marker() -> None:
    assert validate_comment_template(DEFAULT_COMMENT_TEMPLATE) == DEFAULT_COMMENT_TEMPLATE
    assert "tt:{sha}" in DEFAULT_COMMENT_TEMPLATE


def test_all_spec_variables_are_known() -> None:
    assert {
        "sha",
        "short_sha",
        "message",
        "subject",
        "body",
        "author_name",
        "author_email",
        "author_date",
        "branch",
        "repo_name",
        "commit_url",
    } == TEMPLATE_VARIABLES


def test_literal_braces_can_be_escaped() -> None:
    validate_comment_template("{{not a variable}} {sha}")


@pytest.mark.parametrize(
    ("template", "reason"),
    [
        ("", "empty"),
        ("   \n", "empty"),
        ("{author}", "unknown variable"),
        ("{}", "unknown variable"),
        ("{sha", "unmatched"),
        ("sha}", "unmatched"),
        ("{sha:>10}", "format options"),
        ("{sha!r}", "format options"),
        ("x" * 10_001, "at most"),
    ],
)
def test_invalid_templates(template: str, reason: str) -> None:
    with pytest.raises(InvalidTemplateError, match=reason):
        validate_comment_template(template)

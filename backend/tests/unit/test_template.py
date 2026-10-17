import pytest

from app.sync.template import (
    DEFAULT_COMMENT_TEMPLATE,
    TEMPLATE_VARIABLES,
    InvalidTemplateError,
    validate_comment_template,
)


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

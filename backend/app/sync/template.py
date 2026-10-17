"""Comment templates: the default and the rules for user templates (spec section 6).

Rendering is added in Milestone 5. The frontend mirrors the variable list in
frontend/src/lib/commentTemplate.ts.
"""

import string

DEFAULT_COMMENT_TEMPLATE = (
    "**Commit** [`{short_sha}`]({commit_url}) on `{branch}` by {author_name}, {author_date}\n"
    "\n"
    "{message}\n"
    "\n"
    "<sub>Posted by TicketTrail · tt:{sha}</sub>"
)

TEMPLATE_VARIABLES = frozenset(
    {
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
    }
)

MAX_TEMPLATE_LENGTH = 10_000


class InvalidTemplateError(ValueError):
    pass


def validate_comment_template(template: str) -> str:
    if not template.strip():
        raise InvalidTemplateError("must not be empty")
    if len(template) > MAX_TEMPLATE_LENGTH:
        raise InvalidTemplateError(f"must be at most {MAX_TEMPLATE_LENGTH} characters")
    try:
        fields = [field for _, field, _, _ in string.Formatter().parse(template)]
        specs = [
            (spec, conv) for _, field, spec, conv in string.Formatter().parse(template) if field
        ]
    except ValueError as exc:
        raise InvalidTemplateError(
            "has an unmatched { or }; write {{ or }} for a literal brace"
        ) from exc
    for field in fields:
        if field is None:
            continue
        if field not in TEMPLATE_VARIABLES:
            known = ", ".join(f"{{{name}}}" for name in sorted(TEMPLATE_VARIABLES))
            raise InvalidTemplateError(f"uses unknown variable {{{field}}}; available: {known}")
    if any(spec or conv for spec, conv in specs):
        raise InvalidTemplateError("variables can't have format options, use {name} only")
    return template

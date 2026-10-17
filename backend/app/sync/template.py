"""Comment templates: the default, the rules for user templates and rendering (spec section 6).

The frontend mirrors all of this for the live preview in
frontend/src/lib/commentTemplate.ts; keep the two in step.
"""

import re
import string
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote

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


# --- Rendering -------------------------------------------------------------------------------

MARKER = "tt:{sha}"
MARKER_SUFFIX = "\n\n<sub>" + MARKER + "</sub>"
MAX_MESSAGE_LENGTH = 10_000

# Characters with a Markdown meaning anywhere in a line, and those that only
# matter at the start of one (headings, lists, quotes).
_INLINE = re.compile(r"([\\`*_{}\[\]()<>|~!&])")
_LINE_START = re.compile(r"^(\s*)([#+\-=>]|\d+[.)])")


def escape_markdown(text: str) -> str:
    """Show text as written: no Markdown, line breaks kept.

    Leading indentation is dropped (it would turn lines into code blocks) and
    each line ends with a hard break, so a commit body keeps its shape.
    """

    def block_marker(match: re.Match[str]) -> str:
        marker = match.group(2)
        # "1." becomes "1\." (escape the punctuation); "#" or "-" becomes "\#" or "\-".
        escaped = marker[:-1] + "\\" + marker[-1] if marker[0].isdigit() else "\\" + marker
        return match.group(1) + escaped

    def line(raw: str) -> str:
        return _LINE_START.sub(block_marker, _INLINE.sub(r"\\\1", raw.strip()))

    paragraphs = re.split(r"\n[ \t]*\n+", text.replace("\r\n", "\n").strip())
    return "\n\n".join(
        "  \n".join(line(raw) for raw in paragraph.split("\n") if raw.strip())
        for paragraph in paragraphs
        if paragraph.strip()
    )


def truncate(text: str, limit: int = MAX_MESSAGE_LENGTH) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


@dataclass(frozen=True)
class CommentContext:
    sha: str
    message: str
    subject: str
    body: str
    author_name: str
    author_email: str
    author_date: datetime
    branch: str
    repo_name: str
    commit_url: str


def _code(value: str) -> str:
    """For values the default template puts in `code spans`: no backticks, no escapes."""
    return value.replace("`", "'").replace("\n", " ")


def _link_target(url: str) -> str:
    return quote(url, safe=":/?#@!$&'*+,;=%~-._") if url else ""


def render_comment(template: str, context: CommentContext) -> str:
    """Fill in a validated template. The tt:{sha} marker is always present."""
    message = truncate(context.message)
    values = {
        "sha": context.sha,
        "short_sha": context.sha[:7],
        "message": escape_markdown(message),
        "subject": escape_markdown(context.subject),
        "body": escape_markdown(truncate(context.body)),
        "author_name": escape_markdown(context.author_name),
        "author_email": escape_markdown(context.author_email),
        "author_date": context.author_date.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "branch": _code(context.branch),
        "repo_name": escape_markdown(context.repo_name),
        "commit_url": _link_target(context.commit_url),
    }
    # Crash recovery looks for the marker, so add it even if the user removed it.
    full = template if MARKER in template else template + MARKER_SUFFIX
    return full.format_map(values)

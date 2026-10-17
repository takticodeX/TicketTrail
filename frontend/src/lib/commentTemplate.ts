// Mirrors backend/app/sync/template.py: the same variables, the same rules
// (Python str.format syntax: {name}, with {{ and }} for literal braces).

export const DEFAULT_COMMENT_TEMPLATE =
  '**Commit** [`{short_sha}`]({commit_url}) on `{branch}` by {author_name}, {author_date}\n' +
  '\n' +
  '{message}\n' +
  '\n' +
  '<sub>Posted by TicketTrail · tt:{sha}</sub>';

export const TEMPLATE_VARIABLES = [
  'sha',
  'short_sha',
  'message',
  'subject',
  'body',
  'author_name',
  'author_email',
  'author_date',
  'branch',
  'repo_name',
  'commit_url',
] as const;

export type TemplateVariable = (typeof TEMPLATE_VARIABLES)[number];
/** Raw commit values; renderTemplate escapes them exactly as the sync will. */
export type TemplateValues = Record<TemplateVariable, string>;

export const MAX_TEMPLATE_LENGTH = 10_000;
export const MARKER = 'tt:{sha}';

interface Field {
  name: string;
  hasOptions: boolean;
}

class TemplateSyntaxError extends Error {}

/** Split like Python's string.Formatter().parse, returning literal text and fields. */
function parse(template: string): (string | Field)[] {
  const parts: (string | Field)[] = [];
  let literal = '';
  let i = 0;
  while (i < template.length) {
    const char = template[i];
    if (char === '{') {
      if (template[i + 1] === '{') {
        literal += '{';
        i += 2;
        continue;
      }
      const end = template.indexOf('}', i);
      if (end === -1) throw new TemplateSyntaxError();
      const inner = template.slice(i + 1, end);
      const name = inner.split(/[!:]/, 1)[0] ?? '';
      parts.push(literal, { name, hasOptions: name.length !== inner.length });
      literal = '';
      i = end + 1;
      continue;
    }
    if (char === '}') {
      if (template[i + 1] !== '}') throw new TemplateSyntaxError();
      literal += '}';
      i += 2;
      continue;
    }
    literal += char;
    i += 1;
  }
  parts.push(literal);
  return parts;
}

/** A reason the template is invalid (same wording as the API), or null. */
export function commentTemplateError(template: string): string | null {
  if (!template.trim()) return 'must not be empty';
  if (template.length > MAX_TEMPLATE_LENGTH) return `must be at most ${MAX_TEMPLATE_LENGTH} characters`;
  let parts: (string | Field)[];
  try {
    parts = parse(template);
  } catch {
    return 'has an unmatched { or }; write {{ or }} for a literal brace';
  }
  const fields = parts.filter((part): part is Field => typeof part !== 'string');
  const known = new Set<string>(TEMPLATE_VARIABLES);
  const unknown = fields.find((field) => !known.has(field.name));
  if (unknown) {
    const list = [...TEMPLATE_VARIABLES].sort().map((name) => `{${name}}`).join(', ');
    return `uses unknown variable {${unknown.name}}; available: ${list}`;
  }
  if (fields.some((field) => field.hasOptions)) {
    return "variables can't have format options, use {name} only";
  }
  return null;
}

// --- Rendering: the same as render_comment in backend/app/sync/template.py ---------------

export const MAX_MESSAGE_LENGTH = 10_000;

const INLINE = /([\\`*_{}[\]()<>|~!&])/g;
const LINE_START = /^(\s*)([#+\-=>]|\d+[.)])/;

/** Show text as written: Markdown neutralised, line breaks and paragraphs kept. */
export function escapeMarkdown(text: string): string {
  const line = (raw: string) =>
    raw
      .trim()
      .replace(INLINE, '\\$1')
      .replace(LINE_START, (_match, space: string, marker: string) =>
        // "1." becomes "1\." (escape the punctuation); "#" or "-" becomes "\#" or "\-".
        space + (/^\d/.test(marker) ? `${marker.slice(0, -1)}\\${marker.slice(-1)}` : `\\${marker}`),
      );
  return text
    .replace(/\r\n/g, '\n')
    .trim()
    .split(/\n[ \t]*\n+/)
    .filter((paragraph) => paragraph.trim())
    .map((paragraph) =>
      paragraph
        .split('\n')
        .filter((raw) => raw.trim())
        .map(line)
        .join('  \n'),
    )
    .join('\n\n');
}

export function truncate(text: string, limit = MAX_MESSAGE_LENGTH): string {
  return text.length <= limit ? text : `${text.slice(0, limit - 1).trimEnd()}…`;
}

function linkTarget(url: string): string {
  return url ? encodeURI(url).replace(/\(/g, '%28').replace(/\)/g, '%29') : '';
}

/**
 * Fill in a valid template for the preview, exactly as the sync will post it.
 * TicketTrail always adds the tt:{sha} marker when the template drops it,
 * because crash recovery needs it.
 */
export function renderTemplate(template: string, raw: TemplateValues): string {
  const values: TemplateValues = {
    ...raw,
    short_sha: raw.sha.slice(0, 7),
    message: escapeMarkdown(truncate(raw.message)),
    subject: escapeMarkdown(raw.subject),
    body: escapeMarkdown(truncate(raw.body)),
    author_name: escapeMarkdown(raw.author_name),
    author_email: escapeMarkdown(raw.author_email),
    branch: raw.branch.replace(/`/g, "'").replace(/\n/g, ' '),
    repo_name: escapeMarkdown(raw.repo_name),
    commit_url: linkTarget(raw.commit_url),
  };
  const withMarker = template.includes(MARKER) ? template : `${template}\n\n<sub>${MARKER}</sub>`;
  return parse(withMarker)
    .map((part) => (typeof part === 'string' ? part : values[part.name as TemplateVariable]))
    .join('');
}

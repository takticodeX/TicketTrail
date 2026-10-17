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

/**
 * Fill in a valid template for the preview. TicketTrail always adds the
 * tt:{sha} marker when the template drops it, because crash recovery needs it.
 */
export function renderTemplate(template: string, values: TemplateValues): string {
  const withMarker = template.includes(MARKER) ? template : `${template}\n\n<sub>${MARKER}</sub>`;
  return parse(withMarker)
    .map((part) => (typeof part === 'string' ? part : values[part.name as TemplateVariable]))
    .join('');
}

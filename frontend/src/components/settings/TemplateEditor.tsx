import { Button, Code, Group, Paper, Stack, Tabs, Text, Textarea, TypographyStylesProvider } from '@mantine/core';
import { useRef } from 'react';
import ReactMarkdown from 'react-markdown';

import {
  MARKER,
  TEMPLATE_VARIABLES,
  commentTemplateError,
  renderTemplate,
  type TemplateValues,
} from '../../lib/commentTemplate';

interface Props {
  value: string;
  onChange: (value: string) => void;
  error?: string;
  sample: TemplateValues;
}

/** The comment template with clickable variables and a live preview on a sample commit. */
export function TemplateEditor({ value, onChange, error, sample }: Props) {
  const textarea = useRef<HTMLTextAreaElement>(null);
  const valid = commentTemplateError(value) === null;
  const rendered = valid ? renderTemplate(value, sample) : '';

  const insert = (variable: string) => {
    const element = textarea.current;
    const token = `{${variable}}`;
    if (!element) {
      onChange(value + token);
      return;
    }
    const { selectionStart, selectionEnd } = element;
    onChange(value.slice(0, selectionStart) + token + value.slice(selectionEnd));
    requestAnimationFrame(() => {
      element.focus();
      element.setSelectionRange(selectionStart + token.length, selectionStart + token.length);
    });
  };

  return (
    <Stack gap="sm">
      <Textarea
        ref={textarea}
        label="Comment template"
        description="Markdown. Click a variable to insert it at the cursor."
        autosize
        minRows={6}
        maxRows={16}
        ff="monospace"
        value={value}
        error={error}
        onChange={(event) => onChange(event.currentTarget.value)}
      />
      <Group gap={6}>
        {TEMPLATE_VARIABLES.map((variable) => (
          <Button key={variable} size="compact-xs" variant="light" onClick={() => insert(variable)}>
            {`{${variable}}`}
          </Button>
        ))}
      </Group>
      {!value.includes(MARKER) && valid && (
        <Text size="xs" c="dimmed">
          The marker <Code>{MARKER}</Code> is added automatically: TicketTrail uses it to make sure a
          comment is never posted twice.
        </Text>
      )}
      <Paper withBorder radius="md" p="sm">
        <Tabs defaultValue="rendered">
          <Tabs.List>
            <Tabs.Tab value="rendered">Preview</Tabs.Tab>
            <Tabs.Tab value="markdown">Markdown</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="rendered" pt="sm" aria-label="Rendered preview">
            {valid ? (
              <TypographyStylesProvider>
                <ReactMarkdown
                  components={{ a: (props) => <a {...props} target="_blank" rel="noreferrer" /> }}
                >
                  {rendered}
                </ReactMarkdown>
              </TypographyStylesProvider>
            ) : (
              <Text size="sm" c="dimmed">
                Fix the template to see the preview.
              </Text>
            )}
          </Tabs.Panel>
          <Tabs.Panel value="markdown" pt="sm">
            <Code block>{rendered || ' '}</Code>
          </Tabs.Panel>
        </Tabs>
      </Paper>
    </Stack>
  );
}

import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { errorResponse, jsonResponse, mockFetch, renderWithProviders } from '../../test/utils';
import { PatternTester } from './PatternTester';

afterEach(() => vi.unstubAllGlobals());

describe('PatternTester', () => {
  it('shows the IDs the server finds in each sample', async () => {
    const fetchMock = mockFetch({
      'POST /api/v1/projects/test-pattern': () =>
        jsonResponse({
          pattern: 'AB#(\\d+)',
          results: [
            { ids: [123], error: null },
            { ids: [], error: null },
          ],
        }),
    });
    renderWithProviders(
      <PatternTester pattern="AB#(\d+)" samples={'Fix AB#123\n---\nchore'} onSamplesChange={vi.fn()} />,
    );

    expect(await screen.findByText('#123')).toBeInTheDocument();
    expect(screen.getByText('No reference')).toBeInTheDocument();
    const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body));
    expect(body).toEqual({ pattern: 'AB#(\\d+)', samples: ['Fix AB#123', 'chore'] });
  });

  it('does not call the server for a pattern without a capture group', async () => {
    const fetchMock = mockFetch({});
    renderWithProviders(<PatternTester pattern="AB#\d+" samples="Fix AB#1" onSamplesChange={vi.fn()} />);
    expect(await screen.findByText('Fix the pattern to see which IDs it finds.')).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows the server's error for Python regex syntax", async () => {
    mockFetch({
      'POST /api/v1/projects/test-pattern': () =>
        jsonResponse(
          {
            error: {
              code: 'validation_error',
              message: 'The request is invalid.',
              details: {
                errors: [{ loc: ['body', 'pattern'], msg: 'pattern is not a valid regular expression', type: 'value_error' }],
              },
            },
          },
          422,
        ),
    });
    renderWithProviders(<PatternTester pattern="AB#((\d+)" samples="x" onSamplesChange={vi.fn()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('pattern is not a valid regular expression');
  });

  it('reports a timeout on one sample', async () => {
    mockFetch({
      'POST /api/v1/projects/test-pattern': () =>
        jsonResponse({ pattern: 'p', results: [{ ids: [], error: 'The pattern took too long.' }] }),
    });
    renderWithProviders(<PatternTester pattern="(?:a|a)+#(\d+)" samples="aaaa" onSamplesChange={vi.fn()} />);
    expect(await screen.findByText('The pattern took too long.')).toBeInTheDocument();
  });

  it('keeps working when the server is unreachable', async () => {
    mockFetch({ 'POST /api/v1/projects/test-pattern': () => errorResponse(502, 'http_error', 'Bad gateway') });
    renderWithProviders(<PatternTester pattern="AB#(\d+)" samples="x" onSamplesChange={vi.fn()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Bad gateway');
  });
});

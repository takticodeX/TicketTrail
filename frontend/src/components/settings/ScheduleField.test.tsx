import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '../../test/utils';
import { ScheduleField } from './ScheduleField';

function Harness({ initialCron = '', initialEnabled = false }) {
  const [cron, setCron] = useState(initialCron);
  const [enabled, setEnabled] = useState(initialEnabled);
  return (
    <>
      <ScheduleField
        cron={cron}
        onCronChange={setCron}
        enabled={enabled}
        onEnabledChange={setEnabled}
        timeZone="Europe/Rome"
      />
      <output data-testid="cron">{cron}</output>
    </>
  );
}

describe('ScheduleField', () => {
  it('turning the schedule on picks the default preset', async () => {
    renderWithProviders(<Harness />);
    await userEvent.click(screen.getByRole('switch', { name: /Sync on a schedule/ }));
    expect(screen.getByTestId('cron')).toHaveTextContent('0 * * * *');
    const runs = screen.getByLabelText('Next runs');
    expect(within(runs).getByText('Every hour')).toBeInTheDocument();
    expect(within(runs).getByText('Next runs (Europe/Rome):')).toBeInTheDocument();
    expect(runs.querySelectorAll('li')).toHaveLength(3);
  });

  it('recognises a preset from the saved cron', () => {
    renderWithProviders(<Harness initialCron="0 8 * * 1-5" initialEnabled />);
    expect(screen.getByRole('textbox', { name: 'When' })).toHaveValue('Weekdays at 08:00');
    expect(screen.getByText('At 08:00, Monday through Friday')).toBeInTheDocument();
  });

  it('shows a custom cron in an editable field', () => {
    renderWithProviders(<Harness initialCron="30 7 * * 1-5" initialEnabled />);
    expect(screen.getByLabelText('Cron expression')).toHaveValue('30 7 * * 1-5');
    expect(screen.getByText('At 07:30, Monday through Friday')).toBeInTheDocument();
  });

  it('hides the next runs for an invalid expression', async () => {
    renderWithProviders(<Harness initialCron="30 7 * * 1-5" initialEnabled />);
    const input = screen.getByLabelText('Cron expression');
    await userEvent.clear(input);
    await userEvent.type(input, '* * * * *');
    expect(screen.queryByLabelText('Next runs')).not.toBeInTheDocument();
  });

  it('reports the field error it is given', () => {
    renderWithProviders(
      <ScheduleField
        cron="* * * * *"
        onCronChange={vi.fn()}
        enabled
        onEnabledChange={vi.fn()}
        timeZone="UTC"
        error="The schedule must not run more often than every 5 minutes"
      />,
    );
    expect(screen.getByText('The schedule must not run more often than every 5 minutes')).toBeInTheDocument();
  });
});

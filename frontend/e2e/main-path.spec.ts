import { expect, request, test, type Page } from '@playwright/test';

/**
 * The main path (spec section 13): register -> create both connections -> create a
 * project -> dry run -> real sync (Azure faked by the fixtures server) -> history,
 * then sharing the project with a viewer.
 */

const FIXTURES = process.env.E2E_FIXTURES_URL ?? 'https://127.0.0.1:8443';
// As the worker sees the fixtures server, inside the compose network.
const GIT_URL = 'https://fixtures:8443/git/demo.git';
const ORG_URL = 'https://fixtures:8443/acme';
const AZURE_PAT = 'e2e-azure-pat-canary';

const email = `e2e-${Date.now()}@example.com`;
const viewerEmail = `e2e-viewer-${Date.now()}@example.com`;
const password = 'e2e-password-123';

async function pick(page: Page, label: string, option: string) {
  await page.getByRole('textbox', { name: label }).click();
  await page.getByRole('option', { name: option }).click();
}

test('register, connect, dry run, sync and see the history', async ({ page }) => {
  const reset = await request.newContext({ baseURL: FIXTURES, ignoreHTTPSErrors: true });
  await reset.post('/__fake__/reset');
  await reset.dispose();

  // Register (lands on the dashboard).
  await page.goto('/register');
  await page.getByLabel('Email', { exact: true }).fill(email);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByLabel('Confirm password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Create account' }).click();
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();

  // Git connection: a public repository, tested from the worker.
  await page.goto('/settings/git');
  await page.getByRole('button', { name: 'Add Git connection' }).click();
  await page.getByLabel('Name', { exact: true }).fill('Demo repo');
  await page.getByLabel('Repository URL', { exact: true }).fill(GIT_URL);
  await page.getByText('Public', { exact: true }).click();
  await page.getByRole('button', { name: 'Save and test' }).click();
  await expect(page.getByText('Connection works')).toBeVisible();
  await expect(page.getByText(/Found 1 branch/)).toBeVisible();
  await page.getByRole('button', { name: 'Close' }).click();

  // Azure connection.
  await page.goto('/settings/azure');
  await page.getByRole('button', { name: 'Add Azure connection' }).click();
  await page.getByLabel('Name', { exact: true }).fill('Web board');
  await page.getByLabel('Organization URL', { exact: true }).fill(ORG_URL);
  await page.getByLabel('Project', { exact: true }).fill('Web');
  await page.getByLabel('Personal access token', { exact: true }).fill(AZURE_PAT);
  await page.getByRole('button', { name: 'Save and test' }).click();
  await expect(page.getByText('Found the project')).toBeVisible();
  await page.getByRole('button', { name: 'Close' }).click();

  // Project, through the wizard.
  await page.goto('/settings/projects/new');
  await page.getByLabel('Project name', { exact: true }).fill('Demo');
  await pick(page, 'Git connection', 'Demo repo');
  await page.getByRole('button', { name: 'Next' }).click();
  await page.getByRole('button', { name: 'Load branches from the repository' }).click();
  await expect(page.getByText('Connection works')).toBeVisible();
  await page.getByRole('textbox', { name: 'Branches to sync' }).fill('main');
  await page.keyboard.press('Enter');
  await page.getByRole('button', { name: 'Next' }).click();
  await pick(page, 'Azure connection', 'Web board (Web)');
  for (let step = 0; step < 4; step += 1) await page.getByRole('button', { name: 'Next' }).click();
  await page.getByRole('button', { name: 'Create project' }).click();
  await expect(page.getByRole('heading', { name: 'Projects' })).toBeVisible();

  // Dry run: lists what would be posted, posts nothing.
  await page.goto('/');
  await page.getByRole('link', { name: 'Demo', exact: true }).click();
  await page.getByRole('button', { name: 'Dry run' }).click();
  await expect(page.getByRole('heading', { name: 'Dry run' })).toBeVisible();
  await expect(page.getByText('Would post (3)', { exact: true })).toBeVisible();
  await expect(page.getByText('No reference (1)', { exact: true })).toBeVisible();

  const fixtures = await request.newContext({ baseURL: FIXTURES, ignoreHTTPSErrors: true });
  expect(await (await fixtures.get('/__fake__/comments')).json()).toEqual({});

  // Real sync, after the confirmation with the dry run's numbers.
  await page.getByRole('link', { name: /Demo/ }).first().click();
  await page.getByRole('button', { name: 'Sync now' }).click();
  await expect(page.getByText('3 comments')).toBeVisible();
  await page.getByRole('button', { name: 'Post comments' }).click();
  await expect(page.getByRole('heading', { name: 'Sync' })).toBeVisible();
  await expect(page.getByText('Success')).toBeVisible();
  await expect(page.getByText('Posted (3)', { exact: true })).toBeVisible();

  const posted = (await (await fixtures.get('/__fake__/comments')).json()) as Record<string, { text: string }[]>;
  expect(Object.keys(posted).sort()).toEqual(['1', '2', '3']);
  expect(posted['1']?.[0]?.text).toContain('Fix login redirect AB#1');
  expect(posted['1']?.[0]?.text).toMatch(/tt:[0-9a-f]{40}/);

  // The history shows both runs; the dashboard shows the result.
  await page.getByRole('link', { name: /Demo/ }).first().click();
  await expect(page.getByRole('cell', { name: 'Success' })).toHaveCount(2);
  await page.goto('/');
  await expect(page.getByText('3 comments posted')).toBeVisible();

  // Syncing again posts nothing new.
  await page.getByRole('link', { name: 'Demo', exact: true }).click();
  const projectUrl = page.url();
  await page.getByRole('button', { name: 'Sync now' }).click();
  await page.getByRole('button', { name: 'Post comments' }).click();
  await page.waitForURL((url) => url.href !== projectUrl && url.pathname.includes('/runs/'));
  await expect(page.getByText('Success', { exact: true })).toBeVisible();
  const again = (await (await fixtures.get('/__fake__/comments')).json()) as Record<string, unknown[]>;
  expect(Object.values(again).map((c) => c.length)).toEqual([1, 1, 1]);

  // Share the project with a second user, as a viewer.
  const api = await request.newContext({ baseURL: test.info().project.use.baseURL });
  const registered = await api.post('/api/v1/auth/register', {
    data: { email: viewerEmail, password, display_name: 'Victor' },
  });
  expect(registered.status()).toBe(201);
  await api.dispose();
  await page.getByRole('link', { name: /Demo/ }).first().click();
  await page.getByRole('button', { name: 'Share' }).click();
  const drawer = page.getByRole('dialog', { name: 'Share "Demo"' });
  await drawer.getByRole('textbox', { name: 'Email' }).fill(viewerEmail);
  await drawer.getByRole('button', { name: 'Share' }).click();
  await expect(drawer.getByRole('table', { name: 'Shared with' }).getByText(viewerEmail)).toBeVisible();

  // The viewer sees it under "Shared with me", can dry run, can't sync.
  await page.context().clearCookies();
  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(viewerEmail);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Log in' }).click();
  await expect(page.getByRole('heading', { name: 'Shared with me' })).toBeVisible();
  const card = page.getByLabel('Demo', { exact: true });
  await expect(card.getByText('Viewer')).toBeVisible();
  await expect(card.getByRole('button', { name: 'Sync now' })).toHaveCount(0);
  await card.getByRole('button', { name: 'Dry run' }).click();
  await expect(page.getByRole('heading', { name: 'Dry run' })).toBeVisible();
  await expect(page.getByText('Success', { exact: true })).toBeVisible();
  await expect(page.getByText(/by Victor/)).toBeVisible();
  const afterViewer = (await (await fixtures.get('/__fake__/comments')).json()) as Record<string, unknown[]>;
  expect(Object.values(afterViewer).map((c) => c.length)).toEqual([1, 1, 1]);
  await fixtures.dispose();
});

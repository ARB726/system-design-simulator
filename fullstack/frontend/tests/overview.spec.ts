import { expect, test } from '@playwright/test';
import recorded from '../public/guest-demo.json';

test.beforeEach(async ({ page }) => {
  await page.route('**/api/settings', route => route.fulfill({ json: { auth: 'local' } }));
  await page.route('**/api/catalog', route => route.fulfill({ json: { presets: [], challenges: [] } }));
});

test('the overview compares the two recorded designs with keyboard controls', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Understand a system before you scale it.');
  const preview = page.getByRole('region', { name: 'What changes with a read cache?' });
  const metrics = preview.locator('dl');
  const baseline = preview.getByRole('radio', { name: 'No cache' });
  const candidate = preview.getByRole('radio', { name: 'Read cache' });
  const [first, second] = recorded.experiments;
  await expect(baseline).toBeChecked();
  await expect(metrics).toContainText(first.result.summary.p95_ms.toFixed(1));
  await expect(metrics).toContainText('$' + first.result.cost);
  await baseline.focus();
  await page.keyboard.press('ArrowRight');
  await expect(candidate).toBeFocused();
  await expect(candidate).toBeChecked();
  await expect(metrics).toContainText(second.result.summary.p95_ms.toFixed(1));
  await expect(metrics).toContainText('$' + second.result.cost);
  await page.keyboard.press('ArrowLeft');
  await expect(baseline).toBeChecked();
  await expect(metrics).toContainText(first.result.summary.p95_ms.toFixed(1));
});

test('choosing a workflow preserves the current sandbox design', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('link', { name: 'Test your own design' }).click();
  await expect(page).toHaveURL(/#sandbox$/);
  const name = page.getByLabel('Experiment name', { exact: true });
  await name.fill('Keep my design');
  await page.evaluate(() => { location.hash = 'experiment-settings'; });
  await expect(name).toHaveValue('Keep my design');
  await page.getByRole('button', { name: 'Overview', exact: true }).click();
  await page.getByRole('link', { name: 'Open sandbox', exact: true }).click();
  await expect(name).toHaveValue('Keep my design');
  await page.reload();
  await expect(name).toBeVisible();
});

test('the guest demo keeps the standalone walkthrough and transcript reachable', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('link', { name: 'Try without signing in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Two designs. See the tradeoff.' })).toBeVisible();
  await page.getByRole('link', { name: 'Summary & walkthrough' }).click();
  await expect(page).toHaveURL(/\/overview\/$/);
  await page.getByRole('link', { name: 'Jump to walkthrough' }).click();
  await expect(page.getByText('Watch the 75-second walkthrough', { exact: true })).toBeInViewport();
  await page.getByText('Watch the 75-second walkthrough', { exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Walkthrough transcript' })).toBeVisible();
  await expect(page.locator('video')).toBeVisible();
  await expect(page.locator('track[kind=captions]')).toHaveAttribute('src', '/walkthrough.vtt');
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Choose your workflow' })).toBeVisible();
});

test('phone layouts keep labeled workspace navigation and reloadable workflow links', async ({ page }) => {
  for (const width of [320, 390, 550]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto('/');
    const nav = page.getByRole('navigation', { name: 'Workspace' });
    await expect(nav.getByText('Library', { exact: true })).toBeVisible();
    const overview = nav.getByRole('button', { name: 'Overview' });
    await expect(overview).toHaveAttribute('aria-current', 'page');
    expect((await overview.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    await expect(page.getByRole('link', { name: 'Try without signing in', exact: true })).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  }
  for (const [link, hash, title] of [
    ['Compare experiments', 'library', 'A record of your reasoning.'],
    ['Practice a challenge', 'learn', 'Build your intuition.'],
  ]) {
    await page.getByRole('link', { name: link }).click();
    await expect(page).toHaveURL(new RegExp('#' + hash + '$'));
    await expect(page.getByRole('heading', { name: title })).toBeInViewport();
    await page.reload();
    await expect(page.getByRole('heading', { name: title })).toBeVisible();
    await page.getByRole('button', { name: 'Overview', exact: true }).click();
  }
});

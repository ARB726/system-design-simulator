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
  await page.getByRole('link', { name: 'Explore the cache example', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Two designs. See the tradeoff.' })).toBeVisible();
  await page.getByRole('link', { name: 'Summary & walkthrough' }).click();
  await expect(page).toHaveURL(/\/overview\/index\.html$/);
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
    await expect(page.getByRole('link', { name: 'Explore the cache example', exact: true })).toBeInViewport();
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

test('read replay follows the selected design and respects both motion controls', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.goto('/');
  const preview = page.getByRole('region', { name: 'What changes with a read cache?' });
  const wire = preview.locator('.read-route-wire');
  const animationName = () => wire.evaluate(el => getComputedStyle(el, '::after').animationName);
  const replay = preview.getByRole('button', { name: 'Replay the read path' });
  await expect(preview).toContainText('the app sends this read to the database');
  await replay.click();
  await expect.poll(animationName).toBe('follow-read');
  expect(await wire.evaluate(el => getComputedStyle(el, '::after').animationIterationCount)).toBe('1');
  await preview.getByRole('radio', { name: 'No cache' }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(preview).toContainText('A cache hit serves this read');
  await page.getByRole('button', { name: 'Pause background animations' }).click();
  await replay.click();
  await expect.poll(animationName).toBe('none');
  await expect(preview.locator('.trace-active')).toHaveCSS('animation-name', 'none');
  await page.getByRole('button', { name: 'Resume background animations' }).click();
  await expect.poll(animationName).toBe('follow-read');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/overview/');
  await replay.click();
  await expect.poll(animationName).toBe('none');
  await expect(preview.locator('.trace-active')).toHaveCSS('animation-name', 'none');
  await expect(preview.locator('.preview-metrics dl')).toHaveCSS('animation-name', 'none');
});

test('the guide explains experiments, result metrics and access on both entry points', async ({ page }) => {
  for (const route of ['/', '/overview/']) {
    await page.goto(route);
    await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(5, 5, 5)');
    await expect(page.getByRole('link', { name: 'Explore the cache example', exact: true }))
      .toHaveCSS('background-color', 'rgb(166, 244, 119)');
    await page.getByRole('link', { name: 'How to run a first experiment' }).click();
    await expect(page.getByRole('heading', { name: 'A useful first experiment' })).toBeInViewport();
    await page.getByText('Where does an async write wait?', { exact: true }).click();
    await expect(page.getByText(/In a separate run, change only the consumer count/)).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Read the results' })).toBeVisible();
    await expect(page.getByText('Offered load and throughput', { exact: true })).toBeVisible();
    await expect(page.getByText('p95 and p99 latency', { exact: true })).toBeVisible();
    await expect(page.getByText('Write acknowledgements and lag', { exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'What you can do as a guest' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'What the model measures' })).toBeVisible();
  }
});

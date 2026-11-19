import {test,expect} from '@playwright/test';
import fixture from '../public/guest-demo.json';

test('guest comparison shows measured deltas and the architecture change',async({page})=>{
  await page.route('**/api/settings',r=>r.fulfill({json:{auth:'local'}}));
  await page.route('**/api/catalog',r=>r.fulfill({json:{presets:[],challenges:[]}}));
  await page.goto('/#demo');
  const changes=page.getByRole('region',{name:'Before and after'});
  await expect(changes).toBeVisible({timeout:20000});
  const [a,b]=fixture.experiments;
  const delta=b.result.summary.p95_ms-a.result.summary.p95_ms;
  await expect(changes.getByTestId('delta-latency')).toContainText(delta.toLocaleString('en-US',{maximumFractionDigits:1}));
  await expect(changes.getByTestId('delta-success')).toContainText('percentage points');
  await expect(changes).toContainText('Read cache: off → on');
  await expect(changes).toContainText('Illustrative cost change');
});

test('zero baseline yields no invalid percentage and a regression is labelled',async({page})=>{
  const data=structuredClone(fixture);
  data.experiments[0].result.summary.served_rps=0;
  data.experiments[1].result.summary.p95_ms=data.experiments[0].result.summary.p95_ms+10;
  await page.route('**/api/settings',r=>r.fulfill({json:{auth:'local'}}));
  await page.route('**/api/catalog',r=>r.fulfill({json:{presets:[],challenges:[]}}));
  await page.route('**/guest-demo.json',r=>r.fulfill({json:data}));
  await page.goto('/#demo');
  const changes=page.getByRole('region',{name:'Before and after'});
  await expect(changes).toBeVisible({timeout:20000});
  await expect(changes.getByTestId('delta-throughput')).toContainText('No relative change from a zero baseline');
  await expect(changes.getByTestId('delta-latency')).toContainText('Worse');
  await expect(changes).not.toContainText(/NaN|Infinity/);
});

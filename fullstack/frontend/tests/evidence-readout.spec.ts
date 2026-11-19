import {test,expect} from '@playwright/test';
import fixture from '../public/guest-demo.json';

test('a guest can read the measured tradeoff before inspecting the charts',async({page})=>{
  await page.route('**/api/settings',r=>r.fulfill({json:{auth:'local'}}));
  await page.route('**/api/catalog',r=>r.fulfill({json:{presets:[],challenges:[]}}));
  await page.goto('/#demo');
  const outcome=page.getByRole('note',{name:'Comparison outcome'});
  await expect(outcome).toContainText('p95 latency fell');
  await expect(outcome).toContainText('Illustrative cost rose');
  await expect(outcome).toContainText('Matched configured workload');
  await expect(page.getByRole('region',{name:'Experiment brief'})).toContainText('120');
});

test('a regression and mismatched conditions are described plainly',async({page})=>{
  const data=structuredClone(fixture);
  data.experiments[1].result.summary.p95_ms=data.experiments[0].result.summary.p95_ms+10;
  data.experiments[1].payload.config.workload.rps+=10;
  await page.route('**/api/settings',r=>r.fulfill({json:{auth:'local'}}));
  await page.route('**/api/catalog',r=>r.fulfill({json:{presets:[],challenges:[]}}));
  await page.route('**/guest-demo.json',r=>r.fulfill({json:data}));
  await page.goto('/#demo');
  const outcome=page.getByRole('note',{name:'Comparison outcome'});
  await expect(outcome).toContainText('p95 latency rose by 10 ms');
  await expect(outcome).toContainText('Conditions differ');
  await expect(outcome).not.toContainText('Matched configured workload');
});

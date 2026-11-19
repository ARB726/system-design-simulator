import {test,expect} from '@playwright/test';
import fixture from '../public/guest-demo.json';

test('bottleneck takeaway uses evidence and distinguishes a healthy candidate',async({page})=>{
  await page.route('**/api/settings',r=>r.fulfill({json:{auth:'local'}}));
  await page.route('**/api/catalog',r=>r.fulfill({json:{presets:[],challenges:[]}}));
  await page.goto('/#demo');
  const takeaway=page.getByRole('region',{name:'Bottleneck takeaway'});
  await expect(takeaway).toContainText('Database primary shows the most pressure',{timeout:20000});
  const tier=fixture.experiments[0].result.summary.tiers.db_primary;
  await expect(takeaway).toContainText((tier.mean_util*100).toFixed(1)+'%');
  await expect(takeaway).toContainText('Change one thing');
  await page.getByRole('button',{name:'Candidate: cache enabled',exact:true}).click();
  await expect(takeaway).toContainText('No clear capacity bottleneck in this snapshot');
  await expect(takeaway).not.toContainText('is limiting throughput');
});

test('missing tier evidence does not invent a bottleneck',async({page})=>{
  const data=structuredClone(fixture);
  data.experiments[0].result.summary.tiers={} as typeof data.experiments[0]['result']['summary']['tiers'];
  await page.route('**/api/settings',r=>r.fulfill({json:{auth:'local'}}));
  await page.route('**/api/catalog',r=>r.fulfill({json:{presets:[],challenges:[]}}));
  await page.route('**/guest-demo.json',r=>r.fulfill({json:data}));
  await page.goto('/#demo');
  await expect(page.getByRole('region',{name:'Bottleneck takeaway'})).toContainText('Not enough tier evidence',{timeout:20000});
});

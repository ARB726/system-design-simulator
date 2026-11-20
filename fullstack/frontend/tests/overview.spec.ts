import {test,expect} from '@playwright/test';

test.beforeEach(async({page})=>{
  await page.route('**/api/settings',r=>r.fulfill({json:{auth:'local'}}));
  await page.route('**/api/catalog',r=>r.fulfill({json:{presets:[],challenges:[]}}));
});

test('new visitors choose a workflow before entering the simulator',async({page})=>{
  await page.goto('/');
  await expect(page.getByRole('heading',{name:'Understand a system before you scale it.'})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Choose your workflow'})).toBeVisible();
  await page.getByRole('link',{name:'Open sandbox',exact:true}).click();
  await expect(page.getByLabel('Experiment name',{exact:true})).toBeVisible();
  await page.getByLabel('Experiment name',{exact:true}).fill('Keep my design');
  await page.evaluate(()=>{location.hash='experiment-settings'});
  await expect(page.getByLabel('Experiment name',{exact:true})).toHaveValue('Keep my design');
  await page.getByRole('button',{name:'Overview',exact:true}).click();
  await page.getByRole('link',{name:'Open sandbox',exact:true}).click();
  await expect(page.getByLabel('Experiment name',{exact:true})).toHaveValue('Keep my design');
  await page.reload();
  await expect(page.getByLabel('Experiment name',{exact:true})).toBeVisible();
});

test('summary and transcript remain reachable from the demo',async({page})=>{
  await page.goto('/');
  await page.getByRole('link',{name:'Try without signing in',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Two designs. See the tradeoff.'})).toBeVisible();
  await page.getByRole('link',{name:'Summary & walkthrough'}).click();
  await expect(page).toHaveURL(/\/overview\/$/);
  await page.getByText('Watch the 75-second walkthrough',{exact:true}).click();
  await expect(page.getByRole('heading',{name:'Walkthrough transcript'})).toBeVisible();
  await expect(page.locator('video')).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading',{name:'Choose your workflow'})).toBeVisible();
});

test('workflow links survive reload and the overview fits mobile',async({page})=>{
  for(const [hash,title] of [['library','A record of your reasoning.'],['learn','Build your intuition.']]){
    await page.goto('/#'+hash);
    await expect(page.getByRole('heading',{name:title})).toBeVisible();
    await page.reload();
    await expect(page.getByRole('heading',{name:title})).toBeVisible();
  }
  await page.setViewportSize({width:390,height:844});
  await page.goto('/');
  await expect(page.getByRole('link',{name:'Try without signing in',exact:true})).toBeInViewport();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  const summary=await page.getByRole('link',{name:'Summary & walkthrough'}).boundingBox();
  const environment=await page.locator('.environment').boundingBox();
  expect(summary!.x+summary!.width).toBeLessThanOrEqual(environment!.x);
  await page.screenshot({path:'test-results/overview-mobile.png',fullPage:true});
});

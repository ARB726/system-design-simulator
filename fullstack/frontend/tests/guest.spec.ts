import {test,expect} from '@playwright/test';

test('guest compares engine snapshots without protected requests or AI calls',async({page})=>{
  const protectedRequests:string[]=[];
  await page.route('**/api/settings',r=>r.fulfill({json:{auth:'supabase'}}));
  await page.route('**/api/catalog',r=>r.fulfill({json:{presets:[],challenges:[]}}));
  page.on('request',request=>{
    if(/\/api\/(experiments|import|auth)\b|\/auth\/v1\//.test(request.url()))protectedRequests.push(request.url());
  });
  await page.goto('/');
  await page.getByRole('button',{name:'Explore guest demo'}).click();
  await expect(page.getByRole('heading',{name:'Two designs. See the tradeoff.'})).toBeVisible();
  await expect(page.getByRole('table')).toBeVisible();
  await expect(page.getByRole('heading',{name:'Baseline: reads reach the database'})).toBeVisible();
  await page.getByRole('button',{name:'Candidate: cache enabled',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Candidate: add a read cache'})).toBeVisible();
  await expect(page.getByRole('button',{name:'Cache',exact:true})).toBeDisabled();
  await expect(page.getByRole('button',{name:'Explain my results'})).toHaveCount(0);
  await page.setViewportSize({width:390,height:844});
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  await page.screenshot({path:'../../test-results/guest-mobile.png',fullPage:true});
  expect(protectedRequests).toEqual([]);
  await page.getByRole('button',{name:'Back to sandbox'}).click();
  await expect(page.getByRole('button',{name:'Run simulation',exact:true})).toBeVisible();
});

test('a missing guest fixture shows a recoverable loading error',async({page})=>{
  await page.route('**/api/settings',r=>r.fulfill({json:{auth:'local'}}));
  await page.route('**/api/catalog',r=>r.fulfill({json:{presets:[],challenges:[]}}));
  await page.route('**/guest-demo.json',r=>r.fulfill({status:503}));
  await page.goto('/');
  await page.getByRole('button',{name:'Explore guest demo'}).click();
  await expect(page.getByRole('alert').filter({hasText:'Sample experiments could not be loaded'})).toBeVisible();
  await page.getByRole('button',{name:'Back to sandbox'}).click();
  await expect(page.getByRole('button',{name:'Explore guest demo'})).toBeVisible();
});

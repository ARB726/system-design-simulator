import {test,expect} from '@playwright/test';

test('a guest snapshot opens read-only in a fresh session without API or auth requests',async({page,context})=>{
  await page.route('**/api/settings',r=>r.fulfill({json:{auth:'local'}}));
  await page.route('**/api/catalog',r=>r.fulfill({json:{presets:[],challenges:[]}}));
  await page.goto('/#demo');
  await page.getByText('Share read-only snapshot',{exact:true}).click();
  await expect(page.getByText(/Anyone with this link/)).toBeVisible();
  await page.getByRole('button',{name:'Create snapshot link'}).click();
  const url=await page.getByRole('textbox',{name:'Snapshot link'}).inputValue();
  expect(url).toContain('#share=v1.');
  const receiver=await context.newPage();
  const privateRequests:string[]=[];
  receiver.on('request',r=>{if(/\/api\/|\/auth\/v1\//.test(r.url()))privateRequests.push(r.url())});
  await receiver.goto(url);
  await expect(receiver.getByRole('heading',{name:'Baseline: reads reach the database'})).toBeVisible({timeout:20000});
  await expect(receiver.getByText('Unverified shared snapshot',{exact:true})).toBeVisible();
  await expect(receiver.getByRole('button',{name:'Run simulation',exact:true})).toHaveCount(0);
  await expect(receiver.getByRole('button',{name:'Cache',exact:true})).toBeDisabled();
  await receiver.getByText('View configuration',{exact:true}).click();
  await expect(receiver.getByLabel('Shared configuration')).toContainText('read_ratio');
  expect(privateRequests).toEqual([]);
  await receiver.setViewportSize({width:390,height:844});
  expect(await receiver.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});

test('an invalid snapshot offers recovery without executing a job',async({page})=>{
  await page.goto('/#share=v1.invalid');
  await expect(page.getByRole('alert').filter({hasText:'This snapshot link is invalid'})).toBeVisible({timeout:20000});
  await page.getByRole('button',{name:'Open sandbox'}).click();
  await expect(page.getByRole('heading',{name:'Find the constraint.'})).toBeVisible();
});

import {test,expect} from '@playwright/test';

test('the first screen offers a no-sign-in demo with a reloadable link',async({page})=>{
  await page.route('**/api/settings',r=>r.fulfill({json:{auth:'local'}}));
  await page.route('**/api/catalog',r=>r.fulfill({json:{presets:[],challenges:[]}}));
  await page.goto('/#sandbox');
  const entry=page.getByRole('button',{name:'Try without signing in',exact:true});
  await expect(entry).toBeInViewport();
  await entry.click();
  await expect(page).toHaveURL(/#demo$/);
  await expect(page.getByRole('heading',{name:'Two designs. See the tradeoff.'})).toBeVisible({timeout:20000});
  await page.reload();
  await expect(page.getByRole('heading',{name:'Two designs. See the tradeoff.'})).toBeVisible({timeout:20000});
  await page.getByRole('button',{name:'Back to sandbox'}).click();
  await expect(page).not.toHaveURL(/#demo$/);
  await expect(entry).toBeVisible();
});

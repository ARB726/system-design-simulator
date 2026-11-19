import {test,expect} from '@playwright/test';

test('one live architecture supports component inspection and a clear experiment sequence',async({page})=>{
  await page.goto('/');
  await expect(page.getByRole('heading',{name:'Find the constraint.'})).toBeVisible();
  const diagram=page.getByRole('region',{name:'Interactive architecture preview'});
  await expect(diagram).toHaveCount(1);
  await expect(page.getByRole('navigation',{name:'Experiment steps'})).toBeVisible();
  await diagram.getByRole('button',{name:'Inspect database',exact:true}).click();
  await expect(diagram.getByRole('status')).toContainText('16 connections');
  await expect(diagram.getByRole('status')).toContainText('8 ms reads');
  await page.getByLabel('DB connections',{exact:true}).fill('32');
  await expect(diagram.getByRole('status')).toContainText('32 connections');
  await diagram.getByRole('button',{name:'Cache',exact:true}).click();
  await expect(page.getByRole('switch',{name:'Cache',exact:true})).not.toBeChecked();
  await page.getByRole('button',{name:'Pause flow animation'}).click();
  await expect(diagram.locator('.topology-signal').first()).toHaveCSS('animation-play-state','paused');
  await page.emulateMedia({reducedMotion:'reduce'});
  await expect(diagram.locator('.topology-signal').first()).toHaveCSS('animation-name','none');
  await expect(page.locator('.lab-atmosphere canvas')).toHaveCount(0);
});

test('the configure step jumps directly to editable parameters on mobile',async({page})=>{
  await page.setViewportSize({width:390,height:844});
  await page.goto('/');
  await page.getByRole('link',{name:'01 Configure'}).click();
  await expect(page.getByLabel('Experiment name',{exact:true})).toBeInViewport();
});

import {test,expect} from '@playwright/test';

test('architecture illustration controls real configuration and respects motion preferences',async({page})=>{
  await page.goto('/#sandbox');
  await page.evaluate(()=>document.fonts.ready);
  const preview=page.getByRole('region',{name:'Interactive architecture preview'});
  await expect(preview).toBeVisible();
  await preview.getByRole('button',{name:'Cache',exact:true}).click();
  await expect(page.getByRole('switch',{name:'Cache',exact:true})).not.toBeChecked();
  await expect(preview.getByRole('img')).toHaveAccessibleName(/cache disabled/);
  await preview.getByRole('button',{name:'Write queue',exact:true}).click();
  await expect(page.getByRole('switch',{name:'Async write queue',exact:true})).toBeChecked();
  await page.getByLabel('App replicas',{exact:true}).fill('5');
  await expect(preview.getByRole('img')).toHaveAccessibleName(/5 application replicas/);
  await page.getByRole('button',{name:'Pause background animations'}).click();
  await expect(page.locator('.topology-signal').first()).toHaveCSS('animation-play-state','paused');
  await page.emulateMedia({reducedMotion:'reduce'});
  await expect(page.locator('.topology-signal').first()).toHaveCSS('animation-name','none');
  for(const width of [1440,390,320]){
    await page.setViewportSize({width,height:900});
    await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  }
  await page.setViewportSize({width:1440,height:1000});
  await preview.screenshot({path:'../../.local/topology-desktop.png'});
  await page.setViewportSize({width:390,height:844});
  await preview.screenshot({path:'../../.local/topology-mobile.png'});
});

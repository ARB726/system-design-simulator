import {test,expect} from '@playwright/test';

test('request flow can pause, honours reduced motion and fits narrow screens',async({page})=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/');
  const signal=page.locator('.topology-signal').first();
  await expect(signal).toHaveCSS('animation-play-state','running');
  await page.getByRole('button',{name:'Pause flow animation'}).click();
  await expect(page.getByRole('button',{name:'Resume flow animation'})).toHaveAttribute('aria-pressed','true');
  await expect(signal).toHaveCSS('animation-play-state','paused');
  await page.getByRole('button',{name:'Resume flow animation'}).click();
  await expect(signal).toHaveCSS('animation-play-state','running');
  await page.emulateMedia({reducedMotion:'reduce'});
  await expect(signal).toHaveCSS('animation-name','none');
  for(const width of [1440,768,390,320]){
    await page.setViewportSize({width,height:900});
    await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await expect(page.getByRole('button',{name:'Learning lab',exact:true})).toBeVisible();
  }
  expect(errors).toEqual([]);
});

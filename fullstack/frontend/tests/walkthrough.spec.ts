import {test,expect} from '@playwright/test';

test('guest walkthrough provides a playable short video, captions and a transcript',async({page})=>{
  await page.route('**/api/settings',r=>r.fulfill({json:{auth:'local'}}));
  await page.route('**/api/catalog',r=>r.fulfill({json:{presets:[],challenges:[]}}));
  await page.goto('/#demo');
  await page.getByText('Watch the 75-second walkthrough',{exact:true}).click({timeout:20000});
  const video=page.getByLabel('Systems Lab walkthrough video');
  await expect(video).toBeVisible();
  await video.evaluate((v:HTMLVideoElement)=>v.load());
  await expect.poll(()=>video.evaluate((v:HTMLVideoElement)=>Number.isFinite(v.duration)?v.duration:0),{timeout:20000}).toBeGreaterThanOrEqual(60);
  expect(await video.evaluate((v:HTMLVideoElement)=>v.duration)).toBeLessThanOrEqual(90);
  await expect(video.locator('track[kind="captions"]')).toHaveAttribute('src','/walkthrough.vtt');
  await expect(page.getByRole('region',{name:'Walkthrough transcript'})).toContainText('database');
  await video.evaluate((v:HTMLVideoElement)=>v.play());
  await expect.poll(()=>video.evaluate((v:HTMLVideoElement)=>v.currentTime)).toBeGreaterThan(0);
  await video.evaluate((v:HTMLVideoElement)=>v.pause());
});

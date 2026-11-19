import {test,expect} from '@playwright/test';

test('the workbench keeps essential controls readable, touchable and responsive',async({page})=>{
  const fontRequests:string[]=[];
  page.on('request',r=>{if(/fonts\.googleapis|fonts\.gstatic/.test(r.url()))fontRequests.push(r.url())});
  await page.goto('/');
  const run=page.getByRole('button',{name:'Run simulation',exact:true});
  await expect(run).toBeVisible();
  expect(await run.evaluate(el=>parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(14);
  expect((await run.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  const label=page.getByLabel('Experiment name',{exact:true});
  expect(await label.evaluate(el=>parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(16);
  const contrast=await run.evaluate(el=>{
    const luminance=(s:string)=>{const rgb=s.match(/[\d.]+/g)!.slice(0,3).map(Number).map(v=>{const c=v/255;return c<=.04045?c/12.92:((c+.055)/1.055)**2.4});return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722};
    const style=getComputedStyle(el),a=luminance(style.color),b=luminance(style.backgroundColor);
    return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
  });
  expect(contrast).toBeGreaterThanOrEqual(4.5);
  for(const width of [1440,768,390,320]){
    await page.setViewportSize({width,height:900});
    await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  }
  expect(fontRequests).toEqual([]);
});

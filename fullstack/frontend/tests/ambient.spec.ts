import { test, expect } from '@playwright/test';

test('ambient effects pause, respect reduced motion, and fit narrow screens',async({page})=>{
  const errors:string[]=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto('/');
  const canvas=page.locator('.lab-atmosphere canvas');
  await expect(canvas).toBeVisible();
  await expect.poll(()=>canvas.evaluate(el=>(el as HTMLCanvasElement).width)).toBeGreaterThan(0);
  await page.getByRole('button',{name:'Pause background animations'}).click();
  await expect(page.getByRole('button',{name:'Resume background animations'})).toHaveAttribute('aria-pressed','true');
  await expect(page.locator('.aurora-violet')).toHaveCSS('animation-play-state','paused');
  await expect(page.locator('.connector.vertical').first()).toHaveCSS('animation-play-state','running');
  await expect.poll(()=>page.locator('.connector.vertical').first().evaluate(el=>getComputedStyle(el,'::before').animationPlayState)).toBe('paused');
  // Allow tiny GPU readback rounding differences while checking rendered pixels.
  const movement=()=>canvas.evaluate(async el=>{
    const c=el as HTMLCanvasElement,ctx=c.getContext('2d')!;
    const before=ctx.getImageData(0,0,c.width,c.height).data;
    await new Promise(resolve=>setTimeout(resolve,200));
    const after=ctx.getImageData(0,0,c.width,c.height).data;
    let changed=0;
    for(let i=0;i<before.length;i++)if(Math.abs(before[i]-after[i])>4)changed++;
    return changed/before.length;
  });
  await expect.poll(movement).toBeLessThan(.001);
  const still=await canvas.evaluate(el=>(el as HTMLCanvasElement).toDataURL());
  await page.getByRole('button',{name:'Resume background animations'}).click();
  await expect.poll(()=>canvas.evaluate((el,old)=>(el as HTMLCanvasElement).toDataURL()!==old,still)).toBeTruthy();
  await page.emulateMedia({reducedMotion:'reduce'});
  await expect(page.locator('.aurora-violet')).toHaveCSS('animation-name','none');
  await expect.poll(()=>page.locator('.connector.vertical').first().evaluate(el=>getComputedStyle(el,'::before').animationName)).toBe('none');
  await expect.poll(movement).toBeLessThan(.001);
  for(const width of [1440,768,390,320]){
    await page.setViewportSize({width,height:900});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
    await expect(page.getByRole('button',{name:'Learning lab',exact:true})).toBeVisible();
  }
  expect(errors).toEqual([]);
});

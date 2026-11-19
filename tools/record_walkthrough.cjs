/* Create a 75-second captioned UI slideshow from real engine snapshots.
 * Requires installed frontend dependencies, Chrome and Playwright FFmpeg.
 * Usage: node tools/record_walkthrough.cjs <fixture.json> <ffmpeg.exe> [baseURL]
 */
const {chromium}=require('../fullstack/frontend/node_modules/playwright');
const fs=require('node:fs/promises');
const path=require('node:path');
const {spawn}=require('node:child_process');
const {once}=require('node:events');

async function main(){
  const [fixturePath,ffmpeg,baseURL='http://127.0.0.1:8080']=process.argv.slice(2);
  if(!fixturePath||!ffmpeg)throw new Error('Supply the engine fixture JSON and FFmpeg executable paths.');
  const fixture=JSON.parse(await fs.readFile(fixturePath,'utf8'));
  const [baseline,candidate]=fixture.experiments;
  if(baseline.result.summary.success_rate>=1||candidate.result.summary.success_rate<=baseline.result.summary.success_rate)throw new Error('The walkthrough requires a failing baseline and improved candidate.');
  const publicDir=path.resolve(__dirname,'../fullstack/frontend/public');
  const frames=[];
  const evidence=path.resolve(__dirname,'../.local/walkthrough-frames');
  if(process.argv.includes('--encode-only')){
    for(let i=1;i<=5;i++)frames.push(await fs.readFile(path.join(evidence,`step-${i}.jpg`)));
  }else{
  const browser=await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL||'chrome',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1280,height:900},reducedMotion:'reduce'});
    await page.route('**/api/settings',r=>r.fulfill({json:{auth:'local'}}));
    await page.route('**/api/catalog',r=>r.fulfill({json:{presets:[],challenges:[]}}));
    await page.route('**/guest-demo.json',r=>r.fulfill({json:fixture}));
    await page.goto(baseURL+'/#demo');
    await page.getByRole('region',{name:'Before and after'}).waitFor();
    await page.addStyleTag({content:'.lab-atmosphere,.ambient-toggle,nextjs-portal{display:none!important}body{padding-bottom:170px!important}'});
    await page.evaluate(()=>{
      const caption=document.createElement('div');caption.id='video-caption';
      caption.style.cssText='position:fixed;bottom:0;left:0;right:0;z-index:9999;background:#090c16f5;border-top:2px solid #b49aff;padding:26px 40px;color:#fff;font:22px/1.5 system-ui;min-height:130px';
      document.body.append(caption);
    });
    async function frame(title,caption,locator){
      if(locator)await locator.scrollIntoViewIfNeeded();else await page.evaluate(()=>scrollTo(0,0));
      await page.evaluate(({title,caption})=>{const el=document.getElementById('video-caption');el.replaceChildren();const strong=document.createElement('strong');strong.textContent=title;const line=document.createElement('div');line.textContent=caption;el.append(strong,line)},{title,caption});
      frames.push(await page.screenshot({animations:'disabled',type:'jpeg',quality:85}));
    }
    await frame('1 / 5 · Start with an overloaded design','500 offered requests/s · two database connections · recorded Python/SimPy evidence');
    await frame('2 / 5 · Identify the pressure','Inspect database utilization, queues and failed requests. Form a hypothesis.',page.getByRole('region',{name:'Bottleneck takeaway'}));
    await page.getByRole('button',{name:'Candidate: cache enabled',exact:true}).click();
    await frame('3 / 5 · Change one thing','Enable a read cache. Keep workload, seed and database capacity fixed.',page.getByRole('heading',{name:'Candidate: add a read cache'}));
    await frame('4 / 5 · Compare the measured tradeoff','Check throughput, p95 latency, success and illustrative cost. This is not production capacity.',page.getByRole('region',{name:'Before and after'}));
    await page.getByText('Share read-only snapshot',{exact:true}).click();
    await page.getByRole('button',{name:'Create snapshot link'}).click();
    await frame('5 / 5 · Share the evidence','A read-only link includes configuration and results. No recipient sign-in required.',page.getByText('Share read-only snapshot',{exact:true}));
    await page.evaluate(()=>document.getElementById('video-caption').remove());
    await page.evaluate(()=>scrollTo(0,0));
    await page.screenshot({path:path.join(publicDir,'walkthrough-poster.jpg'),type:'jpeg',quality:80});
  }finally{await browser.close()}
  }
  await fs.mkdir(evidence,{recursive:true});
  for(let i=0;i<frames.length;i++)await fs.writeFile(path.join(evidence,`step-${i+1}.jpg`),frames[i]);
  const encoder=spawn(ffmpeg,['-hide_banner','-loglevel','error','-y','-f','image2pipe','-r','1','-vcodec','mjpeg','-i','pipe:0','-c:v','libvpx-vp9','-deadline','realtime','-cpu-used','8','-crf','32','-b:v','0','-g','15','-pix_fmt','yuv420p','-r','1',path.join(publicDir,'walkthrough.webm')],{stdio:['pipe','ignore','pipe'],windowsHide:true});
  let errors='';encoder.stderr.on('data',b=>{errors+=b});
  const finished=once(encoder,'close');
  try{for(const frame of frames)for(let i=0;i<15;i++)if(!encoder.stdin.write(frame))await once(encoder.stdin,'drain')}catch{await finished;throw new Error(errors||'Video encoder closed its input unexpectedly.')}
  encoder.stdin.end();const [code]=await finished;
  if(code!==0)throw new Error(errors);
  console.log('Created 75-second captioned walkthrough and poster.');
}
main().catch(error=>{console.error(error.message);process.exitCode=1});

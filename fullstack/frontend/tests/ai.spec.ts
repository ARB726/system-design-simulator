import { test, expect, type Page } from '@playwright/test';

const job={id:'ai-baseline',created:1700000000,status:'completed',payload:{name:'AI baseline',config:{seed:42},kind:'simulate'},result:{type:'simulation',summary:{served_rps:480,p50_ms:20,p95_ms:50,p99_ms:90,success_rate:.96,tiers:{},fail:{}},timeline:[],histogram:[],findings:[],warnings:[],cost:491,runtime_s:.2}};
const answer={explanation:{summary:'The saved run has a measured p95 latency of 50 ms.',observations:[{metric:'p95_ms',interpretation:'Inspect saturation before changing capacity.'}],next_experiment:'Increase app workers with workload and seed fixed.',limitations:'This simplified simulation does not predict production performance.'},measurements:[{key:'p95_ms',label:'p95 latency',value:50,unit:'ms'}],model:'test-model',cached:true};

async function workspace(page:Page,enabled:boolean,provider:'openai'|'gemini'='openai'){
  await page.addInitScript(()=>{sessionStorage.setItem('lab-token','test-ui-token');sessionStorage.setItem('lab-identity','Test workspace');});
  await page.route('**/api/settings',route=>route.fulfill({json:{auth:'local',ai_enabled:enabled,ai_provider:provider}}));
  await page.route('**/api/catalog',route=>route.fulfill({json:{presets:[],challenges:[]}}));
  await page.route('**/api/experiments',route=>route.fulfill({json:[job]}));
  await page.route('**/api/experiments/ai-baseline',route=>route.fulfill({json:job}));
  await page.goto('/#sandbox');
  await page.getByRole('button',{name:'Experiment library',exact:true}).click();
  await page.getByRole('button',{name:/AI baseline.*Seed/}).click();
  await expect(page.getByRole('heading',{name:'Understand this experiment'})).toBeVisible();
}

test('AI is on demand, recovers from errors, and shows measured evidence',async({page})=>{
  let calls=0;
  await page.route('**/api/experiments/ai-baseline/explanation',async route=>{
    calls++;
    expect(route.request().method()).toBe('POST');
    expect(route.request().headers().authorization).toBe('Bearer test-ui-token');
    if(calls===1)await route.fulfill({status:504,json:{detail:'The AI explanation timed out. Your simulation results are still available.'}});
    else await route.fulfill({json:answer});
  });
  await workspace(page,true);
  expect(calls).toBe(0);
  await expect(page.getByText(/selected metrics are sent to OpenAI/)).toBeVisible();
  await page.getByRole('button',{name:'Explain my results'}).click();
  await expect(page.locator('.ai-coach').getByRole('alert')).toContainText('timed out');
  await expect(page.getByText('Successful throughput',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Retry explanation'}).click();
  await expect(page.getByText(answer.explanation.summary)).toBeVisible();
  await expect(page.getByText('p95 latency: 50 ms',{exact:true})).toHaveCount(2);
  await expect(page.getByText(/Cached explanation/)).toBeVisible();
  expect(calls).toBe(2);
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  await page.screenshot({path:'../../.local/fullstack-ai.png',fullPage:true});
  await page.locator('.ai-coach').screenshot({path:'../../.local/fullstack-ai-panel.png'});
});

test('unconfigured AI preserves the results without making model requests',async({page})=>{
  let calls=0;
  await page.route('**/api/experiments/ai-baseline/explanation',route=>{calls++;return route.abort();});
  await workspace(page,false);
  await expect(page.getByText(/AI explanations are not enabled/)).toBeVisible();
  await expect(page.getByRole('button',{name:'Explain my results'})).toHaveCount(0);
  await expect(page.getByText('Successful throughput',{exact:true})).toBeVisible();
  expect(calls).toBe(0);
});


test('Gemini consent and provenance name the configured provider',async({page})=>{
  let calls=0;
  await page.route('**/api/experiments/ai-baseline/explanation',route=>{
    calls++;
    expect(route.request().headers()).not.toHaveProperty('x-goog-api-key');
    return route.fulfill({json:{...answer,provider:'gemini',model:'gemini-flash-latest'}});
  });
  await workspace(page,true,'gemini');
  await expect(page.getByText(/selected metrics are sent to Google Gemini/)).toBeVisible();
  await expect(page.getByText(/selected metrics are sent to OpenAI/)).toHaveCount(0);
  expect(calls).toBe(0);
  await page.getByRole('button',{name:'Explain my results'}).click();
  await expect(page.locator('.ai-provenance')).toContainText('Google Gemini');
  await expect(page.locator('.ai-provenance')).toContainText('gemini-flash-latest');
  await expect(page.getByText(answer.explanation.summary)).toBeVisible();
  expect(calls).toBe(1);
  await page.locator('.ai-coach').screenshot({path:'../../.local/fullstack-gemini-panel.png'});
});

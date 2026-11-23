'use client';

import { useEffect, useRef, useState } from 'react';
import { LabMotion, LabScene, ViewTransition, DesignTelemetry } from './lab-effects';
import { Activity, ArrowDownToLine, ArrowRight, BookOpen, Boxes, Check, ChevronRight, Clock3, Database, FlaskConical, GitCompareArrows, Layers3, LayoutDashboard, Library, LoaderCircle, LogOut, Play, Plus, Radio, RotateCcw, Server, ShieldCheck, Workflow, Zap } from 'lucide-react';
import dynamic from 'next/dynamic';
import TopologyHero from './topology-hero';
import ComparisonDeltas from './comparison-deltas';
import OverviewContent from './overview-content';
const AIExplanation=dynamic(()=>import('./ai-explanation'),{loading:()=> <div className="panel empty-results" role="status">Loading architecture coach...</div>});
const GuestDemo=dynamic(()=>import('./guest-demo'),{loading:()=> <p role="status">Opening guest demo...</p>});
const ResultCharts = dynamic(()=>import('./result-charts'),{loading:()=> <div className="empty-results" role="status">Loading charts...</div>});

import type { Config, Result, Job, Preset, Challenge, Settings } from './lab-types';
type Runtime = {apiUrl?:string};
declare global { interface Window { SYSTEMS_LAB?: Runtime } }

const defaults: Config = {name:'Custom design',app:{replicas:3,workers:8,latency_ms:20,lb_strategy:'least_queue',max_queue:200},cache:{enabled:true,hit_rate:.85,latency_ms:1,workers:64},cdn:{enabled:false,hit_rate:.6,latency_ms:8},queue:{enabled:false,consumers:8,max_depth:5000,enqueue_ms:2},db:{workers:16,read_ms:8,write_ms:25,read_replicas:0,max_queue:500,shards:1,hot_share:0},workload:{rps:500,read_ratio:.95,duration_s:30,timeout_ms:1000,warmup_s:5},events:[],seed:42,app_only:false,policy:{max_retries:0,backoff_ms:100,backoff_multiplier:2,jitter:true,rate_limit_rps:null,burst:100}};

const number = (n:number|undefined, digits=0) => n == null ? '—' : n.toLocaleString(undefined,{maximumFractionDigits:digits});
const money = (n:number) => '$'+number(n);
const cost = (c:Config) => c.app.replicas*(15+6*c.app.workers)+(c.cache.enabled?50:0)+(c.cdn.enabled?40:0)+(c.queue.enabled?30+4*c.queue.consumers:0)+c.db.shards*(1+c.db.read_replicas)*(60+12*c.db.workers);
const enc = (b:Uint8Array) => btoa(String.fromCharCode(...b)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');

export default function Home() {
  const [guest,setGuest]=useState(false);
  useEffect(()=>{
    const sync=()=>{
      const view=location.hash.slice(1);
      setGuest(view==='demo');
      if(['overview','sandbox','library','compare','learn'].includes(view))setView(view);
      else if(!view || view === 'first-experiment')setView('overview');
    };
    function navigate(){
      sync();
      if(['overview','sandbox','library','compare','learn','demo'].includes(location.hash.slice(1)))window.scrollTo(0,0);
    }
    sync();window.addEventListener('hashchange',navigate);
    return()=>window.removeEventListener('hashchange',navigate);
  },[]);
  function openGuest(){location.hash='demo';setGuest(true)}
  function closeGuest(){location.hash='sandbox';setTab('sandbox');setGuest(false)}
  const [apiBase,setApiBase]=useState(''); const [settings,setSettings]=useState<Settings>();
  const [token,setToken]=useState(''); const [identity,setIdentity]=useState('');
  const [tab,setView]=useState('overview');
  function setTab(view:string){setView(view);if(location.hash.slice(1)!==view)location.hash=view;} const [config,setConfig]=useState<Config>(defaults);
  const [presets,setPresets]=useState<Preset[]>([]); const [challenges,setChallenges]=useState<Challenge[]>([]);
  const [preset,setPreset]=useState('Custom design'); const [story,setStory]=useState('Start with a design. Change one thing. See what happens.');
  const [jobs,setJobs]=useState<Job[]>([]); const [selected,setSelected]=useState<Job>(); const [comparison,setComparison]=useState<string[]>([]); const [compareJobs,setCompareJobs]=useState<Job[]>([]);
  const [error,setError]=useState(''); const [loading,setLoading]=useState(false); const [authOpen,setAuthOpen]=useState(false); const [register,setRegister]=useState(true); const [email,setEmail]=useState(''); const [password,setPassword]=useState('');
  const [challenge,setChallenge]=useState<Challenge>(); const [advanced,setAdvanced]=useState(''); const [exporting,setExporting]=useState(false);
  const fileRef=useRef<HTMLInputElement>(null);
  const archiveRef=useRef<HTMLInputElement>(null);

  async function api<T>(path:string, options:RequestInit={}, auth=token):Promise<T> {
    const response=await fetch(apiBase+path,{...options,headers:{'Content-Type':'application/json',...(auth?{Authorization:'Bearer '+auth}:{}),...options.headers}});
    if (!response.ok) { const data=await response.json().catch(()=>({detail:'Request failed'})); if(response.status===401){setAuthOpen(true)} throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail)); }
    return response.json();
  }
  useEffect(()=>{ let active=true;let disconnect:(()=>void)|undefined; (async()=>{
    let runtime:Runtime={};
    try { const r=await fetch('/runtime-config.json',{cache:'no-store'}); if(r.ok)runtime=await r.json(); }catch{}
    const base=runtime.apiUrl || process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';
    if(!active)return; setApiBase(base.replace(/\/$/,''));
    const [s,c]=await Promise.all([fetch(base+'/api/settings').then(r=>r.json()),fetch(base+'/api/catalog').then(r=>r.json())]);
    if(!active)return;setSettings(s);setPresets(c.presets);setChallenges(c.challenges);
    if(s.auth==='supabase'){
      sessionStorage.removeItem('lab-token');sessionStorage.removeItem('lab-identity');
      const {connectGoogleSession}=await import('./google-auth');
      const stop=await connectGoogleSession(s,session=>{
        if(!active)return;
        setToken(session?.access_token||'');setIdentity(session?.user.email||'');
        if(session)setAuthOpen(false);
        else{setJobs([]);setSelected(undefined);setComparison([]);setCompareJobs([]);}
      });
      if(active)disconnect=stop;else stop();
      return;
    }
    const saved=sessionStorage.getItem('lab-token');if(saved){setToken(saved);setIdentity(sessionStorage.getItem('lab-identity')||'My workspace')}
    const params=new URLSearchParams(location.search);
    if(params.has('error'))throw new Error(params.get('error_description')||'Sign-in was canceled.');
    if(s.auth==='cognito'&&params.has('code')){
      const state=sessionStorage.getItem('oauth-state');const verifier=sessionStorage.getItem('oauth-verifier');
      if(!state || state!==params.get('state') || !verifier)throw new Error('Sign-in state did not match. Please try again.');
      const response=await fetch(s.domain+'/oauth2/token',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({grant_type:'authorization_code',client_id:s.client_id,code:params.get('code')!,redirect_uri:location.origin+'/',code_verifier:verifier})});
      if(!response.ok)throw new Error('Unable to finish sign-in. Please try again.');
      const data=await response.json();sessionStorage.removeItem('oauth-verifier');sessionStorage.removeItem('oauth-state');
      sessionStorage.setItem('lab-token',data.access_token);sessionStorage.setItem('lab-identity','My workspace');setToken(data.access_token);setIdentity('My workspace');history.replaceState(null,'','/');
    }
  })().catch(e=>{if(active)setError('Could not connect: '+e.message)});return()=>{active=false;disconnect?.()}},[]);
  async function refresh(){if(token)setJobs(await api<Job[]>('/api/experiments'))}
  useEffect(()=>{if(!token||!apiBase)return;refresh().catch(e=>setError(e.message))},[token,apiBase]);
  useEffect(()=>{if(!token||!selected||!['queued','running'].includes(selected.status))return;
    let active=true,delay=1800,timer:ReturnType<typeof setTimeout>;
    const controller=new AbortController();
    async function poll(){
      try{
        const job=await api<Job>('/api/experiments/'+selected!.id,{signal:controller.signal});
        if(!active)return;
        setSelected(job);
        if(['completed','failed'].includes(job.status)){refresh().catch(()=>{});return;}
        delay=job.status==='running'?1800:Math.min(delay*1.5,8000);
      }catch(e){if(!active)return;setError((e as Error).message);delay=Math.min(delay*2,10000);}
      if(active)timer=setTimeout(poll,delay);
    }
    timer=setTimeout(poll,delay);
    return()=>{active=false;clearTimeout(timer);controller.abort();};
  },[selected?.id,selected?.status,token,apiBase]);
  useEffect(()=>{if(comparison.length!==2){setCompareJobs([]);return}Promise.all(comparison.map(id=>api<Job>('/api/experiments/'+id))).then(setCompareJobs).catch(e=>setError(e.message))},[comparison.join(','),token]);
  function update(section:keyof Config,key:string,value:unknown){setConfig(c=>({...c,[section]:{...(c[section] as object),[key]:value}}));setPreset('Custom design')}
  function loadPreset(p:Preset){setConfig(structuredClone(p.config));setPreset(p.name);setStory(p.story);setChallenge(undefined);setSelected(undefined)}
  async function signIn(){setError('');if(settings?.auth!=='cognito'){setAuthOpen(true);return}
    const verifier=enc(crypto.getRandomValues(new Uint8Array(32))); const state=enc(crypto.getRandomValues(new Uint8Array(24)));
    sessionStorage.setItem('oauth-verifier',verifier);sessionStorage.setItem('oauth-state',state);
    const challenge=enc(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(verifier))));
    location.assign(settings.domain+'/oauth2/authorize?'+new URLSearchParams({response_type:'code',client_id:settings.client_id!,redirect_uri:location.origin+'/',scope:'openid email',state,code_challenge:challenge,code_challenge_method:'S256'}));
  }
  async function authenticate(e:React.FormEvent){e.preventDefault();setLoading(true);setError('');try{const data=await api<{access_token:string;email:string}>('/api/auth/'+(register?'register':'login'),{method:'POST',body:JSON.stringify({email,password})},'');sessionStorage.setItem('lab-token',data.access_token);sessionStorage.setItem('lab-identity',data.email);setToken(data.access_token);setIdentity(data.email);setAuthOpen(false);setPassword('')}catch(e){setError((e as Error).message)}finally{setLoading(false)}}
  async function logout(){if(settings?.auth==='supabase'){try{const {signOutGoogle}=await import('./google-auth');await signOutGoogle(settings)}catch(e){setError((e as Error).message);return;}}sessionStorage.removeItem('lab-token');sessionStorage.removeItem('lab-identity');setToken('');setIdentity('');setJobs([]);setSelected(undefined);setComparison([]);setCompareJobs([]);if(settings?.auth==='cognito')location.assign(settings.domain+'/logout?'+new URLSearchParams({client_id:settings.client_id!,logout_uri:location.origin+'/'}))}
  async function run(kind='simulate'){setError('');if(!token){await signIn();return}setLoading(true);try{const j=await api<Job>('/api/experiments',{method:'POST',body:JSON.stringify({name:config.name||preset,config,kind,challenge:challenge?.id})});setSelected(j);setTab('sandbox');await refresh()}catch(e){setError((e as Error).message)}finally{setLoading(false)}}
  async function openJob(j:Job){try{setSelected(await api<Job>('/api/experiments/'+j.id));setTab('sandbox')}catch(e){setError((e as Error).message)}}
  function download(value:unknown,name:string){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();URL.revokeObjectURL(url)}
  async function exportAll(){setExporting(true);try{const all:Job[]=[];for(const j of jobs){if(!['completed','failed'].includes(j.status))throw new Error('Wait for active experiments to finish before exporting the archive.');all.push(await api<Job>('/api/experiments/'+j.id));if(settings?.auth==='cognito')await new Promise(resolve=>setTimeout(resolve,600))}download({version:1,experiments:all},'systems-lab-experiments.json')}catch(e){setError((e as Error).message)}finally{setExporting(false)}}
  async function importArchive(file?:File){if(!file)return;setError('');try{if(file.size>8000000)throw new Error('Archive must be under 8 MB. Export individual experiments for larger libraries.');const data=JSON.parse(await file.text());const archive=data.payload?{version:1,experiments:[data]}:data;await api('/api/import',{method:'POST',body:JSON.stringify(archive)});await refresh()}catch(e){setError((e as Error).message)}finally{if(archiveRef.current)archiveRef.current.value=''}}
  const result=selected?.result;const summary=result?.summary;const busy=loading||!!(selected&&['queued','running'].includes(selected.status));

  if(guest)return <GuestDemo onExit={closeGuest} onSignIn={()=>{closeGuest();void signIn()}}/>;
  return <LabMotion><div className="app-shell"><LabScene/>
    <aside className="sidebar">
      <a className="brand" href="/" aria-label="Systems Lab home"><span className="brand-mark"><Layers3 size={23}/></span><span>systems<span className="brand-light">lab</span><small>THE ARCHITECTURE PLAYGROUND</small></span></a>
      <div className="workspace"><span className="workspace-icon">S</span><span>Personal workspace<small>{token?'Connected workspace':'Explore the lab'}</small></span><ChevronRight size={15}/></div>
      <div className="nav-label">WORKSPACE</div>
      <nav aria-label="Workspace">{[
        {id:'overview',label:'Overview',short:'Overview',icon:Layers3},
        {id:'sandbox',label:'Sandbox',short:'Sandbox',icon:LayoutDashboard},
        {id:'library',label:'Experiment library',short:'Library',icon:Library},
        {id:'compare',label:'Compare designs',short:'Compare',icon:GitCompareArrows},
        {id:'learn',label:'Learning lab',short:'Learn',icon:BookOpen},
      ].map(n=><button key={n.id} aria-label={n.label} aria-current={tab===n.id?'page':undefined} title={n.label}
        className={'nav-item '+(tab===n.id?'active':'')} onClick={()=>setTab(n.id)}>
        <n.icon size={18}/><span className="nav-full-label">{n.label}</span><span className="nav-short-label">{n.short}</span>
        {n.id==='library'&&jobs.length>0&&<span className="count">{jobs.length}</span>}
      </button>)}</nav>
      <div className="sidebar-bottom"><div className="lab-note"><FlaskConical size={22}/><strong>Experiment with confidence.</strong><p>These are simulations. Your design does not provision real infrastructure.</p></div><button className="profile" aria-label={token?'Sign out of '+identity:'Sign in to save experiments'} onClick={()=>token?logout():signIn()}><span className="avatar">{identity?identity[0].toUpperCase():'Y'}</span><span>{identity||'Your workspace'}<small>{token?'Sign out':'Sign in to save experiments'}</small></span><span className="profile-mobile-label">{token?'Sign out':'Sign in'}</span>{token?<LogOut size={16}/>:<ArrowRight size={16}/>}</button></div>
    </aside>
    <div className="main-shell"><header className="topbar"><span>Workspace <ChevronRight size={13}/> <strong>{tab==='overview'?'Overview':tab==='sandbox'?'Sandbox':tab==='library'?'Experiment library':tab==='compare'?'Compare designs':'Learning lab'}</strong></span><a className="button text-button summary-link" href="/overview/">Summary &amp; walkthrough</a><span className="environment"><span/> {settings?.auth==='local'?'Local workspace':'Cloud workspace'}</span></header>
    <main><ViewTransition view={tab}>
      {error&&<div className="error" role="alert">{error}<button aria-label="Dismiss error" onClick={()=>setError('')}>×</button></div>}
      {tab==='overview'&&<OverviewContent signedIn={!!token}/>}
      {tab==='sandbox'&&<>
        {!token&&<section className="panel guest-entry"><div><strong>See what a read cache changes.</strong><p>Explore two recorded simulations and compare their results. No sign-in required.</p></div><button className="button primary" onClick={()=>{setError('');openGuest()}}>Try without signing in <ArrowRight size={16}/></button></section>}
        <div className="page-heading"><div><div className="eyebrow"><span/> BUILD · BREAK · UNDERSTAND</div><h1>Your architecture. Under pressure.</h1><p>Design a system, push its limits, and discover what really makes it work.</p></div><button className="button secondary" onClick={()=>{setConfig(structuredClone(defaults));setSelected(undefined);setPreset('Custom design');setChallenge(undefined);setStory('Start with a design. Change one thing. See what happens.')}}><Plus size={16}/> New experiment</button></div>
        <TopologyHero config={config} onToggle={(section,value)=>update(section,'enabled',value)}/><DesignTelemetry rps={config.workload.rps} replicas={config.app.replicas} seed={config.seed} busy={busy}/><div className="scenario-bar"><div className="scenario-icon"><FlaskConical size={20}/></div><label>STARTING POINT<select aria-label="Scenario" value={preset} onChange={e=>{const p=presets.find(p=>p.name===e.target.value);if(p)loadPreset(p)}}><option value="Custom design">Custom design</option>{presets.map(p=><option key={p.name}>{p.name}</option>)}</select></label><div className="scenario-description">{story}</div><span className="badge">SimPy engine</span></div>
        <div className="editor-grid"><section className="panel architecture"><div className="panel-heading"><div><h2><Workflow size={17}/> Architecture canvas</h2><p>A live view of the system you’re designing</p></div><span className="subtle">{[true,config.cache.enabled,config.cdn.enabled,config.queue.enabled,true].filter(Boolean).length} components</span></div>
          <div className="canvas"><div className="canvas-tag"><span/> DESIGN MODE</div><div className="flow-origin"><Radio size={19}/><strong>Incoming traffic</strong><small>{number(config.workload.rps)} requests / sec</small></div><div className="connector vertical"/>{config.cdn.enabled&&<><div className="mini-node"><Zap size={16}/> CDN <span>{number(config.cdn.hit_rate*100)}% hit rate</span></div><div className="connector vertical"/></>}
          <div className="flow-node app-node"><span className="node-icon violet"><Server size={22}/></span><div><strong>Application tier</strong><small>{config.app.replicas} replicas · {config.app.workers} workers each</small></div><span className="node-status"/></div><div className="connector vertical"><span>reads & writes</span></div>
          <div className="branch-nodes">{config.cache.enabled&&<div className="flow-node compact"><span className="node-icon amber"><Zap size={20}/></span><div><strong>Cache</strong><small>{number(config.cache.hit_rate*100)}% hit rate</small></div></div>}{config.queue.enabled&&<div className="flow-node compact"><span className="node-icon blue"><Layers3 size={20}/></span><div><strong>Write queue</strong><small>{config.queue.consumers} consumers</small></div></div>}</div>{(config.cache.enabled||config.queue.enabled)&&<div className="connector vertical"/>}
          <div className="flow-node"><span className="node-icon teal"><Database size={22}/></span><div><strong>Database tier</strong><small>{config.db.shards} shard{config.db.shards!==1?'s':''} · {config.db.workers} connections · {config.db.read_replicas} read replicas</small></div><span className="node-status"/></div><div className="canvas-legend"><span><i className="legend-dot violet"/>Compute</span><span><i className="legend-dot amber"/>Acceleration</span><span><i className="legend-dot teal"/>Persistence</span></div></div>
          <div className="cost-strip"><span>Illustrative design cost <small>Simulated resources, not your AWS bill</small></span><strong>{money(cost(config))}<small> / month</small></strong></div>
        </section>
        <section className="panel controls"><div className="panel-heading"><div><h2><Activity size={17}/> Experiment settings</h2><p>Small changes. Measurable differences.</p></div><button className="icon-button" aria-label="Reset settings" onClick={()=>setConfig(structuredClone(defaults))}><RotateCcw size={15}/></button></div>
          <div className="control-body"><label className="text-label">Experiment name<input value={config.name} maxLength={100} onChange={e=>setConfig({...config,name:e.target.value})}/></label><div className="control-section">WORKLOAD</div>
          <Slider label="Request rate" value={config.workload.rps} min={10} max={2000} step={10} suffix="req/s" onChange={v=>update('workload','rps',v)}/><Slider label="Simulation duration" value={config.workload.duration_s} min={10} max={60} step={5} suffix="sec" onChange={v=>update('workload','duration_s',v)}/><Slider label="Read traffic" value={config.workload.read_ratio*100} min={0} max={100} step={1} suffix="%" onChange={v=>update('workload','read_ratio',v/100)}/>
          <div className="control-section">CAPACITY</div><div className="two-fields"><NumberField label="App replicas" value={config.app.replicas} min={1} max={64} onChange={v=>update('app','replicas',v)}/><NumberField label="Workers / replica" value={config.app.workers} min={1} max={256} onChange={v=>update('app','workers',v)}/><NumberField label="DB connections" value={config.db.workers} min={1} max={256} onChange={v=>update('db','workers',v)}/><NumberField label="Database shards" value={config.db.shards} min={1} max={64} onChange={v=>update('db','shards',v)}/><NumberField label="Read replicas" value={config.db.read_replicas} min={0} max={16} onChange={v=>update('db','read_replicas',v)}/><NumberField label="Random seed" value={config.seed} min={0} max={999999} onChange={v=>setConfig({...config,seed:v})}/></div>
          <div className="control-section">COMPONENTS</div>{(['cache','cdn','queue'] as const).map(k=><div key={k}><Toggle label={k==='cache'?'Cache':k==='cdn'?'Content delivery network':'Async write queue'} checked={config[k].enabled} onChange={v=>update(k,'enabled',v)}/>{config[k].enabled&&(k==='queue'?<NumberField label="Queue consumers" value={config.queue.consumers} min={1} max={256} onChange={v=>update('queue','consumers',v)}/>:<Slider label="Hit rate" value={config[k].hit_rate*100} min={0} max={100} step={1} suffix="%" onChange={v=>update(k,'hit_rate',v/100)}/>)}</div>)}
          <div className="control-section">FAILURE INJECTION</div><label className="text-label">Chaos event<select aria-label="Chaos event" value={config.events[0]?.kind||''} onChange={e=>setConfig({...config,events:e.target.value?[{kind:e.target.value,start_s:Math.min(10,config.workload.duration_s/3),duration_s:Math.min(10,config.workload.duration_s/3),magnitude:e.target.value==='cold_cache'?0:e.target.value==='kill_app'?1:3}]:[]})}><option value="">No failures — steady state</option><option value="cold_cache">Cache goes cold</option><option value="traffic_spike">Traffic spike ×3</option><option value="db_slow">Database slowdown ×3</option><option value="kill_app">One app replica crashes</option></select></label>
          <details onToggle={e=>{if(e.currentTarget.open)setAdvanced(JSON.stringify(config,null,2))}}><summary>Advanced configuration & import</summary><p className="subtle">Edit all engine parameters, including retries, admission control, and chaos timing.</p><textarea aria-label="Advanced configuration" value={advanced} onChange={e=>setAdvanced(e.target.value)} rows={10}/><button className="button secondary" onClick={()=>{try{const c=JSON.parse(advanced);if(!c.app||!c.workload||!c.db)throw new Error('Missing configuration sections');setConfig(c);setPreset('Custom design');setError('')}catch(e){setError((e as Error).message)}}}>Apply JSON</button><button className="button text-button" onClick={()=>download(config,'architecture.json')}>Export configuration</button><input ref={fileRef} type="file" accept="application/json,.json" aria-label="Import configuration" onChange={async e=>{try{const f=e.target.files?.[0];if(!f)return;if(f.size>24000)throw new Error('Configuration must be under 24 KB');const data=JSON.parse(await f.text());const c=data.payload?.config||data.config||data;if(!c.app||!c.db||!c.workload)throw new Error('Choose an exported configuration or experiment');setConfig(c);setPreset('Custom design');setAdvanced(JSON.stringify(c,null,2))}catch(e){setError((e as Error).message)}}}/></details>
          </div><div className="run-footer"><button className="button primary run" disabled={busy} onClick={()=>run()}>{busy?<LoaderCircle size={17} className="spin"/>:<Play size={17}/>} {busy?(selected?.status==='running'?'Running simulation…':'Experiment queued…'):'Run simulation'}{!busy&&<ArrowRight size={17}/>}</button><span><ShieldCheck size={12}/> Reproducible with seed {config.seed}</span></div>
        </section></div>
        {challenge&&<section className="panel challenge-active"><h2>{challenge.title}</h2><p>{challenge.slo} · Budget {money(challenge.budget)}/month</p><button className="button secondary" disabled={busy} onClick={()=>run('grade')}>Grade against challenge checks</button><p className="subtle">Allowed values: {Object.entries(challenge.knobs).map(([k,v])=>k+': '+v.join(', ')).join(' · ')}</p></section>}
        <section className="results-section"><div className="section-heading"><div><h2>Experiment results</h2><p>{selected?`${selected.payload.name} · ${new Date(selected.created*1000).toLocaleString()}`:'The evidence behind your next design decision.'}</p></div>{selected?.result&&<button className="button secondary" onClick={()=>download(selected,'experiment-'+selected.id+'.json')}><ArrowDownToLine size={15}/> Export result</button>}</div>
        {!selected?<div className="empty-results"><span className="empty-icon"><Activity size={25}/></span><h3>Every good design starts with a question.</h3><p>Run your first simulation to uncover throughput, latency, and bottlenecks.</p><div className="empty-metrics"><span><i/> Throughput</span><span><i/> Tail latency</span><span><i/> Reliability</span><span><i/> Resource pressure</span></div></div>:busy?<div className="empty-results" role="status"><LoaderCircle className="spin" size={26}/><h3>{selected.status==='running'?'Your architecture is under pressure.':'Your experiment is in the queue.'}</h3><p>You can leave this page. Your experiment is saved in the library.</p></div>:selected.status==='failed'?<div className="error">{selected.error}</div>:result?.type==='grade'?<div className="panel grade"><h3>{result.passed?'Challenge passed':'Keep experimenting'}</h3><p>Design cost {money(result.cost)} / budget {money(result.budget||0)}</p>{result.checks?.map(c=><div className="check-row" key={c.name}><strong>{c.passed?'Passed':'Failed'} · {c.name}</strong><span>p99 {number(c.p99_ms,1)} ms · {number(c.success*100,2)}% success</span><p>{c.reasons.join(' · ')}</p></div>)}</div>:summary&&result?<>
          <div className="metrics"><Metric label="Successful throughput" value={number(summary.served_rps)} unit="req/s" note="Requests completed per second"/><Metric label="p95 latency" value={number(summary.p95_ms,1)} unit="ms" note="95% of measured requests finish within"/><Metric label="Success rate" value={number(summary.success_rate*100,2)} unit="%" note={`${Object.values(summary.fail).reduce((a,b)=>a+b,0)} failed requests`}/><Metric label="Illustrative design cost" value={money(result.cost)} unit="/mo" note="Simulated infrastructure estimate"/></div>
          <ResultCharts result={result}/>
          <AIExplanation key={selected.id} jobId={selected.id} apiBase={apiBase} token={token} enabled={settings?.ai_enabled===true} provider={settings?.ai_provider}/>
          {summary.queue&&<div className="notice">Async writes: p95 write-apply lag <strong>{number(summary.queue.lag_p95_s,2)} sec</strong> · ending backlog <strong>{number(summary.queue.end_depth)}</strong>. Acknowledgement latency does not measure when writes land.</div>}
          <div className="panel findings"><h2>What the experiment tells us</h2>{result.findings.map((f,i)=><article key={i}><span className={'finding-dot '+f.level}/><div><h3>{f.title}</h3><p>{f.detail}</p></div></article>)}{result.warnings.map((w,i)=><p className="notice" key={i}>{w}</p>)}<p className="subtle">Executed by the Python/SimPy engine in {number(result.runtime_s,2)} seconds. These simplified models illustrate tradeoffs; they do not predict production performance.</p></div>
        </>:<div className="empty-results">Waiting for results…</div>}</section>
      </>}
      {tab==='library'&&<><div className="page-heading"><div><div className="eyebrow">YOUR EXPERIMENTS</div><h1>A record of your reasoning.</h1><p>Every configuration and result, ready to revisit.</p></div><button className="button secondary" disabled={!jobs.length||exporting} onClick={exportAll}><ArrowDownToLine size={16}/>{exporting?'Exporting…':'Export all'}</button></div>{!token?<SignIn onClick={signIn}/>:<div className="panel library"><div className="panel-heading"><h2>Saved experiments <span className="badge">{jobs.length}</span></h2><button className="button text-button" onClick={()=>refresh().catch(e=>setError(e.message))}>Refresh</button></div>{jobs.length===0?<div className="empty-results"><Library size={28}/><h3>Your next idea belongs here.</h3><p>Run a simulation to automatically save its configuration and result.</p></div>:jobs.map(j=><div className="library-row" key={j.id}><input type="checkbox" aria-label={'Compare '+j.payload.name} checked={comparison.includes(j.id)} disabled={j.status!=='completed'||j.payload.kind==='grade'||(!comparison.includes(j.id)&&comparison.length>=2)} onChange={e=>setComparison(e.target.checked?[...comparison,j.id]:comparison.filter(id=>id!==j.id))}/><span className="row-icon"><FlaskConical size={20}/></span><button onClick={()=>openJob(j)}><strong>{j.payload.name}</strong><small>{new Date(j.created*1000).toLocaleString()} · Seed {j.payload.config.seed}</small></button><span className={'status '+j.status}>{j.status}</span><button className="icon-button" aria-label={'Open '+j.payload.name} onClick={()=>openJob(j)}><ArrowRight size={17}/></button></div>)}{comparison.length>0&&<div className="library-footer"><span>{comparison.length} of 2 designs selected</span><button className="button primary" disabled={comparison.length!==2} onClick={()=>setTab('compare')}>Compare designs <ArrowRight size={16}/></button></div>}</div>}</>}
      {tab==='compare'&&<><div className="page-heading"><div><div className="eyebrow">MAKE THE TRADEOFF VISIBLE</div><h1>Better is a comparison.</h1><p>Compare two completed experiments under the same conditions.</p></div><button className="button secondary" onClick={()=>setTab('library')}>Choose experiments <Library size={16}/></button></div>{compareJobs.length!==2?<div className="empty-results"><GitCompareArrows size={30}/><h3>Two designs. One clear decision.</h3><p>Select two experiments in your library to compare results.</p><button className="button primary" onClick={()=>setTab('library')}>Open experiment library</button></div>:<><ComparisonWarning jobs={compareJobs}/><ComparisonDeltas jobs={compareJobs}/><div className="compare-grid">{compareJobs.map((j,i)=><section className="panel comparison" key={j.id}><span className="eyebrow">{i===0?'BASELINE':'CANDIDATE'}</span><h2>{j.payload.name}</h2><Metric label="Throughput" value={number(j.result?.summary?.served_rps)} unit="req/s"/><Metric label="p95 latency" value={number(j.result?.summary?.p95_ms,1)} unit="ms"/><Metric label="Success rate" value={number((j.result?.summary?.success_rate||0)*100,2)} unit="%"/><Metric label="Illustrative monthly cost" value={money(j.result?.cost||0)}/><p className="subtle">{j.payload.config.app.replicas} app replicas · {j.payload.config.db.shards} shards · {j.payload.config.db.workers} DB connections</p></section>)}</div></>}</>}
      {tab==='learn'&&<><div className="page-heading"><div><div className="eyebrow">LEARN BY BREAKING THINGS</div><h1>Build your intuition.</h1><p>Real architecture questions. Reproducible experiments. Your decisions.</p></div><span className="badge">{challenges.length} challenges</span></div><div className="learning-grid">{challenges.map((c,i)=><section className="panel lesson" key={c.id}><div className="lesson-number">{String(i+1).padStart(2,'0')}<BookOpen size={20}/></div><h2>{c.title}</h2><p>{c.story}</p><div className="lesson-slo">{c.slo}<br/>Budget: {money(c.budget)} / month</div><button className="button secondary" onClick={()=>{setChallenge(c);setConfig(structuredClone(c.config));setSelected(undefined);setPreset('Custom design');setStory(c.story);setTab('sandbox')}}>Take on the challenge <ArrowRight size={16}/></button></section>)}</div></>}
      {tab==='library'&&token&&settings?.auth==='local'&&<div className="notice"><p>Bring your completed cloud experiments back to this computer.</p><button className="button secondary" onClick={()=>archiveRef.current?.click()}>Import archive</button><input hidden ref={archiveRef} type="file" accept="application/json,.json" aria-label="Experiment archive" onChange={e=>importArchive(e.target.files?.[0])}/></div>}
      <footer className="page-footer"><span><Boxes size={14}/> Systems Lab</span><span>Understand the system. Make the tradeoff.</span><span>Python + SimPy · Reproducible experiments</span></footer>
    </ViewTransition></main></div>
    {authOpen&&<div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="auth-title"><button className="close" aria-label="Close sign-in" onClick={()=>setAuthOpen(false)}>×</button><span className="brand-mark"><Layers3 size={24}/></span><h2 id="auth-title">{settings?.auth==='supabase'?'Your next idea starts here.':settings?.auth==='cognito'?'Sign in to your cloud workspace':register?'Make room for your experiments.':'Welcome back to the lab.'}</h2>{settings?.auth==='supabase'?<div className="google-sign-in"><p>Save your experiments, compare designs, and explore your results with an AI architecture coach.</p><button className="button primary run" disabled={loading} onClick={async()=>{setError('');setLoading(true);try{const {signInGoogle}=await import('./google-auth');await signInGoogle(settings)}catch(e){setError((e as Error).message)}finally{setLoading(false)}}}><span aria-hidden="true">G</span>{loading?'Connecting...':'Continue with Google'}</button>{error&&<p role="alert" className="auth-error">{error}</p>}<small>Your experiments are private to your workspace.</small></div>:settings?.auth==='cognito'?<button className="button primary" onClick={signIn}>Continue to secure sign-in</button>:<form onSubmit={authenticate}><p>Your experiments stay on this computer unless you export them.</p><label className="text-label">Email<input type="email" required autoComplete="username" value={email} onChange={e=>setEmail(e.target.value)}/></label><label className="text-label">Password<input type="password" required minLength={12} maxLength={128} autoComplete={register?'new-password':'current-password'} value={password} onChange={e=>setPassword(e.target.value)}/></label><small>Use at least 12 characters.</small>{error&&<p role="alert" className="auth-error">{error}</p>}<button className="button primary run" disabled={loading}>{loading?'Please wait…':register?'Create local account':'Sign in'}</button><button type="button" className="button text-button" onClick={()=>{setRegister(!register);setError('')}}>{register?'Already have an account? Sign in':'New here? Create an account'}</button></form>}</section></div>}
  </div></LabMotion>
}

function Slider({label,value,min,max,step,suffix,onChange}:{label:string;value:number;min:number;max:number;step:number;suffix:string;onChange:(n:number)=>void}){return <label className="slider-label"><span>{label}<strong>{number(value)} <small>{suffix}</small></strong></span><input type="range" aria-label={label} min={min} max={max} step={step} value={value} onChange={e=>onChange(Number(e.target.value))}/><span className="range-ends"><small>{min}</small><small>{number(max)}</small></span></label>}
function NumberField({label,value,min,max,onChange}:{label:string;value:number;min:number;max:number;onChange:(n:number)=>void}){return <label className="text-label">{label}<input type="number" min={min} max={max} step={1} value={value} onChange={e=>onChange(Number(e.target.value))}/></label>}
function Toggle({label,checked,onChange}:{label:string;checked:boolean;onChange:(v:boolean)=>void}){return <label className="toggle-label"><span>{label}</span><input type="checkbox" role="switch" checked={checked} onChange={e=>onChange(e.target.checked)}/></label>}
function Metric({label,value,unit,note}:{label:string;value:string;unit?:string;note?:string}){return <div className="metric"><span>{label}</span><strong>{value}<small>{unit}</small></strong>{note&&<p>{note}</p>}</div>}
function SignIn({onClick}:{onClick:()=>void}){return <div className="empty-results"><Library size={28}/><h3>Your ideas deserve a workspace.</h3><p>Sign in to save experiments and compare designs.</p><button className="button primary" onClick={onClick}>Sign in</button></div>}
function ComparisonWarning({jobs}:{jobs:Job[]}){const a=jobs[0].payload.config,b=jobs[1].payload.config;const differences=[JSON.stringify(a.workload)!==JSON.stringify(b.workload)?'workload':null,a.seed!==b.seed?'random seed':null,JSON.stringify(a.events)!==JSON.stringify(b.events)?'chaos events':null].filter(Boolean);return <div className={'notice '+(!differences.length?'success':'')}>{differences.length?'Different '+differences.join(', ')+'. These results do not isolate architecture changes.':'Matched workload, seed, and chaos events. Compare architecture tradeoffs under the same conditions.'}</div>}

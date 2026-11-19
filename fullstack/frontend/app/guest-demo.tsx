'use client';

import {useEffect,useState} from 'react';
import dynamic from 'next/dynamic';
import {ArrowLeft,ArrowRight,FlaskConical,GitCompareArrows,ShieldCheck} from 'lucide-react';
import type {Job} from './lab-types';
import {LabMotion,LabScene} from './lab-effects';
import TopologyHero from './topology-hero';
import ComparisonDeltas from './comparison-deltas';
const ResultCharts=dynamic(()=>import('./result-charts'),{loading:()=> <p role="status">Loading sample charts...</p>});
const number=(n:number,digits=1)=>n.toLocaleString(undefined,{maximumFractionDigits:digits});

export default function GuestDemo({onExit,onSignIn}:{onExit:()=>void;onSignIn:()=>void}){
  const [jobs,setJobs]=useState<Job[]>([]);
  const [index,setIndex]=useState(0);
  const [error,setError]=useState('');
  useEffect(()=>{
    const controller=new AbortController();
    fetch('/guest-demo.json',{signal:controller.signal}).then(async response=>{
      if(!response.ok)throw new Error('Sample experiments could not be loaded. Please reload to try again.');
      const data=await response.json();setJobs(data.experiments);
    }).catch(error=>{if(!controller.signal.aborted)setError(error.message)});
    return()=>controller.abort();
  },[]);
  const job=jobs[index],result=job?.result,summary=result?.summary;
  return <LabMotion><div className="guest-shell"><LabScene/><main className="guest-main">
    <div className="page-heading"><div><div className="eyebrow"><ShieldCheck size={15}/> READ-ONLY GUEST DEMO</div><h1>Two designs. See the tradeoff.</h1><p>Explore real simulation snapshots without an account.</p></div><button className="button secondary" onClick={onExit}><ArrowLeft size={16}/> Back to sandbox</button></div>
    <div className="notice">These are precomputed, synthetic examples from the Python/SimPy engine. Viewing them creates no jobs and makes no AI calls.</div>
    {error&&<p role="alert" className="error">{error}</p>}
    {!jobs.length&&!error&&<p role="status">Loading sample experiments...</p>}
    {!!jobs.length&&<>
      <section className="guest-samples" aria-label="Sample experiments">{jobs.map((sample,i)=><button key={sample.id} className={'button '+(index===i?'primary':'secondary')} aria-pressed={index===i} onClick={()=>setIndex(i)}><FlaskConical size={16}/>{i===0?'Baseline: no cache':'Candidate: cache enabled'}</button>)}</section>
      <ComparisonDeltas jobs={jobs}/>
      <TopologyHero config={job.payload.config} onToggle={()=>{}} readOnly/>
      <section className="panel guest-details"><div className="panel-heading"><div><h2>{job.payload.name}</h2><p>Seed {job.payload.config.seed} · {job.payload.config.workload.rps} offered req/s · {job.payload.config.workload.duration_s} simulated seconds</p></div><span className="badge">Recorded sample</span></div>
        {summary&&<div className="metrics">{[
          ['Successful throughput',number(summary.served_rps),'req/s'],
          ['p95 latency',number(summary.p95_ms),'ms'],
          ['Success rate',number(summary.success_rate*100,2),'%'],
          ['Illustrative monthly cost','$'+number(result!.cost,0),'/month'],
        ].map(([label,value,unit])=><div className="metric" key={label}><span>{label}</span><strong>{value} <small>{unit}</small></strong></div>)}</div>}
      </section>
      {result&&<ResultCharts result={result}/>}
      <section className="panel guest-details"><div className="panel-heading"><div><h2><GitCompareArrows size={18}/> Compare the evidence</h2><p>Same workload, seed, and capacity. Only the read cache changes.</p></div></div>
        <div className="guest-table-wrap"><table className="guest-table"><thead><tr><th scope="col">Design</th><th scope="col">Throughput</th><th scope="col">p95 latency</th><th scope="col">Success</th><th scope="col">Illustrative cost</th></tr></thead><tbody>{jobs.map(sample=><tr key={sample.id}><th scope="row">{sample.payload.config.cache.enabled?'Cache enabled':'No cache'}</th><td>{number(sample.result!.summary!.served_rps)} req/s</td><td>{number(sample.result!.summary!.p95_ms)} ms</td><td>{number(sample.result!.summary!.success_rate*100,2)}%</td><td>${number(sample.result!.cost,0)}/mo</td></tr>)}</tbody></table></div>
        <p className="subtle">This is one paired experiment, not a production capacity prediction. Cache hit rate is a model input; a cache also adds illustrative cost.</p>
      </section>
      <section className="panel guest-details"><div className="panel-heading"><div><h2>What would you try next?</h2><p>Sign in to run your own designs, save results, and request an AI explanation.</p></div><button className="button primary" onClick={onSignIn}>Sign in to experiment <ArrowRight size={16}/></button></div></section>
    </>}
  </main></div></LabMotion>;
}

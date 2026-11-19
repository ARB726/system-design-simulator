'use client';
import {useEffect,useState} from 'react';
import dynamic from 'next/dynamic';
import type {Job} from './lab-types';
import {decodeSnapshot} from './snapshot-codec';
import {LabMotion,LabScene} from './lab-effects';
import TopologyHero from './topology-hero';
import BottleneckTakeaway from './bottleneck-takeaway';
const ResultCharts=dynamic(()=>import('./result-charts'));

export default function SharedSnapshot({hash}:{hash:string}){
  const [job,setJob]=useState<Job>(),[error,setError]=useState('');
  useEffect(()=>{let active=true;decodeSnapshot(hash).then(j=>{if(active)setJob(j)}).catch(e=>{if(active)setError(e.message)});return()=>{active=false}},[hash]);
  return <LabMotion><div className="guest-shell"><LabScene/><main className="guest-main">
    <button className="button secondary" onClick={()=>location.assign(location.pathname)}>Open sandbox</button>
    {error?<p role="alert" className="error">{error}</p>:!job?<p role="status">Opening shared snapshot...</p>:<>
      <div className="page-heading"><div><div className="eyebrow">READ-ONLY RESULT</div><h1>{job.payload.name}</h1></div></div>
      <div className="notice"><strong>Unverified shared snapshot</strong><p>The sender supplied these values. This link is not proof of a server-verified run. Editing the URL can change the snapshot. No simulation runs when you open it.</p></div>
      <TopologyHero config={job.payload.config} onToggle={()=>{}} readOnly/>
      <section className="panel guest-details" aria-label="Shared measurements"><h2>Recorded results</h2><div className="metrics">{[
        ['Successful throughput',job.result!.summary!.served_rps,'req/s'],['p95 latency',job.result!.summary!.p95_ms,'ms'],['Success rate',job.result!.summary!.success_rate*100,'%'],['Illustrative monthly cost',job.result!.cost,'USD/month'],
      ].map(([label,value,unit])=><div className="metric" key={label}><span>{label}</span><strong>{Number(value).toLocaleString('en-US',{maximumFractionDigits:2})} <small>{unit}</small></strong></div>)}</div></section>
      <BottleneckTakeaway result={job.result!}/><ResultCharts result={job.result!}/>
      <details className="panel guest-details shared-config"><summary>View configuration</summary><pre aria-label="Shared configuration">{JSON.stringify(job.payload.config,null,2)}</pre></details>
      <p className="notice">Synthetic simulation measurements and illustrative design costs do not predict production capacity or your hosting bill.</p>
    </>}
  </main></div></LabMotion>;
}

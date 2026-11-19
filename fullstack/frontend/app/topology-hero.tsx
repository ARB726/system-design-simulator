'use client';
import {useState} from 'react';
import {Database,Globe,Layers3,Server,Users,Zap} from 'lucide-react';
import type {Config} from './lab-types';

type Part='traffic'|'cdn'|'app'|'cache'|'queue'|'database';
export default function TopologyHero({config,onToggle,readOnly=false}:{config:Config;onToggle:(section:'cache'|'cdn'|'queue',value:boolean)=>void;readOnly?:boolean}){
  const [selected,setSelected]=useState<Part>('app');
  const parts=[
    {id:'traffic' as const,label:'Incoming traffic',meta:`${config.workload.rps.toLocaleString()} req/s`,icon:Users,detail:`${Math.round(config.workload.read_ratio*100)}% reads. ${config.workload.duration_s} simulated seconds. Seed ${config.seed}.`},
    {id:'cdn' as const,label:'Edge network',meta:config.cdn.enabled?`${Math.round(config.cdn.hit_rate*100)}% hit rate`:'Bypassed',icon:Globe,detail:config.cdn.enabled?`CDN hits return before the application. Configured hit rate: ${Math.round(config.cdn.hit_rate*100)}%.`:'The CDN is off. Requests continue to the application.'},
    {id:'app' as const,label:'Application pool',meta:`${config.app.replicas} replicas ? ${config.app.workers} workers`,icon:Server,detail:`${config.app.replicas*config.app.workers} worker slots in total. ${config.app.latency_ms} ms configured service time. Load balancing: ${config.app.lb_strategy.replaceAll('_',' ')}.`},
    {id:'cache' as const,label:'Read cache',meta:config.cache.enabled?`${Math.round(config.cache.hit_rate*100)}% hit rate`:'Not in path',icon:Zap,detail:config.cache.enabled?`Configured hit rate: ${Math.round(config.cache.hit_rate*100)}%. Misses continue to the database. This is a model input, not a measured result.`:'The cache is off. Reads continue to the database.'},
    {id:'queue' as const,label:'Write queue',meta:config.queue.enabled?`${config.queue.consumers} consumers`:'Not in path',icon:Layers3,detail:config.queue.enabled?`${config.queue.consumers} consumers. Maximum depth: ${config.queue.max_depth.toLocaleString()}. Check write-apply lag as well as acknowledgement latency.`:'Writes wait for the database. Enable the queue to explore asynchronous acknowledgement.'},
    {id:'database' as const,label:'Database',meta:`${config.db.workers} connections`,icon:Database,detail:`${config.db.workers} connections per node. ${config.db.read_ms} ms reads / ${config.db.write_ms} ms writes. ${config.db.shards} shards and ${config.db.read_replicas} read replicas.`},
  ];
  const focused=parts.find(p=>p.id===selected)!;
  return <section className="topology-hero" aria-label="Interactive architecture preview">
    <div className="schematic-caption"><span>REQUEST PATH / {readOnly?'RECORDED DESIGN':'LIVE CONFIGURATION'}</span><span>Click a tier to inspect</span></div>
    <span className="sr-only" role="img" aria-label={`Architecture preview: ${config.app.replicas} application replicas, ${config.db.shards} database shards, cache ${config.cache.enabled?'enabled':'disabled'}`}/>
    <div className="schematic-layout">
      <svg className="schematic-wires" viewBox="0 0 800 400" preserveAspectRatio="none" aria-hidden="true">
        <path className="schematic-wire" d={config.cdn.enabled?'M100 200H500':'M100 200V270H500V200'}/>
        <path className="topology-signal" d={config.cdn.enabled?'M100 200H500':'M100 200V270H500V200'}/>
        <path className="schematic-wire" d="M500 200H700"/><path className="topology-signal" d="M500 200H700"/>
        {config.cache.enabled&&<><path className="schematic-wire" d="M500 200V60H700V200"/><path className="topology-signal read-signal" d="M500 200V60H700V200"/></>}
        {config.queue.enabled&&<><path className="schematic-wire" d="M500 200V340H700V200"/><path className="topology-signal write-signal" d="M500 200V340H700V200"/></>}
      </svg>
      {parts.map(p=>{
        const inactive=(p.id==='cdn'||p.id==='cache'||p.id==='queue')&&!config[p.id].enabled;
        return <button key={p.id} className={`schematic-node node-${p.id}${inactive?' is-bypassed':''}`} aria-label={`Inspect ${p.id}`} aria-pressed={selected===p.id} onClick={()=>setSelected(p.id)}><p.icon size={21}/><strong>{p.label}</strong><small>{p.meta}</small>{inactive&&<span className="node-bypass">OFF</span>}</button>;
      })}
    </div>
    <div className="schematic-inspector" role="status" aria-live="polite"><span>{focused.label}</span><p>{focused.detail}</p></div>
    <div className="schematic-toolbar"><span>Optional layers</span><div className="topology-switches">{(['cache','cdn','queue'] as const).map(layer=><button key={layer} disabled={readOnly} aria-pressed={config[layer].enabled} onClick={()=>onToggle(layer,!config[layer].enabled)}><span/>{layer==='cdn'?'CDN':layer==='cache'?'Cache':'Write queue'}</button>)}</div></div>
  </section>;
}

'use client';
import { CircuitBoard, Layers3, Sparkles } from 'lucide-react';
import type {Config} from './lab-types';

function Rack({x,y,color}:{x:number;y:number;color:string}){
  return <g transform={`translate(${x} ${y})`}><path d="M0 0 24 -12 48 0 24 12Z" fill={color} fillOpacity=".3" stroke={color} strokeOpacity=".75"/><path d="M0 0 24 12V55L0 43Z" fill="#171f35" stroke={color} strokeOpacity=".4"/><path d="M24 12 48 0V43L24 55Z" fill="#232a44" stroke={color} strokeOpacity=".5"/>{[16,29,42].map(offset=><g key={offset}><path d={`M5 ${offset-9} 19 ${offset-2}`} stroke={color} strokeOpacity=".5"/><circle cx="33" cy={offset+1} r="1.7" fill={color}/><path d={`M38 ${offset-2} 43 ${offset-5}`} stroke={color} strokeWidth="2"/></g>)}</g>;
}

function DataStore({x,y,color,enabled=true}:{x:number;y:number;color:string;enabled?:boolean}){
  return <g transform={`translate(${x} ${y})`} opacity={enabled?1:.25}><path d="M-24 0V32C-24 49 24 49 24 32V0" fill="#18283a" stroke={color} strokeOpacity=".6"/>{[0,16,32].map(offset=><ellipse key={offset} cy={offset} rx="24" ry="10" fill={offset===0?color:'none'} fillOpacity=".18" stroke={color} strokeOpacity=".65"/>)}<circle cx="14" cy="22" r="2" fill={color}/></g>;
}

export default function TopologyHero({config,onToggle}:{config:Config;onToggle:(section:'cache'|'cdn'|'queue',value:boolean)=>void}){
  const replicas=Math.min(config.app.replicas,4);
  return <section className="topology-hero" aria-label="Interactive architecture preview"><div className="topology-copy"><span className="topology-kicker"><Sparkles size={13}/> YOUR SYSTEM, IN PERSPECTIVE</span><h2>Big ideas.<br/><span>Connected by design.</span></h2><p>Explore the architecture before you put it to the test. Switch a layer on and watch the system take shape.</p><div className="topology-switches">{(['cache','cdn','queue'] as const).map(layer=><button key={layer} aria-pressed={config[layer].enabled} onClick={()=>onToggle(layer,!config[layer].enabled)}><span/>{layer==='cdn'?'CDN':layer==='cache'?'Cache':'Write queue'}</button>)}</div><span className="topology-footnote"><CircuitBoard size={13}/>{config.app.replicas} app replicas<small> / </small>{config.db.shards} database shards</span></div>
    <div className="topology-art"><div className="topology-orbit"/><svg viewBox="0 0 600 300" role="img" aria-label={`Architecture preview: ${config.app.replicas} application replicas, ${config.db.shards} database shards, cache ${config.cache.enabled?'enabled':'disabled'}`}><defs><linearGradient id="topology-floor" x2="0" y2="1"><stop stopColor="#a78bfa" stopOpacity=".1"/><stop offset="1" stopColor="#6ee7ce" stopOpacity=".01"/></linearGradient><filter id="topology-glow"><feGaussianBlur stdDeviation="3"/></filter></defs>
      <path d="M300 45 560 165 300 285 40 165Z" fill="url(#topology-floor)" stroke="#a68bdd" strokeOpacity=".2"/>{[0,1,2,3,4].map(i=><g key={i} stroke="#aa95d5" strokeOpacity=".08"><path d={`M${92+i*52} ${141-i*24} ${352+i*52} ${261-i*24}`}/><path d={`M${92+i*52} ${189+i*24} ${352+i*52} ${69+i*24}`}/></g>)}
      <g fill="none" strokeWidth="1.5"><path d="M140 166 265 110 450 195" stroke="#a78bfa" strokeOpacity=".3"/><path d="M300 57 300 126 300 243 450 175" stroke="#78ddce" strokeOpacity=".25"/>{config.cache.enabled&&<path className="topology-signal" d="M140 166 265 110" stroke="#c0a7ff"/>}<path className="topology-signal" d="M300 126 450 195" stroke="#6ee7ce"/>{config.cdn.enabled&&<path className="topology-signal" d="M300 57 300 126" stroke="#8bbdff"/>}{config.queue.enabled&&<path className="topology-signal" d="M300 126 300 243 450 175" stroke="#f3c087"/>}</g>
      <g transform="translate(300 48)" opacity={config.cdn.enabled?1:.25}><ellipse rx="39" ry="15" fill="#82b5fa" fillOpacity=".08" stroke="#82b5fa" strokeOpacity=".5"/><path d="M-17 0C-29-4-23-19-12-15-9-31 16-28 17-13 32-17 37 4 20 4H-17" fill="#172a44" stroke="#90bffc"/><text y="30" textAnchor="middle" fill="#91aacb" fontSize="9" letterSpacing="2">EDGE NETWORK</text></g>
      {Array.from({length:replicas},(_,i)=><Rack key={i} x={230+i*29} y={114-i*13} color="#b69aff"/>)}
      <text x="310" y="196" textAnchor="middle" fill="#ccbbef" fontSize="9" letterSpacing="2">APPLICATION TIER</text>
      <DataStore x={140} y={150} color="#d7b386" enabled={config.cache.enabled}/><text x="140" y="219" textAnchor="middle" fill="#c3a88b" fontSize="9" letterSpacing="2">CACHE</text>
      <DataStore x={450} y={159} color="#78ddce"/><text x="450" y="227" textAnchor="middle" fill="#97c9c1" fontSize="9" letterSpacing="2">DATABASE</text>
      <g transform="translate(300 240)" opacity={config.queue.enabled?1:.25}>{[-7,0,7].map(offset=><path key={offset} d={`M-22 ${offset} 0 ${offset-10} 22 ${offset} 0 ${offset+10}Z`} fill="#382c2d" stroke="#e7b787" strokeOpacity=".7"/>)}<text y="33" textAnchor="middle" fill="#d3ac8d" fontSize="8" letterSpacing="1.8">ASYNC QUEUE</text></g>
      <g fill="#b9a7f1" opacity=".65">{[[69,115],[524,119],[205,54],[510,252],[81,242]].map(([x,y],i)=><circle className="topology-star" key={i} cx={x} cy={y} r={i%2?1.5:2}/>)}</g>
    </svg><span className="topology-preview"><Layers3 size={11}/> DESIGN PREVIEW</span></div>
  </section>;
}

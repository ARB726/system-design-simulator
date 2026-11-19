import type {Job} from './lab-types';

const format=(n:number)=>n.toLocaleString('en-US',{maximumFractionDigits:1});
const signed=(n:number)=>(n>0?'+':'')+format(n);
const sections={app:'Application',cache:'Read cache',cdn:'CDN',queue:'Write queue',db:'Database',policy:'Request policy'};
const settingNames:Record<string,string>={lb_strategy:'load balancing',latency_ms:'service time',max_queue:'queue limit',hit_rate:'hit rate',read_ms:'read time',write_ms:'write time',hot_share:'hot-shard share',rate_limit_rps:'admission limit'};
function settingValue(value:unknown,key:string){
  if(value===null)return 'unbounded';
  if(typeof value==='boolean')return value?'on':'off';
  if(typeof value==='number'){
    if(key==='hit_rate'||key==='hot_share')return format(value*100)+'%';
    return format(value)+(key.endsWith('_ms')?' ms':key.endsWith('_rps')?' req/s':'');
  }
  return String(value).replaceAll('_',' ');
}

export default function ComparisonDeltas({jobs}:{jobs:Job[]}){
  const [baseline,candidate]=jobs;
  const a=baseline?.result,b=candidate?.result;
  if(!a?.summary||!b?.summary)return null;
  const latency=b.summary.p95_ms-a.summary.p95_ms,price=b.cost-a.cost;
  const matched=baseline.payload.config.seed===candidate.payload.config.seed&&JSON.stringify(baseline.payload.config.workload)===JSON.stringify(candidate.payload.config.workload)&&JSON.stringify(baseline.payload.config.events)===JSON.stringify(candidate.payload.config.events);
  const metrics=[
    {id:'throughput',label:'Throughput change',a:a.summary.served_rps,b:b.summary.served_rps,unit:'req/s',higher:true},
    {id:'latency',label:'p95 latency change',a:a.summary.p95_ms,b:b.summary.p95_ms,unit:'ms',higher:false},
    {id:'success',label:'Success rate change',a:a.summary.success_rate*100,b:b.summary.success_rate*100,unit:'percentage points',higher:true},
    {id:'cost',label:'Illustrative cost change',a:a.cost,b:b.cost,unit:'USD/month',higher:false},
  ];
  const changes:string[]=[];
  for(const section of ['app','cache','cdn','queue','db','policy'] as const){
    for(const [key,value] of Object.entries(baseline.payload.config[section])){
      const next=(candidate.payload.config[section] as Record<string,unknown>)[key];
      if(value!==next){
        const label=key==='enabled'?sections[section]:section==='db'&&key==='workers'?'Database connections':sections[section]+' '+(settingNames[key]||key.replaceAll('_',' '));
        changes.push(`${label}: ${settingValue(value,key)} → ${settingValue(next,key)}`);
      }
    }
  }
  return <section className="panel guest-details comparison-deltas" aria-label="Before and after">
    <div className="evidence-kicker">PAIRED RESULTS / CANDIDATE VS BASELINE</div><h2>Before and after</h2>
    <div className="comparison-outcome" role="note" aria-label="Comparison outcome">
      <p>{latency===0?'p95 latency was unchanged.':`p95 latency ${latency<0?'fell':'rose'} by ${format(Math.abs(latency))} ms.`} {price===0?'Illustrative cost was unchanged.':`Illustrative cost ${price<0?'fell':'rose'} by $${format(Math.abs(price))}/month.`}</p>
      <small>{matched?'Matched configured workload, seed and failure schedule.':'Conditions differ. Treat these deltas as descriptive, not a controlled result.'}</small>
    </div>
    <p>Candidate minus baseline. Lower latency and higher throughput or success are improvements; cost is part of the tradeoff.</p>
    <div className="metrics">{metrics.map(m=>{
      const delta=m.b-m.a;
      const direction=delta===0?'Unchanged':m.id==='cost'?(delta>0?'Added cost':'Lower cost'):((delta>0)===m.higher?'Better':'Worse');
      const tone=delta===0?'neutral':m.id==='cost'?'tradeoff':((delta>0)===m.higher?'better':'worse');
      return <div className="metric" key={m.id} data-direction={tone} data-testid={'delta-'+m.id}>
        <span>{m.label}</span><strong>{signed(delta)} <small>{m.unit}</small></strong>
        <p>{direction} · {format(m.a)} → {format(m.b)} {m.id==='success'?'%':m.unit}</p>
        {m.id!=='success'&&<p>{m.a===0?'No relative change from a zero baseline':signed(delta/m.a*100)+'% relative change'}</p>}
      </div>;
    })}</div>
    <h3>Architecture changes</h3>{changes.length?<ul>{changes.map(change=><li key={change}>{change}</li>)}</ul>:<p>No architecture settings changed.</p>}
    <p className="subtle">These are simulated measurements and illustrative design costs, not production capacity or hosting charges.</p>
  </section>;
}

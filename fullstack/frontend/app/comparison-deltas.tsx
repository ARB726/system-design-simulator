import type {Job} from './lab-types';

const format=(n:number)=>n.toLocaleString('en-US',{maximumFractionDigits:1});
const signed=(n:number)=>(n>0?'+':'')+format(n);

export default function ComparisonDeltas({jobs}:{jobs:Job[]}){
  const [baseline,candidate]=jobs;
  const a=baseline?.result,b=candidate?.result;
  if(!a?.summary||!b?.summary)return null;
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
        const text=(v:unknown)=>typeof v==='boolean'?(v?'on':'off'):String(v);
        changes.push(`${section}.${key}: ${text(value)} → ${text(next)}`);
      }
    }
  }
  return <section className="panel guest-details comparison-deltas" aria-label="Before and after">
    <h2>Before and after</h2><p>Candidate minus baseline. A lower cost or latency is better; a higher throughput or success rate is better.</p>
    <div className="metrics">{metrics.map(m=>{
      const delta=m.b-m.a;
      const direction=delta===0?'Unchanged':((delta>0)===m.higher?'Better':'Worse');
      return <div className="metric" key={m.id} data-testid={'delta-'+m.id} data-direction={direction.toLowerCase()}>
        <span>{m.label}</span><strong>{signed(delta)} <small>{m.unit}</small></strong>
        <p>{direction} · {format(m.a)} → {format(m.b)} {m.id==='success'?'%':m.unit}</p>
        {m.id!=='success'&&<p>{m.a===0?'No relative change from a zero baseline':signed(delta/m.a*100)+'% relative change'}</p>}
      </div>;
    })}</div>
    <h3>Architecture changes</h3>{changes.length?<ul>{changes.map(change=><li key={change}>{change}</li>)}</ul>:<p>No architecture settings changed.</p>}
    <p className="subtle">These are simulated measurements and illustrative design costs, not production capacity or hosting charges.</p>
  </section>;
}

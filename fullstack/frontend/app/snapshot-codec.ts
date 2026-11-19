import type {Config,Job,Result} from './lab-types';

const PREFIX='#share=v1.';
const MAX_TEXT=64000,MAX_LINK=16000;
const invalid=()=>new Error('This snapshot link is invalid or too large. Ask the sender for a new link.');
function record(value:unknown):Record<string,unknown>{
  if(!value||typeof value!=='object'||Array.isArray(value))throw invalid();
  return value as Record<string,unknown>;
}
function num(value:unknown,min=0,max=1e12):number{
  if(typeof value!=='number'||!Number.isFinite(value)||value<min||value>max)throw invalid();
  return value;
}
function text(value:unknown,max=120):string{
  if(typeof value!=='string'||value.length>max)throw invalid();
  return value;
}
// Project only documented fields. Private IDs, tokens, arbitrary payload fields,
// AI answers and account information never enter the encoded snapshot.
const fields={
  app:{replicas:'n',workers:'n',latency_ms:'n',lb_strategy:'s',max_queue:'nullable'},
  cache:{enabled:'b',hit_rate:'n',latency_ms:'n',workers:'n'},
  cdn:{enabled:'b',hit_rate:'n',latency_ms:'n'},
  queue:{enabled:'b',consumers:'n',max_depth:'n',enqueue_ms:'n'},
  db:{workers:'n',read_ms:'n',write_ms:'n',read_replicas:'n',max_queue:'nullable',shards:'n',hot_share:'n'},
  workload:{rps:'n',read_ratio:'n',duration_s:'n',timeout_ms:'nullable',warmup_s:'n'},
  policy:{max_retries:'n',backoff_ms:'n',backoff_multiplier:'n',jitter:'b',rate_limit_rps:'nullable',burst:'n'},
} as const;
function configuration(value:unknown):Config{
  const source=record(value),out:Record<string,unknown>={name:text(source.name),seed:num(source.seed),app_only:source.app_only};
  if(typeof source.app_only!=='boolean')throw invalid();
  for(const [section,spec] of Object.entries(fields)){
    const input=record(source[section]),target:Record<string,unknown>={};
    for(const [key,type] of Object.entries(spec)){
      const v=input[key];
      if(type==='b'){if(typeof v!=='boolean')throw invalid();target[key]=v;}
      else if(type==='s')target[key]=text(v,40);
      else target[key]=type==='nullable'&&v===null?null:num(v);
    }
    out[section]=target;
  }
  if(!Array.isArray(source.events)||source.events.length>30)throw invalid();
  out.events=source.events.map(value=>{const e=record(value);return {kind:text(e.kind,40),start_s:num(e.start_s),duration_s:num(e.duration_s),magnitude:num(e.magnitude)}});
  return out as Config;
}
function snapshot(value:unknown):Job{
  const job=record(value),payload=record(job.payload),result=record(job.result),summary=record(result.summary);
  if(job.status!=='completed'||payload.kind!=='simulate'||result.type!=='simulation')throw invalid();
  const tiers:NonNullable<Result['summary']>['tiers']={};
  for(const key of ['app','cache','queue','db_primary','db_replicas']){
    const raw=record(summary.tiers)[key];if(!raw)continue;
    const t=record(raw);tiers[key]={mean_util:num(t.mean_util,0,1),peak_queue:num(t.peak_queue),status:text(t.status,30)};
  }
  const fail:Record<string,number>={};
  for(const [key,v] of Object.entries(record(summary.fail))){if(!/^[a-z_]{1,40}$/.test(key))throw invalid();fail[key]=num(v)}
  const queue=summary.queue==null?undefined:record(summary.queue);
  if(!Array.isArray(result.timeline)||!Array.isArray(result.histogram))throw invalid();
  const timeline=result.timeline;
  const sampled=Array.from({length:Math.min(timeline.length,40)},(_,i)=>timeline[Math.round(i*(timeline.length-1)/Math.max(1,Math.min(timeline.length,40)-1))]);
  const clean:Result={type:'simulation',summary:{success_rate:num(summary.success_rate,0,1),served_rps:num(summary.served_rps),p50_ms:num(summary.p50_ms),p95_ms:num(summary.p95_ms),p99_ms:num(summary.p99_ms),bottleneck:text(summary.bottleneck,40),tiers,fail,...(queue?{queue:{lag_p95_s:num(queue.lag_p95_s),end_depth:num(queue.end_depth)}}:{})},
    timeline:sampled.map(row=>{
      const clean:Record<string,number>={};
      for(const key of ['t','offered_rps','served_rps','p50','p95','p99','q_app','q_cache','q_queue','q_db_primary','q_db_replicas']){
        const value=record(row)[key];if(value!==undefined)clean[key]=num(value);
      }
      return clean;
    }),histogram:result.histogram.slice(0,50).map(row=>{const r=record(row);return {latency:num(r.latency),requests:num(r.requests)}}),
    findings:[],warnings:[],cost:num(result.cost),runtime_s:num(result.runtime_s),cost_breakdown:{}};
  return {id:'shared-snapshot',created:0,updated:0,status:'completed',payload:{name:text(payload.name),kind:'simulate',config:configuration(payload.config)},result:clean};
}
async function bounded(stream:ReadableStream<Uint8Array>,limit:number){
  const reader=stream.getReader(),parts:Uint8Array[]=[];let size=0;
  try{while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>limit)throw invalid();parts.push(value)}}finally{await reader.cancel()}
  const bytes=new Uint8Array(size);let offset=0;for(const part of parts){bytes.set(part,offset);offset+=part.length}return bytes;
}
export async function encodeSnapshot(job:Job):Promise<string>{
  const data=JSON.stringify({version:1,job:snapshot(job)});
  if(data.length>MAX_TEXT)throw invalid();
  const bytes=await bounded(new Blob([data]).stream().pipeThrough(new CompressionStream('deflate')),MAX_LINK);
  const hash=PREFIX+btoa(String.fromCharCode(...bytes)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
  if(hash.length>MAX_LINK)throw invalid();return hash;
}
export async function decodeSnapshot(hash:string):Promise<Job>{
  try{
    if(!hash.startsWith(PREFIX)||hash.length>MAX_LINK)throw invalid();
    const encoded=hash.slice(PREFIX.length);if(!/^[A-Za-z0-9_-]+$/.test(encoded))throw invalid();
    const bytes=Uint8Array.from(atob(encoded.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0));
    const data=JSON.parse(new TextDecoder().decode(await bounded(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate')),MAX_TEXT)));
    if(data.version!==1)throw invalid();return snapshot(data.job);
  }catch{throw invalid()}
}

import type {Result} from './lab-types';

const labels:Record<string,string>={app:'Application tier',cache:'Cache',db_primary:'Database primary',db_replicas:'Read replicas',queue:'Write queue'};
const experiments:Record<string,string>={
  app:'Increase application workers or replicas, then rerun the same workload and seed.',
  cache:'Increase cache workers, then rerun the same workload and seed.',
  db_primary:'Try a read cache or increase database connections, then rerun the same workload and seed.',
  db_replicas:'Increase read replicas, then rerun the same workload and seed.',
  queue:'Increase queue consumers, then compare write-apply lag under the same workload and seed.',
};

export default function BottleneckTakeaway({result}:{result:Result}){
  const summary=result.summary;
  if(!summary)return null;
  const key=summary.bottleneck,tier=summary.tiers[key];
  // A highest-ranked tier is not necessarily saturated. Use the recorded status
  // and pressure measurements before describing it as a capacity concern.
  const pressure=tier&&(tier.mean_util>=.85||tier.peak_queue>=1||['serious','critical','warning'].includes(tier.status));
  return <section className="panel guest-details bottleneck-takeaway" aria-label="Bottleneck takeaway">
    <h2>{!tier?'Not enough tier evidence':pressure?`${labels[key]||key} shows the most pressure`:'No clear capacity bottleneck in this snapshot'}</h2>
    {tier?<>
      <p><strong>Observed:</strong> {labels[key]||key} averaged {(tier.mean_util*100).toFixed(1)}% utilization; peak sampled queue was {tier.peak_queue.toLocaleString('en-US',{maximumFractionDigits:1})}. Engine status: {tier.status}.</p>
      <p><strong>Change one thing:</strong> {pressure?(experiments[key]||'Adjust the busiest tier, then repeat the same workload and seed.'):'Increase offered traffic in a separate experiment to find where pressure begins.'}</p>
      <p className="subtle">This is a hypothesis from sampled simulation evidence. Confirm it with a paired experiment; the highest-ranked tier alone does not prove a throughput limit.</p>
    </>:<p>Rerun the experiment to collect utilization and queue measurements before drawing a capacity conclusion.</p>}
  </section>;
}

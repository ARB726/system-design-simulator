export default function Walkthrough(){
  return <details className="panel guest-details walkthrough">
    <summary>Watch the 75-second walkthrough</summary>
    <p>Follow a database overload, inspect the evidence, add a read cache and compare the tradeoff. The captioned recording uses synthetic engine snapshots at 500 offered requests/s. The guest example uses 120 requests/s. You can follow the recording with the sound off.</p>
    <video controls playsInline preload="none" poster="/walkthrough-poster.jpg" aria-label="Systems Lab walkthrough video">
      <source src="/walkthrough.webm" type="video/webm"/>
      <track kind="captions" src="/walkthrough.vtt" srcLang="en" label="English"/>
      Your browser cannot play this video. Read the transcript below.
    </video>
    <section aria-label="Walkthrough transcript"><h3>Walkthrough transcript</h3><ol>
      <li>Start with the baseline: 500 offered requests/s and two database connections. These are recorded Python/SimPy results.</li>
      <li>Inspect the database queue, utilization, timeouts and success rate. Use the bottleneck takeaway to form a hypothesis.</li>
      <li>Add a read cache. Keep the workload, random seed and database capacity fixed.</li>
      <li>Compare throughput, p95 latency, success rate and illustrative monthly cost. A faster design may cost more.</li>
      <li>The final scene shows sharing a read-only snapshot. Open the <a href="/#demo">recorded guest example</a> to inspect an architecture, configuration and results without signing in.</li>
    </ol><p>These simplified simulations illustrate tradeoffs; they do not establish production capacity or actual hosting costs.</p></section>
  </details>;
}

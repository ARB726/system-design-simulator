import { BookOpen, FlaskConical, GitCompareArrows, Play, SlidersHorizontal } from 'lucide-react';
import ExperimentPreview from './experiment-preview';
import Walkthrough from './walkthrough';

const workflows = [
  { title: 'Explore an example', href: '/#demo', icon: Play,
    description: 'Inspect two recorded designs and follow their request paths. Start here without signing in.' },
  { title: 'Test your own design', href: '/#sandbox', icon: SlidersHorizontal,
    description: 'Configure replicas, queues and traffic. Sign in to run a simulation and inspect where requests slow down.' },
  { title: 'Compare experiments', href: '/#library', icon: GitCompareArrows,
    description: 'Select two completed runs in your saved library. Compare throughput, tail latency, success rate and cost.' },
  { title: 'Practice a challenge', href: '/#learn', icon: BookOpen,
    description: 'Choose a problem in the Learning lab. Grade your design against latency, reliability and budget targets.' },
];

const metrics = [
  ['Offered load and throughput', 'Offered load is the rate the workload tries to send. Served throughput counts successful requests per second. A growing gap calls for a look at failures and queued work.'],
  ['p95 and p99 latency', 'p95 is the time at or below which 95% of measured requests finish. p99 describes the slowest 1% boundary. Timeouts can lift both, so read them alongside success rate.'],
  ['Success rate', 'This is the share of measured requests that succeed. Inspect the failure counts to distinguish timeouts, drops and other errors.'],
  ['Queues and utilization', 'Queue depth counts waiting work. Utilization measures how busy a tier was. A growing queue alongside high utilization helps locate a capacity limit.'],
  ['Write acknowledgements and lag', 'An asynchronous queue can acknowledge a write before the database applies it. Check p95 write-apply lag and the ending backlog before calling the write path faster.'],
  ['Illustrative monthly cost', 'This is a model estimate for the configured design. Opening or running a simulation does not provision that infrastructure or create a matching cloud bill.'],
];

export default function OverviewContent({signedIn=false,standalone=false}:{signedIn?:boolean;standalone?:boolean}) {
  return <div className="overview">
    <section className="overview-intro" aria-labelledby="overview-title">
      <div>
        <p className="overview-kicker"><FlaskConical size={17} aria-hidden="true"/> System design simulator</p>
        <h1 id="overview-title">Understand a system before you <span>scale it.</span></h1>
        <p className="overview-lead">Build an architecture, send traffic through it and see where requests slow down. Change one design choice to measure its effect.</p>
        <div className="overview-actions">
          {!signedIn&&<a className="button primary" href="/#demo"><Play size={16} aria-hidden="true"/> Explore the cache example</a>}
          <a className="button secondary" href="/#sandbox">Open sandbox</a>
        </div>
        {!signedIn&&<p>No sign-in needed for the recorded example.</p>}
        <a className="overview-guide-link" href="#first-experiment">How to run a first experiment</a>
      </div>
      <ExperimentPreview/>
    </section>
    <section aria-labelledby="workflows-title">
      <h2 id="workflows-title">Choose your workflow</h2>
      <div className="overview-grid">
        {workflows.map(({title, description, href, icon: Icon}) => <a key={href} href={href} className="workflow-card" aria-label={title}>
          <span className="workflow-icon"><Icon size={20} aria-hidden="true"/></span>
          <div><h3>{title}</h3><p>{description}</p></div>
        </a>)}
      </div>
    </section>
    <section id="walkthrough" className="overview-tour" aria-labelledby="tour-title">
      <h2 id="tour-title">Watch or read the walkthrough</h2>
      <Walkthrough/>
    </section>
    <section id="first-experiment" className="experiment-guide" aria-labelledby="method-title">
      <div><h2 id="method-title">A useful first experiment</h2>
        <p>Does a read cache ease database pressure? Use the guest example to inspect the evidence, or sign in to run your own pair in the sandbox.</p>
        <ol className="experiment-steps">
          <li><strong>Record the baseline.</strong> Choose a read-heavy workload, turn the cache off and name the run. Note served throughput, p95 latency and database utilization.</li>
          <li><strong>Change one setting.</strong> Enable the read cache. Keep the request rate, read share, database capacity, failure events and random seed fixed.</li>
          <li><strong>Run the candidate.</strong> Give it a different name. In the experiment library, select both completed runs and open Compare designs.</li>
          <li><strong>Explain the tradeoff.</strong> Did the database queue shrink? Check the latency change against success rate and the extra monthly design cost.</li>
        </ol>
      </div>
      <div className="experiment-questions"><h2>Questions to try next</h2>
        <details><summary>Can more app replicas handle a spike?</summary><p>Select the traffic spike chaos event and run a baseline. Increase app replicas for the candidate. Compare peak app queue depth, p99 latency and failed requests during the spike.</p></details>
        <details><summary>Where does an async write wait?</summary><p>Use a write-heavy workload. Enable the asynchronous write queue, then compare acknowledgement latency with write-apply lag and ending backlog. In a separate run, change only the consumer count.</p></details>
        <details><summary>Will more database connections help?</summary><p>Keep cache settings and offered load fixed. Increase DB connections, then inspect database utilization, queue depth and throughput. Check whether waiting has moved to the application tier.</p></details>
      </div>
    </section>
    <section className="metric-guide" aria-labelledby="metrics-title">
      <h2 id="metrics-title">Read the results</h2>
      <dl>{metrics.map(([term, meaning]) => <div key={term}><dt>{term}</dt><dd>{meaning}</dd></div>)}</dl>
    </section>
    <section className="overview-method" aria-labelledby="boundaries-title">
      <div><h2 id="boundaries-title">What you can do as a guest</h2><p>Explore the two recorded designs, inspect charts, read this guide and configure a sandbox design. Sign in to run simulations, save experiments, compare your own runs and grade challenges. Where enabled, the AI coach can explain a completed result.</p></div>
      <div><h2>What the model measures</h2><p>Python and SimPy simulate queues, service times, cache hits and failures from the inputs you choose. Reusing a seed makes a design reproducible. Use the results to form hypotheses, then test them with measurements from your own system.</p></div>
    </section>
  </div>;
}

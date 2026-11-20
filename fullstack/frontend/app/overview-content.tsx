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

export default function OverviewContent() {
  return <div className="overview">
    <section className="overview-intro" aria-labelledby="overview-title">
      <div>
        <p className="overview-kicker"><FlaskConical size={17} aria-hidden="true"/> System design simulator</p>
        <h1 id="overview-title">Understand a system before you scale it.</h1>
        <p className="overview-lead">Build an architecture, send traffic through it and see where requests slow down. Change one design choice to measure its effect.</p>
        <div className="overview-actions">
          <a className="button primary" href="/#demo"><Play size={16} aria-hidden="true"/> Try without signing in</a>
          <a className="button secondary" href="/#sandbox">Open sandbox</a>
        </div>
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
    <section className="overview-method" aria-labelledby="method-title">
      <div><h2 id="method-title">A useful first experiment</h2>
        <ol><li>Run a baseline and inspect where requests queue or fail.</li>
          <li>Form a hypothesis. Could a read cache reduce database pressure?</li>
          <li>Change one variable. Keep the workload, failures and random seed fixed.</li>
          <li>Compare results and explain the tradeoff, including added cost.</li></ol>
      </div>
      <div><h2>What the results mean</h2>
        <p>Python and SimPy model simplified systems with reproducible inputs. Use the results to explore tradeoffs. Production capacity requires measurements on your own system.</p>
        <p>Monthly design costs are illustrative estimates. Sign in to save runs and, where enabled, ask the AI architecture coach about a completed experiment.</p>
      </div>
    </section>
  </div>;
}

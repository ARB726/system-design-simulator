import Walkthrough from './walkthrough';

export default function OverviewContent(){
  return <div className="overview">
    <section className="overview-intro">
      <div className="eyebrow">SYSTEMS LAB / START HERE</div>
      <h1>Understand a system before you scale it.</h1>
      <p>Systems Lab is an interactive system design simulator. Configure an architecture, model traffic and failures, and see how your choices affect throughput, latency, reliability and illustrative cost.</p>
      <div className="overview-actions"><a className="button primary" href="/#demo">Try without signing in</a><a className="button secondary" href="/#sandbox">Open sandbox</a></div>
      <p className="overview-note">New here? Start with two recorded experiments. No sign-in required.</p>
    </section>
    <section aria-labelledby="workflows-title"><h2 id="workflows-title">Choose your workflow</h2><div className="overview-grid">
      <article className="panel"><h3>Explore an example</h3><p>Compare the same workload with and without a read cache. Inspect the request path and measured results before changing anything.</p><a className="button secondary" href="/#demo">Explore recorded results</a></article>
      <article className="panel"><h3>Test your own design</h3><p>Choose a scenario or configure application replicas, database capacity, caching and queues. Adjust traffic or inject failures, then run a simulation.</p><a className="button secondary" href="/#sandbox">Configure a design</a></article>
      <article className="panel"><h3>Compare experiments</h3><p>Sign in to save runs in your experiment library. Select two completed runs to compare throughput, tail latency, success rate and illustrative cost.</p><a className="button secondary" href="/#library">Open experiment library</a></article>
      <article className="panel"><h3>Practice a challenge</h3><p>Open the Learning lab, choose an architecture problem, and work toward its latency, reliability and budget targets. Grade your design and iterate.</p><a className="button secondary" href="/#learn">Browse challenges</a></article>
    </div></section>
    <section className="panel overview-method" aria-labelledby="method-title"><h2 id="method-title">A useful first experiment</h2><ol><li>Run a baseline and inspect where requests queue or fail.</li><li>Form a hypothesis, such as: a read cache could reduce database pressure.</li><li>Change one variable. Keep the workload, failure events and random seed fixed.</li><li>Compare the evidence and explain the tradeoff, including added cost.</li></ol><p>Sign in to run and save your own simulations. Where enabled, the AI architecture coach can explain a completed result and suggest a next experiment.</p></section>
    <section aria-labelledby="tour-title"><h2 id="tour-title">Watch or read the walkthrough</h2><p>The video and full transcript stay available here whenever you need a refresher.</p><Walkthrough/></section>
    <section className="panel overview-method"><h2>What the results mean</h2><p>Python and SimPy simulate simplified systems with reproducible inputs. Results illustrate architecture tradeoffs; they do not predict production capacity. Monthly design costs are illustrative estimates, not hosting charges. Recorded examples are available without signing in; custom runs and saved experiments require sign-in.</p></section>
  </div>;
}

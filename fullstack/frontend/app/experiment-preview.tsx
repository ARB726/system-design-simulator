'use client';

import { useState } from 'react';
import { Activity } from 'lucide-react';
import recorded from '../public/guest-demo.json';

// Both traces share axes so switching designs preserves the visual comparison.
const samples = recorded.experiments.map(({ payload, result }) => ({
  label: payload.config.cache.enabled ? 'Read cache' : 'No cache',
  offered: payload.config.workload.rps,
  latency: result.summary.p95_ms,
  cost: result.cost,
  timeline: result.timeline,
}));
const maxLatency = Math.ceil(Math.max(...samples.flatMap(s => s.timeline.map(p => p.p95))) / 25) * 25;
const lastSecond = Math.max(...samples.flatMap(s => s.timeline.map(p => p.t)));
const traces = samples.map(sample => sample.timeline.map(p =>
  `${p.t / lastSecond * 400},${88 - p.p95 / maxLatency * 84}`
).join(' '));

export default function ExperimentPreview() {
  const [active, setActive] = useState(0);
  const sample = samples[active];
  return <section className="experiment-preview" aria-labelledby="preview-title">
    <header>
      <div className="preview-label"><Activity size={16} aria-hidden="true"/> Recorded experiment</div>
      <h2 id="preview-title">What changes with a read cache?</h2>
      <p>Same workload, {sample.offered} offered requests per second.</p>
    </header>
    <fieldset className="preview-picker">
      <legend className="visually-hidden">Recorded design</legend>
      {samples.map(({ label }, i) => <label key={label}>
        <input type="radio" name="preview-design" checked={active === i} onChange={() => setActive(i)}/>
        <span>{label}</span>
      </label>)}
    </fieldset>
    <div className="preview-metrics" aria-live="polite" aria-atomic="true">
      <span className="visually-hidden">{sample.label}.</span>
      <dl><div><dt>p95 latency</dt><dd>{sample.latency.toFixed(1)} <small>ms</small></dd></div>
        <div><dt>Illustrative cost</dt><dd>${sample.cost}<small> / mo</small></dd></div></dl>
    </div>
    <figure className="latency-trace">
      <figcaption>p95 latency by second <span>(ms)</span>
        <span className="visually-hidden">. The {sample.label.toLowerCase()} design ranged from {Math.min(...sample.timeline.map(p => p.p95)).toFixed(1)} to {Math.max(...sample.timeline.map(p => p.p95)).toFixed(1)} milliseconds.</span>
      </figcaption>
      <div className="trace-plot" aria-hidden="true">
        <div className="trace-scale"><span>{maxLatency}</span><span>0</span></div>
        <svg viewBox="0 0 400 92" preserveAspectRatio="none">
          <path d="M0 4H400 M0 46H400 M0 88H400" className="trace-grid"/>
          {traces.map((points, i) => <polyline key={i} points={points} className={i === active ? 'trace-active' : 'trace-reference'}/>)}
        </svg>
      </div>
      <div className="trace-time" aria-hidden="true"><span>0 s</span><span>{lastSecond} s</span></div>
      <p className="trace-key"><span>Selected design</span><span>Other design</span></p>
    </figure>
  </section>;
}

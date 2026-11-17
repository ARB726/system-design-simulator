# Evidence, repeatable experiments, and resilience

## Start with a guided experiment

In Sandbox, select **Start guided walkthrough**. It replaces the current settings with the cold-cache scenario and disables prediction mode for this walkthrough.

1. Inspect the database pressure window, queues, and end-to-end latency during the event.
2. Select **Step 2: try one capacity change**. The app retains the baseline in session state, changes one capacity setting, and runs the candidate with the same workload, seed, and failure schedule.
3. Select **Run paired comparison** to repeat both designs across seeds. Review reliability, latency, throughput, and illustrative monthly cost, then finish the walkthrough. Save named runs separately if you want durable snapshots.

You can leave or restart the walkthrough at any time. Selecting another scenario also exits it.

## Read bottleneck evidence

Findings include a measured post-warmup pressure window. **Inspect bottleneck evidence** shows mean tier utilization, the peak sampled queue, queue change, and the outcomes of requests arriving in that window. The chosen window maximizes three-bin mean utilization, breaking ties by mean queue depth. Short runs may contain fewer than three usable bins.

A tier is proposed as constrained only when window utilization is at least 85% and its sampled queue is nonzero. A busy tier with no observed queue does not automatically get a capacity recommendation. Sampled queues are per-bin averages, not exact instantaneous peaks. End-to-end p95 covers the whole request path; correlation with a tier's pressure does not prove that tier alone caused the latency.

**Test one change** proposes one bounded capacity increase. It does not promise an improvement. If both the write queue and database are constrained, the proposal increases database capacity rather than adding consumers that would compete for the same database workers.

## Compare across seeds

Suggested experiments and **Saved runs & compare / Check whether the difference holds across seeds** support 3, 5, 7, or 10 distinct seeds per design. Both designs use the same seed list, workload, failure schedule, and model mode. Comparisons with different workloads or failures are rejected.

Reports contain every seed's result, mean, sample standard deviation, observed minimum/maximum, paired candidate-minus-baseline differences, and the number of seeds that improved. Success rates are fractions from 0 to 1. Lower latency is better; higher throughput and success are better. Monthly cost is deterministic under the illustrative pricing model.

An observed difference spanning zero has mixed directions across those seeds. The observed range is not a confidence interval. Seed variability measures uncertainty within this model; it does not establish production accuracy or statistical significance. Changing a design can change random-number consumption even when initial seeds match.

Reports remain in the current session and can be downloaded as JSON, including both configurations and the seed list. Changing inputs marks older results as stale. This does not replace saving design snapshots in the run library.

## Model retries and admission control

Open **Retries and admission control** in the sidebar, then press **Run simulation** to apply changes. Two Infrastructure scenarios provide starting points: **Resilience: retry storm** and **Resilience: protect the database**.

- Retries are off by default and apply to reads only. Writes are never retried because the model has no idempotency semantics.
- A failed read can make at most three additional attempts. Backoff grows by the configured multiplier and is capped at 10 seconds per retry. Full jitter samples uniformly between zero and that delay.
- Each attempt gets its own configured timeout. Logical request latency includes attempts and backoff. For failed requests with retries, effective latency retains the greater of the configured timeout and observed elapsed time. Requests still running at the drain horizon remain incomplete, with lower-bound elapsed latency.
- A shared token bucket admits attempts before the CDN/app path. It starts full, replenishes at the admission rate, and caps stored tokens at the burst size. Every retry must obtain a token again. An excess attempt is rejected immediately; a read may retry it according to the same policy.
- User-visible success uses one row per original logical request, including rejected and incomplete requests. Attempt counts, retry schedules, rate-limited attempts, and amplification are reported separately for requests arriving after warmup. Retries scheduled near the drain horizon might not start before the simulation ends.
- Architecture flows use measured attempt-level counters when a policy is active, so retries are not hidden as a single downstream request. Napkin-math utilization continues to use original offered traffic without retries or admission filtering.

Admission control can protect downstream queues while rejecting users. A lower queue or lower admitted load alone is not a successful outcome. Policy infrastructure has no additional price in the illustrative cost model. The native C++ validation lab remains a plain M/M/c model and does not implement these policies.

## Run bounded parallel sweeps

In **Experiments**, choose **Experiment workers**, then run a load or scaling sweep. Local parallel execution uses a bounded number of persistent subprocesses. As each child finishes a point, it receives the next available point, avoiding idle workers waiting for a slow fixed chunk. Results are restored to their input order, and progress updates after each point. Small batches can be slower in parallel because of interpreter and import startup.

`SYSDESIGN_SWEEP_WORKERS` sets the local per-experiment ceiling (default 2, capped at 4 and CPU count). Celery jobs always execute their points sequentially inside an existing worker; deployment-level concurrency belongs to the Celery pool, so jobs do not create nested process pools.

All points are validated before work starts. Batches allow at most 32 points and an aggregate expected arrival/attempt budget of 8,000,000, configurable with `SYSDESIGN_MAX_BATCH_ARRIVALS`. The estimate conservatively includes retry amplification and the product of spike magnitudes. Existing per-run limits and the runtime attempt cap still apply. Each subprocess has a 180-second wall-clock lifetime budget including startup and all assigned points; assigning another point does not reset it. On failure, remaining children are terminated and reaped before returning the error. Reducing load, duration, points, or workers can help constrained hosts.

## Earlier local sweep benchmark

For six load points from 400 to 1,400 requests/s, each simulating 25 seconds with a 5-second warmup and seed 7:

| Execution | Median wall time |
| --- | ---: |
| Sequential | 22.18 s |
| Two subprocess workers | 12.03 s |

The observed baseline/candidate ratio was **1.84x** for the earlier static-chunk implementation. Three timing rounds alternated execution order after warming both paths. Every point matched exactly in all runs. Timing includes child interpreter/import startup; the Streamlit verification server and test runners were stopped before measuring. This is one local workload, not a production capacity claim. See [raw samples and environment details](benchmarks/sweeps-local.json). The current implementation dispatches points dynamically; see [engine profiling and scheduling](engine-and-scheduling.md) for its separate comparison.

Reproduce from the repository root with at least two CPUs available:

```bash
python tools/benchmark_sweeps.py --workers 2 --rounds 3 --output .local/sweep-benchmark.json
```

## Verify

```bash
python -m pytest tests/test_resilience.py tests/test_experiments.py tests/test_coaching.py tests/test_learning_ui.py -q
ty check app.py sim/coaching.py sim/batch.py sim/sweep_worker.py sim/learning_ui.py
```

Parallel correctness tests launch real child processes and compare every result with sequential execution. Tests cover paired statistics, confounded comparisons, batch limits, worker protocol/ownership routing, retry timing and caps, write safety, token refill, amplification, and the guided UI flow. Existing theory, native, history, and challenge regressions remain applicable.

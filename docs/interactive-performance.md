# Interactive analysis performance

Timeline aggregation now selects only status and effective latency from the request trace. Outcome counts filter a single Series instead of copying request rows. Summary success counts also avoid constructing a second table of successful requests. Full request, resource-sample, and write-lag traces remain available for replay and diagnosis; no sampling interval or percentile definition changes.

Local simulation/replay and distributed simulation/replay share `sim.execution.analyzed_run`. `SimResult.timings` records simulation (including trace construction), timeline, summary, diagnosis, and total pipeline seconds. Worker payloads additionally record DataFrame serialization seconds, and decoding adds reconstruction seconds. These use a monotonic performance clock. They describe actual computation; Streamlit cache hits retain the original computation's timings. They exclude browser rendering, network transfer, JSON encoding, and queue wait. Existing worker telemetry measures job wait/runtime and result bytes separately.

Numeric/boolean dtype metadata preserves all-null numeric columns and empty boolean masks through JSON. Decoding still accepts older payloads without dtype or timing metadata. Tests also exposed an existing empty-arrival failure: empty request tables now have numeric/boolean types, and empty timeline percentiles remain undefined rather than raising an exception.

## Recorded local benchmark

The benchmark compares the baseline timeline function at `b517932` against the current function on the same retained trace. Both paths are warmed, five timing rounds alternate execution order, and allocation measurements run separately from timing. Every timeline value matches exactly.

| Requests in trace | Baseline median | Candidate median | Baseline peak traced allocation | Candidate peak traced allocation |
| --- | ---: | ---: | ---: | ---: |
| 9,991 | 30.95 ms | 28.17 ms | 457,753 bytes | 456,102 bytes |
| 39,699 | 31.84 ms | 30.43 ms | 2,111,992 bytes | 1,670,891 bytes |

The larger trace used about 21% less peak traced allocation during timeline analysis. Timing improvements were small in absolute terms; simulation still dominated the recorded pipeline. This is two workloads with one seed on one machine, with five timing samples and one allocation sample per path. Tracemalloc excludes total process RSS and some native allocations. These measurements do not establish an application-wide speedup or production capacity.

Raw configurations, versions, timings, and allocations: [analysis-local.json](benchmarks/analysis-local.json).

```powershell
./.venv/Scripts/python.exe tools/benchmark_analysis.py --baseline-ref b517932 --rounds 5 --output .local/analysis-benchmark.json
./.venv/Scripts/python.exe -m pytest tests/test_interactive_performance.py tests/test_summary.py tests/test_production.py -q
```

Regression coverage compares the old aggregation with the optimized calculation across normal traffic, overload, async writes, retry/admission policies, and chaos events at three bin widths. It checks exact timeline equality, unchanged summaries/findings, input immutability, timing accounting, JSON round-trips, legacy payload compatibility, and empty runs. Existing UI and engine tests cover the shared local/worker pipeline integration.

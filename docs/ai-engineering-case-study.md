# Measuring and bounding the architecture coach

The simulator already produced structured AI explanations, but schema validation alone could accept an invented measurement. I added deterministic evaluation cases, canonical citations, rejection of explicit mismatched measurement claims, a bounded experiment workflow, and structured provider traces.

## Architecture

Saved experiment -> numeric evidence allowlist -> structured provider response -> schema and measurement checks -> canonical citations -> owner-scoped cache.

The provider can refer to four measured summary keys: successful throughput, p95 latency, p99 latency, and success rate. Accepted observations receive a server-owned `value`, `unit`, and `source` such as `result.summary.p95_ms`. Rejected explanations return a recoverable 502 and never enter the cache. The grounding version participates in the cache key so old responses cannot bypass the new checks.

The local search runs the original design first. Each following proposal changes exactly one allowlisted integer parameter relative to that original design. Workload and seed remain fixed. Configuration validation and illustrative monthly cost checks run before each simulation. Search stops at its throughput target, run limit, repeated proposal, or budget boundary. It can run at most eight simulations, each with at most 60 simulated seconds and 60,000 nominal arrivals; the engine's validation also applies.

`tools/search_experiments.py` defaults to a deterministic database-worker search. `--ai` explicitly selects the configured provider for structured proposals. The model sees numeric history, the illustrative budget, and the throughput target; experiment names are omitted. Proposals never provision resources or modify saved experiments. This CLI is local and does not use the hosted explanation endpoint's per-user quota; it makes at most `max_runs - 1` provider requests. Each request has the existing 18-second outer timeout and 1,600 output-token limit. There are no automatic provider retries; rerunning the command is explicit.

## Test-driven development

For each behavior I wrote and ran tests before implementing it. Initial runs failed for missing evaluation/search functions, absent traces, unsupported token validation, and missing rejection events. Implementations then passed the same tests. Coverage includes fabricated values, invalid shapes and units, privacy, budget/run limits, immutable input, fixed workload/seed, provider timeouts, missing usage, and rejected-answer cache cleanup.

The focused AI suite passed **44 tests** locally; the broader API, authentication, and AI suite passed **65 tests**. CI now discovers the new AI tests and the experiment-search tests.

## Reproducible evidence

The checked-in [corpus](benchmarks/ai-corpus.json) contains 36 actual engine snapshots: three traffic rates, three database capacities, two cache states, and two seeds. Each run uses four simulated seconds and a one-second warmup. Configurations and the exact sanitized evidence are retained.

The [offline scorer controls](benchmarks/ai-controls.json) accepted **36/36** correctly quoted p95 values and rejected **36/36** values deliberately inflated by 10,000 ms. These are deterministic scorer controls, **not model-generated answers or a model-accuracy benchmark**. Their latency measures scorer execution only. No paid model calls were made for these artifacts. Token usage and cost remain unknown (`null`).

The [local search example](benchmarks/search-local.json) used the same seed and offered workload for both attempts. Raising database workers from one to two increased measured successful throughput from **99.67 to 170.33 req/s**, meeting the 170 req/s target in two attempts. Illustrative monthly cost increased from **$261 to $273**, within the $1,000 model budget. This is a short synthetic run with a deterministic proposal, not evidence of model planning skill or production capacity.

Regenerate the corpus and controls from the repository root:

```powershell
./.venv/Scripts/python.exe tools/evaluate_ai.py --generate --corpus docs/benchmarks/ai-corpus.json --output docs/benchmarks/ai-controls.json
```

Run a search with a JSON configuration from the corpus's `config` field:

```powershell
./.venv/Scripts/python.exe tools/search_experiments.py config.json --budget 1000 --target-rps 170 --max-runs 4
# Add --ai to opt into the configured provider's paid calls.
```

## Comparing models or prompts

Record one JSONL row per case and variant, with these fields:

```json
{"case_id":"r60-db1-cache0-s7","variant":"model-a-prompt-v1","answer":{"summary":"...","observations":[{"metric":"p95_ms","interpretation":"..."}],"next_experiment":"...","limitations":"..."},"latency_ms":1234,"input_tokens":400,"output_tokens":200}
```

Each variant must cover the entire corpus; duplicates and incomplete paired comparisons are rejected. Record failed provider requests as `answer: {}` with their elapsed time and usage when known, so failures remain in the denominator. Use `null` for unavailable usage. Keep a separate held-out set before tuning prompts against this corpus.

Supply explicit USD prices per million tokens in a JSON file:

```json
{"model-a-prompt-v1":{"input_per_million":1.0,"output_per_million":2.0}}
```

These numbers demonstrate the format; they are not provider price claims. Then run:

```powershell
./.venv/Scripts/python.exe tools/evaluate_ai.py --corpus docs/benchmarks/ai-corpus.json --responses responses.jsonl --prices prices.json --output report.json
```

The report includes pass rate, nearest-rank p95 request latency, token totals, estimated aggregate cost, and estimated cost per passing answer. Estimates assume the supplied rates apply to every recorded token; discounts, caching rates, and other billing adjustments are not modeled. Unknown usage or prices produce unknown cost. Model variants should use the same prompt inputs and inference settings for a useful comparison.

## Observability and limitations

Enable INFO logs for `systems_lab.ai` to collect JSON request events containing a trace ID, provider/model, operation, prompt version, status, latency, and provider-reported token counts. Prompt bodies, answers, API keys, names, email addresses, and raw provider errors are excluded. A separate `grounding_rejected` event counts validation failures. Existing quota and cache behavior remain in place for hosted explanations.

The scorer checks schema, referenced metric availability, and explicit observation numbers followed by `ms`, `req/s`, or `%`, with a rounding tolerance. It does not verify every number in the summary or proposed experiment, causal reasoning, bottleneck diagnosis, arbitrary numeric formats, or whether recommendations are useful. A passed response is not certified hallucination-free. Human review should assess those dimensions, including uncertainty and failure cases; no such review or live two-model comparison is claimed here.

The corpus covers a narrow workload matrix, not failure events or every architecture. The search does not guarantee a global optimum and stops on an over-budget proposal rather than asking for another. Its cost budget applies to simulated architecture cost, not provider spend. These limits make the current results auditable and identify what a future evaluation should measure.

Validation:

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_fullstack.py tests/test_ai_service.py tests/test_ai.py tests/test_supabase_auth.py tests/test_ai_shared.py tests/test_ai_evaluation.py tests/test_ai_grounding.py tests/test_experiment_search.py tests/test_ai_benchmarks.py tests/test_ai_tracing.py -q
git diff --check
```

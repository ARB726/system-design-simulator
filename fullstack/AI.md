# Optional AI result explanations

After a simulation completes, **Explain my results** sends selected measurements and the saved numeric configuration to OpenAI's Responses API. It returns a structured summary, observations, one next experiment, and limitations. No model output changes configurations or starts simulations. The simulation engine remains the source of measured values.

The feature is disabled unless both `OPENAI_API_KEY` and `OPENAI_MODEL` are set on the API process. Choose a model available to your API project that supports Responses and strict JSON-schema output. API usage is billed by the provider separately from application hosting. Do not place the key in a `NEXT_PUBLIC_` variable, runtime-config.json, browser storage, or source control.

For a local PowerShell session:

```powershell
# Set OPENAI_API_KEY through your local secret-management mechanism first.
$env:OPENAI_MODEL = 'your-supported-model-id'
./.venv/Scripts/python.exe tools/run_fullstack.py
```

Restart the API after configuring the environment. The local runner inherits environment variables; it does not automatically read `.env`. Docker Compose accepts these two variables from the shell or `fullstack/.env` and passes them only to the API service. Keep real values out of `.env.example`.

The UI explains the data transfer before the user clicks. Requests exclude email, experiment names, timelines, findings text, and request traces. The API verifies ownership before accessing results, excludes unknown configuration fields and free-form text, and includes at most eight recognized failure events. OpenAI receives `store: false`; this disables response storage but is not a claim of zero provider retention. See the provider's data controls for its applicable retention policy.

There are no automatic AI calls or retries. Each response is limited to 1,600 output tokens, 16 KB of evidence, 128 KB of response data, and an 18-second total request timeout. Malformed output, refusals, incomplete responses, timeouts, and provider failures produce a recoverable error without affecting simulation results.

Admission control allows two concurrent requests, five new attempts per user per hour, and twenty total new attempts per hour **per API process**. Failed attempts also count. Successful responses are cached for one hour in an owner-scoped cache of at most 128 entries; cache hits do not consume attempts. These controls are in memory: restarts reset them, and multiple instances each have independent budgets. They are not a distributed spending cap. Before enabling a public multi-instance deployment, add shared durable admission control and configure provider-side usage controls. No hosting configuration or deployment is changed by this feature.

Validation uses an HTTP mock, not a paid model call. Run:

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_ai.py tests/test_fullstack.py -q
```

Tests cover ownership, disabled operation, evidence filtering, cache isolation, quotas, provider errors, and incomplete/invalid responses. Browser tests exercise the coach with mocked provider results. Real model quality, availability, billing, and hosted routing must be verified separately when credentials and deployment configuration are supplied.

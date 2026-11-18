# Optional AI result explanations

For Google sign-in and shared access across hosted API instances, see [PUBLIC_ACCESS.md](PUBLIC_ACCESS.md).

After a simulation completes, **Explain my results** sends selected measurements and the saved numeric configuration to the explicitly selected AI provider. It returns a structured summary, observations, one next experiment, and limitations. No model output changes configurations or starts simulations. The simulation engine remains the source of measured values.

Set `AI_PROVIDER=gemini` with `GEMINI_API_KEY` and `GEMINI_MODEL` to use Google's Gemini generateContent API. Set `AI_PROVIDER=openai` (the backward-compatible default) with `OPENAI_API_KEY` and `OPENAI_MODEL` to use OpenAI Responses. The selected provider needs both its key and model. Unsupported providers, invalid Gemini model IDs, or missing settings disable the feature; there is no automatic fallback. Choose a model that supports JSON-schema structured output. API usage is billed by the provider separately from application hosting. Do not place the key in a `NEXT_PUBLIC_` variable, runtime-config.json, browser storage, or source control.

## Gemini setup without saving a key

If a key has been pasted into chat, a command history, or a public location, revoke it in [Google AI Studio](https://aistudio.google.com/apikey) and create a replacement. Never paste the replacement into chat.

From the repository root, run:

```powershell
./tools/start_gemini.ps1 -Model gemini-3.1-flash-lite
```

The launcher prompts with hidden input, passes the key to the local API through the process environment, and restores the caller's previous environment when the app stops. It never writes the key to a file or puts it in command arguments. The worker does not receive AI API keys. The launcher requires the Python environment, backend dependencies, and an existing frontend build. Stop an existing local app first, or choose unused `-Port` and `-ApiPort` values.

The local setup defaults to `gemini-3.1-flash-lite`, which passed the live integration check. The optional `gemini-flash-latest` alias can change behind the scenes and timed out during initial testing. Verify availability, structured-output support, and free-tier eligibility for the chosen model and API project in [Google's pricing documentation](https://ai.google.dev/gemini-api/docs/pricing). Gemini's free tier is quota-limited, and its data-use terms differ from paid usage. The app cannot guarantee free usage if the provider project has billing enabled. No fallback provider is used when Gemini runs out of quota.

## OpenAI setup

For a local PowerShell session:

```powershell
# Set OPENAI_API_KEY through your local secret-management mechanism first.
$env:OPENAI_MODEL = 'your-supported-model-id'
./.venv/Scripts/python.exe tools/run_fullstack.py
```

Restart the API after configuring the environment. The local runner inherits environment variables; it does not automatically read `.env`. Docker Compose accepts the provider and its key/model variables from the shell or `fullstack/.env` and passes them only to the API service. Keep real values out of `.env.example`.

The UI explains the data transfer before the user clicks. Requests exclude email, experiment names, timelines, findings text, and request traces. The API verifies ownership before accessing results, excludes unknown configuration fields and free-form text, and includes at most eight recognized failure events. The panel names the selected provider before sending evidence. OpenAI receives `store: false`; this disables response storage but is not a claim of zero provider retention. Gemini uses Google's generateContent API and follows Google's applicable free/paid data-use terms. See each provider's data controls and retention policy.

There are no automatic AI calls or retries. Each response is limited to 1,600 output tokens, 16 KB of evidence, 128 KB of response data, and an 18-second total request timeout. Malformed output, refusals, incomplete responses, timeouts, and provider failures produce a recoverable error without affecting simulation results.

In private local-password mode, in-memory admission control allows two concurrent requests, five new attempts per user per hour, and twenty total new attempts per hour **per API process**. Failed attempts also count. Successful responses are cached for one hour in an owner-scoped cache of at most 128 entries; cache hits do not consume attempts. These controls are in memory: restarts reset them, and multiple instances each have independent budgets. They are not a distributed spending cap. Public Supabase/Cognito modes now require shared PostgreSQL admission control; see PUBLIC_ACCESS.md for its setup and fixed UTC-hour limits. Configure provider-side usage controls as well. No hosting configuration or deployment is changed by this feature.

Validation uses an HTTP mock, not a paid model call. Run:

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_ai.py tests/test_ai_service.py tests/test_fullstack.py -q
```

Tests cover ownership, disabled operation, evidence filtering, cache isolation, quotas, provider errors, and incomplete/invalid responses. Browser tests exercise the coach with mocked provider results. Real model quality, availability, billing, and hosted routing must be verified separately when credentials and deployment configuration are supplied.

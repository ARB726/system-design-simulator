# Google sign-in and shared AI access

This adds Supabase Google sign-in to the existing static Next.js frontend and FastAPI backend. Existing DynamoDB experiment metadata, S3 results, and the simulation workers remain in place. Supabase PostgreSQL stores only shared AI usage counters, request leases, and cached explanations in a private schema.

## Connect the services

1. Install and connect the Supabase plugin, then choose or create the intended project. Keep a free project/plan unless you explicitly want to upgrade.
2. In Google Cloud, create a **Web application** OAuth client. Use your Supabase project's exact Google callback URL, typically `https://PROJECT_REF.supabase.co/auth/v1/callback`, as its authorized redirect URI. Enter the Google client ID and client secret in **Supabase Authentication > Providers > Google**. The client secret belongs in Supabase, never in the browser or repository. Configure the OAuth consent screen and any test-user restrictions before expecting other people to sign in.
3. Set the Supabase site URL to the application origin. Allow exact redirect URLs for the hosted site and local development, each ending in `/`. For the existing hosted frontend this is `https://d11ry0yeilwlgs.cloudfront.net/`; local defaults are `http://127.0.0.1:8080/` and the optional Gemini preview `http://127.0.0.1:8081/`.
4. Use Supabase asymmetric JWT signing keys (ES256 or RS256). The backend verifies the project's JWKS, issuer, audience, expiry, authenticated role, and UUID subject. Legacy HS256 signing secrets are intentionally unsupported. The frontend uses the public **publishable key**; secret/service-role keys are rejected by the settings endpoint.

The browser uses OAuth code flow with PKCE and keeps its session in sessionStorage. The Supabase SDK refreshes sessions; sign-out clears private UI state. No Google Drive/Sheets scopes are requested. Changing the backend to Supabase auth creates a new identity namespace: existing Cognito histories retain their original owner IDs. Export existing histories before switching; account linking or ownership migration requires a separate reviewed operation.

## Shared AI budget database

Apply [sql/ai_quotas.sql](sql/ai_quotas.sql) with a database administrator. Do not expose `lab_private` through the Supabase Data API. Use a dedicated backend database login with only `USAGE` on that schema and `SELECT, INSERT, UPDATE, DELETE` on its three tables. Supply its private connection URL as `AI_BUDGET_DATABASE_URL`. It must use the `postgresql+psycopg` driver. The backend requires TLS and disables prepared statements for transaction-pooler compatibility.

Example URL shape (never commit real credentials):

```text
postgresql+psycopg://BACKEND_ROLE.PROJECT_REF:PRIVATE_PASSWORD@YOUR_POOLER_HOST:6543/postgres
```

Use the host, port, username, and URL encoding from your project's actual connection instructions. The service does not create production schemas automatically.

Public authentication modes require shared PostgreSQL storage before AI is enabled. Admission is serialized in a database transaction, so limits apply across API instances and restarts: **five attempts per user per UTC hour, twenty attempts globally per UTC hour, and two simultaneous requests**. Failed attempts count; cached explanations do not. Successful answers are owner-scoped and cached for one hour. Abandoned request leases expire after thirty seconds, and an old request cannot overwrite a reclaimed lease. Database failures prevent new model calls.

## Backend-only configuration

Set these on the API process after the PRs are reviewed and merged:

```text
AUTH_PROVIDER=supabase
SUPABASE_URL=https://PROJECT_REF.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_REPLACE_ME
AI_PROVIDER=gemini
GEMINI_MODEL=gemini-3.1-flash-lite
GEMINI_API_KEY=<private Gemini key>
AI_BUDGET_DATABASE_URL=<private PostgreSQL connection URL>
```

For the existing AWS backend, keep `STORAGE_MODE=aws` and its current DynamoDB/S3/queue environment values. Configure only the API Lambda with AI and database credentials. Do not add them to the workers, static hosting, frontend runtime-config.json, screenshots, or CloudFormation outputs. Use your deployment's private secret configuration; these examples deliberately contain no credentials. The existing API route forwards to FastAPI, where every protected endpoint verifies the configured auth provider.

Regional resources remain in the selected Region `us-east-2`; confirm it in **AWS Settings > View all projects > Overview > Additional Info > Region** before any deployment. No hosting resources are created or changed by opening these PRs. Keep the current resources while reviewing; cleanup would be a separate requested operation.

Gemini free-tier availability and quotas depend on the selected model and Google project. There is no automatic provider fallback or billing-plan upgrade. Each user clicks **Explain my results** after a completed simulation; the server loads only that user's saved evidence. Users never supply or receive the Gemini key.

## Validation and activation

The tests use signed test JWTs and mocked Google/Supabase OAuth endpoints. They cover Google PKCE redirect/callback, private experiment ownership, invalid claims, sign-out, and AI limits shared across independent database clients. SQLite exercises concurrent admission and stale-lease recovery locally; PostgreSQL and live Google login still need verification against the connected Supabase project.

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_supabase_auth.py tests/test_ai_shared.py tests/test_ai.py tests/test_ai_service.py tests/test_fullstack.py -q
cd fullstack/frontend
npm run build
npm run test:e2e
```

Opening a PR does not activate Google sign-in or publish the UI. After the service configuration is complete and deployment is authorized, verify a real Google sign-in, a simulation, a Gemini explanation, sign-out, and cross-user isolation before announcing public access.

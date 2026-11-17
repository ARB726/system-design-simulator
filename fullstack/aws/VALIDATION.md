# Validation record — 17 November 2026 UTC

- **Backend:** nine FastAPI/worker tests and 38 existing engine summary/workload-limit tests passed. Coverage includes authentication, owner isolation, persistent queue processing, invalid workloads, pending-job quotas, failed workers, cloud-archive restoration, real challenge grading, and numerical equivalence with the original engine.
- **Frontend:** TypeScript checking and the Next.js production static build passed. npm reported no known vulnerabilities at installation.
- **Browser:** one end-to-end workflow passed using installed Chrome: local registration, two actual Python simulations, saved experiment comparison, JSON export, six challenge cards, and a 390-pixel mobile layout with no horizontal overflow. Desktop and mobile screenshots were inspected. Chart animation is disabled to make results immediately readable and reproducible.
- **CloudFormation schema:** cfn-lint 1.40.2 returned `[]`: zero errors, warnings or informational findings for us-east-2.
- **Targeted storage security:** CloudFormation Guard 3.2.2 passed all four unmodified AWS registry rules shipped in `guard/`: S3 public access blocks, S3 encryption, S3 TLS-only policies, and DynamoDB encryption. This is scoped validation, not a full compliance assessment.
- **AWS basic template check:** `cloudformation validate-template` accepted the template. This verifies basic template structure, not every property, service restriction, runtime dependency, permission, or service quota.
- **Lambda packaging/runtime:** Python 3.12 x86_64 Linux wheels were assembled into a 48.45 MiB deployment archive, 126.42 MiB extracted, below the 250 MiB limit. The actual cloud simulation completed, verifying the native dependencies in Lambda's Linux runtime.

## Live AWS verification

Deployed to **https://d11ry0yeilwlgs.cloudfront.net**, project **675345028735**, stack **systems-lab**, selected Region **us-east-2**.

- All 30 CloudFormation resources reached `CREATE_COMPLETE`; no deployment validation errors were reported.
- Public website, runtime configuration, API health, hosted Cognito login, PKCE callback, and verified access-token authorization worked in installed Chrome.
- A real queued simulation completed through SQS, Lambda, DynamoDB and S3: **501.12 successful requests/sec, 100% success** for the default simulated workload. This is a simulation result, not a measurement of the hosting platform's request capacity.
- Anonymous library requests returned 401. A second signed-in synthetic user saw an empty library and received 404 when requesting the first user's experiment ID.
- The first user's completed experiment exported successfully. That exact JSON archive was imported into the running local application with identical result metrics, verifying the cloud-to-local fallback.
- The deployed website passed a 390-pixel mobile layout check. Browser JavaScript errors: zero. API/worker error-log checks returned no errors for the test interval.
- Synthetic test users used `example.invalid` addresses, no emails were sent, and no email address was marked verified. These fixtures and private local test passwords are removed after testing. Public self-service email confirmation itself requires the real user's email and was not automated.

## Not yet verified

The optional Docker/PostgreSQL workflow has not run because Docker is unavailable on this machine. Recovery from an actual Lambda timeout/dead-letter event, public self-service email delivery, sustained production traffic, and a full security audit were not tested. CloudFormation's automatic validation ran during stack creation; a separate change set was not used. No durable CloudTrail trail was configured in the new project, so audit retention relies on the default management-event history rather than a dedicated long-term trail.

## Billing verification

The earlier Paid-plan profile was not used for deployment. The user signed into the intended project **675345028735** under **system-design-simulator-free**. STS confirmed its identity; the Free Tier API reported **FREE / ACTIVE / USD 100 credits**, expiring **17 May 2027**. No billing upgrade or AWS Organizations operation was performed. The deployment helper also checked the expected project ID before creating resources. Credit usage and AWS bills can update after a delay; the hosting estimate is not a spending cap.

After deployment and test cleanup, a fresh API check reported **FREE / ACTIVE / USD 140 credits** with the same expiration date. Both isolated test identities, their DynamoDB/S3 fixtures, and private local password files were removed.

## Reproduce

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_fullstack.py -q
./.venv/Scripts/cfn-lint.exe --format json --regions us-east-2 --template fullstack/aws/template.json
./.local/cfn-guard/cfn-guard-v3-x86_64-windows-latest/cfn-guard.exe validate --rules fullstack/aws/guard --data fullstack/aws/template.json --output-format json
cd fullstack/frontend
npm run typecheck
npm run build
npm run test:e2e
```

The browser test expects the local application on http://127.0.0.1:8080 and uses the installed Chrome channel by default. Set `PLAYWRIGHT_CHANNEL` to another installed supported channel if needed.

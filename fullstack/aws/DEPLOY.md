# AWS deployment and recovery

## Current status

Deployed successfully to **https://d11ry0yeilwlgs.cloudfront.net** on 17 November 2026 UTC. The `systems-lab` stack contains 30 resources, plus a private deployment-artifact bucket. Hosted sign-in, API access checks, background simulation execution, saved results, export, mobile layout, and restoring an actual cloud export locally were verified. See `VALIDATION.md` for the full check record and remaining limitations.

The deployment project is **675345028735** in **us-east-2**, using profile **system-design-simulator-free**. On 17 November 2026 UTC, STS confirmed that project and the Free Tier API confirmed **FREE / ACTIVE / USD 100 credits**, expiring **17 May 2027**. The previous profile remains separate and is not used for deployment. No plan upgrades or AWS Organizations operations are part of this workflow.

## Architecture

```text
Browser → CloudFront → private S3 static Next.js export
        → Cognito hosted OAuth sign-in (code + PKCE)
        → HTTP API → FastAPI Lambda → DynamoDB jobs + SQS
                                            SQS → SimPy worker Lambda → S3 result JSON
                                            DLQ → recovery Lambda → terminal failure state
```

All regional application resources live in us-east-2. CloudFront is global. There is no RDS instance, NAT gateway, VPC, Redis, or always-running compute in the cloud variant. DynamoDB stores job metadata and transactional per-user active counts; S3 stores aggregated result documents outside DynamoDB's item size limit. Locally, SQLStore uses SQLite or PostgreSQL and a polling worker without AWS.

## Cost estimate, not a spending cap

Budget approximately **USD 1–5/month** for light demo usage before applicable free allowances, taxes, or credits: 1,000 simulations/month averaging 10 seconds at 1 GiB, 20,000 API reads/polls, 1 GB website delivery, <=1 GB persistent data, 10 monthly active users, and modest logs. CPU execution alone in that scenario is about $0.17 before allowances (10,000 GB-seconds at $0.0000166667). This is a planning estimate, not a price quote or measured workload forecast.

- Lambda: https://aws.amazon.com/lambda/pricing/
- API Gateway: https://aws.amazon.com/api-gateway/pricing/
- DynamoDB: https://aws.amazon.com/dynamodb/pricing/
- S3: https://aws.amazon.com/s3/pricing/
- CloudFront: https://aws.amazon.com/cloudfront/pricing/
- Cognito: https://aws.amazon.com/cognito/pricing/
- SQS: https://aws.amazon.com/sqs/pricing/

CloudFront, SQS pollers, storage, identity users, logging, retries and abuse can add costs. There is no guarantee that this architecture stays free. The API is throttled and simulation work is capped, but those controls do not cap the bill. Use AWS Settings project spend limits where available, plus AWS Budgets notifications. Budget notifications can be delayed. Avoid a public announcement until the deployment has been monitored under real traffic.

## Prepare locally (no cloud changes)

From the repository root:

```powershell
./.venv/Scripts/python.exe fullstack/aws/template.py
./.venv/Scripts/python.exe -m pip install -r fullstack/aws/requirements-deploy.txt
./.venv/Scripts/python.exe fullstack/aws/deploy.py --prepare
./.venv/Scripts/python.exe fullstack/aws/deploy.py --plan
```

`--prepare` downloads Python 3.12 x86_64 Linux wheels and creates `.local/systems-lab-lambda.zip`, checking the 250 MiB extracted limit. It does not create AWS resources. API and worker share this package. Linux runtime execution still needs verification on AWS or in an appropriate Linux container. `--plan` reads identity/billing and invokes basic CloudFormation validation. It creates no resources.

Run the local schema validator and Guard checks before deploying. The generated `template.json` is reviewable and can be used independently of the helper script. Regenerate it after edits to `template.py`.

## Deploy after billing is confirmed

Build the frontend (`npm ci`, `npm run build` in `fullstack/frontend`) and prepare the Lambda package first. Then:

```powershell
./.venv/Scripts/python.exe fullstack/aws/deploy.py --deploy --profile system-design-simulator-free --expected-project 675345028735
```

This creates a private artifact bucket, CloudFormation stack, website/result buckets, DynamoDB table, Cognito user pool, HTTP API, SQS queues and three Lambda functions. It uploads the application and prints the HTTPS website URL. It may take several minutes. The helper preserves an ignored `deployment.json` containing resource identifiers, not credentials. Repeating the command updates the stack and publishes the current frontend.

The deployment dependency `botocore[crt]` supports browser-based `aws login` credentials. It is needed by the local deployer; Lambda uses its execution role and does not need local login credentials. `--expected-project` stops deployment if STS identifies another project.

Audit note: no durable CloudTrail trail was configured in this newly created project. AWS's default management-event history provides limited retention, not a durable audit archive. This workflow does not change audit logging configuration.

On a Paid plan the script refuses to create resources unless you explicitly pass `--allow-paid` **after reviewing and approving the costs**. That flag does not upgrade a Free plan. Region is constrained to us-east-2 to match this project. Authentication must target the intended project; don't use an unrelated profile to bypass the billing check.

If provisioning fails, inspect CloudFormation validation results/events, correct the cause and retry. Do not automatically delete retained data or unrelated resources. The artifact bucket is created outside CloudFormation and remains if stack creation fails. New AWS projects can have low Lambda concurrency quotas or service restrictions that require revising event-source concurrency or enabling supported services; deployment is not guaranteed until account-aware checks and smoke tests pass.

## Verify the deployed result

1. Open the HTTPS website. Confirm browser requests reach the API without CORS errors.
2. Sign up through Cognito; confirm the email and sign in. No admin bypass of email ownership.
3. Submit a bounded experiment. Verify queued → running → completed and charts/results.
4. Sign in as a second user and verify the first user's experiment is absent and its URL/API ID returns 404.
5. Compare two runs, export the completed library, and restore it locally.
6. Check Lambda errors, SQS dead letters, retained results, and actual AWS cost/credit usage.

No Cognito passwords or refresh tokens are saved to the application database. The browser uses access tokens in sessionStorage, verifies OAuth state, and keeps the PKCE verifier only for the login round trip. A session expires after an hour on AWS and requires sign-in again; automatic refresh is intentionally not implemented. Each API request verifies JWT signature, issuer, expiration, token use and client ID. Configurations and result documents are scoped to the verified subject.

## Keep using it after AWS ends

Use **Experiment library → Export all** before credits expire or the project is paused. Run the local application as documented in `../README.md` and import the JSON archive. Local operation has no AWS time limit. Keep a separate database/archive backup.

## Stop or remove cloud resources

Export data first. To stop new simulations temporarily, disable the HTTP API or remove its routes and disable the worker's SQS mapping; inspect queued messages and costs before deleting anything. CloudFormation stack deletion is a deliberate action, not part of this script. It retains the Cognito user pool, DynamoDB table, and S3 data by design. Retained storage can continue to incur costs. The artifact bucket also remains. Full cleanup requires explicit deletion of those resources after backup; empty all S3 versions before deleting versioned buckets. Confirm the resources belong to this stack. Do not delete the entire AWS project as an application cleanup step.

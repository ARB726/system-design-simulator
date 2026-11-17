"""Prepare, inspect, or deploy Systems Lab. No AWS changes without --deploy."""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4
import zipfile

from fullstack.aws.template import template

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def prepare(wheelhouse=None):
    staging = Path(wheelhouse).resolve() if wheelhouse else ROOT / '.local' / ('wheels-' + uuid4().hex[:10])
    if wheelhouse:
        if len(list(staging.glob('*.whl'))) < 20:
            raise SystemExit('Wheelhouse is incomplete. Prepare without --wheelhouse to download dependencies.')
    else:
        staging.mkdir(parents=True)
        subprocess.run([sys.executable, '-m', 'pip', 'download', '--platform', 'manylinux_2_28_x86_64', '--platform', 'manylinux2014_x86_64', '--implementation', 'cp', '--python-version', '3.12', '--only-binary=:all:', '--dest', str(staging), '-r', str(HERE / 'requirements-lambda.txt')], check=True)
    archive = ROOT / '.local/systems-lab-lambda.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
        written = set()
        # Stream wheel contents directly into the deployment ZIP instead of creating
        # two full extracted copies. Wheels contain the same importable package layout.
        for wheel in sorted(staging.glob('*.whl')):
            with zipfile.ZipFile(wheel) as source:
                for info in source.infolist():
                    name = info.filename
                    if info.is_dir() or 'tests' in Path(name).parts or '__pycache__' in Path(name).parts:
                        continue
                    if '.data/' in name:
                        _, relative = name.split('.data/', 1)
                        if relative.startswith(('purelib/', 'platlib/')):
                            name = relative.split('/', 1)[1]
                        else:
                            continue
                    if name in written:
                        raise RuntimeError('Duplicate wheel entry: ' + name)
                    written.add(name)
                    with source.open(info) as src, output.open(name, 'w') as dst:
                        import shutil
                        shutil.copyfileobj(src, dst)
        for directory in ('sim', 'fullstack/backend'):
            for file in (ROOT / directory).rglob('*.py'):
                output.write(file, file.relative_to(ROOT))
        output.write(ROOT / 'fullstack/__init__.py', 'fullstack/__init__.py')
        output.write(ROOT / 'data/optima.json', 'data/optima.json')
        size = sum(info.file_size for info in output.infolist())
    if size >= 250 * 1024 * 1024:
        raise SystemExit('Lambda package exceeds the 250 MiB extracted limit.')
    print(json.dumps({'archive': str(archive), 'compressed_mb': round(archive.stat().st_size / 1024**2, 2), 'extracted_mb': round(size / 1024**2, 2)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare', action='store_true', help='Build a Linux-compatible Lambda ZIP locally; no AWS calls.')
    mode.add_argument('--plan', action='store_true', help='Read-only identity, plan, and basic template validation.')
    mode.add_argument('--deploy', action='store_true', help='Create/update the reviewed AWS infrastructure and publish the frontend.')
    parser.add_argument('--profile', default='system-design-simulator-free')
    parser.add_argument('--expected-project', help='Refuse to deploy if STS returns a different project ID.')
    parser.add_argument('--region', default='us-east-2', choices=['us-east-2'])
    parser.add_argument('--stack', default='systems-lab')
    parser.add_argument('--allow-paid', action='store_true', help='Explicitly allow deployment to a Paid plan after reviewing costs.')
    parser.add_argument('--wheelhouse', help='Reuse a complete, previously downloaded Linux wheel directory for a code-only package rebuild.')
    args = parser.parse_args()
    if not args.stack.replace('-', '').isalnum() or not args.stack[0].isalpha() or len(args.stack) > 30:
        parser.error('Stack name must start with a letter, contain letters/numbers/hyphens, and be <=30 characters.')
    body = json.dumps(template(), indent=2)
    (HERE / 'template.json').write_text(body + '\n')
    if args.prepare:
        prepare(args.wheelhouse)
        return
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    config = Config(retries={'mode':'standard','max_attempts':3},connect_timeout=5,read_timeout=30)
    client = lambda service: session.client(service, config=config)
    identity = client('sts').get_caller_identity()
    if args.expected_project and identity['Account'] != args.expected_project:
        raise SystemExit('Authenticated project does not match --expected-project. No resources created.')
    plan = client('freetier').get_account_plan_state()
    summary = {'project': identity['Account'], 'region': args.region, 'plan': plan.get('accountPlanType'), 'credits': plan.get('accountPlanRemainingCredits'), 'architecture': 'CloudFront/S3 + Cognito + HTTP API/FastAPI + SQS/Lambda + DynamoDB/S3', 'cost_estimate': 'Approximate USD 1–5/month at light demo usage, before applicable allowances; not a cap. See DEPLOY.md.'}
    print(json.dumps(summary, indent=2, ensure_ascii=True), flush=True)
    cf = client('cloudformation')
    cf.validate_template(TemplateBody=body)
    print('AWS basic template validation passed. This does not verify runtime behavior or permissions.', flush=True)
    if args.plan:
        return
    if plan.get('accountPlanType') == 'PAID' and not args.allow_paid:
        raise SystemExit('Paid plan detected. Reconcile billing or explicitly approve the cost estimate and pass --allow-paid. No resources created.')
    archive = ROOT / '.local/systems-lab-lambda.zip'
    website = ROOT / 'fullstack/frontend/out'
    if not archive.exists() or not (website / 'index.html').exists():
        parser.error('Build the frontend and run --prepare before deploying. No resources created.')
    code_bucket = f"{args.stack}-artifacts-{identity['Account']}-{args.region}"
    s3 = client('s3')
    try:
        s3.head_bucket(Bucket=code_bucket)
    except ClientError as exc:
        if exc.response['Error']['Code'] not in ('404','NoSuchBucket','NotFound'):
            raise
        s3.create_bucket(Bucket=code_bucket, CreateBucketConfiguration={'LocationConstraint':args.region})
        s3.put_public_access_block(Bucket=code_bucket,PublicAccessBlockConfiguration={k:True for k in ('BlockPublicAcls','IgnorePublicAcls','BlockPublicPolicy','RestrictPublicBuckets')})
        s3.put_bucket_encryption(Bucket=code_bucket,ServerSideEncryptionConfiguration={'Rules':[{'ApplyServerSideEncryptionByDefault':{'SSEAlgorithm':'AES256'}}]})
        s3.put_bucket_policy(Bucket=code_bucket,Policy=json.dumps({'Version':'2012-10-17','Statement':[{'Effect':'Deny','Principal':'*','Action':'s3:*','Resource':[f'arn:aws:s3:::{code_bucket}',f'arn:aws:s3:::{code_bucket}/*'],'Condition':{'Bool':{'aws:SecureTransport':False}}}]}))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()[:20]
    key = f'packages/{digest}.zip'
    s3.upload_file(str(archive), code_bucket, key, ExtraArgs={'ServerSideEncryption':'AES256'})
    parameters = [{'ParameterKey':'CodeBucket','ParameterValue':code_bucket},{'ParameterKey':'CodeKey','ParameterValue':key}]
    request = dict(StackName=args.stack,TemplateBody=body,Parameters=parameters,Capabilities=['CAPABILITY_IAM'],Tags=[{'Key':'Application','Value':'systems-lab'}])
    try:
        cf.describe_stacks(StackName=args.stack)
    except ClientError as exc:
        if 'does not exist' not in exc.response['Error']['Message']:
            raise
        cf.create_stack(**request)
        waiter = 'stack_create_complete'
    else:
        try:
            cf.update_stack(**request)
        except ClientError as exc:
            if 'No updates are to be performed' not in exc.response['Error']['Message']:
                raise
            waiter = None
        else:
            waiter = 'stack_update_complete'
    if waiter:
        print('Infrastructure provisioning; this may take several minutes.', flush=True)
        cf.get_waiter(waiter).wait(StackName=args.stack,WaiterConfig={'Delay':20,'MaxAttempts':90})
    stack = cf.describe_stacks(StackName=args.stack)['Stacks'][0]
    outputs = {o['OutputKey']:o['OutputValue'] for o in stack['Outputs']}
    for file in website.rglob('*'):
        if not file.is_file() or file.name == 'runtime-config.json':
            continue
        relative = file.relative_to(website).as_posix()
        content_type = mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
        # Next's immutable build assets can be cached for a year; HTML/config must refresh.
        cache = 'public,max-age=31536000,immutable' if relative.startswith('_next/') else 'no-cache'
        s3.upload_file(str(file),outputs['WebsiteBucket'],relative,ExtraArgs={'ContentType':content_type,'CacheControl':cache,'ServerSideEncryption':'AES256'})
    s3.put_object(Bucket=outputs['WebsiteBucket'],Key='runtime-config.json',Body=json.dumps({'apiUrl':outputs['ApiUrl']}).encode(),ContentType='application/json',CacheControl='no-store',ServerSideEncryption='AES256')
    client('cloudfront').create_invalidation(DistributionId=outputs['DistributionId'],InvalidationBatch={'Paths':{'Quantity':1,'Items':['/*']},'CallerReference':str(time.time_ns())})
    outputs.update(CodeBucket=code_bucket,StackName=args.stack,Region=args.region)
    (HERE / 'deployment.json').write_text(json.dumps(outputs,indent=2)+'\n')
    print(json.dumps(outputs,indent=2),flush=True)
    print('Deployment finished. Verify hosted sign-up, a real simulation, account ownership, export, and local restore.',flush=True)


if __name__ == '__main__':
    main()

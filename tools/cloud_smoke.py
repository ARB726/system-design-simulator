"""Create/clean an isolated, non-email-verified test identity for deployment QA."""
import argparse
import json
from pathlib import Path
import secrets
from uuid import uuid4

import boto3
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['create', 'cleanup'])
    parser.add_argument('--label', choices=['primary', 'second'], default='primary')
    args = parser.parse_args()
    outputs = json.loads((ROOT / 'fullstack/aws/deployment.json').read_text())
    session = boto3.Session(profile_name='system-design-simulator-free', region_name='us-east-2')
    if session.client('sts').get_caller_identity()['Account'] != '675345028735':
        raise SystemExit('Wrong project for smoke test.')
    client = session.client('cognito-idp', config=Config(retries={'mode':'standard','max_attempts':3}))
    path = ROOT / ('.local/cloud-smoke-private.json' if args.label == 'primary' else '.local/cloud-smoke-second-private.json')
    if args.action == 'create':
        if path.exists():
            raise SystemExit('A test identity already exists; clean it up before creating another.')
        email = 'deployment-smoke-' + uuid4().hex[:12] + '@example.invalid'
        password = secrets.token_urlsafe(32) + 'Aa1!'
        user = client.admin_create_user(UserPoolId=outputs['UserPool'], Username=email, UserAttributes=[{'Name':'email','Value':email}], MessageAction='SUPPRESS')['User']
        # This synthetic test identity never asserts ownership of a real email address.
        # No email_verified attribute or admin-confirm-sign-up bypass is used.
        path.write_text(json.dumps({'username':user['Username'],'email':email,'password':password,'pool':outputs['UserPool']}))
        client.admin_set_user_password(UserPoolId=outputs['UserPool'], Username=user['Username'], Password=password, Permanent=True)
        print('Created isolated smoke-test identity. No email was sent or marked verified.')
    else:
        record = json.loads(path.read_text())
        if record['pool'] != outputs['UserPool'] or not record['email'].startswith('deployment-smoke-') or not record['email'].endswith('@example.invalid'):
            raise SystemExit('Unexpected identity; refusing cleanup.')
        attributes = {a['Name']: a['Value'] for a in client.admin_get_user(UserPoolId=record['pool'], Username=record['username'])['UserAttributes']}
        if attributes.get('email') != record['email']:
            raise SystemExit('Identity attributes changed; refusing cleanup.')
        subject = attributes['sub']
        from boto3.dynamodb.conditions import Key
        table = session.resource('dynamodb').Table(outputs['JobsTable'])
        rows = table.query(KeyConditionExpression=Key('owner').eq(subject), ConsistentRead=True)['Items']
        for row in rows:
            if 'document' not in row:
                continue
            job = json.loads(row['document'])
            if job['status'] not in ('completed', 'failed'):
                raise SystemExit('Test job is still active; refusing cleanup.')
        s3 = session.client('s3')
        prefix = 'results/' + subject + '/'
        for page in s3.get_paginator('list_object_versions').paginate(Bucket=outputs['ResultsBucket'], Prefix=prefix):
            versions = page.get('Versions', []) + page.get('DeleteMarkers', [])
            if versions:
                s3.delete_objects(Bucket=outputs['ResultsBucket'], Delete={'Objects':[{'Key':v['Key'],'VersionId':v['VersionId']} for v in versions], 'Quiet':True})
        with table.batch_writer() as batch:
            for row in rows:
                batch.delete_item(Key={'owner':subject,'id':row['id']})
        client.admin_delete_user(UserPoolId=record['pool'], Username=record['username'])
        path.unlink()
        print('Removed only the isolated test identity, its job/result fixtures, and its local password file.')


if __name__ == '__main__':
    main()

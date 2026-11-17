"""Durable SQL job queue locally; DynamoDB/SQS/S3 adapters on AWS."""
from __future__ import annotations

import json
import os
import time
from functools import lru_cache
from pathlib import Path
from uuid import uuid4


def now():
    return int(time.time())


class SQLStore:
    def __init__(self, url=None):
        from sqlalchemy import create_engine, text
        self.text = text
        Path('data').mkdir(exist_ok=True)
        self.engine = create_engine(url or os.getenv('DATABASE_URL', 'sqlite:///data/fullstack.db'))
        with self.engine.begin() as cx:
            cx.execute(text('CREATE TABLE IF NOT EXISTS lab_users (email VARCHAR(254) PRIMARY KEY, salt TEXT NOT NULL, password_hash TEXT NOT NULL)'))
            cx.execute(text('CREATE TABLE IF NOT EXISTS lab_jobs (id VARCHAR(36) PRIMARY KEY, owner VARCHAR(254) NOT NULL, created BIGINT NOT NULL, updated BIGINT NOT NULL, status VARCHAR(20) NOT NULL, payload TEXT NOT NULL, result TEXT, error TEXT)'))
            cx.execute(text('CREATE INDEX IF NOT EXISTS lab_jobs_owner ON lab_jobs(owner, created)'))

    def user(self, email):
        with self.engine.connect() as cx:
            row = cx.execute(self.text('SELECT * FROM lab_users WHERE email=:e'), {'e': email}).mappings().first()
            return dict(row) if row else None

    def add_user(self, email, salt, password_hash):
        from sqlalchemy.exc import IntegrityError
        try:
            with self.engine.begin() as cx:
                cx.execute(self.text('INSERT INTO lab_users VALUES (:e,:s,:h)'), {'e': email, 's': salt, 'h': password_hash})
            return True
        except IntegrityError:
            return False

    def create(self, owner, payload):
        job = dict(id=str(uuid4()), owner=owner, created=now(), updated=now(), status='queued', payload=payload)
        with self.engine.begin() as cx:
            # A database transaction serializes submissions with workers on SQLite.
            if self.engine.dialect.name == 'sqlite':
                cx.exec_driver_sql('UPDATE lab_jobs SET updated=updated WHERE 1=0')
            else:
                cx.execute(self.text('SELECT pg_advisory_xact_lock(hashtext(:o))'), {'o': owner})
            count = cx.execute(self.text("SELECT count(*) FROM lab_jobs WHERE owner=:o AND status IN ('queued','running')"), {'o': owner}).scalar_one()
            if count >= 2:
                raise ValueError('Two experiments are already active. Wait for one to finish.')
            cx.execute(self.text('INSERT INTO lab_jobs (id,owner,created,updated,status,payload) VALUES (:id,:owner,:created,:updated,:status,:payload)'), {**job, 'payload': json.dumps(payload)})
        return job

    def list(self, owner):
        with self.engine.connect() as cx:
            rows = cx.execute(self.text('SELECT id,owner,created,updated,status,payload,error FROM lab_jobs WHERE owner=:o ORDER BY created DESC LIMIT 100'), {'o': owner}).mappings()
            return [{**r, 'payload': json.loads(r['payload'])} for r in rows]

    def get(self, owner, job_id):
        with self.engine.connect() as cx:
            row = cx.execute(self.text('SELECT * FROM lab_jobs WHERE id=:i AND owner=:o'), {'i': job_id, 'o': owner}).mappings().first()
            if not row:
                return None
            return {**row, 'payload': json.loads(row['payload']), 'result': json.loads(row['result']) if row['result'] else None}

    def claim(self):
        with self.engine.begin() as cx:
            if self.engine.dialect.name == 'sqlite':
                cx.exec_driver_sql('UPDATE lab_jobs SET updated=updated WHERE 1=0')
            # A crashed worker must not leave an experiment running forever.
            cx.execute(self.text("UPDATE lab_jobs SET status='failed', error='Worker stopped or exceeded its execution limit.' WHERE status='running' AND updated<:cut"), {'cut': now() - 900})
            suffix = ' FOR UPDATE SKIP LOCKED' if self.engine.dialect.name == 'postgresql' else ''
            row = cx.execute(self.text("SELECT * FROM lab_jobs WHERE status='queued' ORDER BY created LIMIT 1" + suffix)).mappings().first()
            if not row:
                return None
            cx.execute(self.text("UPDATE lab_jobs SET status='running',updated=:t WHERE id=:i"), {'t': now(), 'i': row['id']})
            return {**row, 'payload': json.loads(row['payload'])}

    def finish(self, job, result=None, error=None):
        with self.engine.begin() as cx:
            cx.execute(self.text('UPDATE lab_jobs SET status=:s, result=:r,error=:e,updated=:t WHERE id=:i AND owner=:o'), dict(s='failed' if error else 'completed', r=json.dumps(result, allow_nan=False) if result else None, e=error, t=now(), i=job['id'], o=job['owner']))

    def restore(self, owner, jobs):
        with self.engine.begin() as cx:
            for job in jobs:
                cx.execute(self.text('INSERT INTO lab_jobs (id,owner,created,updated,status,payload,result,error) VALUES (:id,:owner,:created,:updated,:status,:payload,:result,:error)'), dict(id=str(uuid4()), owner=owner, created=int(job['created']), updated=now(), status=job['status'], payload=json.dumps(job['payload']), result=json.dumps(job.get('result'), allow_nan=False) if job.get('result') else None, error=job.get('error')))


class AWSStore:
    def __init__(self):
        import boto3
        from botocore.config import Config
        session = boto3.Session()
        settings = Config(retries={'mode': 'standard', 'max_attempts': 3}, connect_timeout=5, read_timeout=20)
        self.table = session.resource('dynamodb', config=settings).Table(os.environ['JOBS_TABLE'])
        self.s3 = session.client('s3', config=settings)
        self.sqs = session.client('sqs', config=settings)
        self.bucket = os.environ['RESULTS_BUCKET']

    def create(self, owner, payload):
        # A transactional per-owner counter bounds pending jobs across concurrent requests.
        import boto3
        from botocore.exceptions import ClientError
        job = dict(id=str(uuid4()), owner=owner, created=now(), updated=now(), status='queued', payload=payload)
        item = {'owner': owner, 'id': job['id'], 'document': json.dumps(job)}
        from boto3.dynamodb.types import TypeSerializer
        serialize = TypeSerializer().serialize
        client = self.table.meta.client
        # Resource clients apply their serializer to transactions, so use a separate low-level client.
        client = boto3.client('dynamodb')
        try:
            client.transact_write_items(TransactItems=[
                {'Update': {'TableName': self.table.name, 'Key': {k: serialize(v) for k, v in {'owner': owner, 'id': '_quota'}.items()},
                            'UpdateExpression': 'SET #active = if_not_exists(#active, :zero) + :one',
                            'ConditionExpression': 'attribute_not_exists(#active) OR #active < :limit',
                            'ExpressionAttributeNames': {'#active': 'active'},
                            'ExpressionAttributeValues': {k: serialize(v) for k, v in {':zero': 0, ':one': 1, ':limit': 2}.items()}}},
                {'Put': {'TableName': self.table.name, 'Item': {k: serialize(v) for k, v in item.items()}}}])
        except ClientError as exc:
            if exc.response['Error']['Code'] == 'TransactionCanceledException':
                raise ValueError('Two experiments are already active. Wait for one to finish.') from exc
            raise
        try:
            self.sqs.send_message(QueueUrl=os.environ['JOBS_QUEUE_URL'], MessageBody=json.dumps({'owner': owner, 'id': job['id']}))
        except Exception:
            self.finish(job, error='Unable to queue experiment. Please try again.')
            raise
        return job

    def list(self, owner):
        from boto3.dynamodb.conditions import Key
        rows, kwargs = [], {'KeyConditionExpression': Key('owner').eq(owner)}
        # Keys are UUIDs, not timestamps: paginate before sorting by creation time.
        while True:
            page = self.table.query(**kwargs)
            rows.extend(json.loads(r['document']) for r in page['Items'] if 'document' in r)
            if 'LastEvaluatedKey' not in page:
                break
            kwargs['ExclusiveStartKey'] = page['LastEvaluatedKey']
        return sorted(rows, key=lambda r: r['created'], reverse=True)[:100]

    def get(self, owner, job_id):
        item = self.table.get_item(Key={'owner': owner, 'id': job_id}, ConsistentRead=True).get('Item')
        if not item or 'document' not in item:
            return None
        job = json.loads(item['document'])
        if job.get('result_key'):
            body = self.s3.get_object(Bucket=self.bucket, Key=job['result_key'])['Body']
            try:
                job['result'] = json.loads(body.read())
            finally:
                body.close()
        return job

    def mark_running(self, job):
        from botocore.exceptions import ClientError
        document = json.dumps({k: v for k, v in job.items() if k != 'result'})
        updated = {**job, 'status': 'running', 'updated': now()}
        try:
            self.table.update_item(Key={'owner': job['owner'], 'id': job['id']}, UpdateExpression='SET #doc=:new', ConditionExpression='#doc=:old', ExpressionAttributeNames={'#doc':'document'}, ExpressionAttributeValues={':new': json.dumps(updated), ':old': document})
            return True
        except ClientError as exc:
            if exc.response['Error']['Code'] == 'ConditionalCheckFailedException':
                return False
            raise

    def finish(self, job, result=None, error=None):
        import boto3
        from boto3.dynamodb.types import TypeSerializer
        current = self.get(job['owner'], job['id'])
        if not current or current['status'] in ('completed', 'failed'):
            return
        expected = json.dumps({k: v for k, v in current.items() if k != 'result'})
        completed = {**current, 'status': 'failed' if error else 'completed', 'updated': now(), 'error': error}
        completed.pop('result', None)
        if result is not None:
            key = f"results/{job['owner']}/{job['id']}.json"
            self.s3.put_object(Bucket=self.bucket, Key=key, Body=json.dumps(result, allow_nan=False).encode(), ContentType='application/json', ServerSideEncryption='AES256')
            completed['result_key'] = key
        ser = TypeSerializer().serialize
        boto3.client('dynamodb').transact_write_items(TransactItems=[
            {'Update': {'TableName': self.table.name, 'Key': {k: ser(v) for k, v in {'owner': job['owner'], 'id': job['id']}.items()}, 'UpdateExpression': 'SET #doc=:new', 'ConditionExpression': '#doc=:old', 'ExpressionAttributeNames': {'#doc':'document'}, 'ExpressionAttributeValues': {':new': ser(json.dumps(completed)), ':old': ser(expected)}}},
            {'Update': {'TableName': self.table.name, 'Key': {k: ser(v) for k, v in {'owner': job['owner'], 'id': '_quota'}.items()}, 'UpdateExpression': 'SET #active = #active - :one', 'ConditionExpression': '#active > :zero', 'ExpressionAttributeNames': {'#active':'active'}, 'ExpressionAttributeValues': {':one': ser(1), ':zero': ser(0)}}}])


@lru_cache
def store():
    return AWSStore() if os.getenv('STORAGE_MODE') == 'aws' else SQLStore()

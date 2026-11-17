"""Persistent local worker and SQS Lambda entry point."""
import json
import logging
import time

from .jobs import execute
from .store import store

log = logging.getLogger(__name__)


def run_job(job):
    try:
        result = execute(job['payload'])
    except Exception:
        log.exception('Experiment %s failed', job['id'])
        store().finish(job, error='Simulation failed. Check worker logs and reduce workload before retrying.')
    else:
        store().finish(job, result=result)


def handler(event, context):
    failures = []
    for record in event['Records']:
        ref = json.loads(record['body'])
        job = store().get(ref['owner'], ref['id'])
        if not job or job['status'] in ('completed', 'failed'):
            continue
        try:
            # Retry an interrupted invocation only after the previous lease expired.
            if job['status'] == 'running' and time.time() - job['updated'] < 330:
                failures.append({'itemIdentifier': record['messageId']})
                continue
            if not store().mark_running(job):
                failures.append({'itemIdentifier': record['messageId']})
                continue
            run_job(job)
        except Exception:
            log.exception('Job persistence failed')
            failures.append({'itemIdentifier': record['messageId']})
    return {'batchItemFailures': failures}


def dead_letter_handler(event, context):
    for record in event['Records']:
        ref = json.loads(record['body'])
        job = store().get(ref['owner'], ref['id'])
        if job and job['status'] not in ('completed', 'failed'):
            store().finish(job, error='The worker exceeded its retry or time limit. Reduce the workload and retry.')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    while True:
        job = store().claim()
        if job:
            run_job(job)
        else:
            time.sleep(1)

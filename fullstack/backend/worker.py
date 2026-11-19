"""Persistent local worker and SQS Lambda entry point."""
import json
import logging
import time

from .jobs import execute
from .store import store
from .leases import EXHAUSTED, LeaseLost

log = logging.getLogger(__name__)


def run_job(job):
    log.info('Job attempt started id=%s attempt=%s', job['id'], job.get('attempts'))
    try:
        result = execute(job['payload'])
    except Exception:
        log.exception('Experiment %s failed', job['id'])
        outcome = 'failed'
        committed = store().finish(job, error='Simulation failed. Check worker logs and reduce workload before retrying.')
    else:
        outcome = 'completed'
        committed = store().finish(job, result=result)
    if not committed:
        log.warning('Job publication lease lost id=%s attempt=%s', job['id'], job.get('attempts'))
        raise LeaseLost(f"Publication lease lost for {job['id']}")
    log.info('Job attempt published id=%s attempt=%s outcome=%s', job['id'], job.get('attempts'), outcome)


def handler(event, context):
    failures = []
    for record in event['Records']:
        try:
            ref = json.loads(record['body'])
            job = store().get(ref['owner'], ref['id'])
            if not job or job['status'] in ('completed', 'failed'):
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
    failures = []
    for record in event['Records']:
        try:
            ref = json.loads(record['body'])
            job = store().get(ref['owner'], ref['id'])
            if job and job['status'] not in ('completed', 'failed'):
                if not store().finish(job, error=EXHAUSTED, exhausted=True):
                    failures.append({'itemIdentifier': record['messageId']})
        except Exception:
            log.exception('Dead-letter persistence failed')
            failures.append({'itemIdentifier': record['messageId']})
    return {'batchItemFailures': failures}


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            job = store().claim()
            if job:
                run_job(job)
            else:
                time.sleep(1)
        except Exception:
            log.exception('Worker attempt interrupted; lease recovery will retry')
            time.sleep(1)

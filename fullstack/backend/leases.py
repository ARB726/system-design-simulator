"""Shared bounded lease policy; execution may repeat, publication is fenced."""
from uuid import uuid4

LEASE_SECONDS = 330
MAX_ATTEMPTS = 3
EXHAUSTED = 'Worker stopped or exceeded its retry limit. Reduce the workload and retry.'


def deadline(job):
    # Compatibility with running documents written before lease tokens existed.
    return job.get('lease_until') or job['updated'] + LEASE_SECONDS


def claimable(job, timestamp):
    return job['status'] == 'queued' or (
        job['status'] == 'running' and deadline(job) <= timestamp
    )


def leased(job, timestamp):
    return {**job, 'status': 'running', 'updated': timestamp,
            'lease_token': str(uuid4()), 'lease_until': timestamp + LEASE_SECONDS,
            'attempts': job.get('attempts', 0) + 1}


class LeaseLost(RuntimeError):
    """Retry delivery: this attempt no longer has publication authority."""

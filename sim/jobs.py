"""Bounded Redis/Celery job admission and ownership checks."""
import os
import logging
import time
from functools import lru_cache
from uuid import uuid4


class JobError(RuntimeError):
    pass


def enabled():
    return os.environ.get("SYSDESIGN_EXECUTION", "local") == "celery"


@lru_cache(maxsize=1)
def redis_client():
    from redis import Redis
    return Redis.from_url(os.environ["SYSDESIGN_REDIS_URL"], decode_responses=True,
                          socket_connect_timeout=5, socket_timeout=5)


# Expiring sorted-set leases also recover capacity after a killed worker.
ADMIT = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', ARGV[1])
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[4]) then return 0 end
if redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[5]) then return 0 end
redis.call('ZADD', KEYS[1], ARGV[2], ARGV[3])
redis.call('ZADD', KEYS[2], ARGV[2], ARGV[3])
redis.call('EXPIRE', KEYS[1], 810)
redis.call('EXPIRE', KEYS[2], 810)
return 1
"""


def release(job_id, owner):
    client = redis_client()
    pipe = client.pipeline()
    pipe.zrem("sysdesign:active", job_id)
    pipe.zrem(f"sysdesign:owner:{owner}", job_id)
    pipe.execute()


def queue_snapshot():
    """Operator snapshot; ready counts exclude tasks reserved by workers."""
    client = redis_client()
    pipe = client.pipeline()
    pipe.zcount("sysdesign:active", time.time(), "+inf")
    for queue in ("interactive", "batch", "celery"):
        pipe.llen(queue)
    active, interactive, batch, legacy = pipe.execute()
    return dict(admitted=active, ready=dict(interactive=interactive, batch=batch, celery=legacy),
                redis_used_memory_bytes=client.info("memory")["used_memory"])


def submit(kind, payload, owner):
    from .telemetry import emit, queue_for
    queue = queue_for(kind)
    from .worker import celery_app
    from redis.exceptions import RedisError
    from kombu.exceptions import OperationalError
    job_id = uuid4().hex
    try:
        client = redis_client()
        admitted = client.eval(ADMIT, 2, "sysdesign:active", f"sysdesign:owner:{owner}",
                               time.time(), time.time() + 800, job_id,
                               int(os.environ.get("SYSDESIGN_MAX_PENDING", "32")),
                               int(os.environ.get("SYSDESIGN_JOBS_PER_USER", "2")))
        if not admitted:
            emit("job_rejected", kind=kind, queue=queue)
            raise JobError("The job queue is busy. Wait for a running job to finish and try again.")
        try:
            client.set(f"sysdesign:job:{job_id}", owner, ex=3600)
            celery_app.send_task("sysdesign.execute", args=[kind, payload, owner], task_id=job_id,
                                 kwargs={"submitted_at": time.time()}, queue=queue,
                                 expires=600, retry=False)
        except Exception:
            # Cleanup is best effort: an outage must not mask the submission error.
            # The admission leases expire even if Redis cannot accept cleanup.
            for cleanup in (lambda: release(job_id, owner),
                            lambda: client.delete(f"sysdesign:job:{job_id}")):
                try:
                    cleanup()
                except Exception:
                    logging.getLogger(__name__).warning(
                        "Could not clean up failed job submission; its lease will expire.")
            raise
    except JobError:
        raise
    except (RedisError, OSError, OperationalError) as exc:
        emit("job_submission_failed", kind=kind, queue=queue)
        raise JobError("The simulation queue is unavailable. Please try again later.") from exc
    emit("job_submitted", job_id=job_id, kind=kind, queue=queue)
    return job_id


def poll(job_id, owner):
    from .worker import celery_app
    from redis.exceptions import RedisError
    from kombu.exceptions import OperationalError
    try:
        # Check ownership before asking the result backend for any result.
        client = redis_client()
        if client.get(f"sysdesign:job:{job_id}") != owner:
            raise JobError("The job is unavailable or expired. Submit the experiment again.")
        result = celery_app.AsyncResult(job_id)
        state = result.state
        if state == "SUCCESS":
            return "complete", result.result
        if state in ("FAILURE", "REVOKED"):
            raise JobError("The simulation failed or exceeded its time limit. Reduce its size and retry.")
        if client.ttl(f"sysdesign:job:{job_id}") < 2800:
            raise JobError("The job expired before completing. Submit the experiment again.")
        return ("running" if state == "STARTED" else "queued"), None
    except (RedisError, OSError, OperationalError) as exc:
        raise JobError("The simulation queue is unavailable. Please try again later.") from exc

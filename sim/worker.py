"""Start with: celery -A sim.worker:celery_app worker --concurrency=2."""
import logging
import os
import json
import time

from celery import Celery
from kombu import Queue

from .telemetry import emit, queue_for

celery_app = Celery("sysdesign", broker=os.environ.get("SYSDESIGN_REDIS_URL", "redis://localhost:6379/0"),
                    backend=os.environ.get("SYSDESIGN_REDIS_URL", "redis://localhost:6379/0"))
celery_app.conf.update(
    task_queues=(Queue("interactive"), Queue("batch"), Queue("celery")),
    task_serializer="json", result_serializer="json", accept_content=["json"],
    task_track_started=True, result_expires=3600,
    task_time_limit=180, task_soft_time_limit=165,
    worker_prefetch_multiplier=1, worker_max_tasks_per_child=20,
    broker_connection_timeout=5, broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 900, "socket_timeout": 5},
    result_backend_transport_options={"socket_timeout": 5},
)


@celery_app.task(bind=True, name="sysdesign.execute")
def execute_job(self, kind, payload, owner, submitted_at=None):
    from .execution import execute
    from .jobs import release
    from .limits import SimulationLimitError
    started = time.perf_counter()
    metrics = dict(queue=queue_for(kind),
                   queue_wait_s=max(0.0, time.time() - submitted_at) if submitted_at is not None else None)
    outcome = "failed"
    result = None
    try:
        result = execute(kind, payload)
        outcome = "complete"
    except (SimulationLimitError, ValueError) as exc:
        result = {"error": str(exc)}
    except Exception:
        logging.getLogger(__name__).exception("Simulation job failed: %s", self.request.id)
        result = {"error": "The simulation could not finish. Try a smaller experiment."}
    finally:
        metrics["execution_s"] = time.perf_counter() - started
        emit("job_finished", job_id=self.request.id, kind=kind, outcome=outcome, **metrics)
        try:
            release(self.request.id, owner)
        except Exception:
            logging.getLogger(__name__).warning("Could not release job lease; it will expire.")
    metrics["result_bytes"] = len(json.dumps(result).encode("utf-8"))
    emit("job_result", job_id=self.request.id, result_bytes=metrics["result_bytes"])
    result["job_metrics"] = metrics
    return result

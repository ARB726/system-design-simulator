"""Start with: celery -A sim.worker:celery_app worker --concurrency=2."""
import logging
import os

from celery import Celery

celery_app = Celery("sysdesign", broker=os.environ.get("SYSDESIGN_REDIS_URL", "redis://localhost:6379/0"),
                    backend=os.environ.get("SYSDESIGN_REDIS_URL", "redis://localhost:6379/0"))
celery_app.conf.update(
    task_serializer="json", result_serializer="json", accept_content=["json"],
    task_track_started=True, result_expires=3600,
    task_time_limit=180, task_soft_time_limit=165,
    worker_prefetch_multiplier=1, worker_max_tasks_per_child=20,
    broker_connection_timeout=5, broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 900, "socket_timeout": 5},
    result_backend_transport_options={"socket_timeout": 5},
)


@celery_app.task(bind=True, name="sysdesign.execute")
def execute_job(self, kind, payload, owner):
    from .execution import execute
    from .jobs import release
    from .limits import SimulationLimitError
    try:
        return execute(kind, payload)
    except (SimulationLimitError, ValueError) as exc:
        return {"error": str(exc)}
    except Exception:
        logging.getLogger(__name__).exception("Simulation job failed: %s", self.request.id)
        return {"error": "The simulation could not finish. Try a smaller experiment."}
    finally:
        try:
            release(self.request.id, owner)
        except Exception:
            logging.getLogger(__name__).warning("Could not release job lease; it will expire.")

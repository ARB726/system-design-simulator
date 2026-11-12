"""Small, structured operational events; never log owners or workload payloads."""
import json
import logging

logger = logging.getLogger("sysdesign.metrics")
logger.setLevel(logging.INFO)


def emit(event, **fields):
    logger.info(json.dumps(dict(event=event, **fields), sort_keys=True))


def queue_for(kind):
    if kind in ("simulate", "replay"):
        return "interactive"
    if kind in ("grade", "sweep_load", "sweep_replicas", "validate_mmc"):
        return "batch"
    raise ValueError("Unknown simulation job type.")

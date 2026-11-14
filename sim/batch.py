"""Bounded subprocess batches, safe when called from a Streamlit script on Windows."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import os
from pathlib import Path
import subprocess
import sys

from .engine import run_summary
from .limits import validate_batch


def worker_limit():
    return max(1, min(4, os.cpu_count() or 1, int(os.environ.get("SYSDESIGN_SWEEP_WORKERS", "2"))))


def _chunk(points):
    try:
        result = subprocess.run([sys.executable, "-m", "sim.sweep_worker"],
                                input=json.dumps([(i, cfg.to_dict()) for i, cfg in points]),
                                capture_output=True, text=True, timeout=180,
                                cwd=Path(__file__).resolve().parents[1])
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise ValueError("An experiment worker timed out or could not start. Try fewer points or one worker.") from exc
    if result.returncode:
        logging.getLogger(__name__).error("Sweep subprocess failed: %s", result.stderr[-2000:])
        raise ValueError("An experiment worker failed; reduce the batch or check server logs.")
    return json.loads(result.stdout)


def summaries(configs, *, workers=1, progress=None, runner=None):
    validate_batch(configs)
    if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= worker_limit():
        raise ValueError(f"Choose 1 to {worker_limit()} experiment workers.")
    rows = [None] * len(configs)
    if workers == 1:
        for i, cfg in enumerate(configs):
            rows[i] = (runner or run_summary)(cfg)
            if progress:
                progress((i + 1) / len(configs), f"{i + 1}/{len(configs)} points complete")
        return rows
    # One persistent subprocess per chunk amortizes interpreter/import startup.
    # Threads only coordinate child processes; simulation CPU work is isolated.
    chunks = [list(enumerate(configs))[i::workers] for i in range(min(workers, len(configs)))]
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_chunk, chunk) for chunk in chunks]
        for future in as_completed(futures):
            for index, result in future.result():
                rows[index] = result
                done += 1
            if progress:
                progress(done / len(configs), f"{done}/{len(configs)} points complete")
    return rows

"""Bounded subprocess batches, safe when called from a Streamlit script on Windows."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import ExitStack, suppress
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from queue import Empty, Queue
import tempfile
from threading import Thread
from time import perf_counter

from .engine import run_summary
from .limits import validate_batch


def worker_limit():
    return max(1, min(4, os.cpu_count() or 1, int(os.environ.get("SYSDESIGN_SWEEP_WORKERS", "2"))))


WORKER_TIMEOUT_S = 180


class _Worker:
    """One persistent JSON-lines child, with a bounded lifetime and pipe cleanup."""

    def __init__(self):
        self.started = perf_counter()
        self.messages = Queue()
        self.stderr = tempfile.TemporaryFile()
        try:
            self.process = subprocess.Popen(
                [sys.executable, "-m", "sim.sweep_worker", "--stream"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr,
                text=True, encoding="utf-8", bufsize=1,
                cwd=Path(__file__).resolve().parents[1])
        except OSError as exc:
            self.stderr.close()
            raise ValueError("An experiment worker could not start. Try one worker.") from exc
        self.reader = Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                self.messages.put(line)
        except (OSError, UnicodeError):
            # The consumer reports an actionable worker error on end-of-stream.
            pass
        finally:
            self.messages.put(None)

    def run(self, point):
        index, cfg = point
        try:
            assert self.process.stdin is not None
            self.process.stdin.write(json.dumps([index, cfg.to_dict()], allow_nan=False) + "\n")
            self.process.stdin.flush()
            line = self.messages.get(timeout=max(0, WORKER_TIMEOUT_S - (perf_counter() - self.started)))
            if line is None:
                raise ValueError("Worker exited without a result")
            returned_index, result = json.loads(line)
            if type(returned_index) is not int or returned_index != index or not isinstance(result, dict):
                raise ValueError("Worker returned an invalid result")
            return index, result
        except Empty as exc:
            raise ValueError("An experiment worker timed out. Try fewer points or one worker.") from exc
        except (OSError, ValueError, TypeError) as exc:
            raise ValueError("An experiment worker failed; reduce the batch or check server logs.") from exc

    def close(self):
        if self.stderr.closed:
            return
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()
        self.reader.join(timeout=2)
        assert self.process.stdin is not None and self.process.stdout is not None
        with suppress(OSError):
            self.process.stdin.close()
        with suppress(OSError):
            self.process.stdout.close()
        self.stderr.seek(0, 2)
        size = self.stderr.tell()
        if size:
            self.stderr.seek(max(0, size - 2000))
            logging.getLogger(__name__).error("Sweep subprocess stderr: %s", self.stderr.read().decode("utf-8", errors="replace"))
        self.stderr.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


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
    # Reuse child interpreters; dispatch the next point to whichever finishes first.
    points = iter(enumerate(configs))
    done = 0
    with ExitStack() as stack:
        children = [stack.enter_context(_Worker()) for _ in range(min(workers, len(configs)))]
        with ThreadPoolExecutor(max_workers=len(children)) as pool:
            pending = {pool.submit(child.run, next(points)): child for child in children}
            try:
                while pending:
                    completed, _ = wait(pending, return_when=FIRST_COMPLETED)
                    for future in completed:
                        child = pending.pop(future)
                        index, result = future.result()
                        rows[index] = result
                        done += 1
                        if progress:
                            progress(done / len(configs), f"{done}/{len(configs)} points complete")
                        point = next(points, None)
                        if point is not None:
                            pending[pool.submit(child.run, point)] = child
            except BaseException:
                # Kill peers before joining executor threads; a failed point must
                # not wait for other children to consume their lifetime budgets.
                for child in children:
                    child.close()
                raise
    return rows

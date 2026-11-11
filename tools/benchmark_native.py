"""Report measured validation runtimes; no fabricated speedup target."""
import json
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sim.experiments import validate_mmc

results = {}
for backend in ("simpy", "cpp"):
    start = time.perf_counter()
    frame = validate_mmc(rhos=(0.5, 0.7, 0.8), backend=backend)
    results[backend] = dict(seconds=time.perf_counter() - start,
                            max_error_pct=float(frame.error_pct.abs().max()))
results["speedup"] = results["simpy"]["seconds"] / results["cpp"]["seconds"]
print(json.dumps(results, indent=2))

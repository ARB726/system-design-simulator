import json
import subprocess

import pytest

from sim.native import available, binary_path, simulate_mmc
from sim.theory import mmc_mean_response

pytestmark = [pytest.mark.native, pytest.mark.skipif(not available(), reason="Build the C++ kernel first")]


def test_known_fcfs_trace():
    # One server: responses are 2, 3, 1; waits are 0, 1, 0.
    result = subprocess.run([binary_path(), "--trace", "1", "0"], input="0 2\n1 2\n5 1\n",
                            text=True, capture_output=True, check=True)
    data = json.loads(result.stdout)
    assert data["mean_response_s"] == pytest.approx(2)
    assert data["mean_wait_s"] == pytest.approx(1 / 3)


def test_native_matches_theory_across_seeds():
    values = [simulate_mmc(4, 140, 50, seed=s)["mean_response_s"] for s in range(6)]
    assert sum(values) / len(values) == pytest.approx(mmc_mean_response(140, 50, 4), rel=0.05)


def test_native_seed_reproducible_and_invalid_input_rejected():
    assert simulate_mmc(4, 100, 50) == simulate_mmc(4, 100, 50)
    for args in (["0", "10", "50", "300", "20", "1"], ["4", "nan", "50", "300", "20", "1"],
                 ["4", "1000000", "50", "300", "20", "1"]):
        result = subprocess.run([binary_path(), *args], capture_output=True, text=True)
        assert result.returncode != 0


def test_cpp_validation_integration():
    from sim.experiments import validate_mmc
    result = validate_mmc(rhos=(0.5, 0.7), backend="cpp")
    assert len(result) == 2
    assert result.error_pct.abs().max() < 10


@pytest.mark.parametrize("servers", [1, 2, 4, 16])
@pytest.mark.parametrize("warmup", [0, 10, 100])
def test_native_trace_matches_simpy_fcfs(servers, warmup):
    """Feed both runtimes the same trace; their RNG algorithms need not match."""
    import random
    import simpy

    rng = random.Random(1701)
    trace, at = [], 0
    for _ in range(500):
        at += rng.randrange(4)
        trace.append((at, rng.randrange(1, 21)))

    env = simpy.Environment()
    resource = simpy.Resource(env, capacity=servers)
    responses, waits = [], []

    def request(at, service):
        with resource.request() as slot:
            yield slot
            start = env.now
            yield env.timeout(service)
        if at >= warmup:
            waits.append(start - at)
            responses.append(env.now - at)

    def arrivals():
        for at, service in trace:
            yield env.timeout(at - env.now)
            env.process(request(at, service))

    env.process(arrivals())
    env.run()
    result = subprocess.run([binary_path(), "--trace", str(servers), str(warmup)],
                            input="".join(f"{at} {service}\n" for at, service in trace),
                            text=True, capture_output=True, check=True, timeout=30)
    data = json.loads(result.stdout)
    assert data["requests"] == len(responses)
    assert data["mean_response_s"] == pytest.approx(sum(responses) / len(responses), abs=1e-12)
    assert data["mean_wait_s"] == pytest.approx(sum(waits) / len(waits), abs=1e-12)

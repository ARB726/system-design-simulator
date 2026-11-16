"""Both sweep worker transports preserve seeded summaries and validate inputs."""
import io
import json
import sys

import pytest

from sim.config import Config, Workload
from sim.engine import run_summary
from sim import sweep_worker


@pytest.mark.parametrize("stream", [False, True])
def test_worker_protocol_returns_each_seeded_point(monkeypatch, capsys, stream):
    configs = [Config(workload=Workload(rps=20, duration_s=.5, warmup_s=.1), seed=seed)
               for seed in (7, 9)]
    points = [[i, cfg.to_dict()] for i, cfg in enumerate(configs)]
    payload = "\n".join(json.dumps(point) for point in points) if stream else json.dumps(points)
    monkeypatch.setattr(sys, "argv", ["sweep_worker"] + (["--stream"] if stream else []))
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    sweep_worker.main()
    output = capsys.readouterr().out
    actual = [json.loads(line) for line in output.splitlines()] if stream else json.loads(output)
    assert actual == [[i, run_summary(cfg)] for i, cfg in enumerate(configs)]


@pytest.mark.parametrize("stream", [False, True])
def test_worker_protocol_rejects_invalid_configuration(monkeypatch, stream):
    cfg = Config().to_dict()
    cfg["seed"] = -1
    point = [0, cfg]
    monkeypatch.setattr(sys, "argv", ["sweep_worker"] + (["--stream"] if stream else []))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(point if stream else [point])))
    with pytest.raises(ValueError):
        sweep_worker.main()

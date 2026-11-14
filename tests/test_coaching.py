from types import SimpleNamespace

import pandas as pd
import pytest

from sim.analysis import summarize, timeline
from sim.coaching import evidence_findings, pressure_evidence, suggest_experiment
from sim.config import Config, Workload
from sim.engine import run
from sim.history import config_changes


def small():
    return Config(workload=Workload(rps=60, duration_s=2, warmup_s=.25), seed=7)


def test_pressure_evidence_is_measured_and_proposal_changes_one_setting():
    cfg = small()
    cfg.app.replicas, cfg.app.workers, cfg.app.latency_ms = 1, 1, 100
    result = run(cfg)
    tl = timeline(result)
    evidence = pressure_evidence(result, tl, summarize(result, tl))
    app = next(row for row in evidence if row["tier"] == "app")
    assert app["constrained"] and app["peak_queue"] > 0 and app["utilization"] >= .85
    assert .25 <= app["start_s"] < app["end_s"] <= cfg.workload.duration_s
    proposal = suggest_experiment(cfg, evidence)
    assert proposal["setting"] == "app.replicas"
    assert len(config_changes(cfg.to_dict(), proposal["candidate"])) == 1
    assert cfg.app.replicas == 1


def test_healthy_pressure_does_not_invent_a_fix():
    cfg = small()
    cfg.workload.rps = 1
    result = run(cfg)
    tl = timeline(result)
    evidence = pressure_evidence(result, tl, summarize(result, tl))
    assert not any(row["constrained"] for row in evidence)
    assert suggest_experiment(cfg, evidence) is None


def test_queue_proposal_respects_saturated_database():
    cfg = small()
    proposal = suggest_experiment(cfg, [dict(tier="queue", constrained=True), dict(tier="db_primary", constrained=True)])
    assert proposal["setting"] == "db.workers"


@pytest.mark.parametrize("bin_width", [1, 2])
def test_evidence_prefers_full_window_over_initial_spike(bin_width):
    cfg = Config(workload=Workload(duration_s=6 * bin_width, warmup_s=0))
    res = SimpleNamespace(cfg=cfg, requests=pd.DataFrame(dict(t=[3 * bin_width], status=["ok"], eff_ms=[10.])))
    tl = pd.DataFrame(dict(util_app=[1., .1, .1, .9, .9, .9], q_app=[1.] * 6),
                      index=[i * bin_width for i in range(6)])
    row = pressure_evidence(res, tl, {"tiers": {"app": {}}})[0]
    assert row["start_s"] == 3 * bin_width and row["end_s"] == 6 * bin_width
    assert row["utilization"] == pytest.approx(.9)


def test_recovered_burst_keeps_informational_severity():
    cfg = Config(workload=Workload(duration_s=6, warmup_s=0))
    cfg.queue.enabled = True
    res = SimpleNamespace(cfg=cfg, requests=pd.DataFrame(dict(t=[1], status=["ok"], eff_ms=[10.])))
    tl = pd.DataFrame(dict(util_queue=[.99] * 6, q_queue=[1., 2., 5., 3., 2., 0.]))
    summary = dict(tiers={"queue": {}}, queue=dict(end_depth=0), success_rate=1.)
    assert evidence_findings(res, tl, summary)[0]["level"] == "info"
    summary["success_rate"] = .9
    assert evidence_findings(res, tl, summary)[0]["level"] == "serious"

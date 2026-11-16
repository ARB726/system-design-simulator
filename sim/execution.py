"""JSON-only worker boundary; no Streamlit or per-user global state."""
from time import perf_counter

import pandas as pd

from .analysis import diagnose, summarize, timeline
from .config import config_from_dict
from .engine import SimResult, run


def analyzed_run(cfg):
    """Shared local/worker pipeline; timings describe computation, not cache hits."""
    started = perf_counter()
    res = run(cfg)
    simulated = perf_counter()
    tl = timeline(res)
    timelined = perf_counter()
    summary = summarize(res, tl)
    summarized = perf_counter()
    findings = diagnose(res, summary, tl)
    finished = perf_counter()
    res.timings = dict(simulation_s=simulated - started, timeline_s=timelined - simulated,
                       summary_s=summarized - timelined, diagnosis_s=finished - summarized,
                       pipeline_s=finished - started)
    return res, tl, summary, findings


def frame_data(frame):
    data = frame.astype(object).where(pd.notnull(frame), None).to_dict(orient="split")
    data["index_name"] = frame.index.name
    # Preserve numeric/all-null columns and empty boolean masks across JSON.
    data["dtypes"] = {name: str(dtype) for name, dtype in frame.dtypes.items() if dtype.kind in "biuf"}
    return data


def frame_from(data):
    frame = pd.DataFrame(data["data"], columns=data["columns"], index=data["index"])
    if data.get("dtypes"):
        frame = frame.astype(data["dtypes"])
    frame.index.name = data.get("index_name")
    return frame


def execute(kind, payload):
    if kind in ("simulate", "replay"):
        if kind == "simulate":
            cfg = config_from_dict(payload["config"])
        else:
            from .challenges import challenges, check_config
            ch = challenges()[payload["cid"]]
            cfg = check_config(ch, payload["design"], ch.checks[payload["index"]])
        res, tl, summary, findings = analyzed_run(cfg)
        started = perf_counter()
        result = dict(type="simulation", config=cfg.to_dict(), requests=frame_data(res.requests),
                    series=frame_data(res.series), lag=frame_data(res.lag), timeline=frame_data(tl),
                    summary=summary, findings=findings, warnings=res.warnings,
                    runtime_s=res.runtime_s, traffic=res.traffic)
        result["timings"] = dict(res.timings, serialization_s=perf_counter() - started)
        return result
    if kind == "grade":
        from .challenges import challenges, run_check
        ch, results, base = challenges()[payload["cid"]], [], None
        for i, check in enumerate(ch.checks):
            result = run_check(ch, payload["design"], check, keep_result=i == 0)
            if i == 0:
                base = result.pop("summary")
                result.pop("res")
                result.pop("tl")
            results.append(result)
        return dict(type="grade", results=results, summary=base)
    from .experiments import sweep_load, sweep_replicas, validate_mmc, compare_seeds
    if kind == "compare_seeds":
        report = compare_seeds(config_from_dict(payload["baseline"]), config_from_dict(payload["candidate"]),
                               payload["seeds"], workers=1)
        return dict(type="comparison", report=report)
    if kind == "sweep_load":
        values = payload["values"]
        if not 1 <= len(values) <= 12:
            raise ValueError("At most 12 load points are allowed.")
        frame = sweep_load(config_from_dict(payload["config"]), values)
    elif kind == "sweep_replicas":
        reps, strategies = payload["replicas"], payload["strategies"]
        if not 1 <= len(reps) * len(strategies) <= 32:
            raise ValueError("At most 32 scaling points are allowed.")
        frame = sweep_replicas(config_from_dict(payload["config"]), reps, strategies)
    elif kind == "validate_mmc":
        frame = validate_mmc(payload["c"], payload["mu"], backend=payload.get("backend", "simpy"))
    else:
        raise ValueError("Unknown simulation job type.")
    return dict(type="frame", frame=frame_data(frame))


def decode(data):
    if data.get("error"):
        raise ValueError(data["error"])
    if data["type"] == "frame":
        return frame_from(data["frame"])
    if data["type"] == "grade":
        return data["results"], data["summary"]
    if data["type"] == "comparison":
        return data["report"]
    started = perf_counter()
    res = SimResult(config_from_dict(data["config"]), frame_from(data["requests"]),
                    frame_from(data["series"]), frame_from(data["lag"]), data["warnings"], data["runtime_s"], data.get("traffic", {}))
    tl = frame_from(data["timeline"])
    res.timings = dict(data.get("timings", {}))
    res.timings["decode_s"] = perf_counter() - started
    return res, tl, data["summary"], data["findings"]

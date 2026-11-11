"""Durable run snapshots and deterministic comparisons, independent of the UI."""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .analysis import TIER_LABEL
from .config import Config, monthly_cost


class RunStore:
    """Small SQLite library. Every operation is scoped to an unguessable library key."""

    def __init__(self, path=None):
        self.path = Path(path or os.environ.get("SYSDESIGN_RUN_DB") or
                         Path(__file__).resolve().parents[1] / ".local" / "runs.sqlite3")

    @contextmanager
    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                db.execute("""CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, library TEXT NOT NULL,
                    created_at TEXT NOT NULL, payload TEXT NOT NULL)""")
                db.execute("CREATE INDEX IF NOT EXISTS runs_library ON runs(library, created_at)")
                yield db
        finally:
            db.close()

    @staticmethod
    def _check_library(library):
        if not isinstance(library, str) or not re.fullmatch(r"[a-f0-9]{32}", library):
            raise ValueError("Invalid run library key.")

    def save(self, library: str, name: str, cfg: Config, summary: dict, findings: list) -> dict:
        self._check_library(library)
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError("Give the run a name between 1 and 80 characters.")
        # Store the cost as measured now, even if illustrative prices change later.
        record = dict(version=1, id=uuid4().hex, name=name,
                      created_at=datetime.now(timezone.utc).isoformat(),
                      config=cfg.to_dict(), cost=monthly_cost(cfg), summary=summary,
                      findings=findings)
        payload = json.dumps(record, allow_nan=False, default=float)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute("SELECT count(*) FROM runs WHERE library = ?", (library,)).fetchone()[0]
            if count >= 100:
                raise ValueError("This library has 100 runs. Delete an old run before saving another.")
            db.execute("INSERT INTO runs VALUES (?, ?, ?, ?)",
                       (record["id"], library, record["created_at"], payload))
        return record

    def list(self, library: str) -> list[dict]:
        self._check_library(library)
        with self._connect() as db:
            rows = db.execute("SELECT payload FROM runs WHERE library = ? ORDER BY created_at DESC, id",
                              (library,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def delete(self, library: str, run_id: str) -> None:
        self._check_library(library)
        with self._connect() as db:
            db.execute("DELETE FROM runs WHERE library = ? AND id = ?", (library, run_id))


def config_changes(before: dict, after: dict) -> list[dict]:
    """Include workload and chaos changes so unlike experiments cannot look equivalent."""
    def flatten(value, prefix=""):
        out = {}
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(item, dict):
                out.update(flatten(item, path))
            else:
                out[path] = json.dumps(item, ensure_ascii=False, sort_keys=True)
        return out
    a, b = flatten(before), flatten(after)
    return [{"Setting": key, "Baseline": a.get(key, "-"), "Candidate": b.get(key, "-")}
            for key in sorted(a.keys() | b.keys()) if a.get(key) != b.get(key) and key != "name"]


def compare_runs(baseline: dict, candidate: dict) -> dict:
    """Report observations; one stochastic run does not establish a causal improvement."""
    a, b = baseline["summary"], candidate["summary"]
    metrics = [
        ("Served throughput", "served_rps", "rps", False),
        ("Success rate", "success_rate", "%", False),
        ("p95 latency", "p95_ms", "ms", True),
        ("p99 latency", "p99_ms", "ms", True),
        ("Monthly cost", "cost", "USD", True),
    ]
    rows, notes = [], []
    for label, key, unit, lower_better in metrics:
        av, bv = (baseline["cost"], candidate["cost"]) if key == "cost" else (a[key], b[key])
        scale = 100 if unit == "%" else 1
        delta = (bv - av) * scale
        equal = math.isclose(av, bv, rel_tol=1e-9, abs_tol=1e-9)
        outcome = "Unchanged" if equal else "Better" if (bv < av) == lower_better else "Worse"
        rows.append({"Metric": label, "Baseline": av * scale, "Candidate": bv * scale,
                     "Change": delta, "Unit": "percentage points" if unit == "%" else unit,
                     "Direction": outcome})
        if not equal:
            change_unit = "percentage points" if unit == "%" else unit
            notes.append(f"{label} {'decreased' if delta < 0 else 'increased'} by "
                         f"{abs(delta):,.2f} {change_unit} ({outcome.lower()} in this run).")

    warnings = []
    ca, cb = baseline["config"], candidate["config"]
    changed_conditions = [key for key in ("workload", "events", "seed", "app_only") if ca.get(key) != cb.get(key)]
    if changed_conditions:
        warnings.append("Experiment conditions differ: " + ", ".join(changed_conditions) +
                        ". These runs do not isolate the effect of architecture changes.")
    old, new = a.get("bottleneck"), b.get("bottleneck")
    if old != new:
        notes.append(f"The most loaded tier moved from {TIER_LABEL.get(old, 'none')} "
                     f"to {TIER_LABEL.get(new, 'none')}.")
    # A queue can improve acknowledgement latency while delaying actual writes.
    for run, label in ((baseline, "Baseline"), (candidate, "Candidate")):
        queue = run["summary"].get("queue")
        if queue:
            notes.append(f"{label} async writes: p95 apply lag {queue['lag_p95_s']:.2f} s; "
                         f"ending backlog {queue['end_depth']:,.0f}. Response latency measures acknowledgement.")
    if not notes:
        notes.append("The recorded metrics and bottleneck are unchanged.")
    warnings.append("These are individual seeded simulations with illustrative prices. "
                    "Repeat across seeds before treating small differences as improvements.")
    return dict(metrics=rows, notes=notes, warnings=warnings, changes=config_changes(ca, cb))

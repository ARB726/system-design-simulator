"""Progress tracking: stars, XP, levels, badges and campaign unlocks.

State is a plain dict kept in Streamlit's session state and can be saved to / loaded from a small JSON file,
so there is no database and no account. Loading sanitizes everything (the file is user input).
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

LEVELS = [(0, "Intern"), (100, "Junior Engineer"), (250, "Engineer"), (450, "Senior Engineer"),
          (700, "Staff Engineer"), (1000, "Principal Engineer"), (1400, "Distinguished Engineer")]
STAR_EFFICIENCY = {2: 0.80, 3: 0.97}       # cost efficiency needed (optimum cost / your cost)
STAR_BONUS_XP = 40

BADGES: Dict[str, tuple] = {
    "first_run":   ("\U0001F680 First deploy", "Grade your first design."),
    "green":       ("\U0001F7E2 All green", "Pass every hidden test of a challenge."),
    "frugal":      ("\U0001FA99 Frugal", "Pass every test while spending 60% of the budget or less."),
    "cost_crusher": ("\U0001F3AF Cost crusher", "Match the optimizer's cost (3 stars) on a challenge."),
    "queue_whisperer": ("\U0001F4EC Queue whisperer", "Pass a write-heavy challenge using the async queue."),
    "shard_sage":  ("\U0001F9E9 Shard sage", "Pass the payments ledger with a sharded database."),
    "napkin_master": ("\U0001F4DD Napkin master", "Score 90+ on three predictions."),
    "bottleneck_whisperer": ("\U0001F50D Bottleneck whisperer", "Name the bottleneck correctly five times."),
    "triple_crown": ("\U0001F451 Triple crown", "Earn 3 stars on three different challenges."),
    "completionist": ("\U0001F3C6 Completionist", "Earn at least one star on every challenge."),
}
QUEUE_CHALLENGES = {"writes", "flash"}


def empty() -> Dict:
    return dict(v=1, best={}, stars={}, attempts={}, pred=dict(n=0, sum=0.0, bottleneck_hits=0, high=0, xp=0),
                badges=[], flags=[])


# ---------------------------------------------------------------- stars, xp, levels
def stars_for(score: Dict) -> int:
    if not score.get("all_pass") or score.get("over_budget"):
        return 0
    eff = score.get("efficiency")
    if eff is None:
        return 1
    if eff >= STAR_EFFICIENCY[3]:
        return 3
    if eff >= STAR_EFFICIENCY[2]:
        return 2
    return 1


def xp_total(prog: Dict) -> int:
    return int(round(sum(prog["best"].values()) + STAR_BONUS_XP * sum(prog["stars"].values()) + prog["pred"]["xp"]))


def level_info(xp: int) -> Dict:
    idx = max(i for i, (t, _) in enumerate(LEVELS) if xp >= t)
    cur = LEVELS[idx][0]
    nxt = LEVELS[idx + 1] if idx + 1 < len(LEVELS) else None
    frac = 1.0 if not nxt else (xp - cur) / (nxt[0] - cur)
    return dict(level=idx + 1, title=LEVELS[idx][1], xp=xp, next_title=nxt[1] if nxt else None,
                to_next=(nxt[0] - xp) if nxt else 0, frac=float(frac))


def unlocked(prog: Dict, order: List[str]) -> List[str]:
    out = []
    for i, cid in enumerate(order):
        if i == 0 or prog["stars"].get(order[i - 1], 0) >= 1:
            out.append(cid)
    return out


# ---------------------------------------------------------------- recording events
def _award(prog: Dict, all_ids: List[str]) -> List[str]:
    have, new = set(prog["badges"]), []

    def give(b):
        if b not in have:
            have.add(b)
            new.append(b)

    p = prog["pred"]
    if sum(prog["attempts"].values()) >= 1:
        give("first_run")
    if any(s >= 1 for s in prog["stars"].values()):
        give("green")
    if "frugal" in prog["flags"]:
        give("frugal")
    if "queue" in prog["flags"]:
        give("queue_whisperer")
    if "shard" in prog["flags"]:
        give("shard_sage")
    if any(s >= 3 for s in prog["stars"].values()):
        give("cost_crusher")
    if sum(1 for s in prog["stars"].values() if s >= 3) >= 3:
        give("triple_crown")
    if all_ids and all(prog["stars"].get(c, 0) >= 1 for c in all_ids):
        give("completionist")
    if p["high"] >= 3:
        give("napkin_master")
    if p["bottleneck_hits"] >= 5:
        give("bottleneck_whisperer")
    prog["badges"] = [b for b in BADGES if b in have]
    return new


def record_attempt(prog: Dict, cid: str, design: Dict, budget: float, score: Dict, all_ids: List[str]) -> Dict:
    xp0 = xp_total(prog)
    lvl0 = level_info(xp0)["level"]
    st0 = prog["stars"].get(cid, 0)
    prog["attempts"][cid] = prog["attempts"].get(cid, 0) + 1
    prog["best"][cid] = max(prog["best"].get(cid, 0.0), float(score["total_score"]))
    st = stars_for(score)
    prog["stars"][cid] = max(st0, st)
    if score.get("all_pass") and not score.get("over_budget"):
        flags = set(prog["flags"])
        if score["cost"] <= 0.6 * budget:
            flags.add("frugal")
        if cid in QUEUE_CHALLENGES and design.get("queue"):
            flags.add("queue")
        if cid == "ledger" and int(design.get("shards", 1)) > 1:
            flags.add("shard")
        prog["flags"] = sorted(flags)
    new = _award(prog, all_ids)
    xp1 = xp_total(prog)
    info = level_info(xp1)
    return dict(new_badges=new, stars_gained=prog["stars"][cid] - st0, xp_gained=xp1 - xp0,
                level_up=info["level"] > lvl0, level=info)


def record_prediction(prog: Dict, ps: Dict, all_ids: List[str]) -> Dict:
    xp0 = xp_total(prog)
    lvl0 = level_info(xp0)["level"]
    p = prog["pred"]
    p["n"] += 1
    p["sum"] += float(ps["total"])
    p["bottleneck_hits"] += 1 if ps["parts"]["bottleneck"] > 0 else 0
    p["high"] += 1 if ps["total"] >= 90 else 0
    p["xp"] += int(round(min(ps["total"], 100) / 10))
    new = _award(prog, all_ids)
    info = level_info(xp_total(prog))
    return dict(new_badges=new, xp_gained=xp_total(prog) - xp0, level_up=info["level"] > lvl0, level=info)


# ---------------------------------------------------------------- save / load (sanitized)
def dumps(prog: Dict) -> str:
    return json.dumps(prog, indent=1, sort_keys=True)


def loads(text: str, valid_ids: Optional[List[str]] = None) -> Dict:
    """Parse an uploaded save file. Unknown or malformed fields are dropped; numbers are clamped."""
    out = empty()
    try:
        raw = json.loads(text)
    except (ValueError, TypeError):
        raise ValueError("Not a valid progress file.")
    if not isinstance(raw, dict):
        raise ValueError("Not a valid progress file.")
    ids = set(valid_ids) if valid_ids is not None else None

    def num(v, lo, hi, default=0.0):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return default
        return min(max(v, lo), hi) if v == v else default

    for key, lo, hi, cast in (("best", 0, 100, float), ("stars", 0, 3, int), ("attempts", 0, 10_000, int)):
        d = raw.get(key, {})
        if isinstance(d, dict):
            for cid, v in d.items():
                if isinstance(cid, str) and (ids is None or cid in ids):
                    out[key][cid] = cast(num(v, lo, hi))
    p = raw.get("pred", {})
    if isinstance(p, dict):
        out["pred"] = dict(n=int(num(p.get("n"), 0, 100_000)), sum=num(p.get("sum"), 0, 10_000_000),
                           bottleneck_hits=int(num(p.get("bottleneck_hits"), 0, 100_000)),
                           high=int(num(p.get("high"), 0, 100_000)), xp=int(num(p.get("xp"), 0, 100_000)))
    flags = raw.get("flags", [])
    if isinstance(flags, list):
        out["flags"] = sorted({f for f in flags if f in ("frugal", "queue", "shard")})
    badges = raw.get("badges", [])
    if isinstance(badges, list):
        out["badges"] = [b for b in BADGES if b in badges]
    return out

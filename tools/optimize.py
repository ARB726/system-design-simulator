"""Offline optimizer: find the cheapest design that passes every hidden check of each challenge.

Usage:  python tools/optimize.py            # all challenges, writes data/optima.json
        python tools/optimize.py launch     # one challenge

Method: enumerate every knob combination, drop designs whose steady-state napkin math is already above 92% on
some tier, sort by monthly cost, and simulate in cost order until one passes all checks (then re-verify the
winner with two other random seeds). A sample of the design space is also fully graded so the app can draw
a cost-vs-reliability frontier. Nothing here runs in the deployed app.
"""
import dataclasses
import json
import os
import random
import sys
import time
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim.challenges import (OPTIMA_PATH, challenges, design_cost, enumerate_designs, run_suite,  # noqa: E402
                            screen)

CH = challenges()


def _with_seed_offset(ch, off):
    return dataclasses.replace(ch, checks=[dataclasses.replace(c, seed=c.seed + off) for c in ch.checks])


def _eval(args):
    cid, design, stop, off = args
    ch = _with_seed_offset(CH[cid], off) if off else CH[cid]
    rs = run_suite(ch, design, stop_on_fail=stop)
    return sum(r["passed"] for r in rs), len(CH[cid].checks)


def optimize(cid, pool):
    ch = CH[cid]
    t0 = time.time()
    designs = [d for d in enumerate_designs(ch) if screen(ch, d)]
    designs = [d for d in designs if design_cost(ch, d) <= ch.budget * 1.6]
    print(f"[{cid}] {len(designs)} candidate designs after screening", flush=True)
    optimum = None
    tried = 0
    for d, (ok, tot) in zip(designs, pool.imap(_eval, [(cid, d, True, 0) for d in designs], chunksize=2)):
        tried += 1
        if ok == tot:
            verified = all(_eval((cid, d, True, off))[0] == tot for off in (17, 31))
            print(f"[{cid}] candidate ${design_cost(ch, d):.0f} passes; robust={verified}", flush=True)
            if verified:
                optimum = d
                break
    # sample of the space, fully graded, for the frontier chart
    rng = random.Random(7)
    pool_d = [d for d in designs if design_cost(ch, d) <= ch.budget * 1.3]
    sample = rng.sample(pool_d, min(60, len(pool_d)))
    graded = pool.map(_eval, [(cid, d, False, 0) for d in sample], chunksize=2)
    explored = [dict(cost=design_cost(ch, d), passed=g[0], total=g[1]) for d, g in zip(sample, graded)]
    out = dict(optimum=optimum, optimum_cost=design_cost(ch, optimum) if optimum else None, explored=explored,
               screened=len(designs), tried=tried, seconds=round(time.time() - t0))
    print(f"[{cid}] optimum cost={out['optimum_cost']} tried={tried} in {out['seconds']}s", flush=True)
    return out


if __name__ == "__main__":
    ids = sys.argv[1:] or list(CH)
    res = {}
    if os.path.exists(OPTIMA_PATH):
        res = json.load(open(OPTIMA_PATH))
    with Pool(2) as pool:
        for cid in ids:
            res[cid] = optimize(cid, pool)
            os.makedirs(os.path.dirname(OPTIMA_PATH), exist_ok=True)
            json.dump(res, open(OPTIMA_PATH, "w"), indent=1)
    print("saved", OPTIMA_PATH)

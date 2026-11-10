"""Plotly figures. Colors follow a validated categorical palette (fixed slot order, never cycled);
status colors are reserved for health and always paired with an icon and a word."""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .analysis import TIER_LABEL, health, tiers_present
from .config import Config, app_capacity_rps
from .engine import SimResult

# ------------------------------------------------------------------ palette
THEMES = {
    "light": dict(ink="#0b0b0b", ink2="#52514e", muted="#898781", grid="rgba(137,135,129,0.22)",
                  surface="#fcfcfb", series=["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"],
                  pct=["#86b6ef", "#2a78d6", "#104281"]),
    "dark": dict(ink="#f0efec", ink2="#c3c2b7", muted="#898781", grid="rgba(137,135,129,0.25)",
                 surface="#1a1a19", series=["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"],
                 pct=["#1c5cab", "#3987e5", "#9ec5f4"]),
}
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}
STATUS_TEXT = {"good": "✓ OK", "warning": "▲ Warm", "serious": "▲ Hot", "critical": "✕ Saturated"}
TIER_SLOT = {"app": 0, "cache": 1, "db_primary": 2, "db_replicas": 3, "queue": 4}
STRATEGY_SLOT = {"least_queue": 0, "round_robin": 1, "random": 2, "shared": 3}
STRATEGY_NAME = {"least_queue": "Least queue", "round_robin": "Round robin", "random": "Random",
                 "shared": "Shared queue"}
FAIL_COLOR = {"timeout": STATUS["warning"], "dropped": STATUS["serious"],
              "error": STATUS["critical"], "incomplete": "#898781"}
ACCENT: Optional[str] = None     # set by the app: tints neutral diagram boxes with the chosen theme
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'
FAIL_KINDS_PLOT = ["timeout", "dropped", "error", "incomplete"]
LOG_TICKS = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000]


def _t(theme: str) -> dict:
    return THEMES.get(theme, THEMES["light"])


def _layout(fig: go.Figure, theme: str, height: int, **kw) -> go.Figure:
    c = _t(theme)
    fig.update_layout(
        height=height, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, size=12, color=c["ink2"]),
        margin=dict(l=56, r=20, t=kw.pop("top", 36), b=kw.pop("bottom", 40)),
        hoverlabel=dict(bgcolor=c["surface"], font=dict(color=c["ink"], family=FONT), bordercolor=c["grid"]),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, bgcolor="rgba(0,0,0,0)"),
        **kw,
    )
    fig.update_xaxes(gridcolor=c["grid"], zeroline=False, linecolor=c["muted"], tickfont=dict(color=c["muted"]),
                     title_font=dict(color=c["ink2"], size=12))
    fig.update_yaxes(gridcolor=c["grid"], zeroline=False, tickfont=dict(color=c["muted"]),
                     title_font=dict(color=c["ink2"], size=12))
    return fig


# ------------------------------------------------------------------ architecture diagram
def _rounded(x0, y0, x1, y1, r=0.1) -> str:
    return (f"M {x0 + r},{y0} L {x1 - r},{y0} Q {x1},{y0} {x1},{y0 + r} L {x1},{y1 - r} "
            f"Q {x1},{y1} {x1 - r},{y1} L {x0 + r},{y1} Q {x0},{y1} {x0},{y1 - r} L {x0},{y0 + r} "
            f"Q {x0},{y0} {x0 + r},{y0} Z")


def _k(v: float) -> str:
    """Compact number: 1,234 -> 1.2k."""
    return f"{v / 1000:.1f}k" if v >= 1000 else f"{v:,.0f}"


def architecture_figure(cfg: Config, summ: Optional[Dict], theme: str = "light") -> go.Figure:
    """Architecture diagram. With summ=None it is a neutral blueprint (no health colors, no flows),
    used in challenge mode before the design has been graded."""
    c = _t(theme)
    fig = go.Figure()
    flows = summ["flows"] if summ else None
    tiers = summ["tiers"] if summ else {}
    a, d, q, x_ = cfg.app, cfg.db, cfg.queue, cfg.cdn

    cols = ["client"] + (["cdn"] if x_.enabled else []) + ["lb", "app"] + (["cache"] if cfg.cache.enabled else []) + ["db"]
    S = 1.75
    X = {k: 0.2 + i * S for i, k in enumerate(cols)}
    W, H = 1.3, 1.7
    n_sh = min(d.shards, 8)
    bars = n_sh if (d.shards > 1 and summ and summ.get("shards")) else 0
    has_rep = d.read_replicas > 0
    hp = 1.25 + 0.15 * bars if has_rep else H + 0.15 * bars
    hr = 1.25
    if has_rep:
        tot = hp + hr + 0.12
        y_p, y_r = tot / 2 - hp / 2, -(tot / 2 - hr / 2)
    else:
        y_p = y_r = 0.0
    db_top = y_p + hp / 2 if has_rep else hp / 2
    qh = 1.6 if q.enabled else 0.0
    top = max(db_top, H / 2) + 0.3 + qh / 2   # y of the write route (the queue box is centered on it)

    def rgba(col, a_):
        rgb = tuple(int(col[i:i + 2], 16) for i in (1, 3, 5))
        return f"rgba({rgb[0]},{rgb[1]},{rgb[2]},{a_})"

    def box(x, y, title, lines, tier=None, h=H, pips=0, shard_bars=()):
        x0, x1, y0, y1 = x - W / 2, x + W / 2, y - h / 2, y + h / 2
        st = tiers.get(tier) if tier else None
        if st:
            col = STATUS[st["status"]]
            fillc = rgba(col, 0.16)
        else:
            col, fillc = (ACCENT, rgba(ACCENT, 0.10)) if ACCENT else (c["muted"], "rgba(137,135,129,0.10)")
        fig.add_shape(type="path", path=_rounded(x0, y0, x1, y1), fillcolor=fillc,
                      line=dict(color=col, width=2), layer="below")
        fig.add_annotation(x=x, y=y1 - 0.2, text=f"<b>{title}</b>", showarrow=False, font=dict(size=12, color=c["ink"]))
        for i, ln in enumerate(lines):
            fig.add_annotation(x=x, y=y1 - 0.44 - i * 0.19, text=ln, showarrow=False, font=dict(size=10, color=c["ink2"]))
        if shard_bars:                          # per-shard utilization mini bars
            top_y = y1 - 0.44 - len(lines) * 0.19 - 0.04
            for i, u in enumerate(shard_bars[:8]):
                yy = top_y - i * 0.15
                bw = (W - 0.5) * min(u, 1.0)
                bcol = STATUS[health(u)]
                fig.add_annotation(x=x0 + 0.17, y=yy, text=f"s{i}", showarrow=False, font=dict(size=9, color=c["ink2"]))
                fig.add_shape(type="rect", x0=x0 + 0.3, x1=x0 + 0.3 + (W - 0.5), y0=yy - 0.045, y1=yy + 0.045,
                              fillcolor="rgba(137,135,129,0.25)", line=dict(width=0))
                fig.add_shape(type="rect", x0=x0 + 0.3, x1=x0 + 0.3 + max(bw, 0.01), y0=yy - 0.045, y1=yy + 0.045,
                              fillcolor=bcol, line=dict(width=0))
        if st:
            fig.add_annotation(x=x, y=y0 + (0.46 if pips else 0.36), text=f"<b>{STATUS_TEXT[st['status']]}</b>",
                               showarrow=False, font=dict(size=10, color=c["ink"]))
            fig.add_annotation(x=x, y=y0 + (0.30 if pips else 0.18), text=f"p90 {st['p90_util']:.0%}",
                               showarrow=False, font=dict(size=10, color=c["ink2"]))
        n = min(pips, 8)
        for i in range(n):                      # one pip per replica
            px = x - (n - 1) * 0.09 + i * 0.18
            fig.add_shape(type="rect", x0=px - 0.06, x1=px + 0.06, y0=y0 + 0.08, y1=y0 + 0.18,
                          fillcolor=col, line=dict(width=0))

    def arrow(x0, y0, x1, y1, label=None, dy=0.17):
        fig.add_annotation(x=x1, y=y1, ax=x0, ay=y0, xref="x", yref="y", axref="x", ayref="y", text="",
                           showarrow=True, arrowhead=2, arrowsize=1.1, arrowwidth=1.6, arrowcolor=c["muted"])
        if label and flows:
            fig.add_annotation(x=(x0 + x1) / 2, y=(y0 + y1) / 2 + dy, text=label, showarrow=False,
                               font=dict(size=10, color=c["ink2"]))

    cap = app_capacity_rps(cfg)
    f = lambda k: flows[k] if flows else 0.0
    box(X["client"], 0, "Clients", [f"{_k(cfg.workload.rps)} rps", f"{cfg.workload.read_ratio:.0%} reads"])
    if x_.enabled:
        box(X["cdn"], 0, "CDN", [f"{x_.hit_rate:.0%} of reads", f"{x_.latency_ms:g} ms"])
    box(X["lb"], 0, "Load balancer", [a.lb_strategy.replace("_", " ")])
    box(X["app"], 0, "App tier", [f"{a.replicas} × {a.workers} workers", f"{a.latency_ms:g} ms each", f"cap {_k(cap)} rps"],
        "app", pips=a.replicas)
    if cfg.cache.enabled:
        hr_ = summ["measured_hit_rate"] if summ else None
        box(X["cache"], 0, "Cache", [f"{(hr_ if hr_ is not None else cfg.cache.hit_rate):.0%} hit rate",
                                     "measured" if hr_ is not None else "configured", f"{cfg.cache.latency_ms:g} ms"], "cache")
    shard_u = summ.get("shards", []) if summ else []
    shard_txt = f"{d.shards} shards" if d.shards > 1 else None
    if has_rep:
        box(X["db"], y_p, "DB primary" if d.shards == 1 else "DB primaries",
            [shard_txt or f"{d.workers} conns", f"write {d.write_ms:g} ms"], "db_primary", h=hp,
            shard_bars=shard_u if bars else ())
        n_rep = d.read_replicas * d.shards
        box(X["db"], y_r, f"{n_rep} replica{'s' * (n_rep > 1)}", [f"{d.workers} conns each", f"read {d.read_ms:g} ms"],
            "db_replicas", h=hr)
    else:
        lines = ([shard_txt, f"{d.workers} conns each"] if shard_txt else [f"{d.workers} conns"]) + \
                ([] if shard_txt else [f"read {d.read_ms:g} ms", f"write {d.write_ms:g} ms"])
        box(X["db"], 0, "Database", lines, "db_primary", h=hp, shard_bars=shard_u if bars else ())

    g = W / 2
    prev, nxt = "client", None
    if x_.enabled:
        arrow(X["client"] + g, 0, X["cdn"] - g, 0, f"{_k(f('offered'))} rps")
        arrow(X["cdn"] + g, 0, X["lb"] - g, 0, f"{_k(f('to_app'))} miss")
    else:
        arrow(X["client"] + g, 0, X["lb"] - g, 0, f"{_k(f('offered'))} rps")
    arrow(X["lb"] + g, 0, X["app"] - g, 0, f"{_k(f('to_app'))} rps")
    if cfg.cache.enabled:
        arrow(X["app"] + g, 0, X["cache"] - g, 0, f"{_k(f('reads'))} reads")
        arrow(X["cache"] + g, 0, X["db"] - g, y_r, f"{_k(f('db_reads'))} miss", dy=0.17 if not has_rep else 0.3)
    else:
        arrow(X["app"] + g, 0, X["db"] - g, y_r, f"{_k(f('reads'))} reads", dy=0.17 if not has_rep else 0.3)

    # writes bypass the cache: over the top, optionally through the write queue
    gap = lambda xa, xb: fig.add_shape(type="path", path=f"M {xa},{top} L {xb},{top}",
                                       line=dict(color=c["muted"], width=1.6), fillcolor="rgba(0,0,0,0)")
    fig.add_shape(type="path", path=f"M {X['app']},{H / 2} L {X['app']},{top}",
                  line=dict(color=c["muted"], width=1.6), fillcolor="rgba(0,0,0,0)")
    if q.enabled:
        xq = (X["app"] + X["db"]) / 2
        gap(X["app"], xq - g)
        qlines = [f"{q.consumers} consumers"]
        if summ and summ.get("queue"):
            qlines += [f"lag p95 {summ['queue']['lag_p95_s']:.1f} s", f"peak {_k(summ['queue']['max_depth'])} queued"]
        box(xq, top, "Write queue", qlines, "queue", h=qh)
        gap(xq + g, X["db"])
        label_x = (X["app"] + xq - g) / 2
    else:
        gap(X["app"], X["db"])
        label_x = (X["app"] + X["db"]) / 2
    fig.add_shape(type="path", path=f"M {X['db']},{top} L {X['db']},{db_top + 0.06}",
                  line=dict(color=c["muted"], width=1.6), fillcolor="rgba(0,0,0,0)")
    fig.add_annotation(x=X["db"], y=db_top, ax=X["db"], ay=top - 0.05, xref="x", yref="y", axref="x", ayref="y",
                       text="", showarrow=True, arrowhead=2, arrowsize=1.1, arrowwidth=1.6, arrowcolor=c["muted"])
    if flows:
        fig.add_annotation(x=label_x, y=top + 0.17, text=f"{_k(f('writes'))} writes", showarrow=False,
                           font=dict(size=10, color=c["ink2"]))

    y_lo = (-(hp + hr + 0.12) / 2 if has_rep else -hp / 2) - 0.2
    y_lo = min(y_lo, -H / 2 - 0.2)
    y_hi = top + (qh / 2 + 0.1 if q.enabled else 0.4)
    fig.update_xaxes(visible=False, range=[-0.6, X["db"] + W / 2 + 0.2], fixedrange=True)
    fig.update_yaxes(visible=False, range=[y_lo, y_hi], fixedrange=True)
    fig.update_layout(height=int((y_hi - y_lo) * 92), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      margin=dict(l=4, r=4, t=4, b=4), showlegend=False, dragmode=False,
                      font=dict(family=FONT, color=c["ink2"]))
    return fig


def _left_titles(fig: go.Figure, c: dict) -> None:
    """Left-align each subplot title with the left edge of its own plot area."""
    for i, ann in enumerate(fig.layout.annotations):
        axis = fig.layout["xaxis" if i == 0 else f"xaxis{i + 1}"]
        ann.update(x=axis.domain[0], xanchor="left", font=dict(size=13, color=c["ink"]))


# ------------------------------------------------------------------ timeline
def _event_bands(fig: go.Figure, cfg: Config, theme: str):
    c = _t(theme)
    for e in cfg.events:
        fig.add_shape(type="rect", xref="x", yref="paper", x0=e.start_s, x1=min(e.end_s, cfg.workload.duration_s),
                      y0=0, y1=1, fillcolor="rgba(137,135,129,0.13)", line=dict(width=0), layer="below")
        fig.add_annotation(x=(e.start_s + min(e.end_s, cfg.workload.duration_s)) / 2, y=1.035, xref="x", yref="paper",
                           text=f"⚡ {e.label()}", showarrow=False, yanchor="bottom",
                           font=dict(size=11, color=c["ink"]))


def timeline_figure(res: SimResult, tl: pd.DataFrame, theme: str = "light") -> go.Figure:
    cfg = res.cfg
    c = _t(theme)
    has_lag = "lag_p95_s" in tl.columns and tl["lag_p95_s"].notna().any()
    titles = ["Traffic: offered vs served (requests/s)", "Latency (ms); failed requests count as the timeout",
              "Utilization of each tier (% of workers busy)"]
    heights = [0.27, 0.27, 0.25]
    if has_lag:
        titles.append("Write queue lag (p95 seconds from acknowledge to applied)")
        heights.append(0.17)
    titles.append("Failed requests per second")
    heights.append(0.2)
    n = len(titles)
    r_fail = n
    fig = make_subplots(rows=n, cols=1, shared_xaxes=True, vertical_spacing=0.06 if has_lag else 0.07,
                        row_heights=heights, subplot_titles=tuple(titles))
    for ann in fig.layout.annotations:
        ann.update(x=0, xanchor="left", font=dict(size=13, color=c["ink"]))
    x = tl.index

    # 1 traffic
    fig.add_trace(go.Scatter(x=x, y=tl.offered_rps, name="Offered", mode="lines",
                             line=dict(color=c["muted"], width=2, dash="dash"),
                             hovertemplate="%{y:,.0f}<extra>Offered</extra>"), row=1, col=1)
    fig.add_trace(go.Scatter(x=x, y=tl.served_rps, name="Served", mode="lines",
                             line=dict(color=c["series"][0], width=2.5),
                             hovertemplate="%{y:,.0f}<extra>Served</extra>"), row=1, col=1)
    fig.add_hline(y=app_capacity_rps(cfg), row=1, col=1, line=dict(color=c["muted"], width=1, dash="dot"),
                  annotation_text="app capacity", annotation_position="top right",
                  annotation_font=dict(size=10, color=c["muted"]))

    # 2 latency
    for col, nm, color in zip(["p50", "p95", "p99"], ["p50", "p95", "p99"], c["pct"]):
        fig.add_trace(go.Scatter(x=x, y=tl[col], name=nm, mode="lines", line=dict(color=color, width=2.2),
                                 hovertemplate="%{y:,.0f} ms<extra>" + nm + "</extra>"), row=2, col=1)
    if cfg.workload.timeout_ms:
        fig.add_hline(y=cfg.workload.timeout_ms, row=2, col=1, line=dict(color=STATUS["serious"], width=1, dash="dot"),
                      annotation_text="client timeout", annotation_position="top right",
                      annotation_font=dict(size=10, color=c["muted"]))

    # 3 utilization
    for t in tiers_present(res):
        fig.add_trace(go.Scatter(x=x, y=tl[f"util_{t}"] * 100, name=TIER_LABEL[t], mode="lines",
                                 line=dict(color=c["series"][TIER_SLOT[t]], width=2.2),
                                 hovertemplate="%{y:.0f}%<extra>" + TIER_LABEL[t] + "</extra>"), row=3, col=1)
    fig.add_hline(y=100, row=3, col=1, line=dict(color=STATUS["critical"], width=1, dash="dot"))

    # 4 write-queue lag
    if has_lag:
        fig.add_trace(go.Scatter(x=x, y=tl["lag_p95_s"], name="Queue lag p95", mode="lines",
                                 line=dict(color=c["series"][TIER_SLOT["queue"]], width=2.2),
                                 hovertemplate="%{y:.1f} s<extra>Queue lag p95</extra>"), row=4, col=1)
        fig.update_yaxes(ticksuffix=" s", row=4, col=1)

    # last: failures
    for k in ["timeout", "dropped", "error", "incomplete"]:
        col = f"{k}_rps"
        if col in tl and tl[col].sum() > 0:
            fig.add_trace(go.Bar(x=x, y=tl[col], name=k.capitalize(), marker_color=FAIL_COLOR[k],
                                 hovertemplate="%{y:,.0f}<extra>" + k.capitalize() + "</extra>"), row=r_fail, col=1)

    if not any(f"{k}_rps" in tl and tl[f"{k}_rps"].sum() > 0 for k in FAIL_KINDS_PLOT):
        yax = fig.layout["yaxis" if r_fail == 1 else f"yaxis{r_fail}"]
        fig.add_annotation(xref="paper", yref="paper", x=0.5, y=(yax.domain[0] + yax.domain[1]) / 2,
                           text="No failed requests", showarrow=False, font=dict(size=12, color=c["muted"]))
    _layout(fig, theme, 900 if has_lag else 800, top=70, bottom=84, hovermode="x unified", barmode="stack", bargap=0)
    fig.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.07 if has_lag else -0.075, xanchor="left", x=0,
                                  traceorder="normal", bgcolor="rgba(0,0,0,0)"))
    fig.update_yaxes(rangemode="tozero")
    fig.update_yaxes(range=[0, 108], ticksuffix="%", row=3, col=1)
    fig.update_xaxes(title_text="Simulated time (s)", row=r_fail, col=1)
    fig.update_xaxes(hoverformat=".0f")
    _event_bands(fig, cfg, theme)
    return fig


def frontier_figure(explored: List[Dict], yours: Optional[Dict], optimum_cost: Optional[float], budget: float,
                    theme: str = "light") -> go.Figure:
    """Cost vs checks passed for a sample of the design space, with the student's design and the optimum."""
    c = _t(theme)
    fig = go.Figure()
    rng = np.random.default_rng(3)
    if explored:
        xs = [e["cost"] for e in explored]
        ys = [e["passed"] / e["total"] * 100 + rng.uniform(-2.5, 2.5) for e in explored]
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="markers", name="Sampled designs",
                                 marker=dict(size=8, color=c["series"][0], opacity=0.45, line=dict(width=0)),
                                 hovertemplate="$%{x:,.0f}/mo<extra>Sampled design</extra>"))
    if optimum_cost:
        fig.add_trace(go.Scatter(x=[optimum_cost], y=[100], mode="markers", name="Cheapest passing design",
                                 marker=dict(size=16, symbol="star", color=c["series"][2], line=dict(color=c["surface"], width=1.5)),
                                 hovertemplate="$%{x:,.0f}/mo<extra>Cheapest passing</extra>"))
    if yours:
        fig.add_trace(go.Scatter(x=[yours["cost"]], y=[yours["passed"] / yours["total"] * 100], mode="markers",
                                 name="Your design",
                                 marker=dict(size=14, symbol="diamond", color=c["series"][1], line=dict(color=c["surface"], width=2)),
                                 hovertemplate="$%{x:,.0f}/mo<extra>Your design</extra>"))
    fig.add_vline(x=budget, line=dict(color=c["muted"], width=1.5, dash="dash"), annotation_text="budget",
                  annotation_position="top left", annotation_font=dict(size=10, color=c["ink2"]))
    _layout(fig, theme, 340, top=40)
    fig.update_xaxes(title_text="Monthly cost ($, illustrative)", tickprefix="$", rangemode="tozero")
    fig.update_yaxes(title_text="Checks passed", ticksuffix="%", range=[-8, 112], tickvals=[0, 33, 67, 100])
    return fig


# ------------------------------------------------------------------ animated replay
def replay_figure(res: SimResult, tl: pd.DataFrame, theme: str = "light") -> go.Figure:
    """Play the run second by second: tiers light up by health, queues fill, the headline tracks traffic."""
    cfg = res.cfg
    c = _t(theme)
    tiers = tiers_present(res)
    labels = [TIER_LABEL[t] for t in tiers][::-1]
    qcols = [("q_app", "App queue", "app"), ("q_cache", "Cache queue", "cache"), ("q_queue", "Write backlog", "queue"),
             ("q_db_primary", "DB queue", "db_primary"), ("q_db_replicas", "Replica queue", "db_replicas")]
    qcols = [(col, nm, t) for col, nm, t in qcols if col in tl.columns]
    qlabels = [nm for _, nm, _ in qcols][::-1]
    qmax = max([float(tl[col].fillna(0).max()) for col, _, _ in qcols] + [10.0])
    xs = list(tl.index)

    def util_bar(i):
        vals = [float(tl[f"util_{t}"].iloc[i]) if pd.notna(tl[f"util_{t}"].iloc[i]) else 0.0 for t in tiers][::-1]
        st = [health(v) for v in vals]
        return go.Bar(x=[v * 100 for v in vals], y=labels, orientation="h",
                      marker=dict(color=[STATUS[k] for k in st]),
                      text=[f"{STATUS_TEXT[k]} · {v:.0%}" for k, v in zip(st, vals)], textposition="outside",
                      cliponaxis=False, hoverinfo="skip", showlegend=False)

    def queue_bar(i):
        vals = [float(tl[col].iloc[i]) if pd.notna(tl[col].iloc[i]) else 0.0 for col, _, _ in qcols][::-1]
        cols = [c["series"][TIER_SLOT[t]] for _, _, t in qcols][::-1]
        return go.Bar(x=vals, y=qlabels, orientation="h", marker=dict(color=cols),
                      text=[f"{v:,.0f}" for v in vals], textposition="outside", cliponaxis=False, hoverinfo="skip",
                      showlegend=False)

    def headline(i):
        t = xs[i]
        active = [e.label() for e in cfg.events if e.start_s <= t < e.end_s]
        fail = sum(float(tl[f"{k}_rps"].iloc[i]) for k in ("timeout", "dropped", "error", "incomplete")
                   if f"{k}_rps" in tl.columns and pd.notna(tl[f"{k}_rps"].iloc[i]))
        p95 = tl["p95"].iloc[i]
        txt = (f"<b>t = {t:.0f} s</b>   offered {tl.offered_rps.iloc[i]:,.0f} rps · served {tl.served_rps.iloc[i]:,.0f} rps"
               f" · p95 {p95:,.0f} ms · failing {fail:,.0f}/s" if pd.notna(p95) else f"<b>t = {t:.0f} s</b>")
        if active:
            txt += "   ⚡ " + ", ".join(active)
        return txt

    fig = make_subplots(rows=1, cols=2, column_widths=[0.58, 0.42], horizontal_spacing=0.2,
                        subplot_titles=("Utilization (% of workers busy)", "Requests waiting in queues"))
    _left_titles(fig, c)
    fig.add_trace(util_bar(0), row=1, col=1)
    fig.add_trace(queue_bar(0), row=1, col=2)
    frames = [go.Frame(name=f"{xs[i]:.0f}", data=[util_bar(i), queue_bar(i)], traces=[0, 1],
                       layout=go.Layout(title=dict(text=headline(i)))) for i in range(len(xs))]
    fig.frames = frames
    _layout(fig, theme, 430, top=70, bottom=96)
    fig.update_layout(
        title=dict(text=headline(0), x=0, xanchor="left", y=0.97, font=dict(size=14, color=c["ink"])),
        updatemenus=[dict(type="buttons", direction="left", x=0, y=-0.12, xanchor="left", yanchor="top", showactive=False,
                          pad=dict(t=0, r=8),
                          buttons=[dict(label="▶ Play", method="animate",
                                        args=[None, dict(frame=dict(duration=140, redraw=True), transition=dict(duration=0),
                                                         fromcurrent=True)]),
                                   dict(label="❚❚ Pause", method="animate",
                                        args=[[None], dict(frame=dict(duration=0, redraw=False), mode="immediate",
                                                           transition=dict(duration=0))])])],
        sliders=[dict(active=0, x=0.2, len=0.8, y=-0.1, yanchor="top", currentvalue=dict(visible=False),
                      pad=dict(t=0, b=0), tickcolor=c["muted"], font=dict(color=c["muted"]),
                      steps=[dict(method="animate", label=f"{xs[i]:.0f}",
                                  args=[[f"{xs[i]:.0f}"], dict(mode="immediate", frame=dict(duration=0, redraw=True),
                                                                transition=dict(duration=0))]) for i in range(len(xs))])])
    fig.update_xaxes(range=[0, 125], ticksuffix="%", row=1, col=1)
    fig.update_xaxes(range=[0, qmax * 1.25], row=1, col=2)
    fig.update_yaxes(gridcolor="rgba(0,0,0,0)")
    return fig


# ------------------------------------------------------------------ latency distribution
def latency_hist_figure(res: SimResult, theme: str = "light") -> go.Figure:
    c = _t(theme)
    w = res.cfg.workload
    r = res.requests[(res.requests.t >= w.warmup_s) & (res.requests.status == "ok")]
    fig = go.Figure()
    if len(r) == 0:
        return _layout(fig, theme, 300)
    fig.add_trace(go.Histogram(x=r.latency_ms, nbinsx=60, marker=dict(color=c["series"][0], line=dict(color=c["surface"], width=1)),
                               name="Served requests", hovertemplate="%{x:.0f} ms: %{y:,} requests<extra></extra>"))
    for q, dash, pos in ((0.50, "dot", "top right"), (0.95, "dash", "top left"), (0.99, "solid", "top right")):
        v = float(r.latency_ms.quantile(q))
        fig.add_vline(x=v, line=dict(color=c["muted"], width=1.5, dash=dash), annotation_text=f"p{int(q * 100)} {v:.0f} ms",
                      annotation_position=pos, annotation_font=dict(size=10, color=c["ink2"]))
    _layout(fig, theme, 300, top=30, showlegend=False)
    fig.update_xaxes(title_text="Latency of served requests (ms)")
    fig.update_yaxes(title_text="Requests")
    return fig


# ------------------------------------------------------------------ experiments
def load_sweep_figure(df: pd.DataFrame, cfg: Config, theme: str = "light") -> go.Figure:
    c = _t(theme)
    fig = make_subplots(rows=1, cols=2, horizontal_spacing=0.1,
                        subplot_titles=("Throughput: served vs offered (requests/s)", "Latency vs offered load (ms)"))
    _left_titles(fig, c)
    hi = float(df.target_rps.max())
    fig.add_trace(go.Scatter(x=[0, hi], y=[0, hi], mode="lines", name="Ideal (all served)",
                             line=dict(color=c["muted"], width=1.5, dash="dash"), hoverinfo="skip"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.target_rps, y=df.served_rps, mode="lines+markers", name="Served",
                             line=dict(color=c["series"][0], width=2.5), marker=dict(size=8, line=dict(color=c["surface"], width=2)),
                             hovertemplate="%{x:,.0f} offered: %{y:,.0f} served<extra></extra>"), row=1, col=1)
    for col, nm, color in (("p50_ms", "p50", c["pct"][0]), ("p95_ms", "p95", c["pct"][1]), ("p99_ms", "p99", c["pct"][2])):
        fig.add_trace(go.Scatter(x=df.target_rps, y=df[col], mode="lines+markers", name=nm,
                                 line=dict(color=color, width=2.2), marker=dict(size=7, line=dict(color=c["surface"], width=2)),
                                 hovertemplate="%{y:,.0f} ms<extra>" + nm + "</extra>"), row=1, col=2)
    cap = app_capacity_rps(cfg)
    line = dict(color=c["series"][1], width=1.5, dash="dot")
    fig.add_vline(x=cap, row=1, col=1, line=line, annotation_text="app capacity",
                  annotation_position="top left", annotation_font=dict(size=10, color=c["ink2"]))
    fig.add_vline(x=cap, row=1, col=2, line=line)
    _layout(fig, theme, 400, top=44, bottom=100)
    fig.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="left", x=0,
                                  bgcolor="rgba(0,0,0,0)"))
    fig.update_xaxes(title_text="Offered load (requests/s)")
    fig.update_yaxes(rangemode="tozero", row=1, col=1)
    fig.update_yaxes(type="log", tickvals=LOG_TICKS, ticktext=[str(v) for v in LOG_TICKS], row=1, col=2,
                     title_text="Latency (ms), log scale")
    return fig


def replica_sweep_figure(df: pd.DataFrame, cfg: Config, theme: str = "light") -> go.Figure:
    c = _t(theme)
    fig = make_subplots(rows=1, cols=2, horizontal_spacing=0.1,
                        subplot_titles=("p95 latency (ms) vs number of replicas", "Served requests/s vs number of replicas"))
    _left_titles(fig, c)
    for strat in df.strategy.unique():
        sub = df[df.strategy == strat].sort_values("replicas")
        color = c["series"][STRATEGY_SLOT.get(strat, 4)]
        nm = STRATEGY_NAME.get(strat, strat)
        for col, dash_ in ((1, "solid"), (2, "solid")):
            y = sub.p95_ms if col == 1 else sub.served_rps
            fig.add_trace(go.Scatter(x=sub.replicas, y=y, mode="lines+markers", name=nm, legendgroup=strat,
                                     showlegend=(col == 1), line=dict(color=color, width=2.4),
                                     marker=dict(size=8, line=dict(color=c["surface"], width=2)),
                                     hovertemplate="%{x} replicas: %{y:,.0f}<extra>" + nm + "</extra>"), row=1, col=col)
    fig.add_hline(y=cfg.workload.rps, row=1, col=2, line=dict(color=c["muted"], width=1.5, dash="dash"),
                  annotation_text="offered load", annotation_position="bottom right",
                  annotation_font=dict(size=10, color=c["muted"]))
    _layout(fig, theme, 400, top=44, bottom=100)
    fig.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="left", x=0,
                                  bgcolor="rgba(0,0,0,0)"))
    fig.update_xaxes(title_text="App replicas", dtick=1)
    fig.update_yaxes(rangemode="tozero", row=1, col=2)
    fig.update_yaxes(type="log", tickvals=LOG_TICKS, ticktext=[str(v) for v in LOG_TICKS], row=1, col=1,
                     title_text="p95 latency (ms), log scale")
    return fig


def validation_figure(df: pd.DataFrame, theme: str = "light") -> go.Figure:
    c = _t(theme)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.utilization * 100, y=df.theory_ms, mode="lines", name="Theory (Erlang C)",
                             line=dict(color=c["series"][0], width=2.5),
                             hovertemplate="%{y:.1f} ms<extra>Theory</extra>"))
    fig.add_trace(go.Scatter(x=df.utilization * 100, y=df.simulated_ms, mode="markers", name="Simulation",
                             marker=dict(size=11, color=c["series"][1], line=dict(color=c["surface"], width=2)),
                             hovertemplate="%{y:.1f} ms<extra>Simulation</extra>"))
    _layout(fig, theme, 340, top=36, hovermode="x unified")
    fig.update_xaxes(title_text="Utilization (%)", ticksuffix="%")
    fig.update_yaxes(title_text="Mean response time (ms)", rangemode="tozero")
    return fig

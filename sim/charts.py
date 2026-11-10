"""Plotly figures. Colors follow a validated categorical palette (fixed slot order, never cycled);
status colors are reserved for health and always paired with an icon and a word."""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .analysis import TIER_LABEL, tiers_present
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
TIER_SLOT = {"app": 0, "cache": 1, "db_primary": 2, "db_replicas": 3}
STRATEGY_SLOT = {"least_queue": 0, "round_robin": 1, "random": 2, "shared": 3}
STRATEGY_NAME = {"least_queue": "Least queue", "round_robin": "Round robin", "random": "Random",
                 "shared": "Shared queue"}
FAIL_COLOR = {"timeout": STATUS["warning"], "dropped": STATUS["serious"],
              "error": STATUS["critical"], "incomplete": "#898781"}
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'
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


def architecture_figure(cfg: Config, summ: Dict, theme: str = "light") -> go.Figure:
    c = _t(theme)
    fig = go.Figure()
    flows = summ["flows"]
    tiers = summ["tiers"]
    W, H = 1.5, 1.5
    X = dict(client=0.2, lb=2.6, app=5.0, cache=7.4, db=9.8)
    has_cache = cfg.cache.enabled
    has_rep = cfg.db.read_replicas > 0
    y_p, y_r = (0.95, -0.95) if has_rep else (0.0, 0.0)

    def box(x, y, title, lines, tier=None, h=H, pips=0):
        x0, x1, y0, y1 = x - W / 2, x + W / 2, y - h / 2, y + h / 2
        if tier:
            st = tiers[tier]["status"]
            col = STATUS[st]
            rgb = tuple(int(col[i:i + 2], 16) for i in (1, 3, 5))
            fillc = f"rgba({rgb[0]},{rgb[1]},{rgb[2]},0.16)"
            badge = f"{STATUS_TEXT[st]} · {tiers[tier]['p90_util']:.0%}"
        else:
            col, fillc, badge = c["muted"], "rgba(137,135,129,0.10)", ""
        fig.add_shape(type="path", path=_rounded(x0, y0, x1, y1), fillcolor=fillc,
                      line=dict(color=col, width=2), layer="below")
        fig.add_annotation(x=x, y=y1 - 0.2, text=f"<b>{title}</b>", showarrow=False,
                           font=dict(size=13, color=c["ink"]))
        for i, ln in enumerate(lines):
            fig.add_annotation(x=x, y=y1 - 0.46 - i * 0.2, text=ln, showarrow=False,
                               font=dict(size=11, color=c["ink2"]))
        if badge:
            fig.add_annotation(x=x, y=y0 + (0.34 if pips else 0.18), text=f"<b>{badge}</b>", showarrow=False,
                               font=dict(size=11, color=c["ink"]))
        n = min(pips, 8)
        for i in range(n):                      # one pip per replica
            px = x - (n - 1) * 0.1 + i * 0.2
            fig.add_shape(type="rect", x0=px - 0.07, x1=px + 0.07, y0=y0 + 0.1, y1=y0 + 0.22,
                          fillcolor=col, line=dict(width=0))

    def arrow(x0, y0, x1, y1, label=None, dy=0.17):
        fig.add_annotation(x=x1, y=y1, ax=x0, ay=y0, xref="x", yref="y", axref="x", ayref="y", text="",
                           showarrow=True, arrowhead=2, arrowsize=1.1, arrowwidth=1.6, arrowcolor=c["muted"])
        if label:
            fig.add_annotation(x=(x0 + x1) / 2, y=(y0 + y1) / 2 + dy, text=label, showarrow=False,
                               font=dict(size=11, color=c["ink2"]))

    a, d = cfg.app, cfg.db
    cap = app_capacity_rps(cfg)
    box(X["client"], 0, "Clients", [f"avg {flows['offered']:,.0f} rps", f"{cfg.workload.read_ratio:.0%} reads"])
    box(X["lb"], 0, "Load balancer", [dict(least_queue="least queue", round_robin="round robin",
                                           random="random", shared="shared queue")[a.lb_strategy]])
    box(X["app"], 0, "App tier", [f"{a.replicas} × {a.workers} workers", f"{a.latency_ms:g} ms each",
                                  f"cap {cap:,.0f} rps"], "app", pips=a.replicas)
    if has_cache:
        hr = summ["measured_hit_rate"]
        box(X["cache"], 0, "Cache", [f"{(hr if hr is not None else cfg.cache.hit_rate):.0%} hit rate",
                                     "(measured)" if hr is not None else "(set)", f"{cfg.cache.latency_ms:g} ms lookup"],
            "cache")
    if has_rep:
        box(X["db"], y_p, "DB primary", [f"{d.workers} conns", f"write {d.write_ms:g} ms"], "db_primary", h=1.1)
        box(X["db"], y_r, f"{d.read_replicas} read replica{'s' * (d.read_replicas > 1)}",
            [f"{d.workers} conns each", f"read {d.read_ms:g} ms"], "db_replicas", h=1.1)
    else:
        box(X["db"], 0, "Database", [f"{d.workers} conns", f"read {d.read_ms:g} ms", f"write {d.write_ms:g} ms"],
            "db_primary")

    g = W / 2
    arrow(X["client"] + g, 0, X["lb"] - g, 0, f"{flows['offered']:,.0f} rps")
    arrow(X["lb"] + g, 0, X["app"] - g, 0, f"{flows['offered']:,.0f} rps")
    if has_cache:
        arrow(X["app"] + g, 0, X["cache"] - g, 0, f"{flows['reads']:,.0f} reads")
        arrow(X["cache"] + g, 0, X["db"] - g, y_r, f"{flows['db_reads']:,.0f} misses", dy=0.17 if not has_rep else 0.32)
    else:
        arrow(X["app"] + g, 0, X["db"] - g, y_r, f"{flows['reads']:,.0f} reads", dy=0.17 if not has_rep else 0.32)

    # writes bypass the cache: route over the top of the diagram into the primary
    top = 1.95
    ytop_db = (y_p + 0.55) if has_rep else H / 2
    fig.add_shape(type="path", path=f"M {X['app']},{H / 2} L {X['app']},{top} L {X['db']},{top} L {X['db']},{ytop_db + 0.06}",
                  line=dict(color=c["muted"], width=1.6), fillcolor="rgba(0,0,0,0)")
    fig.add_annotation(x=X["db"], y=ytop_db, ax=X["db"], ay=top - 0.05, xref="x", yref="y", axref="x", ayref="y",
                       text="", showarrow=True, arrowhead=2, arrowsize=1.1, arrowwidth=1.6, arrowcolor=c["muted"])
    fig.add_annotation(x=(X["app"] + X["db"]) / 2, y=top + 0.17, text=f"{flows['writes']:,.0f} writes (skip cache)",
                       showarrow=False, font=dict(size=11, color=c["ink2"]))

    fig.update_xaxes(visible=False, range=[-0.7, 10.9], fixedrange=True)
    fig.update_yaxes(visible=False, range=[-1.65 if has_rep else -1.0, 2.4], fixedrange=True)
    fig.update_layout(height=400 if has_rep else 330, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
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
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.07,
                        row_heights=[0.27, 0.27, 0.25, 0.21],
                        subplot_titles=("Traffic: offered vs served (requests/s)",
                                        "Latency (ms); failed requests count as the timeout",
                                        "Utilization of each tier (% of workers busy)",
                                        "Failed requests per second"))
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

    # 4 failures
    for k in ["timeout", "dropped", "error", "incomplete"]:
        col = f"{k}_rps"
        if col in tl and tl[col].sum() > 0:
            fig.add_trace(go.Bar(x=x, y=tl[col], name=k.capitalize(), marker_color=FAIL_COLOR[k],
                                 hovertemplate="%{y:,.0f}<extra>" + k.capitalize() + "</extra>"), row=4, col=1)

    _layout(fig, theme, 800, top=70, bottom=84, hovermode="x unified", barmode="stack", bargap=0)
    fig.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.075, xanchor="left", x=0,
                                  traceorder="normal", bgcolor="rgba(0,0,0,0)"))
    fig.update_yaxes(rangemode="tozero")
    fig.update_yaxes(range=[0, 108], ticksuffix="%", row=3, col=1)
    fig.update_xaxes(title_text="Simulated time (s)", row=4, col=1)
    fig.update_xaxes(hoverformat=".0f")
    _event_bands(fig, cfg, theme)
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

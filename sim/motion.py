"""CSS-only request-flow illustrations; simulation values remain server-rendered."""
from html import escape

from .config import Config
from .themes import accent


def traffic_scene(cfg: Config, summary=None, *, theme="Ocean", animate=True) -> str:
    """Show configured routes and measured health, with decorative, pausable motion.

    Packet spacing/speed is illustrative, not a replay of individual requests.
    No timers, JavaScript, external assets, or simulation reruns drive the motion.
    """
    color = accent(theme, True)
    nodes = [("client", "Clients", f"{cfg.workload.rps:,.0f} base rps", None)]
    if cfg.cdn.enabled and not cfg.app_only:
        nodes.append(("cdn", "CDN", f"{cfg.cdn.hit_rate:.0%} configured hits", None))
    nodes += [("lb", "Load balancer", cfg.app.lb_strategy.replace("_", " "), None),
              ("app", "App tier", f"{cfg.app.replicas} × {cfg.app.workers} workers", "app")]
    if not cfg.app_only:
        if cfg.cache.enabled:
            nodes.append(("cache", "Cache", f"{cfg.cache.hit_rate:.0%} configured hits", "cache"))
        db_detail = f"{cfg.db.shards} shard{'s' if cfg.db.shards != 1 else ''}"
        if cfg.db.read_replicas:
            db_detail += f" / {cfg.db.read_replicas} replicas each"
        nodes.append(("db", "Database", db_detail, "db_primary"))
    tiers = (summary or {}).get("tiers", {})
    palette = {"good": ("#66dfb3", "OK"), "warning": ("#ffd17a", "Warm"),
               "serious": ("#ffad84", "Hot"), "critical": ("#ff8496", "Saturated")}
    artwork = []
    write_route = ""
    if not cfg.app_only:
        app_index = next(i for i, node in enumerate(nodes) if node[0] == "app")
        node_width = f'(100% - 60px - {(len(nodes) - 1) * 28}px) / {len(nodes)}'
        left = f'calc(({node_width}) * {app_index + .5} + {app_index * 28 + 30}px)'
        right = f'calc(({node_width}) * .5 + 30px)'
        label = "Write queue" if cfg.queue.enabled else "Writes bypass cache"
        write_route = (f'<div class="lab-write-route" style="left:{left};right:{right}">'
                       f'<span class="lab-write-packets"></span><span class="lab-route-label">{label}</span></div>')
    for index, (key, label, detail, tier) in enumerate(nodes):
        state = tiers.get(tier)
        ink, status = palette.get(state["status"], (color, "Configured")) if state else (color, "Configured")
        health = f'{status} / {state["p90_util"]:.0%} p90' if state else status
        if state and tier == "db_primary" and cfg.db.read_replicas:
            health = f"Primary: {health}"
        link = '<div class="lab-link" aria-hidden="true"><span class="lab-packets"></span></div>' if index < len(nodes) - 1 else ''
        artwork.append(f'''<div class="lab-node" style="--delay:{index * 65}ms;--node-ink:{ink}">
          <div class="lab-node-card"><span class="lab-halo" aria-hidden="true"></span>
          <div class="lab-node-title">{label}</div><div class="lab-node-status">{health}</div></div>
          <div class="lab-detail">{escape(detail)}</div>{link}</div>''')
    stats = (f'<div><span>Measured throughput</span><strong>{summary["served_rps"]:,.0f}<small> rps</small></strong></div>'
             f'<div><span>Requests served</span><strong>{summary["success_rate"]:.1%}</strong></div>') if summary else (
             '<div><span>Design preview</span><strong>Ready to stress test</strong></div>')
    return f'''<style>
    .lab-scene {{ --lab-accent:{color}; color:#eef5ff; border:1px solid #31415c; border-radius:24px;
      overflow:hidden; background:radial-gradient(ellipse at 75% -20%, {color}35, transparent 65%), #0a1426;
      box-shadow:0 20px 55px #06132618; margin:4px 0 20px; }}
    .lab-scene * {{ box-sizing:border-box; }}
    .lab-scene .lab-scene-top {{ padding:25px 28px 0; display:flex; justify-content:space-between; gap:20px; flex-wrap:wrap; }}
    .lab-scene .lab-eyebrow {{ color:#a1b4d0; font:600 11px system-ui; letter-spacing:2px; text-transform:uppercase; }}
    .lab-scene h3 {{ color:#eef5ff; font:600 clamp(20px,3vw,28px) system-ui; letter-spacing:-.7px; margin:8px 0; }}
    .lab-scene .lab-scene-stats {{ display:flex; gap:28px; }}
    .lab-scene .lab-scene-stats span {{ display:block; color:#a1b4d0; font:12px system-ui; }}
    .lab-scene strong {{ display:block; font:600 24px system-ui; margin-top:6px; letter-spacing:-.6px; }}
    .lab-scene small {{ color:#a1b4d0; font-size:12px; }}
    .lab-scene .lab-canvas {{ overflow-x:auto; scrollbar-width:thin; }}
    .lab-scene .lab-scroll-hint {{ display:none; color:#a1b4d0; font:11px system-ui; padding:0 18px 14px; }}
    .lab-scene .lab-track {{ position:relative; display:grid; grid-template-columns:repeat({len(nodes)},minmax(0,1fr));
      gap:28px; min-width:680px; padding:88px 30px 24px; font-family:system-ui,sans-serif; text-align:center; }}
    .lab-scene .lab-node-card {{ border:1px solid var(--node-ink); border-radius:18px; background:#122039; padding:14px 4px 12px; }}
    .lab-scene .lab-node-title {{ color:#eef5ff; font-size:13px; font-weight:600; margin:10px 0 6px; }}
    .lab-scene .lab-node-status {{ color:var(--node-ink); font-size:10px; }}
    .lab-scene .lab-detail {{ color:#a1b4d0; font-size:10px; margin-top:14px; }}
    .lab-scene .lab-link {{ position:absolute; top:45px; right:-28px; width:28px; height:3px; background:#304560; }}
    .lab-scene .lab-packets,.lab-scene .lab-write-packets {{ display:block; width:100%; height:3px;
      background:repeating-linear-gradient(90deg,transparent 0 12px,var(--lab-accent) 12px 16px,transparent 16px 24px);
      animation:lab-flow 1.4s linear infinite; }}
    .lab-scene .lab-write-route {{ position:absolute; top:32px; height:56px; border:1px solid #594a7d; border-bottom:none; border-radius:10px 10px 0 0; }}
    .lab-scene .lab-write-packets {{ --lab-accent:#ba9bff; position:absolute; top:-2px; animation-duration:2.2s; }}
    .lab-scene .lab-route-label {{ color:#d5c4ff; font-size:11px; white-space:nowrap; position:absolute;
      top:-14px; left:50%; transform:translateX(-50%); background:#182741; border:1px solid #594a7d; border-radius:16px; padding:7px 15px; }}
    .lab-scene .lab-halo {{ display:block; margin:auto; width:12px; height:12px; border-radius:50%; background:var(--node-ink);
      box-shadow:0 0 0 5px #ffffff0a; animation:lab-breathe 2.8s ease-in-out infinite; animation-delay:var(--delay); }}
    .lab-scene .lab-node {{ position:relative; animation:lab-arrive .65s ease-out both; animation-delay:var(--delay); }}
    .lab-scene .lab-scene-footer {{ padding:14px 28px; border-top:1px solid #26354e; display:flex;
      flex-wrap:wrap; gap:10px 22px; color:#a1b4d0; font:11px system-ui; }}
    .lab-scene .lab-legend::before {{ content:""; display:inline-block; width:7px; height:7px;
      background:var(--lab-accent); border-radius:50%; margin-right:7px; }}
    .lab-scene .lab-legend-write::before {{ background:#ba9bff; }}
    .lab-scene[data-motion="off"] * {{ animation:none !important; }}
    @keyframes lab-flow {{ to {{ background-position:48px 0; }} }}
    @keyframes lab-breathe {{ 50% {{ box-shadow:0 0 0 9px #ffffff14,0 0 18px var(--node-ink); }} }}
    @keyframes lab-arrive {{ from {{ opacity:0; transform:translateY(8px); }} to {{ opacity:1; transform:translateY(0); }} }}
    @media(prefers-reduced-motion: reduce) {{ .lab-scene * {{ animation: none !important; }} }}
    @media(max-width:640px) {{ .lab-scene .lab-scene-top {{ padding:20px 18px 0; }}
      .lab-scene .lab-scene-footer {{ padding:14px 18px; }} .lab-scene .lab-scene-stats {{ gap:20px; }}
      .lab-scene .lab-scroll-hint {{ display:block; }} }}
    </style>
    <section class="lab-scene" data-motion="{'on' if animate else 'off'}" aria-label="Request flow illustration">
      <div class="lab-scene-top"><div><div class="lab-eyebrow">Architecture / request flow</div>
      <h3>{escape(cfg.name)}</h3></div><div class="lab-scene-stats">{stats}</div></div>
      <div class="lab-canvas" tabindex="0" role="region" aria-label="Request paths; scroll horizontally on small screens">
      <div class="lab-track">{write_route}{''.join(artwork)}</div></div>
      <div class="lab-scroll-hint">Swipe or scroll the diagram to explore all tiers →</div>
      <div class="lab-scene-footer"><span class="lab-legend">Read path</span>
      {'' if cfg.app_only else '<span class="lab-legend lab-legend-write">Write path</span>'}
      <span>Illustrative motion · not individual request traces</span></div>
    </section>'''

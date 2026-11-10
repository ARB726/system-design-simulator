"""A shareable PNG score card (1200x630, the LinkedIn / Open Graph size), drawn with Pillow only."""
from __future__ import annotations

import io
import math
from typing import Dict, List, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .themes import THEMES, DEFAULT_THEME

W, H = 1200, 630
_FONT_PATHS = {
    "regular": ["DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "Arial.ttf"],
    "bold": ["DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "Arial Bold.ttf"],
}


def _font(kind: str, size: int):
    for p in _FONT_PATHS[kind]:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)        # Pillow >= 10.1: scalable built-in font
    except TypeError:
        return ImageFont.load_default()


def _hex(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _star(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, fill, outline=None):
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.42
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    draw.polygon(pts, fill=fill, outline=outline)


def make_card(title: str, score: float, stars: int, level_title: str, level: int, tests: str, cost: float,
              optimum_cost: Optional[float], design_lines: List[str], theme: str = DEFAULT_THEME,
              calibration: Optional[float] = None, footer: str = "System Design Simulator") -> bytes:
    t = THEMES.get(theme, THEMES[DEFAULT_THEME])
    a, b = _hex(t["dark"]), _hex(t["second"])
    ys, xs = np.mgrid[0:H, 0:W]
    u = xs / W * 0.7 + ys / H * 0.3                      # soft diagonal glow in the accent colors
    k = np.clip(0.34 - u * 0.34, 0, None)[..., None]
    k2 = np.clip(0.22 - (1 - u) * 0.30, 0, None)[..., None]
    arr = 16 + (np.array(a) - 16) * k + (np.array(b) - 16) * k2
    img = Image.fromarray(arr.astype("uint8"), "RGB")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((40, 40, W - 40, H - 40), radius=28, outline=a, width=3, fill=(16, 18, 24))
    ink, mute = (240, 240, 236), (160, 164, 172)

    d.text((80, 78), footer.upper(), font=_font("bold", 20), fill=a)
    d.text((80, 112), title, font=_font("bold", 40), fill=ink)

    d.text((80, 200), f"{score:.0f}", font=_font("bold", 150), fill=ink)
    d.text((80 + 20 + d.textlength(f"{score:.0f}", font=_font("bold", 150)), 262), "/ 100", font=_font("regular", 40), fill=mute)
    for i in range(3):
        _star(d, 105 + i * 62, 395, 26, a if i < stars else (60, 64, 72))

    d.text((80, 450), f"Level {level} · {level_title}", font=_font("bold", 28), fill=ink)
    eff = f"  ({optimum_cost / cost:.0%} of optimum)" if optimum_cost and cost else ""
    d.text((80, 495), f"Tests passed {tests}", font=_font("regular", 24), fill=mute)
    d.text((80, 530), f"Cost ${cost:,.0f}/mo" + (f" vs optimum ${optimum_cost:,.0f}" if optimum_cost else "") + eff,
           font=_font("regular", 24), fill=mute)

    x0 = 700
    d.text((x0, 210), "MY DESIGN", font=_font("bold", 20), fill=a)
    for i, ln in enumerate(design_lines[:6]):
        d.rounded_rectangle((x0, 248 + i * 46, x0 + 420, 248 + i * 46 + 36), radius=10, fill=(30, 33, 42))
        d.text((x0 + 14, 254 + i * 46), ln, font=_font("regular", 20), fill=ink)
    if calibration is not None:
        d.text((x0, 548), f"Napkin-math calibration {calibration:.0f}/100", font=_font("regular", 20), fill=mute)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def design_lines(design: Dict) -> List[str]:
    out = [f"{design['app_replicas']} app replicas × {design['app_workers']} workers",
           f"Cache {'on' if design['cache'] else 'off'} · CDN {'on' if design['cdn'] else 'off'}",
           f"DB {design['db_workers']} connections per node"]
    if design.get("shards", 1) > 1 or design.get("read_replicas", 0) > 0:
        out.append(f"{design['shards']} shard(s) · {design['read_replicas']} read replica(s)")
    if design.get("queue"):
        out.append(f"Write queue · {design['consumers']} consumers")
    return out

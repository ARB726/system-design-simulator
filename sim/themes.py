"""Visual themes (accent colors layered on Streamlit's own light/dark base) and industry tags."""
from __future__ import annotations

from typing import Dict, List

# name -> (accent on light, accent on dark, second accent for gradients, emoji)
THEMES: Dict[str, dict] = {
    "Ocean":  dict(light="#1c6fd1", dark="#4a9af0", second="#12a3a3", emoji="\U0001F30A"),
    "Forest": dict(light="#1b8a4a", dark="#3cc27a", second="#8aa51d", emoji="\U0001F332"),
    "Sunset": dict(light="#d9531e", dark="#f07a47", second="#d63b7a", emoji="\U0001F305"),
    "Grape":  dict(light="#7a3fd0", dark="#a077f0", second="#d63b9a", emoji="\U0001F347"),
    "Slate":  dict(light="#3d4a5c", dark="#9fb0c8", second="#6b7a90", emoji="\U0001FAA8"),
}
DEFAULT_THEME = "Ocean"

INDUSTRIES: List[str] = ["All", "E-commerce", "Social", "Fintech", "Gaming", "Infrastructure"]
INDUSTRY_EMOJI = {"E-commerce": "\U0001F6D2", "Social": "\U0001F4AC", "Fintech": "\U0001F4B3",
                  "Gaming": "\U0001F3AE", "Infrastructure": "\U0001F527"}

PRESET_INDUSTRY = {
    "Read-heavy: URL shortener": "Social",
    "Write-heavy: chat messages": "Social",
    "Async writes: absorb a burst": "E-commerce",
    "Sharding: the hot key": "Fintech",
    "Failure: cache goes cold": "E-commerce",
    "Failure: lose app replicas": "Gaming",
    "Gaming: launch-day leaderboard": "Gaming",
    "Lab: load balancing strategy": "Infrastructure",
    "Blank canvas": "Infrastructure",
}


def accent(name: str, dark: bool) -> str:
    t = THEMES.get(name, THEMES[DEFAULT_THEME])
    return t["dark" if dark else "light"]


def tag(industry: str) -> str:
    return f"{INDUSTRY_EMOJI.get(industry, '')} {industry}".strip()


def _rgba(hex_: str, a: float) -> str:
    h = hex_.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{a})"


def theme_css(name: str, dark: bool) -> str:
    """CSS that recolors accents (buttons, tabs, metrics, progress bars, headings, page tint)."""
    t = THEMES.get(name, THEMES[DEFAULT_THEME])
    a = t["dark" if dark else "light"]
    b = t["second"]
    tint_a, tint_b = (0.16, 0.10) if dark else (0.10, 0.07)
    return f"""
    <style>
      .stApp {{ background-image: radial-gradient(1100px 380px at 8% -6%, {_rgba(a, tint_a)}, transparent 70%),
                                   radial-gradient(900px 340px at 100% 0%, {_rgba(b, tint_b)}, transparent 70%);
                background-attachment: fixed; }}
      h1 {{ background: linear-gradient(90deg, {a}, {b}); -webkit-background-clip: text; background-clip: text;
            color: transparent !important; width: fit-content; }}
      [data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {{
            background-color: {a}; border-color: {a}; color: #fff; }}
      [data-testid="stBaseButton-primary"]:hover, [data-testid="stBaseButton-primaryFormSubmit"]:hover {{
            filter: brightness(1.1); background-color: {a}; border-color: {a}; color: #fff; }}
      [data-testid="stMetric"] {{ border-top: 3px solid {a}; background: {_rgba(a, 0.05)}; }}
      button[data-baseweb="tab"][aria-selected="true"] {{ color: {a}; }}
      [data-baseweb="tab-highlight"] {{ background-color: {a} !important; }}
      [data-testid="stProgressBarTrack"] > div {{ background-color: {a} !important; }}
      [data-testid="stSlider"] [role="slider"] {{ background-color: {a} !important; }}
      [data-testid="stSliderThumbValue"] {{ color: {a} !important; }}
      [data-testid="stSidebar"] {{ border-right: 1px solid {_rgba(a, 0.25)}; }}
      .card {{ border: 1px solid rgba(137,135,129,.30); border-radius: 14px; padding: 14px 16px; height: 100%;
               background: {_rgba(a, 0.04)}; }}
      .card.locked {{ opacity: .55; }}
      .card.current {{ border: 2px solid {a}; }}
      .card .stars {{ color: {a}; font-size: 1.25rem; letter-spacing: 2px; }}
      .card .meta {{ opacity: .7; font-size: .85rem; }}
      .chip {{ display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: .78rem;
               border: 1px solid {_rgba(a, 0.5)}; background: {_rgba(a, 0.10)}; margin-right: 6px; }}
      .badge {{ display: inline-block; padding: 4px 12px; border-radius: 999px; font-size: .85rem; margin: 3px 6px 3px 0;
                border: 1px solid {_rgba(a, 0.6)}; background: {_rgba(a, 0.12)}; }}
      .badge.off {{ opacity: .4; border-style: dashed; background: transparent; }}
    </style>
    """

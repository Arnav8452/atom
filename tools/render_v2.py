#!/usr/bin/env python3
"""Programmatic pixel-art renderer for the `v2` ("Atom V2" — Pom-Pom Squishy Blob) skin.

Reproduces art/V2.png ("Version 2: The Pom-Pom Squishy Blob") on native 150x120
32-bit ARGB surfaces using crisp 2x2 coarse pixels (`U = 2`), paired with Atom's
5 Gemini orbital electrons & horizontal loading-wave bar:
- Plump, round sky-cyan squishy blob with fat rounded stubby arms & two stubby legs
  (body blues strictly inside h in [197..207] deg so runtime mood tinting works).
- Rainbow-striped ribbed beanie + cyan/mint/yellow top pom-pom bobble
  (beanie hues kept outside h in [196..226] deg so runtime mood tinting preserves it).
- Signature art/V2.png panels:
  * IDLE: Hero View squishy blob + blinking + 5 orbiting Gemini pixel electrons
  * TYPING: 3/4 right-facing crouch at slanted dark-outlined silver laptop +
    Atom's 5-dot horizontal Gemini loading wave bar above the pom-pom
  * ANGRY: Bright blue body (never painted red!), fierce \\ / eyes, 4-prong spiky
    pom-pom, warm fiery orange outer aura & segmented heat arcs + spark dots
  * THINKING: Grounded upright legs on shadow while upper torso/beanie tilt -16 deg,
    glancing up-right with bobbing '?' + Atom THINK_TILTS orbital comet trails
  * DANCE: No blush, plump thick outward-up arms, high bouncy hop above shadow,
    alternating kicked legs, ^ ^ eyes, art/V2.png 4-point '+' sparkles + Gemini orbs
- Plus all 14 remaining states & moods aligned with Atom's visual language.

Needs only Python stdlib + python-cairo.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import cairo

import tools.render_gemini_typing as R

FW, FH = 150, 120
FPS = 12
U = 2  # coarse pixel block size (2x2 native px -> 64x64 sprite grid on 32x32 coords)

# Body blues strictly inside [197..212] deg (s > 0.78) for atom_inject.js recolour()
BODY_BRIGHT = (40, 186, 248)   # h=197.8, s=0.84
BODY_MID = (34, 158, 226)      # h=201.3, s=0.85
BODY_SHADE = (30, 134, 200)    # h=203.3, s=0.85
BODY_OUTLINE = (32, 108, 168)  # h=206.5, s=0.81

EYE_BLACK = (6, 8, 14)
EYE_GLINT = (68, 52, 104)

# Atom's exact electron kinematics (5 Gemini blobs, scaled 0.5x from 640x360 to 150x120)
IDLE_REV = (+1, -1, +1, -1, +1)
THINK_REV = (+1, -1, +1, -1, +1)
THINK_TILTS = (-34.0, +38.0, -18.0, +44.0, -42.0)
ATOM_WAVE_X = (47.0, 61.0, 75.0, 89.0, 103.0)

# Rainbow column palette (cols 4..27) — every hue strictly outside [196..226] deg
BEANIE_COLS: Dict[int, Tuple[int, int, int]] = {
    4: (166, 124, 222),
    5: (168, 126, 226),
    6: (174, 131, 229),
    7: (247, 142, 227),
    8: (249, 141, 226),
    9: (178, 134, 235),
    10: (146, 148, 251),  # h=238.7
    11: (72, 222, 234),   # h=184.4 (outside 196..226!)
    12: (62, 224, 236),   # h=184.1 (outside 196..226!)
    13: (84, 240, 154),   # mint
    14: (155, 238, 128),  # lime
    15: (157, 238, 128),
    16: (251, 229, 104),  # yellow
    17: (252, 228, 104),
    18: (252, 227, 103),
    19: (254, 183, 98),   # gold
    20: (254, 150, 88),   # orange
    21: (253, 148, 86),
    22: (254, 118, 148),  # coral pink
    23: (254, 116, 148),
    24: (254, 116, 149),
    25: (232, 119, 166),
    26: (224, 120, 172),
    27: (218, 120, 176),
}

# Symmetric 32-wide torso mask (rows 13..29, mirror axis between cols 15 & 16).
_TORSO_ROWS: Dict[int, str] = {
    13: ".....ddddddddddddddddddddd......",
    14: ".....ddbbBBBBBBBBBBBBBBbbdd.....",
    15: ".....dbBBBBBBBBBBBBBBBBBBbd.....",
    16: "....dbbBBBBBBBBBBBBBBBBBBbbd....",
    17: "....dbBBBBBBBBBBBBBBBBBBBBbd....",
    18: "....dbBBBBBBBBBBBBBBBBBBBBbd....",
    19: "....dBBBBBBBBBBBBBBBBBBBBBBd....",
    20: "....dBBBBBBBBBBBBBBBBBBBBBBd....",
    21: "....dBBBBBBBBBBBBBBBBBBBBBBd....",
    22: "....dBBBBBBBBBBBBBBBBBBBBBBd....",
    23: "....dbBBBBBBBBBBBBBBBBBBBBbd....",
    24: "....dbbBBBBBBBBBBBBBBBBBBbbd....",
    25: ".....dbbbbBBBBBBBBBBBBbbbbd.....",
    26: ".....dbbbbbBBBBBBBBBBbbbbbd.....",
    27: "......dbbbbbbbbbbbbbbbbbbd......",
    28: ".......dbbbbSSSSSSSSbbbbd.......",
    29: "........dbbddddddddddbbd........",
}
_TORSO_ROWS[13] = "....." + ("d" * 22) + "....."


def _rgb(r: int, g: int, b: int) -> Tuple[float, float, float]:
    return (r / 255.0, g / 255.0, b / 255.0)


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if v < lo else hi if v > hi else v


def _smoothstep(t: float) -> float:
    t = _clamp(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _lerp(a: float, b: float, u: float) -> float:
    return a + (b - a) * u


def _phase_3(f: int, n_in: int, n_loop: int, n_out: int) -> Tuple[str, float]:
    if f < n_in:
        return "in", _smoothstep((f + 1) / max(1, n_in))
    if f < n_in + n_loop:
        return "loop", (f - n_in) / max(1, n_loop)
    out_i = f - n_in - n_loop
    return "out", 1.0 - _smoothstep((out_i + 1) / max(1, n_out))


def _rgb_to_hsv(r: int, g: int, b: int) -> Tuple[float, float, float]:
    mx, mn = max(r, g, b), min(r, g, b)
    d = mx - mn
    h = 0.0
    if d:
        if mx == r:
            h = ((g - b) / d) % 6.0
        elif mx == g:
            h = (b - r) / d + 2.0
        else:
            h = (r - g) / d + 4.0
        h *= 60.0
        if h < 0.0:
            h += 360.0
    return h, (d / mx if mx else 0.0), mx / 255.0


def _hsv_to_rgb(h: float, s: float, v: float) -> Tuple[int, int, int]:
    c = v * s
    x = c * (1.0 - abs(((h / 60.0) % 2.0) - 1.0))
    m = v - c
    if h < 60:
        rr, gg, bb = c, x, 0.0
    elif h < 120:
        rr, gg, bb = x, c, 0.0
    elif h < 180:
        rr, gg, bb = 0.0, c, x
    elif h < 240:
        rr, gg, bb = 0.0, x, c
    elif h < 300:
        rr, gg, bb = x, 0.0, c
    else:
        rr, gg, bb = c, 0.0, x
    return (
        max(0, min(255, round((rr + m) * 255))),
        max(0, min(255, round((gg + m) * 255))),
        max(0, min(255, round((bb + m) * 255))),
    )


def _tint_rgb(rgb: Tuple[int, int, int], mood: Optional[str], amount: float = 1.0) -> Tuple[int, int, int]:
    if not mood or amount <= 0.0:
        return rgb
    h, s, v = _rgb_to_hsv(*rgb)
    if not (196.0 <= h <= 226.0 and s > 0.35):
        return rgb
    if mood == "sad":
        th, ts, tv = 215.0, s * 0.42, v * 0.78
    elif mood == "tired":
        th, ts, tv = 216.0, s * 0.52, v * 0.68
    elif mood == "closed":
        th, ts, tv = 220.0, s * 0.48, v * 0.48
    elif mood == "canceled":
        th, ts, tv = 212.0, s * 0.56, v * 0.84
    elif mood == "error":
        th, ts, tv = 12.0, min(1.0, s * 1.04), min(1.0, v * 0.96)
    elif mood == "happy":
        th, ts, tv = 192.0, min(1.0, s * 1.04), min(1.0, v * 1.06)
    else:
        return rgb
    nh = h + (((th - h + 540.0) % 360.0) - 180.0) * amount
    nh %= 360.0
    return _hsv_to_rgb(nh, _lerp(s, ts, amount), _lerp(v, tv, amount))


def _arm_cells(mode: str, side: str) -> List[Tuple[int, int, str]]:
    """Fat, rounded pixel stubby arms with zero pointy needle tips."""
    if mode == "rest":
        pts = [
            (3, 20, "d"), (2, 21, "d"), (3, 21, "B"),
            (1, 22, "d"), (2, 22, "B"), (3, 22, "B"),
            (1, 23, "d"), (2, 23, "b"), (3, 23, "b"),
            (2, 24, "d"), (3, 24, "d"),
        ]
    elif mode == "raise":
        # Plump rounded nub sticking outward & slightly upward (zero pointy needles)
        pts = [
            (2, 18, "d"), (3, 18, "d"),
            (1, 19, "d"), (2, 19, "B"), (3, 19, "B"), (4, 19, "d"),
            (1, 20, "d"), (2, 20, "B"), (3, 20, "B"), (4, 20, "b"),
            (2, 21, "d"), (3, 21, "b"), (4, 21, "d"),
        ]
    elif mode == "wave":
        # Joyful plump arm waved higher up (thick rounded 3x3 nub like art/V2.png DANCE)
        pts = [
            (1, 16, "d"), (2, 16, "d"),
            (0, 17, "d"), (1, 17, "B"), (2, 17, "B"), (3, 17, "d"),
            (0, 18, "d"), (1, 18, "B"), (2, 18, "B"), (3, 18, "b"),
            (1, 19, "d"), (2, 19, "d"), (3, 19, "b"), (4, 19, "d"),
        ]
    elif mode == "tense":
        # Compact flexed out-turned plump arm for ANGRY / ERROR
        pts = [
            (2, 20, "d"), (3, 20, "d"),
            (1, 21, "d"), (2, 21, "B"), (3, 21, "B"),
            (1, 22, "d"), (2, 22, "B"), (3, 22, "b"),
            (2, 23, "d"), (3, 23, "d"),
        ]
    elif mode == "droop":
        pts = [
            (3, 21, "d"), (2, 22, "d"), (3, 22, "B"),
            (2, 23, "d"), (3, 23, "b"), (3, 24, "d"), (4, 24, "d"),
        ]
    elif mode == "none":
        pts = []
    else:  # "reach_r" (arm extending right onto laptop keyboard in typing)
        pts = []
    return pts if side == "l" else [(31 - col, row, ch) for col, row, ch in pts]


def _build_v2_cells(
    *,
    arm_l: str = "rest",
    arm_r: str = "rest",
    leg_l: str = "stand",
    leg_r: str = "stand",
    include_legs: bool = True,
    pom: str = "normal",
    eyes: str = "open",
    typing_pose: bool = False,
    typing_tap: bool = False,
    mood_tint: Optional[str] = None,
    mood_amt: float = 1.0,
    squash: int = 0,
    beanie_shimmer_u: Optional[float] = None,
    include_headgear: bool = True,
) -> Dict[Tuple[int, int], Tuple[int, int, int]]:
    """Construct the 32x32 coarse pixel dictionary for Atom V2."""
    g: Dict[Tuple[int, int], Tuple[int, int, int]] = {}
    body_map = {"B": BODY_BRIGHT, "b": BODY_MID, "S": BODY_SHADE, "d": BODY_OUTLINE}

    # 1. Torso rows 13..29
    for row, line in _TORSO_ROWS.items():
        y = row + squash if row < 25 else row
        for col, ch in enumerate(line):
            if ch in body_map:
                g[(col, y)] = body_map[ch]

    # 2. Stubby legs (rows 30..31) — support "half" retract mid-transition or omit when fully tucked
    if include_legs:
        def _draw_leg(cols: Tuple[int, int, int, int], mode: str) -> None:
            c0, c1, c2, c3 = cols
            if mode == "tuck":
                return
            if mode == "half":
                for c in (c0, c1, c2, c3):
                    g[(c, 30)] = BODY_OUTLINE
                return
            dy = -1 if mode in ("kick", "hop", "kick_out") else 0
            dx = -1 if (mode == "kick_out" and c0 < 15) else (1 if (mode == "kick_out" and c0 > 15) else 0)
            g[(c0 + dx, 30 + dy)] = BODY_OUTLINE
            g[(c1 + dx, 30 + dy)] = BODY_MID
            g[(c2 + dx, 30 + dy)] = BODY_MID
            g[(c3 + dx, 30 + dy)] = BODY_OUTLINE
            g[(c1 + dx, 31 + dy)] = BODY_OUTLINE
            g[(c2 + dx, 31 + dy)] = BODY_OUTLINE

        _draw_leg((10, 11, 12, 13), leg_l)
        _draw_leg((18, 19, 20, 21), leg_r)

    # 3. Plump rounded side arms
    if typing_pose:
        for col, row, ch in _arm_cells("droop", "l"):
            g[(col, row + (squash if row < 25 else 0))] = body_map[ch]
        # Cute front arm reaching right onto the laptop keyboard
        ty = 20 + squash + (0 if typing_tap else 1)
        for c in (21, 22, 23, 24, 25):
            g[(c, ty)] = BODY_OUTLINE
            g[(c, ty + 1)] = BODY_BRIGHT
            g[(c, ty + 2)] = BODY_MID
            g[(c, ty + 3)] = BODY_OUTLINE
        g[(20, ty + 1)] = BODY_OUTLINE
        g[(20, ty + 2)] = BODY_OUTLINE
        g[(26, ty + 1)] = BODY_OUTLINE
        g[(26, ty + 2)] = BODY_OUTLINE
    else:
        for col, row, ch in _arm_cells(arm_l, "l") + _arm_cells(arm_r, "r"):
            g[(col, row + (squash if row < 25 else 0))] = body_map[ch]

    # 4. Rainbow Striped Beanie Dome (rows 5..7), Seam (8), Ribbed Cuff (9..12)
    if include_headgear:
        by = squash
        beanie_spans = {
            4: (11, 20, "outline"),
            5: (9, 22, "dome"),
            6: (8, 23, "dome"),
            7: (7, 24, "dome"),
            8: (6, 25, "seam"),
            9: (6, 25, "cuff"),
            10: (5, 26, "cuff"),
            11: (4, 27, "cuff"),
            12: (4, 27, "cuff_bot"),
        }
        for row, (c0, c1, kind) in beanie_spans.items():
            yr = row + by
            for c in range(c0, c1 + 1):
                is_edge = (c == c0 or c == c1)
                if kind == "outline":
                    g[(c, yr)] = BODY_OUTLINE
                elif kind == "dome":
                    if is_edge or (row == 5 and c in (c0 + 1, c1 - 1)):
                        g[(c, yr)] = BODY_OUTLINE
                    else:
                        g[(c, yr)] = BEANIE_COLS.get(c, (251, 229, 104))
                elif kind == "seam":
                    g[(c, yr)] = BEANIE_COLS.get(c, BODY_OUTLINE) if c in (c0 + 1, c1 - 1) else BODY_OUTLINE
                elif kind == "cuff":
                    outer2 = (row == 10 and (c == c0 + 1 or c == c1 - 1))
                    g[(c, yr)] = BODY_OUTLINE if (is_edge or outer2) else BEANIE_COLS.get(c, (251, 229, 104))
                elif kind == "cuff_bot":
                    if c <= c0 + 3 or c >= c1 - 3:
                        g[(c, yr)] = BODY_OUTLINE if (is_edge or c in (c0 + 3, c1 - 3)) else BEANIE_COLS.get(c, BODY_OUTLINE)
                    else:
                        g[(c, yr)] = BODY_OUTLINE

        # 5. Top Pom-Pom Bobble
        pom_cyan = (62, 224, 236)   # h=184.1 deg (outside [196..226])
        pom_mint = (94, 240, 162)
        pom_yel = (252, 228, 108)
        if pom == "normal":
            for c in (14, 15, 16, 17):
                g[(c, 0 + by)] = BODY_OUTLINE
            for r, row_cols in ((1, (pom_cyan, pom_mint, pom_mint, pom_yel)),
                                (2, (pom_cyan, pom_mint, pom_mint, pom_cyan)),
                                (3, (pom_cyan, pom_cyan, pom_cyan, pom_cyan))):
                g[(13, r + by)] = BODY_OUTLINE
                for k, col in enumerate(row_cols):
                    g[(14 + k, r + by)] = col
                g[(18, r + by)] = BODY_OUTLINE
        elif pom == "spiky":
            # Tall 4-prong bristling static pom-pom matching art/V2.png ANGRY panel
            prongs = [
                (11, -1, BODY_OUTLINE), (11, 0, pom_cyan), (12, 0, pom_cyan), (12, 1, pom_cyan),
                (14, -2, BODY_OUTLINE), (14, -1, pom_cyan), (14, 0, pom_mint), (14, 1, pom_mint),
                (16, -2, BODY_OUTLINE), (16, -1, pom_mint), (16, 0, pom_yel), (16, 1, pom_yel),
                (19, -1, BODY_OUTLINE), (19, 0, pom_yel), (18, 0, pom_cyan), (18, 1, pom_cyan),
                (13, 1, pom_cyan), (15, 1, pom_mint), (17, 1, pom_yel),
                (12, 2, BODY_OUTLINE), (13, 2, pom_cyan), (14, 2, pom_mint), (15, 2, pom_mint),
                (16, 2, pom_cyan), (17, 2, pom_cyan), (18, 2, BODY_OUTLINE),
                (13, 3, BODY_OUTLINE), (14, 3, pom_cyan), (15, 3, pom_cyan),
                (16, 3, pom_cyan), (17, 3, pom_cyan), (18, 3, BODY_OUTLINE),
            ]
            for sc, sr, srgb in prongs:
                g[(sc, sr + by)] = srgb
        elif pom == "droop":
            for c in (12, 13, 14, 15):
                g[(c, 1 + by)] = BODY_OUTLINE
            for sr in (2, 3):
                g[(11, sr + by)] = BODY_OUTLINE
                g[(12, sr + by)] = pom_cyan
                g[(13, sr + by)] = pom_mint if sr == 2 else pom_cyan
                g[(14, sr + by)] = BODY_OUTLINE

        if beanie_shimmer_u is not None:
            edge = _smoothstep(beanie_shimmer_u / 0.12) * _smoothstep((1.0 - beanie_shimmer_u) / 0.12)
            if edge > 0.0:
                wave_pos = -0.25 + 1.5 * beanie_shimmer_u
                for (c, yr), val in list(g.items()):
                    if 5 <= yr <= 11 and c in BEANIE_COLS and val == BEANIE_COLS[c]:
                        x_norm = (c - 4) / 23.0
                        sh = math.exp(-((x_norm - wave_pos) / 0.16) ** 2) * edge
                        if sh > 0.01:
                            g[(c, yr)] = tuple(min(255, round(v0 + (255 - v0) * 0.48 * sh)) for v0 in val)

    # Apply optional mood tint BEFORE dark eyes so eyes stay crisp jet-black
    if mood_tint:
        for k, val in list(g.items()):
            g[k] = _tint_rgb(val, mood_tint, mood_amt)

    # 6. Eyes
    ey = 15 + squash
    if typing_pose:
        # 3/4 right-facing eyes matching art/V2.png TYPING panel
        # Left eye (shifted right to cols 13..15, rows 15..17)
        for dr in range(3):
            for dc in range(3):
                rgb_e = EYE_GLINT if (dr == 0 and dc == 2) or (dr == 2 and dc == 0) else EYE_BLACK
                g[(13 + dc, ey + dr)] = rgb_e
        # Right eye foreshortened (2 cols at 21..22, 3 rows 14..16)
        for dr in range(3):
            for dc in range(2):
                rgb_e = EYE_GLINT if (dr == 2 and dc == 0) else EYE_BLACK
                g[(21 + dc, ey - 1 + dr)] = rgb_e
    elif eyes in ("open", "look_ur", "look_ul", "look_r", "look_l", "look_d"):
        ox_e = 1 if eyes in ("look_ur", "look_r") else (-1 if eyes in ("look_ul", "look_l") else 0)
        oy_e = -1 if eyes in ("look_ur", "look_ul") else (1 if eyes == "look_d" else 0)
        for base_c in (10 + ox_e, 19 + ox_e):
            for dr in range(3):
                for dc in range(3):
                    rgb_e = EYE_GLINT if ((dr == 0 and dc == 2) or (dr == 2 and dc == 0)) else EYE_BLACK
                    g[(base_c + dc, ey + oy_e + dr)] = rgb_e
    elif eyes == "blink":
        for base_c in (10, 19):
            for dc in range(3):
                g[(base_c + dc, ey + 1)] = EYE_BLACK
    elif eyes == "sleep":
        for base_c in (10, 19):
            g[(base_c, ey + 1)] = EYE_BLACK
            g[(base_c + 1, ey + 2)] = EYE_BLACK
            g[(base_c + 2, ey + 1)] = EYE_BLACK
    elif eyes == "tired":
        for base_c in (10, 19):
            for dc in range(3):
                g[(base_c + dc, ey + 1)] = EYE_BLACK
                g[(base_c + dc, ey + 2)] = EYE_BLACK
    elif eyes == "happy":
        # Exact 3-cell ^ ^ chevrons matching art/V2.png DANCE panel
        for base_c in (10, 19):
            g[(base_c, ey + 2)] = EYE_BLACK
            g[(base_c + 1, ey + 1)] = EYE_BLACK
            g[(base_c + 2, ey + 2)] = EYE_BLACK
    elif eyes == "angry":
        # Fierce \ / angry eyes matching art/V2.png ANGRY panel (upper inner bevel cut cleanly)
        # Left eye (10..12): outer col full height, mid & inner cols lower 2 rows + violet outer corner
        g[(10, ey)] = EYE_BLACK
        g[(10, ey + 1)] = EYE_BLACK
        g[(10, ey + 2)] = EYE_GLINT
        g[(11, ey + 1)] = EYE_BLACK
        g[(11, ey + 2)] = EYE_BLACK
        g[(12, ey + 1)] = EYE_BLACK
        g[(12, ey + 2)] = EYE_BLACK
        # Right eye (19..21): mirror
        g[(21, ey)] = EYE_BLACK
        g[(21, ey + 1)] = EYE_BLACK
        g[(21, ey + 2)] = EYE_GLINT
        g[(20, ey + 1)] = EYE_BLACK
        g[(20, ey + 2)] = EYE_BLACK
        g[(19, ey + 1)] = EYE_BLACK
        g[(19, ey + 2)] = EYE_BLACK
    elif eyes == "sad":
        # Slanted / \ puppy eyes
        g[(10, ey + 1)] = EYE_BLACK
        g[(10, ey + 2)] = EYE_BLACK
        g[(11, ey + 1)] = EYE_BLACK
        g[(11, ey + 2)] = EYE_BLACK
        g[(12, ey)] = EYE_BLACK
        g[(12, ey + 1)] = EYE_BLACK
        g[(19, ey)] = EYE_BLACK
        g[(19, ey + 1)] = EYE_BLACK
        g[(20, ey + 1)] = EYE_BLACK
        g[(20, ey + 2)] = EYE_BLACK
        g[(21, ey + 1)] = EYE_BLACK
        g[(21, ey + 2)] = EYE_BLACK
    elif eyes == "error":
        # Crisp 3x3 X X eyes matching ATOM ERROR
        for base_c in (10, 19):
            g[(base_c, ey)] = EYE_BLACK
            g[(base_c + 2, ey)] = EYE_BLACK
            g[(base_c + 1, ey + 1)] = EYE_BLACK
            g[(base_c, ey + 2)] = EYE_BLACK
            g[(base_c + 2, ey + 2)] = EYE_BLACK
    elif eyes == "wide":
        # Surprised hollow square eyes matching ATOM CANCELED
        for base_c in (10, 19):
            for dr in range(3):
                for dc in range(3):
                    if dr != 1 or dc != 1:
                        g[(base_c + dc, ey + dr)] = EYE_BLACK

    return g


def _paint_sprite(
    ctx: cairo.Context,
    cells: Dict[Tuple[int, int], Tuple[int, int, int]],
    *,
    cx: float = 75.0,
    foot_y: float = 107.0,
    tilt_deg: float = 0.0,
    shadow: bool = True,
    shadow_y: Optional[float] = None,
    shadow_alpha: float = 0.28,
    alpha: float = 1.0,
    fixed_legs: bool = False,
) -> None:
    """Paint crisp U=2 pixel grid onto cairo Context.

    If `fixed_legs=True` with `tilt_deg != 0`, draws the two stubby legs + ground
    shadow flat on `shadow_y` while tilting only the upper squishy blob body/beanie!
    """
    ox = cx - 16.0 * U
    oy = foot_y - 32.0 * U
    sy = foot_y if shadow_y is None else shadow_y

    if shadow:
        ctx.save()
        ctx.set_source_rgba(0.03, 0.04, 0.08, shadow_alpha * alpha)
        ctx.rectangle(round(ox + 9 * U), round(sy), 14 * U, 2)
        ctx.fill()
        ctx.rectangle(round(ox + 11 * U), round(sy + 2), 10 * U, 1)
        ctx.fill()
        ctx.restore()

    if fixed_legs:
        for leg_cols in ((10, 11, 12, 13), (18, 19, 20, 21)):
            c0, c1, c2, c3 = leg_cols
            leg_pts = (
                (c0, 30, BODY_OUTLINE), (c1, 30, BODY_MID), (c2, 30, BODY_MID), (c3, 30, BODY_OUTLINE),
                (c1, 31, BODY_OUTLINE), (c2, 31, BODY_OUTLINE),
            )
            for lc, lr, (r, gg, b) in leg_pts:
                ctx.set_source_rgba(r / 255.0, gg / 255.0, b / 255.0, alpha)
                ctx.rectangle(round(ox + lc * U), round(oy + lr * U), U, U)
                ctx.fill()

    ctx.save()
    if abs(tilt_deg) > 0.05:
        piv_x = round(cx)
        piv_y = round(foot_y - 4 * U) if fixed_legs else round(foot_y - 12 * U)
        ctx.translate(piv_x, piv_y)
        ctx.rotate(math.radians(tilt_deg))
        ctx.translate(-piv_x, -piv_y)
        tmp = cairo.ImageSurface(cairo.FORMAT_ARGB32, FW, FH)
        tctx = cairo.Context(tmp)
        for (col, row), (r, gg, b) in cells.items():
            tctx.set_source_rgba(r / 255.0, gg / 255.0, b / 255.0, alpha)
            tctx.rectangle(round(ox + col * U), round(oy + row * U), U, U)
            tctx.fill()
        ctx.set_source_surface(tmp, 0, 0)
        ctx.get_source().set_filter(cairo.FILTER_NEAREST)
        ctx.paint()
    else:
        for (col, row), (r, gg, b) in cells.items():
            ctx.set_source_rgba(r / 255.0, gg / 255.0, b / 255.0, alpha)
            ctx.rectangle(round(ox + col * U), round(oy + row * U), U, U)
            ctx.fill()
    ctx.restore()


# ---------------------------------------------------------------------------
# Atom's Exact Electron & Trail Primitives (scaled 0.5x onto 150x120)
# ---------------------------------------------------------------------------

def _orbit_point(ax: float, ay: float, rx: float, ry: float, tilt_deg: float, theta: float) -> Tuple[float, float, float]:
    lx = rx * math.cos(theta)
    ly = ry * math.sin(theta)
    ez = math.sin(theta)
    tilt = math.radians(tilt_deg)
    ct, st = math.cos(tilt), math.sin(tilt)
    return ax + lx * ct - ly * st, ay + lx * st + ly * ct, ez


def _size_from_ez(ez: float) -> int:
    if ez < -0.25:
        return 0
    if ez < 0.15:
        return 1
    if ez < 0.55:
        return 2
    return 3


def _draw_atom_blob(
    ctx: cairo.Context,
    x: float,
    y: float,
    size_idx: int,
    color: Tuple[float, float, float],
    alpha: float = 1.0,
    glow: bool = False,
) -> None:
    """Draw rounded pixelated Gemini electron blob matching Atom's R.draw_pixel_blob (0.5x scale)."""
    if alpha <= 0.02:
        return
    cx, cy = round(x), round(y)
    r, g, b = color
    ctx.save()
    ctx.set_antialias(cairo.ANTIALIAS_NONE)
    if glow:
        rad = 2.6 + size_idx * 1.4
        ctx.set_source_rgba(r, g, b, 0.14 * alpha)
        ctx.arc(cx + 0.5, cy + 0.5, rad + 1.5, 0, 2.0 * math.pi)
        ctx.fill()
        ctx.set_source_rgba(r, g, b, 0.24 * alpha)
        ctx.arc(cx + 0.5, cy + 0.5, rad, 0, 2.0 * math.pi)
        ctx.fill()
    ctx.set_source_rgba(r, g, b, alpha)
    if size_idx <= 0:
        ctx.rectangle(cx - 1, cy - 1, 3, 3)
        ctx.fill()
    elif size_idx == 1:
        ctx.rectangle(cx - 1, cy - 2, 3, 5)
        ctx.rectangle(cx - 2, cy - 1, 5, 3)
        ctx.fill()
    elif size_idx == 2:
        ctx.rectangle(cx - 1, cy - 3, 3, 7)
        ctx.rectangle(cx - 2, cy - 2, 5, 5)
        ctx.rectangle(cx - 3, cy - 1, 7, 3)
        ctx.fill()
    else:
        ctx.rectangle(cx - 1, cy - 4, 3, 9)
        ctx.rectangle(cx - 3, cy - 3, 7, 7)
        ctx.rectangle(cx - 4, cy - 1, 9, 3)
        ctx.fill()
    ctx.restore()


def _draw_trail_sq(
    ctx: cairo.Context, x: float, y: float, size_px: int, color: Tuple[float, float, float], alpha: float = 1.0
) -> None:
    if alpha <= 0.02 or size_px <= 0:
        return
    half = size_px // 2
    ctx.save()
    ctx.set_antialias(cairo.ANTIALIAS_NONE)
    ctx.set_source_rgba(color[0], color[1], color[2], alpha)
    ctx.rectangle(round(x) - half, round(y) - half, size_px, size_px)
    ctx.fill()
    ctx.restore()


def _hover_orbits(
    phase: float,
    *,
    ax: float = 75.0,
    ay: float = 78.0,
    rev: Sequence[int] = IDLE_REV,
    rx_scale: float = 1.0,
    ry_scale: float = 1.0,
    max_size: int = 3,
    trail_steps: Sequence[Tuple[float, int]] = ((0.04, 2),),
) -> Tuple[List[Tuple[float, int, float, float, int]], List[Tuple[float, int, float, float, int]]]:
    blobs, trails = [], []
    for k, sp in enumerate(R.ELECTRONS):
        th = sp.phi0 + rev[k] * 2.0 * math.pi * phase
        px, py, ez = _orbit_point(ax, ay, sp.rx * 0.5 * rx_scale, sp.ry * 0.5 * ry_scale, sp.tilt_deg, th)
        blobs.append((ez, k, px, py, min(max_size, _size_from_ez(ez))))
        for lag_u, sz in trail_steps:
            tlag = th - rev[k] * 2.0 * math.pi * lag_u
            tx, ty, tez = _orbit_point(ax, ay, sp.rx * 0.5 * rx_scale, sp.ry * 0.5 * ry_scale, sp.tilt_deg, tlag)
            trails.append((tez, k, tx, ty, sz))
    blobs.sort(key=lambda item: item[0])
    trails.sort(key=lambda item: item[0])
    return blobs, trails


def _render_orbit_layer(
    ctx: cairo.Context,
    blobs: Sequence[Tuple[float, int, float, float, int]],
    trails: Sequence[Tuple[float, int, float, float, int]],
    *,
    front: bool,
    palette: Optional[Sequence[Tuple[float, float, float]]] = None,
    alpha: float = 1.0,
    glow: bool = False,
) -> None:
    pal = palette if palette is not None else [sp.color for sp in R.ELECTRONS]
    for pz, k, px, py, sz in trails:
        if (pz >= 0.0) == front:
            _draw_trail_sq(ctx, px, py, sz, pal[k], alpha=alpha)
    for pz, k, px, py, sidx in blobs:
        if (pz >= 0.0) == front:
            _draw_atom_blob(ctx, px, py, sidx, pal[k], alpha=alpha, glow=glow)


# ---------------------------------------------------------------------------
# Props & Expressions (matched to art/V2.png & Atom states)
# ---------------------------------------------------------------------------

def _draw_plus_sparkle(ctx: cairo.Context, x: float, y: float, rgb: Tuple[int, int, int], alpha: float = 1.0, hollow: bool = False) -> None:
    """Crisp 4-point `+` sparkle matching art/V2.png DANCE panel."""
    if alpha <= 0.02:
        return
    r, g, b = _rgb(*rgb)
    ix, iy = round(x), round(y)
    ctx.save()
    ctx.set_antialias(cairo.ANTIALIAS_NONE)
    if not hollow:
        ctx.set_source_rgba(r, g, b, alpha)
        ctx.rectangle(ix - 2, iy, 6, 2)
        ctx.rectangle(ix, iy - 2, 2, 6)
        ctx.fill()
    else:
        ctx.set_source_rgba(r, g, b, alpha)
        ctx.rectangle(ix - 3, iy, 2, 2)
        ctx.rectangle(ix + 3, iy, 2, 2)
        ctx.rectangle(ix, iy - 3, 2, 2)
        ctx.rectangle(ix, iy + 3, 2, 2)
        ctx.fill()
    ctx.restore()


def _draw_pixel_glyph(ctx: cairo.Context, rows: Sequence[str], x: float, y: float, px: int, rgb: Tuple[int, int, int], alpha: float = 1.0) -> None:
    if alpha <= 0.02:
        return
    r, g, b = _rgb(*rgb)
    ix, iy = round(x), round(y)
    ctx.save()
    ctx.set_antialias(cairo.ANTIALIAS_NONE)
    ctx.set_source_rgba(r, g, b, alpha)
    for ry, line in enumerate(rows):
        for rx, ch in enumerate(line):
            if ch != ".":
                ctx.rectangle(ix + rx * px, iy + ry * px, px, px)
                ctx.fill()
    ctx.restore()


def _draw_pixel_gear(ctx: cairo.Context, cx: int, cy: int, radius: int, angle: float, color: Tuple[float, float, float], alpha: float = 1.0) -> None:
    if alpha <= 0.05:
        return
    ctx.save()
    ctx.set_antialias(cairo.ANTIALIAS_NONE)
    ctx.set_source_rgba(color[0], color[1], color[2], alpha)
    r_inner = max(2.2, radius - 1.8)
    for dy in range(-radius - 2, radius + 3):
        for dx in range(-radius - 2, radius + 3):
            dist = math.hypot(dx, dy)
            if dist <= 1.6:
                continue
            theta = math.atan2(dy, dx) - angle
            tooth = math.cos(8.0 * theta) > 0.25
            r_lim = (radius + 1.6) if tooth else r_inner
            if dist <= r_lim:
                ctx.rectangle(cx + dx, cy + dy, 2, 2)
                ctx.fill()
    ctx.restore()


def _render(fn: Callable[[cairo.Context, int], None], n: int) -> List[cairo.ImageSurface]:
    out: List[cairo.ImageSurface] = []
    for f in range(n):
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, FW, FH)
        ctx = cairo.Context(surf)
        fn(ctx, f)
        out.append(surf)
    return out


# Exact art/V2.png TYPING sitting pose (36 wide x 30 tall, cols 0..35, rows 0..29):
#   P/V/A/G/Y/O/C = beanie & pom-pom rainbow (all hues strictly outside [196..226])
#   B/b/d = bright/mid/outline blue body (inside [197..207] for mood tinting)
_SITTING_BODY: Tuple[str, ...] = (
    "........dCMYd.......................",  # 00 pom-pom top
    "........dCMMd.......................",  # 01
    "........dCCCd.......................",  # 02
    ".......ddddddd......................",  # 03 beanie crown border
    "......dAAYYYOOPd....................",  # 04 dome
    ".....dPAAAYYYOOPd...................",  # 05
    "....dVPAGGGGYYOOPPd.................",  # 06
    "...dVPVAAGGGGYYOOPPd................",  # 07
    "...dVVVVAAGGGdddddddd...............",  # 08 diagonal seam
    "..ddPPVVGdddddYYYOOPPdd.............",  # 09 upper cuff
    "..dPPPdddAGGGGGGYYOOPPPd............",  # 10 cuff middle
    "..dPddVVVGGGAGGGdddddddPd...........",  # 11 lower cuff edge
    "..ddPPVVVGGGdddddbBBBBdd............",  # 12 left earflap + right forehead
    ".dVVPPVVVdddbbbbBBBBBBBbd...........",  # 13
    ".dVVPPdddbbbBBBBBBBBBBBBbd..........",  # 14
    ".dVVVddbBBBBBBBBBBBBBBBBBd..........",  # 15
    "..dddbbbBBBBBBBBBBBBBBBBBd..........",  # 16
    "..dbbbBBBBBBBBBBBBBBBBBBBd..........",  # 17
    "..dbbbBBBBBBBBBBBBBBBBBBBd..........",  # 18
    "..dbbbBBBBBBBBBBBBBBBBBBBd..........",  # 19
    "..dbbbBBBBBBBBBBBBBBBBBBd...........",  # 20
    "..dbbbBBBBBBBBBBBBBBBBBd............",  # 21
    "..dbbbbBBBBBBBBBBBBBBBBd............",  # 22
    "...dbbbbBBBBBBBBBBBBBBd.............",  # 23
    "...dbbbbBBBBBBdddddd................",  # 24
    "....ddbbbbbdd.......................",  # 25
    ".....dddbbbBbd......................",  # 26 tucked sitting stubby leg
    ".......ddbbBbd......................",  # 27
    ".........ddbbd......................",  # 28
    "..........ddd.......................",  # 29
)

# Exact slanted 3/4 silver pixel laptop from art/V2.png TYPING panel (same grid coords):
#   D = dark charcoal outline/keys, M = silver matte lid/deck, L = light rim, W = white emblem
_SITTING_LAPTOP: Tuple[str, ...] = (
    "....................................",  # 00
    "....................................",  # 01
    "....................................",  # 02
    "....................................",  # 03
    "....................................",  # 04
    "....................................",  # 05
    "....................................",  # 06
    "....................................",  # 07
    "....................................",  # 08
    "....................................",  # 09
    "....................................",  # 10
    "....................................",  # 11
    "....................................",  # 12
    "....................................",  # 13
    "..........................DDDD......",  # 14 top corner bezel
    ".....................DDDDDLLLLD.....",  # 15
    "...................DDLLLLLMMMMD.....",  # 16
    "..................DLMMMMMMMMMMD.....",  # 17
    "..................DLMMMMMMMMMMD.....",  # 18
    "..................DLMMMMMMMMMD......",  # 19
    "..................DLMMMMMMWMMD......",  # 20 cyan-white laptop emblem dot
    "..................DLMMMMMWWMMD......",  # 21
    "..................DLMMMMMMMMMD......",  # 22
    "..........DDDDLLLDLMMMMMMMMMMD......",  # 23 keyboard deck top + lid join
    "..........DMLLMMDLMMMMMMMMMMD.......",  # 24 deck surface under paws
    "..........dDDLMDLMMMMDDDDDDd........",  # 25 deck underside shadow
    "............ddddDDDDD...............",  # 26
)

_SITTING_PALETTE: Dict[str, Tuple[int, int, int]] = {
    "B": BODY_BRIGHT,
    "b": BODY_MID,
    "d": BODY_OUTLINE,
    "C": (62, 224, 236),    # pom-pom aqua (h=184.1)
    "M": (94, 240, 162),    # pom-pom mint
    "V": (174, 131, 229),   # violet
    "P": (249, 141, 226),   # pink
    "A": (72, 222, 234),    # beanie aqua (h=184.4)
    "G": (118, 239, 140),   # green
    "Y": (252, 228, 104),   # yellow
    "O": (254, 150, 88),    # orange
}


def _build_v2_sitting_cells(*, tap_phase: int = 0, blink: bool = False, squash: int = 0) -> Dict[Tuple[int, int], Tuple[int, int, int]]:
    """Build exact art/V2.png 3/4 sitting typing pose with animated tapping paws & blink."""
    g: Dict[Tuple[int, int], Tuple[int, int, int]] = {}
    for r, line in enumerate(_SITTING_BODY):
        yr = r + (squash if r < 25 else 0)
        for c, ch in enumerate(line):
            col = _SITTING_PALETTE.get(ch)
            if col is not None:
                g[(c, yr)] = col

    # Inner curved arm creases + bouncing typing paws reaching onto keyboard deck
    p0 = tap_phase % 2
    p1 = (tap_phase + 1) % 2
    # Upper curved belly/shoulder fold (exact crease lines from art/V2.png)
    for cc, rr in ((12, 20), (13, 20), (14, 20), (15, 21), (11, 22), (12, 22), (13, 23)):
        g[(cc, rr + squash)] = BODY_OUTLINE
    # Left & right front typing paws tapping the keyboard edge (rows 21..24, cols 14..18)
    l_paw_y = 22 + squash + p0
    r_paw_y = 21 + squash + p1
    for c, r, ch in (
        (14, l_paw_y, "B"), (15, l_paw_y, "B"), (15, l_paw_y + 1, "b"), (16, l_paw_y, "d"),
        (17, r_paw_y, "B"), (18, r_paw_y, "B"), (18, r_paw_y + 1, "b"), (19, r_paw_y, "d"),
    ):
        g[(c, r)] = _SITTING_PALETTE[ch]

    # 3/4 tilted eyes (left 3x3 at cols 12..14 rows 16..18, right 2x3 at cols 19..20 rows 14..16)
    if blink:
        for c in (12, 13, 14):
            g[(c, 17 + squash)] = EYE_BLACK
        for c in (19, 20):
            g[(c, 15 + squash)] = EYE_BLACK
    else:
        for dr in range(3):
            for dc in range(3):
                g[(12 + dc, 16 + squash + dr)] = EYE_GLINT if (dr == 0 and dc == 2) else EYE_BLACK
        for dr in range(3):
            for dc in range(2):
                g[(19 + dc, 14 + squash + dr)] = EYE_GLINT if (dr == 0 and dc == 0) else EYE_BLACK
    return g


def _draw_v2_sitting_laptop(ctx: cairo.Context, ox: float, oy: float, tap_phase: int = 0, alpha: float = 1.0) -> None:
    """Draw the exact slanted 3/4 silver pixel laptop from art/V2.png on grid (ox, oy)."""
    if alpha <= 0.05:
        return
    pal = {
        "D": _rgb(52, 54, 62),
        "d": _rgb(44, 46, 54),
        "M": _rgb(126, 130, 142),
        "L": _rgb(168, 174, 188),
        "W": _rgb(205, 240, 255),
    }
    ctx.save()
    ctx.set_antialias(cairo.ANTIALIAS_NONE)
    for r, line in enumerate(_SITTING_LAPTOP):
        for c, ch in enumerate(line):
            col = pal.get(ch)
            if col is not None:
                ctx.set_source_rgba(*col, alpha)
                ctx.rectangle(round(ox + c * U), round(oy + r * U), U, U)
                ctx.fill()
    # Subtle soft keystroke highlight flash on keyboard deck synchronized with paw taps
    kx = round(ox + (13 + (tap_phase % 2) * 3) * U)
    ky = round(oy + 23 * U)
    ctx.set_source_rgba(0.65, 0.94, 1.0, 0.50 * alpha)
    ctx.rectangle(kx, ky, U * 2, U)
    ctx.fill()
    ctx.restore()


# ---------------------------------------------------------------------------
# All 19 State & Mood Renderers
# ---------------------------------------------------------------------------

def build_renderers(
    _RA=None,
    *,
    build_cells: Callable[..., Dict[Tuple[int, int], Tuple[int, int, int]]] = _build_v2_cells,
    build_sitting_cells: Callable[..., Dict[Tuple[int, int], Tuple[int, int, int]]] = _build_v2_sitting_cells,
) -> Dict[str, Callable[[], Tuple]]:
    """Build all 19 state renderers for the `v2` (Atom V2) skin."""

    def render_idle() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n = 30
        def draw(ctx: cairo.Context, f: int) -> None:
            ph = f / n
            bob = round(math.sin(2.0 * math.pi * ph * 2.0) * 1.5)
            eyes = "blink" if f in (14, 15) else "open"
            blobs, trails = _hover_orbits(ph, ax=75.0, ay=77.0 + bob * 0.4)
            _render_orbit_layer(ctx, blobs, trails, front=False, glow=True)
            _paint_sprite(ctx, build_cells(eyes=eyes), cx=75, foot_y=107 + bob)
            _render_orbit_layer(ctx, blobs, trails, front=True, glow=True)
        return _render(draw, n), (0, n - 1)

    def render_typing() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        """Exact art/V2.png sitting TYPING pose & laptop + Atom's 5-dot Gemini loading wave bar."""
        n_in, n_loop, n_out = 7, 30, 13
        n = n_in + n_loop + n_out
        wy = 26.0
        def draw(ctx: cairo.Context, f: int) -> None:
            mode, k = _phase_3(f, n_in, n_loop, n_out)
            w = 1.0 if mode == "loop" else k
            tap_phase = ((f - n_in) // 2) % 4 if mode == "loop" else 0
            bounce = 1 if (mode == "loop" and (f - n_in) % 4 in (1, 2)) else 0
            blink = mode == "loop" and f in (21, 22)

            ax, ay = 75.0 - 4.0 * w, 78.0 + 3.0 * w
            tw = 1.15 + k * 3.0 if mode == "loop" else 0.0
            blobs, trails = [], []
            for idx, sp in enumerate(R.ELECTRONS):
                if mode == "in":
                    th = sp.phi0 + IDLE_REV[idx] * 2.0 * math.pi * (0.15 * k)
                elif mode == "loop":
                    th = sp.phi0
                else:
                    th = sp.phi0 - IDLE_REV[idx] * 2.0 * math.pi * (0.15 * (1.0 - k))
                ox_o, oy_o, ez = _orbit_point(ax, ay, sp.rx * 0.5, sp.ry * 0.5, sp.tilt_deg, th)
                dx, dy = ox_o - ax, oy_o - ay
                dist = math.hypot(dx, dy) + 1e-6
                side_dir = -1.0 if ATOM_WAVE_X[idx] < ax else +1.0
                lower_boost = _clamp((oy_o - (ay - 10.0)) / 25.0)
                push = (11.0 + 15.0 * lower_boost) * w * (1.0 - w)
                px = _lerp(ox_o, ATOM_WAVE_X[idx], w) + side_dir * push
                py = _lerp(oy_o, wy, w) + (dy / dist) * 6.0 * w * (1.0 - w)
                pz = _lerp(ez, 1.0, w)

                bar_score = R.loading_bar_score(idx, tw) if mode == "loop" else 0.0
                if w <= 0.01:
                    sidx = _size_from_ez(ez)
                elif w >= 0.99:
                    sidx = R.size_index_from_score(bar_score)
                else:
                    orbit_score = _clamp((ez + 0.65) / 1.40)
                    sidx = R.size_index_from_score(_lerp(orbit_score, bar_score, w))
                blobs.append((pz, idx, px, py, sidx))
                if w < 0.25:
                    tlag = th - IDLE_REV[idx] * 2.0 * math.pi * 0.04
                    tx, ty, tez = _orbit_point(ax, ay, sp.rx * 0.5, sp.ry * 0.5, sp.tilt_deg, tlag)
                    trails.append((tez, idx, tx, ty, 2))
            blobs.sort(key=lambda it: it[0])
            trails.sort(key=lambda it: it[0])

            _render_orbit_layer(ctx, blobs, trails, front=False)
            if w < 0.35:
                # Standing crouch transition into sit
                squat = 1 if w > 0.15 else 0
                _paint_sprite(ctx, build_cells(eyes="open", arm_l="droop", arm_r="droop", squash=squat),
                              cx=75.0 - 4.0 * w, foot_y=107.0 + 1.0 * squat, tilt_deg=4.0 * w)
            else:
                # Exact sitting art/V2.png sprite + slanted silver laptop
                sit_ox = 41.0
                sit_oy = 47.0
                lap_drop = (1.0 - _clamp((w - 0.35) / 0.65)) * 16.0
                # Soft floor shadow under sitting V2 + laptop
                ctx.save()
                ctx.set_source_rgba(0.03, 0.04, 0.08, 0.28)
                ctx.rectangle(round(sit_ox + 5 * U), 107, 13 * U, 2)
                ctx.rectangle(round(sit_ox + 8 * U), 109, 8 * U, 1)
                ctx.fill()
                ctx.restore()

                land_squash = 1 if (mode == "in" and f in (3, 4)) else bounce
                sit_cells = build_sitting_cells(tap_phase=tap_phase, blink=blink, squash=land_squash)
                ctx.save()
                ctx.set_antialias(cairo.ANTIALIAS_NONE)
                for (col, row), (r, gg, b) in sit_cells.items():
                    ctx.set_source_rgb(r / 255.0, gg / 255.0, b / 255.0)
                    ctx.rectangle(round(sit_ox + col * U), round(sit_oy + row * U), U, U)
                    ctx.fill()
                ctx.restore()
                _draw_v2_sitting_laptop(ctx, sit_ox + 2.0, sit_oy + lap_drop, tap_phase=tap_phase, alpha=_clamp((w - 0.25) / 0.55))
            _render_orbit_layer(ctx, blobs, trails, front=True)
        return _render(draw, n), (n_in, n_in + n_loop - 1)

    def render_angry() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        """Exact art/V2.png ANGRY panel: bright blue body + spiky pom-pom + fiery orange aura & arcs."""
        n_in, n_loop, n_out = 6, 30, 6
        n = n_in + n_loop + n_out
        def draw(ctx: cairo.Context, f: int) -> None:
            mode, k = _phase_3(f, n_in, n_loop, n_out)
            amp = 1.0 if mode == "loop" else k
            shake = math.sin(f * 2.1) * 1.4 * amp
            cx = 75.0 + shake
            cy = 79.0

            # Quantized 7-step fiery orange glow halos (compact lossless WebP, warm art/V2.png glow)
            if amp > 0.05:
                ctx.save()
                for rad, a_step in ((42, 0.04), (37, 0.06), (32, 0.09), (27, 0.12), (22, 0.15)):
                    ctx.set_source_rgba(0.96, 0.44, 0.22, a_step * amp)
                    ctx.arc(round(cx), cy, rad, 0, 2.0 * math.pi)
                    ctx.fill()
                ctx.restore()

            # Body STAYS sky-cyan blue just like art/V2.png ANGRY panel!
            cells = build_cells(
                arm_l="tense" if amp > 0.25 else "rest",
                arm_r="tense" if amp > 0.25 else "rest",
                pom="spiky" if amp > 0.25 else "normal",
                eyes="angry" if amp > 0.2 else "open",
                squash=1 if amp > 0.5 and (f % 4 in (1, 2)) else 0,
            )
            _paint_sprite(ctx, cells, cx=cx, foot_y=107)

            # Segmented curved orange heat/vibration arcs & spark squares exact art/V2.png layout
            if amp > 0.15:
                pulse = 0.78 + 0.22 * math.sin(f * 0.85)
                ox_vib = 30.0 + 1.2 * math.sin(f * 1.4)
                ctx.save()
                ctx.set_antialias(cairo.ANTIALIAS_NONE)
                ctx.set_source_rgba(0.95, 0.46, 0.25, 0.94 * amp * pulse)
                for side in (-1, 1):
                    # Upper short tick arcs flanking beanie
                    ctx.rectangle(round(cx + side * 24), 52, 2, 2)
                    ctx.rectangle(round(cx + side * 26), 54, 2, 4)
                    # Mid/lower curved vibration brackets flanking body
                    ctx.rectangle(round(cx + side * (ox_vib + 1)), 60, 2, 5)
                    ctx.rectangle(round(cx + side * (ox_vib + 4)), 76, 2, 8)
                    ctx.rectangle(round(cx + side * (ox_vib + 2)), 85, 2, 5)
                    ctx.rectangle(round(cx + side * (ox_vib - 1)), 90, 2, 3)
                    ctx.fill()
                # Floating square spark dots (outer left & right)
                for sx, sy, ph_off in ((-39, 64, 0), (-36, 72, 3), (38, 69, 2), (37, 89, 5)):
                    sp = 0.50 + 0.50 * math.sin((f + ph_off) * 0.7)
                    ctx.set_source_rgba(0.98, 0.56, 0.26, amp * sp)
                    ctx.rectangle(round(cx + sx), sy, 2, 2)
                    ctx.fill()
                ctx.restore()
        return _render(draw, n), (n_in, n_in + n_loop - 1)

    def render_thinking() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        """Atom-style floating thinking: body lifts & tucks legs smoothly while Gemini electrons orbit fast."""
        n_in, n_loop, n_out = 7, 30, 7
        n = n_in + n_loop + n_out
        def draw(ctx: cairo.Context, f: int) -> None:
            mode, k = _phase_3(f, n_in, n_loop, n_out)
            w = 1.0 if mode == "loop" else k

            if mode == "in":
                eye_mode = "look_ur" if f >= 3 else "open"
                shimmer_u = None
                bob = 0.0
            elif mode == "loop":
                fl = f - n_in
                if fl < 14:
                    eye_mode = "look_ur"
                elif fl == 14:
                    eye_mode = "blink"
                elif fl < 28:
                    eye_mode = "look_ul"
                else:
                    eye_mode = "look_ur"
                shimmer_u = k
                bob = math.sin(2.0 * math.pi * k * 2.0) * 1.8
            else:
                fo = f - (n_in + n_loop)
                eye_mode = "look_ur" if fo < 3 else "open"
                shimmer_u = None
                bob = 0.0

            lift = 6.0 * w + bob
            leg_mode = "tuck" if w >= 0.65 else ("half" if w >= 0.25 else "stand")
            orb_ay = _lerp(77.0, 68.0, w) - bob * 0.5

            # Atom-style THINK_TILTS Gemini electrons revolving fast (2 revs per 30f loop) with 3-step comet trails
            def eval_theta(idx: int, ff: float) -> float:
                sp = R.ELECTRONS[idx]
                sign = 1.0 if THINK_REV[idx] >= 0 else -1.0
                if ff < 0:
                    return sp.phi0 + IDLE_REV[idx] * 2.0 * math.pi * (ff / 30.0)
                if ff < n_in:
                    u_in = ff / float(n_in)
                    return sp.phi0 + sign * math.pi * (u_in * u_in)
                if ff < n_in + n_loop:
                    ul = (ff - n_in) / float(n_loop)
                    return sp.phi0 + sign * math.pi + THINK_REV[idx] * 4.0 * math.pi * ul
                if ff < n:
                    uo = (ff - (n_in + n_loop)) / float(n_out)
                    return sp.phi0 + sign * math.pi + THINK_REV[idx] * 4.0 * math.pi + sign * math.pi * (1.0 - (1.0 - uo) ** 2)
                return sp.phi0 + sign * 2.0 * math.pi + THINK_REV[idx] * 4.0 * math.pi

            blobs, trails = [], []
            for idx, sp in enumerate(R.ELECTRONS):
                tlt = _lerp(sp.tilt_deg, THINK_TILTS[idx], w)
                rx = _lerp(sp.rx * 0.5, sp.rx * 0.5 + 6.0, w)
                ry = _lerp(sp.ry * 0.5, sp.ry * 0.5 + 2.0, w)
                px, py, ez = _orbit_point(75.0, orb_ay, rx, ry, tlt, eval_theta(idx, float(f)))
                sidx = 3 if (w > 0.5 and ez > 0.25) else _size_from_ez(ez)
                blobs.append((ez, idx, px, py, sidx))
                if w >= 0.35:
                    for step_idx, (lag_f, dsz) in enumerate(((0.38, 4), (0.76, 3), (1.14, 2))):
                        if w < 0.65 and step_idx > 0:
                            continue
                        tx, ty, tez = _orbit_point(75.0, orb_ay, rx, ry, tlt, eval_theta(idx, float(f) - lag_f))
                        trails.append((tez, idx, tx, ty, dsz))
                else:
                    tx, ty, tez = _orbit_point(75.0, orb_ay, rx, ry, tlt, eval_theta(idx, float(f) - 1.14))
                    trails.append((tez, idx, tx, ty, 2))
            blobs.sort(key=lambda it: it[0])
            trails.sort(key=lambda it: it[0])

            _render_orbit_layer(ctx, blobs, trails, front=False)
            cells = build_cells(
                eyes=eye_mode,
                arm_l="rest",
                arm_r="rest",
                leg_l=leg_mode,
                leg_r=leg_mode,
                include_legs=(leg_mode != "tuck"),
                beanie_shimmer_u=shimmer_u,
            )
            _paint_sprite(
                ctx,
                cells,
                cx=75.0,
                foot_y=107.0 - lift,
                shadow_y=107.0,
                shadow_alpha=_lerp(0.28, 0.14, w),
            )
            _render_orbit_layer(ctx, blobs, trails, front=True)
        return _render(draw, n), (n_in, n_in + n_loop - 1)

    def render_dance() -> Tuple[List[cairo.ImageSurface], Tuple[int, int], int]:
        """Exact art/V2.png DANCE: no blush, fat rounded raised arms, high bouncy hop, ^ ^ eyes, + sparkles."""
        n_in, n_loop, n_out = 5, 30, 5
        n = n_in + n_loop + n_out
        def draw(ctx: cairo.Context, f: int) -> None:
            mode, k = _phase_3(f, n_in, n_loop, n_out)
            amp = 1.0 if mode == "loop" else k
            beat = (f - n_in) / 7.5 if mode == "loop" else (f / 7.5)
            hop = (2.5 + abs(math.sin(beat * math.pi)) * 4.5) * amp
            sway_x = math.sin(beat * math.pi) * 2.0 * amp
            step_l = "kick_out" if (f % 10 < 5 and amp > 0.35) else "hop"
            step_r = "kick_out" if (f % 10 >= 5 and amp > 0.35) else "hop"
            wave_up = f % 8 < 4

            blobs, trails = _hover_orbits(f / 30.0, ax=75.0, ay=73.0 - hop * 0.4, ry_scale=1.15)
            _render_orbit_layer(ctx, blobs, trails, front=False)
            cells = build_cells(
                arm_l="wave" if wave_up else "raise",
                arm_r="raise" if wave_up else "wave",
                leg_l=step_l,
                leg_r=step_r,
                eyes="happy" if amp > 0.2 else "open",
            )
            _paint_sprite(ctx, cells, cx=75.0 + sway_x, foot_y=107.0 - hop, shadow_y=107.0, shadow_alpha=max(0.14, 0.28 - hop * 0.02))
            if amp > 0.15:
                # Exact art/V2.png DANCE sparkles: cyan + top-L, yellow + top-R, hollow coral + mid-R, pink dot mid-L
                _draw_plus_sparkle(ctx, 43, 45, (112, 232, 248), alpha=amp * (0.65 + 0.35 * math.sin(f * 0.7)), hollow=False)
                _draw_plus_sparkle(ctx, 105, 48, (252, 224, 106), alpha=amp * (0.65 + 0.35 * math.cos(f * 0.7)), hollow=False)
                _draw_plus_sparkle(ctx, 109, 63, (254, 166, 134), alpha=amp * (0.60 + 0.40 * math.sin(f * 0.9)), hollow=True)
                _draw_trail_sq(ctx, 45, 61, 3, _rgb(238, 170, 243), alpha=amp * 0.9)
            _render_orbit_layer(ctx, blobs, trails, front=True)
        return _render(draw, n), (n_in, n_in + n_loop - 1), 65

    def render_working() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n_in, n_loop, n_out = 5, 30, 5
        n = n_in + n_loop + n_out
        def draw(ctx: cairo.Context, f: int) -> None:
            mode, k = _phase_3(f, n_in, n_loop, n_out)
            a = 1.0 if mode == "loop" else k
            ph = (f / 15.0) % 1.0 if mode == "loop" else 0.2 * k
            ang = 2.0 * math.pi * (k if mode == "loop" else 0.25 * k)
            blobs, trails = _hover_orbits(ph, ax=74.0, ay=77.0, rx_scale=0.95)
            _render_orbit_layer(ctx, blobs, trails, front=False)
            _paint_sprite(ctx, build_cells(arm_r="raise", eyes="look_r" if a > 0.3 else "open"), cx=72, foot_y=107)
            _draw_pixel_gear(ctx, 107, 67, 6, ang, _rgb(92, 232, 255), a)
            _draw_pixel_gear(ctx, 118, 56, 4, -ang * 1.4 + 0.3, _rgb(255, 220, 106), a)
            _render_orbit_layer(ctx, blobs, trails, front=True)
        return _render(draw, n), (n_in, n_in + n_loop - 1)

    def render_exploring() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n_in, n_loop, n_out = 5, 30, 5
        n = n_in + n_loop + n_out
        def draw(ctx: cairo.Context, f: int) -> None:
            mode, k = _phase_3(f, n_in, n_loop, n_out)
            a = 1.0 if mode == "loop" else k
            ph = k if mode == "loop" else 0.2 * k
            eyes = ("look_r" if (f - n_in) % 16 < 8 else "look_l") if mode == "loop" else "open"
            blobs, trails = _hover_orbits(ph, ax=74.0, ay=77.0, rx_scale=0.92)
            _render_orbit_layer(ctx, blobs, trails, front=False)
            _paint_sprite(ctx, build_cells(eyes=eyes, arm_r="raise" if a > 0.3 else "rest"), cx=70, foot_y=107)
            if a > 0.05:
                dx, dy, dw, dh = 101, 61, 24, 28
                ctx.save()
                ctx.set_antialias(cairo.ANTIALIAS_NONE)
                ctx.set_source_rgba(*_rgb(70, 130, 185), a)
                ctx.rectangle(dx - 1, dy - 1, dw + 2, dh + 2)
                ctx.fill()
                ctx.set_source_rgba(*_rgb(232, 242, 255), a)
                ctx.rectangle(dx, dy, dw, dh)
                ctx.fill()
                ctx.set_source_rgba(*_rgb(168, 200, 232), a)
                ctx.rectangle(dx + dw - 5, dy, 5, 5)
                ctx.fill()
                for row, lw in enumerate((14, 18, 12, 18, 14)):
                    ctx.set_source_rgba(*_rgb(110, 145, 185), a)
                    ctx.rectangle(dx + 3, dy + 5 + row * 4, lw, 2)
                    ctx.fill()
                scan_u = 0.5 - 0.5 * math.cos(2.0 * math.pi * ((f - n_in) / 15.0)) if mode == "loop" else 0.0
                sy = round(dy + 3 + scan_u * (dh - 7))
                ctx.set_source_rgba(*_rgb(80, 245, 255), a)
                ctx.rectangle(dx - 2, sy, dw + 4, 2)
                ctx.fill()
                ctx.restore()
            _render_orbit_layer(ctx, blobs, trails, front=True)
        return _render(draw, n), (n_in, n_in + n_loop - 1)

    def render_running() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n_in, n_loop, n_out = 5, 30, 5
        n = n_in + n_loop + n_out
        term_colors = [_rgb(80, 240, 160), _rgb(90, 225, 255), _rgb(140, 250, 180), _rgb(70, 210, 140), _rgb(230, 250, 120)]
        def draw(ctx: cairo.Context, f: int) -> None:
            mode, k = _phase_3(f, n_in, n_loop, n_out)
            a = 1.0 if mode == "loop" else k
            ph = (2.0 * k) % 1.0 if mode == "loop" else 0.25 * k
            blobs, trails = _hover_orbits(ph, ax=74.0, ay=77.0, rx_scale=0.95)
            _render_orbit_layer(ctx, blobs, trails, front=False, palette=term_colors)
            _paint_sprite(ctx, build_cells(eyes="look_r" if a > 0.3 else "open"), cx=70, foot_y=107)
            if a > 0.05:
                tx, ty, tw, th = 100, 62, 30, 26
                scroll = (f - n_in) % 10 if mode == "loop" else 0
                ctx.save()
                ctx.set_antialias(cairo.ANTIALIAS_NONE)
                ctx.set_source_rgba(*_rgb(45, 72, 96), a)
                ctx.rectangle(tx - 1, ty - 1, tw + 2, th + 2)
                ctx.fill()
                ctx.set_source_rgba(*_rgb(14, 22, 32), a)
                ctx.rectangle(tx, ty, tw, th)
                ctx.fill()
                ctx.set_source_rgba(*_rgb(28, 42, 60), a)
                ctx.rectangle(tx, ty, tw, 5)
                ctx.fill()
                for ci, col in enumerate((_rgb(255, 96, 96), _rgb(255, 210, 80), _rgb(80, 235, 140))):
                    ctx.set_source_rgba(*col, a)
                    ctx.rectangle(tx + 2 + ci * 3, ty + 1, 2, 2)
                    ctx.fill()
                widths = (13, 19, 10, 21, 15)
                for row in range(4):
                    ly = ty + 7 + row * 4
                    ctx.set_source_rgba(*_rgb(255, 235, 110), a)
                    ctx.rectangle(tx + 3, ly, 2, 2)
                    ctx.fill()
                    ctx.set_source_rgba(*(_rgb(80, 240, 150) if (row + scroll) % 3 != 1 else _rgb(90, 225, 255)), a)
                    ctx.rectangle(tx + 6, ly, widths[(row + scroll) % len(widths)], 2)
                    ctx.fill()
                if (f // 3) % 2 == 0:
                    ctx.set_source_rgba(*_rgb(110, 255, 175), a)
                    ctx.rectangle(tx + 3, ty + 23, 3, 2)
                    ctx.fill()
                ctx.restore()
            _render_orbit_layer(ctx, blobs, trails, front=True, palette=term_colors)
        return _render(draw, n), (n_in, n_in + n_loop - 1)

    def render_delegating() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        """3 mini V2 pom-pom buddies branching overhead with Atom link dots (matching ATOM DELEGATING)."""
        n_in, n_loop, n_out = 5, 30, 5
        n = n_in + n_loop + n_out
        def _mini_v2(ctx: cairo.Context, mx: float, my: float, a: float) -> None:
            if a <= 0.05:
                return
            ix, iy = round(mx), round(my)
            ctx.save()
            ctx.set_antialias(cairo.ANTIALIAS_NONE)
            ctx.set_source_rgba(*_rgb(*BODY_OUTLINE), a)
            ctx.rectangle(ix - 5, iy - 4, 10, 8)
            ctx.fill()
            ctx.set_source_rgba(*_rgb(*BODY_BRIGHT), a)
            ctx.rectangle(ix - 4, iy - 2, 8, 5)
            ctx.fill()
            # Mini rainbow beanie + tiny pom
            for ci, ccol in enumerate(((174, 131, 229), (62, 224, 236), (155, 238, 128), (252, 228, 104), (254, 118, 148))):
                ctx.set_source_rgba(*_rgb(*ccol), a)
                ctx.rectangle(ix - 5 + ci * 2, iy - 4, 2, 2)
                ctx.fill()
            ctx.set_source_rgba(*_rgb(94, 240, 162), a)
            ctx.rectangle(ix - 1, iy - 6, 2, 2)
            ctx.fill()
            ctx.set_source_rgba(*_rgb(*BODY_MID), a)
            ctx.rectangle(ix - 3, iy + 4, 2, 1)
            ctx.rectangle(ix + 1, iy + 4, 2, 1)
            ctx.fill()
            ctx.set_source_rgba(*_rgb(*EYE_BLACK), a)
            ctx.rectangle(ix - 3, iy, 2, 2)
            ctx.rectangle(ix + 1, iy, 2, 2)
            ctx.fill()
            ctx.restore()

        def draw(ctx: cairo.Context, f: int) -> None:
            mode, k = _phase_3(f, n_in, n_loop, n_out)
            w = 1.0 if mode == "loop" else k
            ph = k if mode == "loop" else 0.25 * k
            blobs, trails = _hover_orbits(ph, ax=75.0, ay=77.0)
            _render_orbit_layer(ctx, blobs, trails, front=False)
            _paint_sprite(ctx, build_cells(eyes="look_ur" if w > 0.3 else "open"), cx=75, foot_y=107)
            if w > 0.05:
                for idx, (ox_m, oy_m) in enumerate(((-33, -24), (0, -34), (+33, -24))):
                    bob = round(2.0 * math.sin(2.0 * math.pi * (ph + idx * 0.33)))
                    bx = round(_lerp(75.0, 75.0 + ox_m, w))
                    by = round(_lerp(60.0, 48.0 + oy_m + bob, w))
                    for step in (1, 2):
                        u_d = step / 3.0
                        lx = round(_lerp(75.0, bx, u_d))
                        ly = round(_lerp(56.0, by, u_d))
                        col = R.ELECTRONS[(idx * 2) % len(R.ELECTRONS)].color
                        if (f + step) % 2 == 0 or w > 0.8:
                            _draw_trail_sq(ctx, lx, ly, 2, col, alpha=w * 0.88)
                    _mini_v2(ctx, bx, by, w)
            _render_orbit_layer(ctx, blobs, trails, front=True)
        return _render(draw, n), (n_in, n_in + n_loop - 1)

    def render_asking() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n_in, n_loop, n_out = 4, 26, 6
        n = n_in + n_loop + n_out
        q_glyph = (".###.", "#...#", "...#.", "..#..", ".....", "..#..")
        def draw(ctx: cairo.Context, f: int) -> None:
            mode, k = _phase_3(f, n_in, n_loop, n_out)
            a = 1.0 if mode == "loop" else k
            ph = k if mode == "loop" else 0.2 * k
            bob = round(1.5 * math.sin(2.0 * math.pi * ph))
            blobs, trails = _hover_orbits(ph, ax=75.0, ay=77.0)
            _render_orbit_layer(ctx, blobs, trails, front=False)
            _paint_sprite(ctx, build_cells(eyes="look_ur" if a > 0.3 else "open"), cx=75, foot_y=107)
            if a > 0.05:
                bx, by, bw, bh = 104, 30 + bob, 20, 22
                ctx.save()
                ctx.set_antialias(cairo.ANTIALIAS_NONE)
                ctx.set_source_rgba(*_rgb(90, 120, 195), a)
                ctx.rectangle(bx - 1, by - 1, bw + 2, bh + 2)
                ctx.fill()
                ctx.set_source_rgba(*_rgb(240, 246, 255), a)
                ctx.rectangle(bx, by, bw, bh)
                ctx.fill()
                ctx.rectangle(bx + 2, by + bh + 1, 4, 2)
                ctx.fill()
                _draw_pixel_glyph(ctx, q_glyph, bx + 5, by + 5, 2, (46, 132, 232), a * (0.8 + 0.2 * math.sin(2.0 * math.pi * ph)))
                ctx.restore()
            _render_orbit_layer(ctx, blobs, trails, front=True)
        return _render(draw, n), (n_in, n_in + n_loop - 1)

    def render_listening() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n = 30
        def draw(ctx: cairo.Context, f: int) -> None:
            ph = f / n
            bob = round(math.sin(2.0 * math.pi * ph * 2.0) * 1.0)
            blobs, trails = _hover_orbits(ph, ax=75.0, ay=77.0 + bob * 0.3)
            _render_orbit_layer(ctx, blobs, trails, front=False, glow=True)
            _paint_sprite(ctx, build_cells(eyes="blink" if f in (12, 13) else "look_d"), cx=75, foot_y=107 + bob)
            # Subtle Atom/cyan soundwave ticks flanking the body
            ctx.save()
            ctx.set_antialias(cairo.ANTIALIAS_NONE)
            for ring in range(2):
                prog = (ph * 2.0 + ring * 0.5) % 1.0
                dx = round(31 + prog * 10)
                a = math.sin(prog * math.pi) * 0.72
                col = R.ELECTRONS[ring].color
                ctx.set_source_rgba(col[0], col[1], col[2], a)
                for side in (-1, 1):
                    ctx.rectangle(75 + side * dx, 72, 2, 10)
                    ctx.rectangle(75 + side * (dx - 2), 69, 2, 3)
                    ctx.rectangle(75 + side * (dx - 2), 82, 2, 3)
                    ctx.fill()
            ctx.restore()
            _render_orbit_layer(ctx, blobs, trails, front=True, glow=True)
        return _render(draw, n), (0, n - 1)

    def render_watching() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n = 30
        def draw(ctx: cairo.Context, f: int) -> None:
            ph = f / n
            eyes = "look_l" if f < 10 else ("look_r" if f < 22 else "open")
            blobs, trails = _hover_orbits(ph, ax=75.0, ay=77.0)
            _render_orbit_layer(ctx, blobs, trails, front=False)
            _paint_sprite(ctx, build_cells(eyes=eyes), cx=75, foot_y=107)
            # Crisp subtle top equalizer/sensor pips matching ATOM WATCHING
            ctx.save()
            ctx.set_antialias(cairo.ANTIALIAS_NONE)
            for j, ox_p in enumerate((-5, 0, 5)):
                h = 2 + (1 if ((f // 3 + j) % 2 == 0) else 0) * 2
                col = R.ELECTRONS[j].color
                ctx.set_source_rgba(col[0], col[1], col[2], 0.88)
                ctx.rectangle(75 + ox_p, 35 - h, 2, h)
                ctx.fill()
            ctx.restore()
            _render_orbit_layer(ctx, blobs, trails, front=True)
        return _render(draw, n), (0, n - 1)

    def render_done() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n = 36
        def draw(ctx: cairo.Context, f: int) -> None:
            ph = f / n
            hop = abs(math.sin(2.0 * math.pi * ph * 2.0)) * 4.5
            blobs, trails = _hover_orbits(ph, ax=75.0, ay=74.0 - hop * 0.4)
            _render_orbit_layer(ctx, blobs, trails, front=False)
            cells = build_cells(arm_l="wave", arm_r="wave", leg_l="hop", leg_r="hop", eyes="happy")
            _paint_sprite(ctx, cells, cx=75, foot_y=107 - hop, shadow_y=107, shadow_alpha=max(0.14, 0.28 - hop * 0.02))
            for idx in range(5):
                t = (ph + idx * 0.2) % 1.0
                sx = 44 + idx * 15 + math.sin(t * 6.28 + idx) * 3.5
                sy = 30 + t * 38.0
                _draw_trail_sq(ctx, sx, sy, 2, R.ELECTRONS[idx].color, alpha=math.sin(t * math.pi) * 0.9)
            _render_orbit_layer(ctx, blobs, trails, front=True)
        return _render(draw, n), (0, n - 1)

    def render_happy() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n = 36
        heart = (".#.#.", "#####", "#####", ".###.", "..#..")
        def draw(ctx: cairo.Context, f: int) -> None:
            ph = f / n
            hop = abs(math.sin(2.0 * math.pi * ph * 2.0)) * 4.0
            wave = f % 12 < 6
            blobs, trails = _hover_orbits(ph, ax=75.0, ay=75.0 - hop * 0.4)
            _render_orbit_layer(ctx, blobs, trails, front=False)
            cells = build_cells(
                arm_l="wave" if wave else "raise",
                arm_r="raise" if wave else "wave",
                eyes="happy",
                mood_tint="happy",
                mood_amt=0.9,
                squash=1 if hop < 0.8 else 0,
            )
            _paint_sprite(ctx, cells, cx=75, foot_y=107 - hop, shadow_y=107)
            for hx, off in ((44, 0.0), (100, 0.5)):
                t = (ph + off) % 1.0
                hy = 62 - t * 26.0
                _draw_pixel_glyph(ctx, heart, hx, hy, 2, (255, 134, 178), math.sin(t * math.pi))
            _render_orbit_layer(ctx, blobs, trails, front=True)
        return _render(draw, n), (0, n - 1)

    def render_sad() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n_in, n_loop, n_out = 6, 30, 6
        n = n_in + n_loop + n_out
        def draw(ctx: cairo.Context, f: int) -> None:
            mode, k = _phase_3(f, n_in, n_loop, n_out)
            amp = 1.0 if mode == "loop" else k
            blobs, trails = _hover_orbits(f / 60.0, ax=75.0, ay=80.0, rx_scale=0.88, max_size=2)
            _render_orbit_layer(ctx, blobs, trails, front=False, alpha=0.55)
            cells = build_cells(
                arm_l="droop" if amp > 0.2 else "rest",
                arm_r="droop" if amp > 0.2 else "rest",
                pom="droop" if amp > 0.2 else "normal",
                eyes="sad" if amp > 0.2 else "open",
                mood_tint="sad" if amp > 0.1 else None,
                mood_amt=amp,
                squash=1 if amp > 0.4 else 0,
            )
            _paint_sprite(ctx, cells, cx=75, foot_y=107)
            if amp > 0.25:
                for idx, tx in enumerate((64, 86)):
                    t = ((f - n_in + idx * 14) % 24) / 24.0
                    ctx.set_source_rgba(0.48, 0.86, 1.0, math.sin(t * math.pi) * amp)
                    ctx.rectangle(tx, round(82 + t * 20.0), 2, 4)
                    ctx.fill()
            _render_orbit_layer(ctx, blobs, trails, front=True, alpha=0.55)
        return _render(draw, n), (n_in, n_in + n_loop - 1)

    def render_error() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n = 30
        err_pal = [_rgb(255, 110, 90), _rgb(255, 175, 90), _rgb(255, 95, 120), _rgb(255, 210, 100), _rgb(255, 125, 95)]
        def draw(ctx: cairo.Context, f: int) -> None:
            ph = f / n
            shake = math.sin(f * 1.9) * 1.4
            blobs, trails = _hover_orbits(ph, ax=75.0, ay=78.0, rx_scale=0.95)
            _render_orbit_layer(ctx, blobs, trails, front=False, palette=err_pal)
            cells = build_cells(arm_l="tense", arm_r="tense", pom="spiky", eyes="error", mood_tint="error", mood_amt=1.0)
            _paint_sprite(ctx, cells, cx=75.0 + shake, foot_y=107)
            _render_orbit_layer(ctx, blobs, trails, front=True, palette=err_pal)
        return _render(draw, n), (0, n - 1)

    def render_canceled() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n = 30
        def draw(ctx: cairo.Context, f: int) -> None:
            ph = f / n
            recoil = abs(math.sin(2.0 * math.pi * ph * 2.0)) * 2.0
            blobs, trails = _hover_orbits(ph, ax=75.0, ay=78.0, rx_scale=0.92, max_size=2)
            _render_orbit_layer(ctx, blobs, trails, front=False, alpha=0.72)
            cells = build_cells(arm_l="raise", arm_r="raise", eyes="wide", mood_tint="canceled", mood_amt=1.0)
            _paint_sprite(ctx, cells, cx=75, foot_y=107 - recoil, shadow_y=107)
            _render_orbit_layer(ctx, blobs, trails, front=True, alpha=0.72)
        return _render(draw, n), (0, n - 1)

    def render_tired() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n = 30
        def draw(ctx: cairo.Context, f: int) -> None:
            ph = f / n
            sq = 1 if math.sin(2.0 * math.pi * ph) > 0.0 else 0
            blobs, trails = _hover_orbits(ph * 0.5, ax=75.0, ay=80.0, rx_scale=0.86, max_size=1)
            _render_orbit_layer(ctx, blobs, trails, front=False, alpha=0.42)
            cells = build_cells(arm_l="droop", arm_r="droop", pom="droop", eyes="tired", mood_tint="tired", mood_amt=1.0, squash=sq)
            _paint_sprite(ctx, cells, cx=75, foot_y=107)
            _render_orbit_layer(ctx, blobs, trails, front=True, alpha=0.42)
        return _render(draw, n), (0, n - 1)

    def render_closed() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n = 30
        z_glyph = ("####", "..#.", ".#..", "####")
        def draw(ctx: cairo.Context, f: int) -> None:
            ph = f / n
            sq = 1 if math.sin(2.0 * math.pi * ph) > 0.1 else 0
            cells = build_cells(arm_l="droop", arm_r="droop", pom="droop", eyes="sleep", mood_tint="closed", mood_amt=1.0, squash=sq)
            _paint_sprite(ctx, cells, cx=75, foot_y=107, shadow_alpha=0.20)
            for idx, off in enumerate((0.0, 0.46)):
                t = (ph + off) % 1.0
                zx = round(97 + t * 14 + math.sin(t * 6.28) * 2.5)
                zy = round(60 - t * 24)
                _draw_pixel_glyph(ctx, z_glyph, zx, zy, 2 if idx == 0 else 1, (164, 206, 242), math.sin(t * math.pi) * 0.9)
        return _render(draw, n), (0, n - 1)

    return {
        "idle": render_idle,
        "thinking": render_thinking,
        "typing": render_typing,
        "working": render_working,
        "exploring": render_exploring,
        "running": render_running,
        "delegating": render_delegating,
        "asking": render_asking,
        "listening": render_listening,
        "watching": render_watching,
        "done": render_done,
        "happy": render_happy,
        "dance": render_dance,
        "sad": render_sad,
        "angry": render_angry,
        "error": render_error,
        "canceled": render_canceled,
        "tired": render_tired,
        "closed": render_closed,
    }

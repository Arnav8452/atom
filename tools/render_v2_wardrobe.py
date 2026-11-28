#!/usr/bin/env python3
"""Programmatic pixel-art renderer for the `v2-wardrobe` ("Nobility Outfits") skin.

Dresses the real Atom V2 (round blue blob, rainbow beanie and pom-pom all kept)
in four model-rank outfits, following `art/outfits.png`:

  * `orchestrator` — gold jeweled crown set down over the beanie, purple royal
                     cape with ermine edges and hem, ermine collar, gold chain
                     with an amethyst pendant, jeweled scepter in the right hand
  * `carbon`       — jagged silver shard crown, black greatcoat with a tall
                     flared collar framing the face, silver piping and zip,
                     coat sleeves, long charcoal cape
  * `neon`         — magenta/aqua feather plume, aqua circlet with a big
                     magenta gem, navy frock coat with magenta and aqua trim,
                     high collar, white cravat, coat sleeves, glowing aqua wand
  * `hydrogen`     — silver braided band with an ice gem, ice capelet with a
                     silver star pin, ice drape, cream tunic with ice bands

Every outfit is drawn as layers around V2's own cells: a back layer (capes,
drapes, plume) under the body, a front layer (collars, coats, props) over it and
a head layer (crowns, circlets) over the beanie. V2's arms, legs and eyes are
painted last so every pose (waves, typing, hops) stays readable, and the
pom-pom is never covered. Each outfit also recolours V2's orbiting sparkles
(gold, silver, neon, ice), like the motes around the figures in the reference.

Design invariants enforced by `validate_palettes()` (see MAKING_SKINS.md):
  1. Every outfit RGB stays outside the runtime mood-tint window
     `196.0 <= h <= 226.0 and s > 0.35`, so `recolour()` only tints Atom's blue.
  2. Every outfit RGB has `max(r, g, b) >= 42`, so `tiltMoodEyes()` never
     mistakes dark fabric for eyes.
  3. Nothing is drawn over the eyes (rows 13..18, cols 9..23).

Needs only Python stdlib + python-cairo (via tools/render_v2.py).
"""

from __future__ import annotations

import dataclasses
import math
from typing import Callable, Dict, Iterable, Optional, Sequence, Tuple

import tools.render_v2 as RV2

VARIANTS: Tuple[str, ...] = ("carbon", "neon", "hydrogen", "orchestrator")
DEFAULT_VARIANT = "carbon"

RGB = Tuple[int, int, int]
Cells = Dict[Tuple[int, int], RGB]

# ---------------------------------------------------------------------------
# Palettes: outside HSV hue [196..226] when s > 0.35, and max(r, g, b) >= 42.
# ---------------------------------------------------------------------------

PALETTES: Dict[str, Dict[str, RGB]] = {
    "orchestrator": {
        "GOLD_HI": (255, 236, 128),
        "GOLD": (248, 196, 56),
        "GOLD_DK": (176, 116, 28),
        "GOLD_OUT": (112, 70, 22),
        "PEARL": (255, 250, 236),
        "RUBY": (246, 48, 88),
        "AMETHYST": (176, 92, 252),     # h=272
        "AMETHYST_DK": (120, 56, 190),  # h=268
        "EMERALD": (60, 220, 130),      # h=146
        "PURP_HI": (150, 70, 196),      # h=279
        "PURP": (104, 40, 150),
        "PURP_DK": (72, 28, 108),
        "OUT": (52, 20, 72),            # max 72
        "ERMINE": (252, 250, 244),
        "ERMINE_SH": (206, 200, 212),
        "FLECK": (58, 50, 62),          # max 62
    },
    "carbon": {
        "SILVER_HI": (240, 242, 248),
        "SILVER": (190, 194, 206),
        "SILVER_DK": (124, 128, 142),   # s=0.13
        "SHARD": (92, 96, 112),
        "GEM": (150, 104, 220),         # h=263
        "COAT_HI": (84, 86, 100),
        "COAT": (50, 52, 62),
        "COAT_DK": (44, 45, 54),        # max 54
        "OUT": (42, 42, 50),            # max 50
    },
    "neon": {
        "NAVY_HI": (66, 74, 136),       # h=233
        "NAVY": (34, 38, 88),           # h=235
        "NAVY_DK": (26, 28, 66),        # h=237, max 66
        "OUT": (20, 20, 50),            # max 50
        "MAG_HI": (255, 160, 228),
        "MAG": (255, 56, 184),
        "PINK": (255, 112, 214),
        "AQUA_HI": (176, 255, 246),
        "AQUA": (40, 240, 220),         # h=173
        "AQUA_DK": (24, 170, 160),
        "LIME": (176, 252, 84),
        "LIME_DK": (110, 196, 60),
        "PLUM": (176, 30, 130),         # h=318
        "WHITE": (246, 247, 255),
        "WHITE_SH": (200, 202, 228),    # s=0.12
        "VIOLET": (150, 90, 255),       # h=262
    },
    "hydrogen": {
        "ICE_HI": (184, 236, 250),      # h=191.8
        "ICE": (110, 206, 232),         # h=192.8
        "ICE_DK": (66, 158, 188),       # h=194.8
        "ICE_OUT": (44, 112, 134),      # h=194.7
        "SILVER_HI": (248, 250, 255),
        "SILVER": (206, 214, 228),
        "GEM": (190, 250, 255),         # h=187
        "GEM_DK": (120, 214, 236),      # h=191.4
        "CREAM": (248, 242, 222),
        "CREAM_SH": (216, 206, 182),
        "CREAM_OUT": (150, 136, 110),
        "BAND": (100, 200, 214),        # h=187.5
    },
}


def validate_palettes() -> None:
    """Assert every outfit RGB stays safe from mood recolour() and eye detection."""
    for vname, pal in PALETTES.items():
        for cname, (r, g, b) in pal.items():
            h, s, _ = RV2._rgb_to_hsv(r, g, b)
            if 196.0 <= h <= 226.0 and s > 0.35:
                raise AssertionError(
                    f"{vname}.{cname}={(r, g, b)} falls inside mood tint hue range (h={h:.1f}, s={s:.2f})"
                )
            if max(r, g, b) < 42:
                raise AssertionError(f"{vname}.{cname}={(r, g, b)} too dark (max < 42), risks tiltMoodEyes false match")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_y(row: int, squash: int) -> int:
    """V2's squash rule: rows above 25 move down with the squash, the base stays planted."""
    return row + squash if row < 25 else row


def _dim_closed(rgb: RGB) -> RGB:
    """Softly dim outfit brightness while sleeping."""
    return tuple(max(0, min(255, round(c * 0.72))) for c in rgb)  # type: ignore[return-value]


def _apply_shimmer(cells: Cells, u: Optional[float]) -> None:
    """Sweep a crisp specular sheen across the headpiece on done/happy/thinking."""
    if u is None:
        return
    edge = RV2._smoothstep(u / 0.12) * RV2._smoothstep((1.0 - u) / 0.12)
    if edge <= 0.0:
        return
    wave_pos = -0.25 + 1.5 * u
    for (c, yr), val in list(cells.items()):
        if max(val) >= 50:
            sh = math.exp(-((((c - 2) / 29.0) - wave_pos) / 0.16) ** 2) * edge
            if sh > 0.02:
                cells[(c, yr)] = tuple(min(255, round(v0 + (255 - v0) * 0.42 * sh)) for v0 in val)  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Segment art: {row: [(x, "letters"), ...]} for the left half, mirrored onto the
# right (x -> 31 - x) with optional letter swaps, so outfits stay symmetric.
# ---------------------------------------------------------------------------

SegArt = Dict[int, Sequence[Tuple[int, str]]]


def _seg(dst: Cells, art: SegArt, pal: Dict[str, RGB], squash: int, *, mirror: bool = True,
         swap: Optional[Dict[str, str]] = None, dx: int = 0, dy: int = 0, rows: Optional[range] = None) -> None:
    swap = swap or {}
    for r, segs in art.items():
        if rows is not None and r not in rows:
            continue
        yy = _row_y(r, squash) + dy
        for x0, letters in segs:
            for i, ch in enumerate(letters):
                if ch == ".":
                    continue
                dst[(x0 + i + dx, yy)] = pal[ch]
                if mirror:
                    dst[(31 - (x0 + i) + dx, yy)] = pal[swap.get(ch, ch)]


# ---------------------------------------------------------------------------
# Headpieces: crowns sit down over the beanie's top half (rows 1..8) the way
# art/outfits.png draws them; the pom-pom always stays in front.
# ---------------------------------------------------------------------------

# Left half, x 4..15 (mirrored to 16..27).
def _rows(rows: Dict[int, str], x0: int = 4) -> SegArt:
    return {r: [(x0, line)] for r, line in rows.items()}


# Left halves, x 4..15. The outer two columns sit one row lower so the band
# curves round the beanie.
_GOLD_CROWN: SegArt = _rows({
    0: ".W....W.....",
    1: "oHo..oHo....",
    2: "oGHo.oGHo.oo",
    3: "oGGHooGGHooH",
    4: "oGGGGGGGGGGG",
    5: "oGGGGGGGGGGG",
    6: "oGHHHHHHHHHH",
    7: "oHEGGRGGEGGA",
    8: "oGDDDDDDDDDD",
    9: "oD",
})

_SHARD_CROWN: SegArt = _rows({
    -1: ".........W..",
    0: "..W......oS.",
    1: ".oSo..W..oSS",
    2: ".oSko.oSo.kS",
    3: "oSkkSooSkoSk",
    4: "oSkkkSSkkkSk",
    5: "oSSkkkSSkkkS",
    6: "oSHHHHHHHHHH",
    7: "oHkSSSSkSSSV",
    8: "oSDDDDDDDDDD",
    9: "oD",
})


def _crown_pal(variant: str) -> Dict[str, RGB]:
    if variant == "orchestrator":
        P = PALETTES["orchestrator"]
        return {"W": P["PEARL"], "o": P["GOLD_OUT"], "H": P["GOLD_HI"], "G": P["GOLD"], "D": P["GOLD_DK"],
                "R": P["RUBY"], "E": P["EMERALD"], "A": P["AMETHYST"]}
    P = PALETTES["carbon"]
    return {"W": P["SILVER_HI"], "o": P["OUT"], "H": P["SILVER_HI"], "S": P["SILVER"], "D": P["SILVER_DK"],
            "k": P["SHARD"], "V": P["GEM"]}


def _crown_cells(variant: str, by: int, base: Cells, dx: int = 0, dy: int = 0,
                 skip_cols: Iterable[int] = (), pom_rows: int = 4) -> Cells:
    """Crown cells; columns in `skip_cols` are squeezed out (sitting 3/4 view) and
    the pom-pom (base cells on rows < pom_rows) is never covered."""
    art = _GOLD_CROWN if variant == "orchestrator" else _SHARD_CROWN
    flat: Cells = {}
    _seg(flat, art, _crown_pal(variant), 0)
    skip = sorted(set(skip_cols))
    head: Cells = {}
    for (x, r), col in flat.items():
        if x in skip:
            continue
        x2 = x - sum(1 for s in skip if s < x) + dx
        k = (x2, r + by + dy)
        if k in base and k[1] < pom_rows + by:
            continue  # never cover the pom-pom
        head[k] = col
    return head


def _neon_circlet(by: int, c0: int = 6, c1: int = 25, row: int = 8, gem_c: int = 15, curve: int = 3) -> Cells:
    """Aqua circlet that curves round the beanie, with a big outlined magenta gem."""
    P = PALETTES["neon"]
    head: Cells = {}
    for c in range(c0, c1 + 1):
        r = row + (1 if (c < c0 + curve or c > c1 - curve) else 0)
        edge = c in (c0, c1)
        head[(c, r + by)] = P["OUT"] if edge else (P["AQUA_HI"] if c % 3 == 0 else P["AQUA"])
        head[(c, r + 1 + by)] = P["OUT"] if edge else P["AQUA_DK"]
    g = gem_c
    gem = {
        -4: [(g, "oo")],
        -3: [(g - 1, "oAAo")],
        -2: [(g - 2, "oAmmAo")],
        -1: [(g - 2, "oAmMAo")],
        0: [(g - 2, "oAMPAo")],
        1: [(g - 2, "odMPdo")],
        2: [(g - 1, "oddo")],
        3: [(g, "oo")],
    }
    pal = {"A": P["AQUA"], "o": P["OUT"], "m": P["MAG_HI"], "M": P["MAG"], "P": P["PLUM"], "d": P["AQUA_DK"]}
    for dr, segs in gem.items():
        for x0, letters in segs:
            for i, ch in enumerate(letters):
                head[(x0 + i, row + dr + by)] = pal[ch]
    return head


# Curved feather (tip up and to the left), pink centre stripe, aqua glow on the
# outer edge, two lime blades at the base. Rows/cols on the standing grid.
_PLUME: SegArt = {
    -7: [(3, "aaA")],
    -6: [(1, "aAMma")],
    -5: [(0, "aMMmpA")],
    -4: [(0, "AMMmpA")],
    -3: [(-1, "aMMMmpA")],
    -2: [(-1, "AMMMmpa")],
    -1: [(-1, "AMMMmpA")],
    0: [(0, "aMMMmpA")],
    1: [(0, "aMMMmmpa")],
    2: [(1, "aMMMmmpA")],
    3: [(3, "aMMmmpA")],
    4: [(0, "LLLl"), (5, "aMmpMA")],
    5: [(1, "lLLl"), (7, "Mmpp")],
    6: [(3, "lll"), (9, "pM")],
}


def _neon_plume(by: int, dx: int = 0, dy: int = 0) -> Cells:
    """Feather sweeping up and out of the beanie's left side (drawn behind it)."""
    P = PALETTES["neon"]
    pal = {"a": P["AQUA_HI"], "A": P["AQUA"], "M": P["MAG"], "m": P["MAG_HI"], "p": P["PINK"],
           "L": P["LIME"], "l": P["LIME_DK"]}
    back: Cells = {}
    _seg(back, _PLUME, pal, 0, mirror=False, dx=dx, dy=by + dy)
    return back


def _hydrogen_circlet(by: int, c0: int = 6, c1: int = 25, row: int = 7, gem_c: int = 15, curve: int = 3) -> Cells:
    """Fine silver band curving round the beanie: silver line, ice diamonds, silver line."""
    P = PALETTES["hydrogen"]
    head: Cells = {}
    for c in range(c0, c1 + 1):
        r = row + (1 if (c < c0 + curve or c > c1 - curve) else 0)
        edge = c in (c0, c1)
        head[(c, r + by)] = P["ICE_OUT"] if edge else P["SILVER_HI"]
        head[(c, r + 1 + by)] = P["ICE_OUT"] if edge else (P["SILVER"] if c % 2 == 0 else P["ICE_DK"])
        head[(c, r + 2 + by)] = P["ICE_OUT"] if edge else P["SILVER"]
    for c, r, col in ((gem_c, row - 2, "SILVER_HI"), (gem_c + 1, row - 2, "SILVER_HI"),
                      (gem_c - 1, row - 1, "SILVER"), (gem_c, row - 1, "GEM"), (gem_c + 1, row - 1, "GEM_DK"), (gem_c + 2, row - 1, "SILVER"),
                      (gem_c, row, "GEM_DK"), (gem_c + 1, row, "GEM")):
        head[(c, r + by)] = P[col]
    return head


# ---------------------------------------------------------------------------
# Garments (standing poses, 32x32 grid). Back layers go under the body, front
# layers over it; arms, legs and eyes are repainted on top afterwards.
# ---------------------------------------------------------------------------

def _flare(r: int, top: int, edge0: int, spread: float) -> int:
    return round(edge0 - spread * (r - top))


def _orchestrator(squash: int, arm_r: str, typing_pose: bool, sleeping: bool) -> Tuple[Cells, Cells]:
    P = PALETTES["orchestrator"]
    pal = {"o": P["OUT"], "P": P["PURP"], "p": P["PURP_DK"], "h": P["PURP_HI"], "E": P["ERMINE"],
           "e": P["ERMINE_SH"], "f": P["FLECK"], "G": P["GOLD"], "H": P["GOLD_HI"], "D": P["GOLD_DK"],
           "A": P["AMETHYST"]}
    back: Cells = {}
    front: Cells = {}

    # Royal cape: hangs from the shoulders, wraps the body's sides and flares to the floor.
    cape: SegArt = {}
    for r in range(18, 31):
        lo = _flare(r, 18, 2, 0.34)
        inner = 4 if r < 22 else 7
        if r >= 29:
            line = "o" + "".join("f" if (x + r) % 3 == 0 else ("E" if r == 29 else "e") for x in range(lo + 1, inner + 1))
        else:
            line = "o" + "".join("h" if x in (lo + 2, lo + 5) else ("p" if x == inner - 2 else "P") for x in range(lo + 1, inner - 1))
            line += "eE" if r >= 22 else "PP"
        cape.setdefault(r, []).append((lo, line[: inner - lo + 1]))
    cape[31] = [(-2, "oooooooooo")]
    _seg(back, cape, pal, squash, rows=range(18, 22))
    _seg(front, cape, pal, squash, rows=range(22, 32))
    for r in range(22, 29):  # ermine front edge flecks
        if r % 3 == 1:
            for x in (7, 24):
                front[(x, _row_y(r, squash))] = P["FLECK"]

    # Ermine collar over the shoulders, white fur with black flecks.
    collar: SegArt = {
        17: [(3, "oEEEo")],
        18: [(2, "oEfEEEo")],
        19: [(1, "oEEEEfEEo")],
        20: [(1, "oeEfEEEEfEo")],
        21: [(1, "oeEEEEfEEEEo")],
        22: [(2, "oeEfEEEEfEGo")],
        23: [(4, "ooeEEEeoo")],
    }
    _seg(front, collar, pal, squash)

    # Gold chain draped across the chest with an amethyst pendant.
    for x, r, col in ((13, 22, "D"), (13, 23, "G"), (14, 23, "H"), (15, 24, "G")):
        front[(x, _row_y(r, squash))] = pal[col]
        front[(31 - x, _row_y(r, squash))] = pal[col]
    front[(15, _row_y(25, squash))] = P["AMETHYST"]
    front[(16, _row_y(25, squash))] = P["AMETHYST_DK"]

    # Gold scepter with a jewelled head, held in the right hand.
    if not typing_pose and not sleeping and arm_r in ("rest", "tense", "droop"):
        shaft = ((30, 18), (29, 19), (29, 20), (29, 21), (28, 22), (28, 23), (28, 24), (27, 25), (27, 26),
                 (27, 27), (26, 28), (26, 29), (26, 30))
        for i, (x, r) in enumerate(shaft):
            front[(x, _row_y(r, squash))] = P["GOLD_HI"] if i % 3 == 0 else (P["GOLD_DK"] if i == len(shaft) - 1 else P["GOLD"])
        for x, r, col in ((30, 13, "GOLD_HI"),
                          (29, 14, "GOLD"), (30, 14, "RUBY"), (31, 14, "GOLD"),
                          (28, 15, "GOLD"), (29, 15, "EMERALD"), (30, 15, "PEARL"), (31, 15, "AMETHYST"), (32, 15, "GOLD"),
                          (29, 16, "GOLD"), (30, 16, "AMETHYST"), (31, 16, "GOLD"),
                          (29, 17, "GOLD_DK"), (30, 17, "GOLD_HI"), (31, 17, "GOLD_DK")):
            front[(x, _row_y(r, squash))] = P[col]
    return back, front


def _carbon(squash: int) -> Tuple[Cells, Cells]:
    P = PALETTES["carbon"]
    pal = {"o": P["OUT"], "C": P["COAT"], "c": P["COAT_DK"], "h": P["COAT_HI"], "s": P["SILVER"],
           "S": P["SILVER_HI"], "d": P["SILVER_DK"], "k": P["SHARD"]}
    back: Cells = {}
    front: Cells = {}

    # Long charcoal cape behind, flaring to the floor on both sides.
    cape: SegArt = {}
    for r in range(18, 32):
        lo = _flare(r, 18, 2, 0.32)
        line = "o" + "d" + "".join("k" if (x - lo) % 4 == 3 else "c" for x in range(lo + 2, 8))
        cape[r] = [(lo, line if r < 31 else "o" * len(line))]
    _seg(back, cape, pal, squash)

    # Black greatcoat with a tall flared collar framing the face, a V neck, silver
    # piping down the lapels, a silver zip and chevrons, flaring a little at the hem.
    coat: SegArt = {
        13: [(3, "os")],
        14: [(2, "osh")],
        15: [(1, "oshCo")],
        16: [(1, "oshCCo")],
        17: [(1, "oshCCCo")],
        18: [(1, "oshCCCCo")],
        19: [(1, "oshCCCCCCs")],
        20: [(2, "ohCCCCCCCCs")],
        21: [(2, "ohCCCCCCCCCCs")],
        22: [(2, "ohCCdCCCCCCCcs")],
        23: [(3, "ohCCdCCCCCdcS")],
        24: [(4, "ohCCdCCCCdcs")],
        25: [(4, "ohCCCdCCdCcS")],
        26: [(5, "ohCCCdddCcs")],
        27: [(5, "ohCCCCCCdcS")],
        28: [(5, "ohCCCCCCCcs")],
        29: [(5, "ohcCCCCCCcS")],
        30: [(6, "oddd")],
    }
    _seg(front, coat, pal, squash)
    return back, front


def _neon(squash: int, arm_r: str, typing_pose: bool, sleeping: bool) -> Tuple[Cells, Cells]:
    P = PALETTES["neon"]
    pal = {"o": P["OUT"], "N": P["NAVY"], "n": P["NAVY_DK"], "v": P["NAVY_HI"], "M": P["MAG"],
           "m": P["MAG_HI"], "A": P["AQUA"], "a": P["AQUA_HI"], "W": P["WHITE"], "w": P["WHITE_SH"]}
    swap = {"M": "A", "m": "a"}  # magenta neon on the left, aqua on the right
    back: Cells = {}
    front: Cells = {}

    # Coat tails flaring behind the legs.
    tails: SegArt = {}
    for r in range(24, 31):
        lo = _flare(r, 24, 3, 0.5)
        tails[r] = [(lo, ("oM" + "n" * (9 - lo - 2)) if r < 30 else "o" + "M" * (8 - lo))]
    _seg(back, tails, pal, squash, swap=swap)

    # Dark navy frock coat: a high collar rising beside the face, neon-piped
    # lapels and front edges, a dark waistcoat between them, a glowing hem.
    coat: SegArt = {
        14: [(3, "om")],
        15: [(2, "omN")],
        16: [(2, "omNo")],
        17: [(2, "omNNo")],
        18: [(1, "omNNNo")],
        19: [(1, "omvNNNmo")],
        20: [(1, "omvvNNNNNm")],
        21: [(1, "omvvNNNNNNMo")],
        22: [(2, "omvNNNNNNNMn")],
        23: [(3, "omNNNNNNNMnnn")],
        24: [(3, "omNNNNNNNMnnn")],
        25: [(4, "omNNNNNNMnnn")],
        26: [(4, "omNNNNNNMnnn")],
        27: [(4, "omNNNNNNMnnn")],
        28: [(3, "omNNNNNNNMnnn")],
        29: [(2, "oMMMMMMMMMMMMM")],
    }
    _seg(front, coat, pal, squash, swap=swap)
    cravat: SegArt = {
        19: [(12, "wWWW")],
        20: [(12, "wWWW")],
        21: [(13, "wWW")],
        22: [(13, "wWW")],
        23: [(15, "W")],
    }
    _seg(front, cravat, pal, squash)
    for r in (25, 27):  # waistcoat buttons
        front[(15, _row_y(r, squash))] = P["VIOLET"]
        front[(16, _row_y(r, squash))] = P["VIOLET"]

    # Glowing aqua wand with a star tip, held in the right hand.
    if not typing_pose and not sleeping and arm_r in ("rest", "tense", "droop"):
        for x, r, col in ((28, 25, "AQUA_DK"), (29, 24, "AQUA"), (29, 23, "AQUA"), (30, 22, "AQUA"), (30, 21, "AQUA"),
                          (31, 20, "AQUA"), (32, 18, "AQUA_HI"), (31, 19, "AQUA_HI"), (32, 19, "WHITE"), (33, 19, "AQUA_HI"),
                          (32, 20, "AQUA_HI"), (32, 17, "AQUA"), (34, 19, "AQUA"), (30, 19, "AQUA")):
            front[(x, _row_y(r, squash))] = P[col]
    return back, front


def _hydrogen(squash: int) -> Tuple[Cells, Cells]:
    P = PALETTES["hydrogen"]
    pal = {"o": P["ICE_OUT"], "I": P["ICE"], "i": P["ICE_DK"], "h": P["ICE_HI"], "C": P["CREAM"],
           "c": P["CREAM_SH"], "k": P["CREAM_OUT"], "B": P["BAND"], "b": P["ICE_DK"], "S": P["SILVER_HI"],
           "s": P["SILVER"]}
    back: Cells = {}
    front: Cells = {}

    # Ice drape behind: falls to the floor on the left, shorter on the right.
    drape: SegArt = {}
    for r in range(19, 31):
        lo = _flare(r, 19, 2, 0.32)
        drape[r] = [(lo, ("oh" + "I" * (6 - lo - 2) + "i") if r < 30 else "o" * (7 - lo))]
    _seg(back, drape, pal, squash, mirror=False)

    # Cream tunic that follows the body and flares into an A-line hem, with an ice
    # sash, an ice V on the chest and a banded hem.
    tunic: SegArt = {
        21: [(4, "cCCCCCCCCCCC")],
        22: [(4, "cCCCCCCCCCCC")],
        23: [(4, "cCCCCCCCCCiC")],
        24: [(5, "cCCCCCCCCCi")],
        25: [(5, "bBBBBBBBBBB")],
        26: [(5, "cCCCCCCCCCC")],
        27: [(5, "cCCCCCCCCCC")],
        28: [(5, "cCCCCCCCCCC")],
        29: [(5, "obBBBBBBBBB")],
    }
    _seg(front, tunic, pal, squash)
    for x, r in ((12, 22), (13, 23), (14, 24)):  # ice V on the chest
        front[(x, _row_y(r, squash))] = P["ICE"]
        front[(31 - x, _row_y(r, squash))] = P["ICE"]

    # Pale capelet wrapped round the neck, falling over the shoulders, soft folds;
    # lighter than Atom's own blue so it never blends into the body.
    shawl: SegArt = {
        17: [(4, "ohh")],
        18: [(3, "ohhIh")],
        19: [(2, "ohIIIhhhhhhhhh")],
        20: [(2, "oIIiIIIIIiIIII")],
        21: [(1, "oIIIiIIIiIIoooo")],
        22: [(1, "oiIIIiIooo")],
        23: [(2, "ooo")],
    }
    _seg(front, shawl, {"o": P["ICE_DK"], "I": P["ICE_HI"], "i": P["ICE"], "h": P["SILVER_HI"]}, squash)

    # Silver star pin on the right shoulder.
    for x, r, col in ((24, 18, "SILVER_HI"), (23, 19, "SILVER"), (24, 19, "GEM"), (25, 19, "SILVER"),
                      (22, 20, "SILVER"), (23, 20, "SILVER_HI"), (24, 20, "SILVER_HI"), (25, 20, "SILVER_HI"), (26, 20, "SILVER"),
                      (23, 21, "SILVER"), (24, 21, "SILVER_HI"), (25, 21, "SILVER"), (24, 22, "SILVER")):
        front[(x, _row_y(r, squash))] = P[col]
    return back, front


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------

# Coat sleeves over the upper arm: (highlight, fill, outline) palette names.
SLEEVES: Dict[str, Tuple[str, str, str]] = {
    "neon": ("NAVY_HI", "NAVY", "OUT"),
    "carbon": ("COAT_HI", "COAT", "OUT"),
}


def build_wardrobe_cells(variant: str = DEFAULT_VARIANT, **kwargs) -> Cells:
    """Drop-in replacement for `RV2._build_v2_cells` wearing `variant`'s outfit."""
    if variant not in VARIANTS:
        raise ValueError(f"Unknown wardrobe variant: {variant!r}")
    squash = int(kwargs.get("squash") or 0)
    arm_r = str(kwargs.get("arm_r") or "rest")
    typing_pose = bool(kwargs.get("typing_pose"))
    sleeping = kwargs.get("mood_tint") == "closed"
    shimmer_u = kwargs.get("beanie_shimmer_u")

    base = RV2._build_v2_cells(**kwargs)
    # Same pose without limbs: whatever differs is an arm or leg, painted on top of the outfit.
    bare = RV2._build_v2_cells(**{**kwargs, "arm_l": "none", "arm_r": "none", "typing_pose": False,
                                  "leg_l": "tuck", "leg_r": "tuck"})
    limbs = {k: v for k, v in base.items()
             if bare.get(k) != v and not (13 + squash <= k[1] <= 18 + squash and 9 <= k[0] <= 23)}

    if variant == "orchestrator":
        back, front = _orchestrator(squash, arm_r, typing_pose, sleeping)
        head = _crown_cells(variant, squash, base)
    elif variant == "carbon":
        back, front = _carbon(squash)
        head = _crown_cells(variant, squash, base)
    elif variant == "neon":
        back, front = _neon(squash, arm_r, typing_pose, sleeping)
        back.update(_neon_plume(squash))
        head = _neon_circlet(squash)
    else:
        back, front = _hydrogen(squash)
        head = _hydrogen_circlet(squash)
    _apply_shimmer(head, shimmer_u)

    out: Cells = {}
    for layer in (back, base, front, head):
        for k, col in layer.items():
            out[k] = _dim_closed(col) if (sleeping and layer is not base) else col
    out.update(limbs)
    if variant in SLEEVES:
        hi, fill, edge = (PALETTES[variant][n] for n in SLEEVES[variant])
        for left in (True, False):
            ax, ay = (4.5 if left else 26.5), 21.5 + squash
            arm = [k for k in limbs if k[1] < 26 + squash and (k[0] < 8 if left else k[0] > 23)]
            if not arm:
                continue
            dist = {k: math.hypot(k[0] - ax, k[1] - ay) for k in arm}
            cut = sorted(dist.values())[len(arm) // 2]
            for k in arm:
                if dist[k] < cut:
                    v = limbs[k]
                    col = edge if v == RV2.BODY_OUTLINE else (hi if v == RV2.BODY_BRIGHT else fill)
                    out[k] = _dim_closed(col) if sleeping else col
    return out


def build_wardrobe_sitting_cells(
    variant: str = DEFAULT_VARIANT,
    *,
    tap_phase: int = 0,
    blink: bool = False,
    squash: int = 0,
) -> Cells:
    """3/4 sitting typing pose (V2's own, beanie kept) wearing `variant`'s outfit."""
    if variant not in VARIANTS:
        raise ValueError(f"Unknown wardrobe variant: {variant!r}")
    base = RV2._build_v2_sitting_cells(tap_phase=tap_phase, blink=blink, squash=squash)
    body = {RV2.BODY_BRIGHT, RV2.BODY_MID, RV2.BODY_OUTLINE}

    # Paws and eyes are repainted last.
    p0, p1 = tap_phase % 2, (tap_phase + 1) % 2
    l_y, r_y = 22 + squash + p0, 21 + squash + p1
    keep_keys = {(14, l_y), (15, l_y), (15, l_y + 1), (16, l_y), (17, r_y), (18, r_y), (18, r_y + 1), (19, r_y)}
    keep = {k: base[k] for k in keep_keys if k in base}
    keep.update({k: v for k, v in base.items() if v in (RV2.EYE_BLACK, RV2.EYE_GLINT)})

    back: Cells = {}
    over: Cells = {}

    def recolour_torso(rows: range, fill: RGB, shade: RGB, out_c: RGB, edge: Optional[RGB] = None) -> None:
        for (c, yr), v in base.items():
            r = yr - (squash if yr - squash < 25 else 0)
            if r in rows and v in body:
                if v == RV2.BODY_OUTLINE:
                    over[(c, yr)] = out_c
                elif edge is not None and base.get((c - 1, yr)) == RV2.BODY_OUTLINE and c < 8:
                    over[(c, yr)] = edge
                else:
                    over[(c, yr)] = fill if v == RV2.BODY_BRIGHT else shade

    P = PALETTES[variant]
    sy = lambda r: r + (squash if r < 25 else 0)  # noqa: E731
    if variant == "orchestrator":
        head = _crown_cells(variant, squash, base, dx=-3, dy=-1, skip_cols=range(8, 11), pom_rows=3)
        for r in range(15, 28):
            lo = round(1 - 3 * (r - 15) / 12)
            for c in range(lo, 4):
                back[(c, sy(r))] = P["OUT"] if (c == lo or r == 27) else (P["ERMINE"] if r >= 25 else P["PURP"])
        for c in range(3, 11):
            over[(c, sy(17))] = P["ERMINE"] if c % 3 else P["FLECK"]
            over[(c, sy(18))] = P["ERMINE_SH"]
        for c, r in ((10, 19), (11, 20), (12, 21)):
            over[(c, sy(r))] = P["GOLD"]
    elif variant == "carbon":
        head = _crown_cells(variant, squash, base, dx=-3, dy=-1, skip_cols=range(8, 11), pom_rows=3)
        recolour_torso(range(19, 25), P["COAT"], P["COAT_DK"], P["OUT"], edge=P["COAT_HI"])
        for r in range(15, 28):
            lo = round(1 - 2 * (r - 15) / 12)
            for c in range(lo, 4):
                back[(c, sy(r))] = P["OUT"] if (c == lo or r == 27) else P["COAT_DK"]
        for r, (c0, c1) in {16: (1, 2), 17: (1, 3), 18: (1, 4)}.items():
            for c in range(c0, c1 + 1):
                over[(c, sy(r))] = P["OUT"] if c == c0 else (P["SILVER"] if c == c1 else P["COAT_HI"])
        for k in range(5):
            over[(5 + k, sy(19 + k))] = P["SILVER"]
    elif variant == "neon":
        head = _neon_circlet(squash, c0=4, c1=20, row=8, gem_c=9, curve=0)
        back.update(_neon_plume(squash, dx=-4, dy=-2))
        recolour_torso(range(19, 25), P["NAVY"], P["NAVY_DK"], P["OUT"], edge=P["MAG"])
        for c in range(5, 12):
            over[(c, sy(19))] = P["WHITE"] if c >= 8 else P["NAVY_HI"]
    else:  # hydrogen
        head = _hydrogen_circlet(squash, c0=3, c1=21, row=9, gem_c=10, curve=0)
        recolour_torso(range(19, 25), P["CREAM"], P["CREAM_SH"], P["CREAM_OUT"])
        for r, (c0, c1) in {17: (2, 12), 18: (2, 13), 19: (2, 11)}.items():
            for c in range(c0, c1 + 1):
                over[(c, sy(r))] = P["ICE_OUT"] if c in (c0, c1) else (P["ICE_HI"] if r == 17 else P["ICE"])
        for c in range(3, 12):
            if (c, sy(22)) in over:
                over[(c, sy(22))] = P["BAND"]
        for r in range(19, 27):
            back[(1, sy(r))] = P["ICE_OUT"]
            back[(2, sy(r))] = P["ICE"]
    _apply_shimmer(head, None)

    out: Cells = {}
    for layer in (back, base, over, head):
        out.update(layer)
    out.update(keep)
    return out


# Each outfit's orbiting sparkles (V2's five electrons), like the stars, shards,
# neon glints and ice motes around the figures in art/outfits.png.
ORB_COLORS: Dict[str, Tuple[RGB, ...]] = {
    "orchestrator": ((255, 236, 128), (248, 196, 56), (176, 92, 252), (255, 250, 236), (246, 48, 88)),
    "carbon": ((240, 242, 248), (190, 194, 206), (150, 104, 220), (124, 128, 142), (240, 242, 248)),
    "neon": ((40, 240, 220), (255, 56, 184), (176, 252, 84), (255, 112, 214), (176, 255, 246)),
    "hydrogen": ((184, 236, 250), (248, 250, 255), (110, 206, 232), (190, 250, 255), (206, 214, 228)),
}


def _themed(fn: Callable[[], Tuple], variant: str) -> Callable[[], Tuple]:
    def run() -> Tuple:
        electrons = RV2.R.ELECTRONS
        RV2.R.ELECTRONS = [dataclasses.replace(sp, color=tuple(v / 255.0 for v in ORB_COLORS[variant][i % 5]))
                           for i, sp in enumerate(electrons)]
        try:
            return fn()
        finally:
            RV2.R.ELECTRONS = electrons
    return run


def build_renderers(_RA=None, variant: str = DEFAULT_VARIANT) -> Dict[str, Callable[[], Tuple]]:
    """Build all 19 state renderers for `v2-wardrobe` wearing `variant`."""
    if variant not in VARIANTS:
        raise ValueError(f"Unknown wardrobe variant: {variant!r}")
    renderers = RV2.build_renderers(
        _RA,
        build_cells=lambda **kw: build_wardrobe_cells(variant, **kw),
        build_sitting_cells=lambda **kw: build_wardrobe_sitting_cells(variant, **kw),
    )
    return {state: _themed(fn, variant) for state, fn in renderers.items()}


validate_palettes()

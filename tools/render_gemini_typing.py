#!/usr/bin/env python3
"""Composite Atom (Gemini rainbow crown + minimal pixel electrons) onto base.gif.

Preserves base.gif's exact 30 frames (640x360 @ 10 fps = 3.0s loop), chubby pixel
aesthetics, organic motion, laptop, and pill bar verbatim, while replacing the
white dots with gemini.gif's scrolling rainbow crown and 4 minimal pixelated
Gemini electrons that form a calm loading wave during typing.
"""

from __future__ import annotations

import argparse
import math
import os
import shutil
import subprocess
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import cairo

W = 640
H = 360
BASE_N_FRAMES = 30
FPS = 10

# Extended 55-frame seamless playback sequence (5.5s @ 10 fps) from base.gif frames
BASE_SEQ: List[int] = (
    [0, 1, 2, 3, 4, 5, 4, 3, 4, 5]   # 10 frames (1.0s): smooth double hover idle
    + [6]                            #  1 frame  (0.1s): drop & laptop opens
    + list(range(7, 18))             # 11 frames (1.1s): typing cycle 1
    + list(range(8, 18))             # 10 frames (1.0s): typing cycle 2 (f17->f8 seamless)
    + list(range(8, 18))             # 10 frames (1.0s): typing cycle 3
    + [18, 19, 20, 21, 22, 23]       #  6 frames (0.6s): reach up & close laptop lid
    + [24, 24]                       #  2 frames (0.2s): cute held blink with closed laptop
    + [25, 26, 27, 28, 29]           #  5 frames (0.5s): float smoothly back to idle f0
)
OUT_FRAMES = len(BASE_SEQ)           # 55 frames
DURATION = OUT_FRAMES / float(FPS)   # 5.5s

ROOT = Path(__file__).resolve().parent.parent
ART_DIR = ROOT / "art"
BASE_GIF = str(ART_DIR / "base.gif")
GEMINI_GIF = str(ART_DIR / "gemini.gif")
DEFAULT_OUT = str(ART_DIR / "gemini_typing.gif")


@dataclass(frozen=True)
class ElectronSpec:
    name: str
    color: Tuple[float, float, float]
    tilt_deg: float
    rx: float
    ry: float
    rev: int
    phi0: float
    wave_x: float


def _rgb(r: int, g: int, b: int) -> Tuple[float, float, float]:
    return (r / 255.0, g / 255.0, b / 255.0)


# 5 vibrant Gemini colored pixel blobs (rev = +-2 over 5.5s = 2.75s/rev, calm & periodic)
ELECTRONS: List[ElectronSpec] = [
    ElectronSpec("cyan",   _rgb(100, 248, 255), -22.0, 86.0, 28.0, +2, math.radians(140.0), 364.0),
    ElectronSpec("blue",   _rgb(110, 192, 255), +20.0, 82.0, 26.0, -2, math.radians(210.0), 392.0),
    ElectronSpec("violet", _rgb(198, 146, 255), -12.0, 90.0, 30.0, +2, math.radians(280.0), 420.0),
    ElectronSpec("pink",   _rgb(255, 118, 230), +16.0, 86.0, 28.0, -2, math.radians(350.0), 448.0),
    ElectronSpec("yellow", _rgb(255, 236, 108), -26.0, 82.0, 24.0, +2, math.radians(60.0),  476.0),
]


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else (hi if x > hi else x)


def lerp(a: float, b: float, u: float) -> float:
    return a + (b - a) * u


def smoothstep(edge0: float, edge1: float, x: float) -> float:
    if edge1 == edge0:
        return 0.0
    u = clamp((x - edge0) / (edge1 - edge0))
    return u * u * (3.0 - 2.0 * u)


def dist_point_to_segment(
    px: float, py: float, x1: float, y1: float, x2: float, y2: float
) -> float:
    vx, vy = x2 - x1, y2 - y1
    wx, wy = px - x1, py - y1
    c1 = wx * vx + wy * vy
    if c1 <= 0.0:
        return math.hypot(px - x1, py - y1)
    c2 = vx * vx + vy * vy
    if c2 <= c1:
        return math.hypot(px - x2, py - y2)
    b = c1 / c2
    return math.hypot(px - (x1 + b * vx), py - (y1 + b * vy))


def median_int(vals: List[int]) -> int:
    s = sorted(vals)
    return s[len(s) // 2]


# ---------------------------------------------------------------------------
# Stage A: Load Raw RGB24 Frames from base.gif & gemini.gif
# ---------------------------------------------------------------------------

def load_gif_frames(gif_path: str) -> List[bytearray]:
    raw = subprocess.check_output(
        ["ffmpeg", "-v", "error", "-i", gif_path, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    )
    frame_bytes = W * H * 3
    if len(raw) != BASE_N_FRAMES * frame_bytes:
        raise RuntimeError(
            f"Expected {BASE_N_FRAMES} frames ({BASE_N_FRAMES * frame_bytes} bytes) from {gif_path}, "
            f"got {len(raw)} bytes"
        )
    return [bytearray(raw[i * frame_bytes:(i + 1) * frame_bytes]) for i in range(BASE_N_FRAMES)]


# ---------------------------------------------------------------------------
# Stage B: Track Head Box & Cleanly Erase Old White Electrons + Watermark
# ---------------------------------------------------------------------------

def track_base_head(rgb: bytearray) -> Tuple[int, int, int]:
    """Return (hx0, hx1, hy0) for Atom's blue head in base.gif frame."""
    hy0 = None
    hx0, hx1 = W, 0
    for y in range(105, 165):
        xs = []
        row_off = y * W * 3
        for x in range(340, 505):
            i = row_off + x * 3
            r, g, b = rgb[i], rgb[i + 1], rgb[i + 2]
            if b > 180 and r < 85 and g > 110:
                xs.append(x)
        if len(xs) >= 55:
            if hy0 is None:
                hy0 = y
            if y < hy0 + 18:
                hx0 = min(hx0, xs[0])
                hx1 = max(hx1, xs[-1])
    if hy0 is None:
        raise RuntimeError("Failed to track Atom head in base.gif frame")
    return hx0, hx1, hy0


def is_protected_laptop(f: int, x: int, y: int, r: int, g: int, b: int) -> bool:
    """Return True if pixel belongs to the grey pixel laptop on frames >= 6."""
    if f < 6:
        return False
    if r > 178 or abs(r - g) > 22 or abs(g - b) > 22:
        return False
    if 452 <= x <= 522 and 236 <= y <= 249:
        return True
    if 6 <= f <= 22 and dist_point_to_segment(x, y, 512.0, 245.0, 536.0, 190.0) <= 6.5:
        return True
    if f == 23 and dist_point_to_segment(x, y, 512.0, 245.0, 480.0, 202.0) <= 6.5:
        return True
    return False


def build_white_electron_mask(f: int, rgb: bytearray) -> bytearray:
    """Build 1-byte/px mask of white electron blobs and pale halos in base.gif."""
    mask = bytearray(W * H)
    for y in range(0, 247):
        row_off = y * W
        for x in range(0, W):
            i = (row_off + x) * 3
            r, g, b = rgb[i], rgb[i + 1], rgb[i + 2]
            if max(r, g, b) < 35:
                continue  # pure black background or black eyes
            if is_protected_laptop(f, x, y, r, g, b):
                continue

            in_body_dot = r > 72
            in_sky_dot = (
                b < 150
                and max(r, g, b) > 36
                and abs(r - g) < 30
                and abs(g - b) < 30
            )
            if in_body_dot or in_sky_dot:
                mask[row_off + x] = 1

    # 1px selective dilation into paler fringes while protecting eyes, pure bg, and laptop
    dilated = bytearray(mask)
    for y in range(1, 246):
        row_off = y * W
        for x in range(1, W - 1):
            idx = row_off + x
            if mask[idx]:
                continue
            has_nbr = (
                mask[idx - 1] or mask[idx + 1]
                or mask[idx - W] or mask[idx + W]
                or mask[idx - W - 1] or mask[idx - W + 1]
                or mask[idx + W - 1] or mask[idx + W + 1]
            )
            if not has_nbr:
                continue
            i = idx * 3
            r, g, b = rgb[i], rgb[i + 1], rgb[i + 2]
            if max(r, g, b) < 35:
                continue
            if is_protected_laptop(f, x, y, r, g, b):
                continue
            if r > 58 or (b < 140 and max(r, g, b) > 25 and not (b > 110 and b > r + 40)):
                dilated[idx] = 1
    return dilated


def bfs_nearest_fill(rgb: bytearray, mask: bytearray) -> None:
    """Inpaint remaining masked pixels in-place via multi-source BFS nearest clean pixel."""
    owner = [-1] * (W * H)
    q: deque[int] = deque()

    # Seed from unmasked boundary pixels touching at least one masked pixel
    for y in range(0, 247):
        row_off = y * W
        for x in range(0, W):
            idx = row_off + x
            if mask[idx]:
                continue
            touch = False
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < W and 0 <= ny < 247 and mask[ny * W + nx]:
                    touch = True
                    break
            if touch:
                owner[idx] = idx
                q.append(idx)

    while q:
        cur = q.popleft()
        cx = cur % W
        cy = cur // W
        src_idx = owner[cur]
        for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
            if 0 <= nx < W and 0 <= ny < 247:
                nidx = ny * W + nx
                if mask[nidx] and owner[nidx] == -1:
                    owner[nidx] = src_idx
                    q.append(nidx)

    updates: List[Tuple[int, int, int, int]] = []
    for idx in range(W * 247):
        if mask[idx]:
            src = owner[idx]
            if src >= 0:
                s3 = src * 3
                updates.append((idx * 3, rgb[s3], rgb[s3 + 1], rgb[s3 + 2]))
    for d3, r, g, b in updates:
        rgb[d3] = r
        rgb[d3 + 1] = g
        rgb[d3 + 2] = b


def clean_base_frames(
    base_frames: List[bytearray],
) -> Tuple[List[bytearray], List[Tuple[int, int, int]]]:
    """Erase bottom-right watermark and white electrons across all 30 base.gif frames."""
    cleaned = [bytearray(fr) for fr in base_frames]

    # 1. Remove bottom-right sparkle watermark
    for fr in cleaned:
        for y in range(275, H):
            row_off = y * W * 3
            for x in range(550, W):
                i = row_off + x * 3
                fr[i] = 0
                fr[i + 1] = 0
                fr[i + 2] = 0

    # 2. Track heads & build electron masks
    heads = [track_base_head(fr) for fr in cleaned]
    masks = [build_white_electron_mask(f, cleaned[f]) for f in range(BASE_N_FRAMES)]

    # Pose pools for temporal lookup
    idle_pool = [0, 1, 2, 3, 4, 5, 25, 26, 27, 28, 29]
    typing_pool = list(range(6, 19))
    reach_pool = [19, 20, 21, 22]

    pools: Dict[int, List[int]] = {}
    for f in idle_pool:
        pools[f] = sorted([p for p in idle_pool if p != f], key=lambda p: abs(p - f))
    for f in typing_pool:
        pools[f] = sorted([p for p in typing_pool if p != f], key=lambda p: abs(p - f))
    for f in reach_pool:
        pools[f] = sorted([p for p in reach_pool if p != f], key=lambda p: abs(p - f))
    pools[23] = sorted([25, 26, 27, 28, 29, 0, 1, 2], key=lambda p: abs(p - 23))
    pools[24] = sorted([25, 26, 27, 28, 29, 0, 1, 2], key=lambda p: abs(p - 24))

    # 3. Temporal + sky + spatial BFS fill
    for f in range(BASE_N_FRAMES):
        fr = cleaned[f]
        m = masks[f]
        hx0, hx1, hy0 = heads[f]
        rem_mask = bytearray(m)

        for y in range(0, 247):
            row_off = y * W
            for x in range(0, W):
                idx = row_off + x
                if not m[idx]:
                    continue

                # Far outside Atom's silhouette -> direct pure black sky
                in_arm_lap = (18 <= f <= 23) and (x >= 450 and y >= 175)
                outside_atom = (
                    (x < hx0 - 26 or x > hx1 + 26 or y < hy0 - 2 or y > hy0 + 115)
                    and not in_arm_lap
                )
                if outside_atom:
                    i3 = idx * 3
                    fr[i3] = 0
                    fr[i3 + 1] = 0
                    fr[i3 + 2] = 0
                    rem_mask[idx] = 0
                    continue

                # For close_blink frames (23, 24), only borrow inside torso interior below eyes
                if f in (23, 24):
                    in_torso_interior = (
                        (hx0 + 10 <= x <= hx1 - 10)
                        and (hy0 + 42 <= y <= hy0 + 74)
                    )
                    if not in_torso_interior:
                        continue

                # Look up head-relative coordinates across same-pose frames
                dx = x - hx0
                dy = y - hy0
                rs: List[int] = []
                gs: List[int] = []
                bs: List[int] = []
                for f2 in pools[f]:
                    hx0_2, _, hy0_2 = heads[f2]
                    x2 = hx0_2 + dx
                    y2 = hy0_2 + dy
                    if 0 <= x2 < W and 0 <= y2 < 247:
                        idx2 = y2 * W + x2
                        if not masks[f2][idx2]:
                            j3 = idx2 * 3
                            rs.append(base_frames[f2][j3])
                            gs.append(base_frames[f2][j3 + 1])
                            bs.append(base_frames[f2][j3 + 2])
                            if len(rs) >= 5:
                                break
                if rs:
                    i3 = idx * 3
                    fr[i3] = median_int(rs)
                    fr[i3 + 1] = median_int(gs)
                    fr[i3 + 2] = median_int(bs)
                    rem_mask[idx] = 0

        bfs_nearest_fill(fr, rem_mask)

    return cleaned, heads


# ---------------------------------------------------------------------------
# Stage C: Smooth gemini.gif Rainbow Hat Gradient Inside base.gif Contour
# ---------------------------------------------------------------------------

def sample_gemini_crowns(
    gemini_frames: List[bytearray],
) -> List[List[Tuple[int, int, int]]]:
    """Sample 19 smooth scrolling rainbow columns from each gemini.gif frame."""
    n_cols = 19
    crowns: List[List[Tuple[int, int, int]]] = []

    for f in range(BASE_N_FRAMES):
        rg = gemini_frames[f]
        gy0 = None
        for y in range(92, 130):
            row_off = y * W * 3
            cnt = 0
            for x in range(250, 395):
                i = row_off + x * 3
                if max(rg[i], rg[i + 1], rg[i + 2]) > 120:
                    cnt += 1
            if cnt >= 60:
                gy0 = y
                break
        if gy0 is None:
            gy0 = 104

        cols: List[Tuple[int, int, int] | None] = []
        for c in range(n_cols):
            cx0 = round(254.0 + c * (136.0 / n_cols))
            cx1 = round(254.0 + (c + 1) * (136.0 / n_cols))
            rs, gs, bs = [], [], []
            for y in range(gy0 + 6, min(H, gy0 + 18)):
                row_off = y * W * 3
                for x in range(cx0, max(cx0 + 1, cx1)):
                    i = row_off + x * 3
                    r, g, b = rg[i], rg[i + 1], rg[i + 2]
                    if min(r, g, b) > 205:
                        continue  # reject crossing white electron core
                    if max(r, g, b) < 70:
                        continue  # reject dark background
                    rs.append(r)
                    gs.append(g)
                    bs.append(b)
            if rs:
                cols.append((median_int(rs), median_int(gs), median_int(bs)))
            else:
                cols.append(None)

        for c in range(n_cols):
            if cols[c] is not None:
                continue
            lc = c - 1
            while lc >= 0 and cols[lc] is None:
                lc -= 1
            rc = c + 1
            while rc < n_cols and cols[rc] is None:
                rc += 1
            if lc >= 0 and rc < n_cols:
                u = (c - lc) / float(rc - lc)
                c0, c1 = cols[lc], cols[rc]
                cols[c] = (
                    round(lerp(c0[0], c1[0], u)),
                    round(lerp(c0[1], c1[1], u)),
                    round(lerp(c0[2], c1[2], u)),
                )
            elif lc >= 0:
                cols[c] = cols[lc]
            elif rc < n_cols:
                cols[c] = cols[rc]
            else:
                cols[c] = (67, 234, 239)

        crowns.append([col for col in cols if col is not None])
    return crowns


def interpolate_crown(
    crowns: List[List[Tuple[int, int, int]]],
    f_out: int,
    out_frames: int | None = None,
) -> List[Tuple[int, int, int]]:
    """Smoothly interpolate 19-column gemini.gif gradient across out_frames."""
    total = OUT_FRAMES if out_frames is None else out_frames
    g_pos = (f_out / float(total)) * float(BASE_N_FRAMES)
    gf0 = int(math.floor(g_pos)) % BASE_N_FRAMES
    gf1 = (gf0 + 1) % BASE_N_FRAMES
    u = g_pos - math.floor(g_pos)
    c0, c1 = crowns[gf0], crowns[gf1]
    return [
        (
            round(lerp(c0[i][0], c1[i][0], u)),
            round(lerp(c0[i][1], c1[i][1], u)),
            round(lerp(c0[i][2], c1[i][2], u)),
        )
        for i in range(len(c0))
    ]


def compute_head_top_contour(
    fg_rgb: bytearray, head: Tuple[int, int, int]
) -> Dict[int, int]:
    """Find median-smoothed topmost head pixel y per column x inside base.gif silhouette."""
    hx0, hx1, hy0 = head
    raw_top: Dict[int, int] = {}
    for x in range(max(0, hx0 - 1), min(W, hx1 + 2)):
        for y in range(max(0, hy0 - 2), min(H, hy0 + 15)):
            i = (y * W + x) * 3
            r, g, b = fg_rgb[i], fg_rgb[i + 1], fg_rgb[i + 2]
            if b > 110 and max(r, g, b) > 60:
                raw_top[x] = y
                break

    smooth_top: Dict[int, int] = {}
    for x in range(max(0, hx0 - 1), min(W, hx1 + 2)):
        vals = [raw_top[nx] for nx in range(x - 2, x + 3) if nx in raw_top]
        if vals:
            smooth_top[x] = median_int(vals)
    return smooth_top


def sample_smooth_gradient(
    crown_cols: List[Tuple[int, int, int]], pos: float
) -> Tuple[int, int, int]:
    """Sample smoothly across the 19-column gemini.gif gradient."""
    n = len(crown_cols)
    p = clamp(pos, 0.0, float(n - 1))
    i0 = int(math.floor(p))
    i1 = min(n - 1, i0 + 1)
    frac = p - i0
    c0, c1 = crown_cols[i0], crown_cols[i1]
    return (
        round(lerp(c0[0], c1[0], frac)),
        round(lerp(c0[1], c1[1], frac)),
        round(lerp(c0[2], c1[2], frac)),
    )


def paint_crown_on_frame(
    fg_rgb: bytearray,
    head: Tuple[int, int, int],
    crown_cols: List[Tuple[int, int, int]],
) -> None:
    """Paint smooth gemini.gif rainbow gradient strictly inside base.gif's head contour."""
    hx0, hx1, _ = head
    head_w = max(1.0, float(hx1 - hx0 + 1))
    n_cols = len(crown_cols)  # 19
    top_contour = compute_head_top_contour(fg_rgb, head)

    for x in range(max(0, hx0 - 1), min(W, hx1 + 2)):
        if x not in top_contour:
            continue
        top_y = top_contour[x]
        u_x = clamp((x - hx0) / head_w)
        hr, hg, hb = sample_smooth_gradient(crown_cols, u_x * float(n_cols - 1))
        is_outer_ear = (x <= hx0 + 7) or (x >= hx1 - 7)

        for dy in range(0, 15):
            y = top_y + dy
            if not (0 <= y < H):
                continue
            i = (y * W + x) * 3
            orig_r, orig_g, orig_b = fg_rgb[i], fg_rgb[i + 1], fg_rgb[i + 2]
            if orig_b <= 110 or max(orig_r, orig_g, orig_b) <= 60:
                continue  # strictly clipped to Atom's head blue pixels

            bevel = 0.78 if (orig_b < 215 or orig_g < 140) else 1.0
            if dy < 11:
                fg_rgb[i] = round(hr * bevel)
                fg_rgb[i + 1] = round(hg * bevel)
                fg_rgb[i + 2] = round(hb * bevel)
            elif is_outer_ear:
                fg_rgb[i] = round(hr * bevel)
                fg_rgb[i + 1] = round(hg * bevel)
                fg_rgb[i + 2] = round(hb * bevel)
            elif dy < 13:
                # Subtle crisp 2px forehead shadow under smooth gradient hat
                fg_rgb[i] = round(orig_r * 0.82)
                fg_rgb[i + 1] = round(orig_g * 0.82)
                fg_rgb[i + 2] = round(orig_b * 0.82)


# ---------------------------------------------------------------------------
# Stage D: Foreground Mask, Flat Pixel Blobs & Horizontal Loading Bar
# ---------------------------------------------------------------------------

def build_foreground_mask(
    rgb_with_crown: bytearray, head: Tuple[int, int, int]
) -> bytearray:
    """Build exact foreground mask (Atom + crown + laptop, plus black eye interiors)."""
    hx0, hx1, hy0 = head
    fg = bytearray(W * H)
    for y in range(0, 249):
        row_off = y * W
        in_eye_band = (hy0 + 15 <= y <= hy0 + 55)
        for x in range(0, W):
            i = (row_off + x) * 3
            r, g, b = rgb_with_crown[i], rgb_with_crown[i + 1], rgb_with_crown[i + 2]
            if max(r, g, b) > 26:
                fg[row_off + x] = 1
            elif in_eye_band and (hx0 + 10 <= x <= hx1 - 10):
                fg[row_off + x] = 1
    return fg


def get_wave_morph(t: float) -> float:
    """Smooth morph w in [0, 1] across 5.5s: 0=orbit, 1=horizontal loading bar (1.15..4.15s)."""
    if t < 0.80:
        return 0.0
    if t < 1.15:
        return smoothstep(0.80, 1.15, t)
    if t < 4.15:
        return 1.0
    if t < 4.60:
        return 1.0 - smoothstep(4.15, 4.60, t)
    return 0.0


def get_tracked_atom_center(
    t: float, heads: List[Tuple[int, int, int]]
) -> Tuple[float, float]:
    """Interpolate tracked Atom torso center smoothly across the 55-frame sequence."""
    pos = (t % DURATION) * FPS
    f0 = int(math.floor(pos)) % OUT_FRAMES
    f1 = (f0 + 1) % OUT_FRAMES
    u = pos - math.floor(pos)
    h0 = heads[BASE_SEQ[f0]]
    h1 = heads[BASE_SEQ[f1]]
    ax0 = 0.5 * (h0[0] + h0[1])
    ay0 = h0[2] + 50.0
    ax1 = 0.5 * (h1[0] + h1[1])
    ay1 = h1[2] + 50.0
    return lerp(ax0, ax1, u), lerp(ay0, ay1, u)


def size_index_from_score(score: float) -> int:
    """Map continuous score in [0, 1] to discrete base.gif blob size index 0..3."""
    if score < 0.22:
        return 0
    if score < 0.50:
        return 1
    if score < 0.78:
        return 2
    return 3


def loading_bar_score(k: int, tw: float) -> float:
    """Compute 2-cycle fill-left-to-right -> hold -> drain-left-to-right score for blob k."""
    if tw < 1.15:
        return 0.0
    if tw >= 4.15:
        return 0.0
    p = ((tw - 1.15) % 1.50) / 1.50  # 2 cycles across [1.15, 4.15)
    if p < 0.50:
        start_k = k * 0.075
        return smoothstep(start_k, start_k + 0.18, p)
    if p < 0.58:
        return 1.0
    dstart_k = 0.58 + k * 0.065
    return 1.0 - smoothstep(dstart_k, dstart_k + 0.16, p)


def electron_pos(
    k: int, t: float, heads: List[Tuple[int, int, int]]
) -> Tuple[float, float, float, float, int]:
    """Return (x, y, z, w, size_idx) for electron k at continuous time t."""
    tw = t % DURATION
    sp = ELECTRONS[k]
    ax, ay = get_tracked_atom_center(tw, heads)

    # 1. Calm 3D tilted elliptical orbit (rev = +-2 per 5.5s = 2.75s/rev)
    theta = sp.phi0 + sp.rev * 2.0 * math.pi * (tw / DURATION)
    lx = sp.rx * math.cos(theta)
    ly = sp.ry * math.sin(theta)
    ez = math.sin(theta)
    tilt = math.radians(sp.tilt_deg)
    ct, st = math.cos(tilt), math.sin(tilt)
    ox = ax + lx * ct - ly * st
    oy = ay + lx * st + ly * ct

    # 2. Straight horizontal loading bar directly above Atom's hat (y = 84)
    wy = 84.0
    bar_score = loading_bar_score(k, tw)

    # 3. Smooth outer-perimeter glide between orbit and horizontal loading bar
    w = get_wave_morph(tw)
    dx, dy = ox - ax, oy - ay
    dist = math.hypot(dx, dy) + 1e-6
    side_dir = -1.0 if sp.wave_x < ax else +1.0
    lower_boost = clamp((oy - (ay - 20.0)) / 50.0)
    push = (22.0 + 30.0 * lower_boost) * w * (1.0 - w)
    px = lerp(ox, sp.wave_x, w) + side_dir * push
    py = lerp(oy, wy, w) + (dy / dist) * 12.0 * w * (1.0 - w)
    pz = lerp(ez, 1.0, w)

    if w <= 0.01:
        if ez < -0.25:
            size_idx = 0
        elif ez < 0.15:
            size_idx = 1
        elif ez < 0.55:
            size_idx = 2
        else:
            size_idx = 3
    elif w >= 0.99:
        size_idx = size_index_from_score(bar_score)
    else:
        orbit_score = clamp((ez + 0.65) / 1.40)
        size_idx = size_index_from_score(lerp(orbit_score, bar_score, w))

    return px, py, pz, w, size_idx


def _snap2(v: float) -> int:
    return int(round(v / 2.0) * 2)


def draw_pixel_blob(
    ctx: cairo.Context, x: float, y: float, size_idx: int, sp: ElectronSpec
) -> None:
    """Draw a flat, crisp pixelated colored blob matching base.gif's exact blob shapes."""
    cx = _snap2(x)
    cy = _snap2(y)
    ctx.save()
    ctx.set_antialias(cairo.ANTIALIAS_NONE)
    ctx.set_source_rgb(*sp.color)

    if size_idx == 0:
        # 6x6 flat dot (exact base.gif small blob)
        ctx.rectangle(cx - 3, cy - 3, 6, 6)
        ctx.fill()
    elif size_idx == 1:
        # 10x10 flat pixel plus
        x0, y0 = cx - 5, cy - 5
        ctx.rectangle(x0 + 2, y0, 6, 10)
        ctx.fill()
        ctx.rectangle(x0, y0 + 2, 10, 6)
        ctx.fill()
    elif size_idx == 2:
        # 14x14 flat rounded pixel blob
        x0, y0 = cx - 7, cy - 7
        ctx.rectangle(x0 + 3, y0, 8, 14)
        ctx.fill()
        ctx.rectangle(x0, y0 + 3, 14, 8)
        ctx.fill()
        ctx.rectangle(x0 + 2, y0 + 1, 10, 12)
        ctx.fill()
    else:
        # 18x18 flat chunky rounded pixel blob (exact base.gif large blob silhouette)
        x0, y0 = cx - 9, cy - 9
        ctx.rectangle(x0 + 4, y0, 10, 18)
        ctx.fill()
        ctx.rectangle(x0, y0 + 4, 18, 10)
        ctx.fill()
        ctx.rectangle(x0 + 2, y0 + 2, 14, 14)
        ctx.fill()

    ctx.restore()


def draw_pixel_trail_dots(
    ctx: cairo.Context, k: int, t: float, behind_pass: bool,
    heads: List[Tuple[int, int, int]]
) -> None:
    """Draw 1 crisp 4x4 trailing pixel dot in settled idle orbit (none during loading bar)."""
    tw = t % DURATION
    if 0.80 <= tw < 4.85:
        return
    sp = ELECTRONS[k]
    ts = (t - 0.18) % DURATION
    px, py, pz, _, _ = electron_pos(k, ts, heads)
    if behind_pass and pz >= 0.0:
        return
    if (not behind_pass) and pz < 0.0:
        return
    ctx.save()
    ctx.set_antialias(cairo.ANTIALIAS_NONE)
    ctx.set_source_rgb(*sp.color)
    ctx.rectangle(_snap2(px) - 2, _snap2(py) - 2, 4, 4)
    ctx.fill()
    ctx.restore()


# ---------------------------------------------------------------------------
# Surface Conversion & Frame Compositing
# ---------------------------------------------------------------------------

def rgb24_to_cairo_bgra(rgb: bytearray, mask: bytearray | None = None) -> cairo.ImageSurface:
    """Create a Cairo FORMAT_ARGB32 surface from an RGB24 buffer (with optional binary mask)."""
    buf = bytearray(W * H * 4)
    for idx in range(W * H):
        i3 = idx * 3
        i4 = idx * 4
        if mask is None or mask[idx]:
            buf[i4] = rgb[i3 + 2]      # B
            buf[i4 + 1] = rgb[i3 + 1]  # G
            buf[i4 + 2] = rgb[i3]      # R
            buf[i4 + 3] = 255          # A
        else:
            buf[i4] = 0
            buf[i4 + 1] = 0
            buf[i4 + 2] = 0
            buf[i4 + 3] = 0
    return cairo.ImageSurface.create_for_data(buf, cairo.FORMAT_ARGB32, W, H)


def composite_and_render(
    clean_frames: List[bytearray],
    heads: List[Tuple[int, int, int]],
    crowns: List[List[Tuple[int, int, int]]],
    out_dir: str,
    transparent_bg: bool = False,
) -> None:
    """Render all 55 composited frames (640x360) into out_dir."""
    for f in range(OUT_FRAMES):
        bf = BASE_SEQ[f]
        t = f / float(FPS)
        base_clean = clean_frames[bf]
        fg_rgb = bytearray(base_clean)
        crown_cols = interpolate_crown(crowns, f)
        paint_crown_on_frame(fg_rgb, heads[bf], crown_cols)
        fg_mask = build_foreground_mask(fg_rgb, heads[bf])

        if transparent_bg:
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
        else:
            surf = rgb24_to_cairo_bgra(base_clean)
        ctx = cairo.Context(surf)

        states = []
        for k in range(len(ELECTRONS)):
            px, py, pz, _, size_idx = electron_pos(k, t, heads)
            states.append((pz, k, px, py, size_idx))
        states.sort(key=lambda item: item[0])

        # 1. Back-pass pixel blobs & trailing dot (behind Atom)
        for pz, k, px, py, size_idx in states:
            draw_pixel_trail_dots(ctx, k, t, behind_pass=True, heads=heads)
            if pz < 0.0:
                draw_pixel_blob(ctx, px, py, size_idx, ELECTRONS[k])

        # 2. Composite Atom + Gradient Hat + Laptop (masked over back blobs)
        fg_surf = rgb24_to_cairo_bgra(fg_rgb, fg_mask)
        ctx.save()
        ctx.set_operator(cairo.OPERATOR_OVER)
        ctx.set_source_surface(fg_surf, 0, 0)
        ctx.paint()
        ctx.restore()

        # 3. Front-pass pixel blobs & trailing dot (in front of Atom)
        for pz, k, px, py, size_idx in states:
            draw_pixel_trail_dots(ctx, k, t, behind_pass=False, heads=heads)
            if pz >= 0.0:
                draw_pixel_blob(ctx, px, py, size_idx, ELECTRONS[k])

        surf.write_to_png(os.path.join(out_dir, f"frame_{f:03d}.png"))


def encode_gif(frames_dir: str, out_gif: str) -> None:
    """Encode 55 PNGs into an exact 10 fps (10cs delay) crisp pixel GIF."""
    pattern = os.path.join(frames_dir, "frame_%03d.png")
    palette = os.path.join(frames_dir, "palette.png")
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-framerate", str(FPS), "-i", pattern,
            "-vf", "palettegen=max_colors=256:stats_mode=diff:reserve_transparent=0",
            palette,
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-framerate", str(FPS), "-i", pattern,
            "-i", palette,
            "-lavfi", f"fps={FPS} [x]; [x][1:v] paletteuse=dither=none:diff_mode=rectangle",
            "-loop", "0", out_gif,
        ],
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Composite 5.5s Gemini pixel loading-bar onto base.gif.")
    parser.add_argument("--out", default="", help="Output GIF path (default: gemini_typing.gif unless --rgba-dir is sole output)")
    parser.add_argument("--rgba-dir", default="", help="Optional dir to write transparent 32-bit RGBA PNG frames directly")
    parser.add_argument("--work-dir", default="/tmp/atom_v2_render", help="Temp frame dir")
    parser.add_argument("--save-clean-dir", default="", help="Optional dir to dump cleaned base PNGs")
    parser.add_argument("--keep-frames", action="store_true", help="Keep rendered PNGs")
    args = parser.parse_args()

    out_gif = args.out or ("" if args.rgba_dir else DEFAULT_OUT)
    base_frames = load_gif_frames(BASE_GIF)
    gemini_frames = load_gif_frames(GEMINI_GIF)

    clean_frames, heads = clean_base_frames(base_frames)
    if args.save_clean_dir:
        os.makedirs(args.save_clean_dir, exist_ok=True)
        for f in range(BASE_N_FRAMES):
            s = rgb24_to_cairo_bgra(clean_frames[f])
            s.write_to_png(os.path.join(args.save_clean_dir, f"clean_{f:02d}.png"))

    crowns = sample_gemini_crowns(gemini_frames)
    if args.rgba_dir:
        os.makedirs(args.rgba_dir, exist_ok=True)
        composite_and_render(clean_frames, heads, crowns, args.rgba_dir, transparent_bg=True)
        print(f"Rendered {OUT_FRAMES} transparent RGBA frames @ {FPS} fps -> {args.rgba_dir}")

    if out_gif:
        os.makedirs(args.work_dir, exist_ok=True)
        composite_and_render(clean_frames, heads, crowns, args.work_dir)
        encode_gif(args.work_dir, out_gif)
        if not args.keep_frames:
            shutil.rmtree(args.work_dir, ignore_errors=True)
        print(f"Rendered {OUT_FRAMES} frames @ {FPS} fps ({DURATION:.1f}s) -> {out_gif}")


if __name__ == "__main__":
    main()

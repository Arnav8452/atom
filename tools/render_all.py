#!/usr/bin/env python3
"""Unified code-generated sprite sheet renderer for all 17 Atom states.

Generates every state programmatically onto transparent 32-bit RGBA surfaces
using base.gif's clean body silhouette, thin scrolling rainbow crown, and
crisp pixel art props/electrons, then encodes lossless WebP sprite sheets +
loop metadata into assets/atom/.

Usage:
  python3 tools/render_all.py               # rebuild all 17 states
  python3 tools/render_all.py idle angry    # rebuild specific states

Needs only stdlib + python-cairo + ffmpeg.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import cairo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import tools.render_gemini_typing as R  # noqa: E402
import tools.render_idle as RI  # noqa: E402

W, H, FPS = R.W, R.H, R.FPS
OUT_DIR = ROOT / "assets" / "atom"

FRAME_W, FRAME_H = 150, 120
COLS = 10
CROP_W, CROP_H = 300, 240
CENTER_X = 417
FEET_Y = 222
FEET_MARGIN = 18
CROP_LEFT = CENTER_X - CROP_W // 2        # 267
CROP_TOP = 12  # y in [12, 252): preserves full laptop base (y=248) with headroom above

EYE_RGB = (10, 14, 20)
HOVER_10 = [0, 1, 2, 3, 3, 4, 4, 5, 1, 0]
IDLE_REV = (+1, -1, +1, -1, +1)
THINK_REV = (+1, -1, +1, -1, +1)
THINK_TILTS = (-34.0, +38.0, -18.0, +44.0, -42.0)

TYPING_INTRO_SEQ = [0, 1, 2, 4, 5, 6, 7]
TYPING_LOOP_SEQ = list(range(8, 18)) * 3
TYPING_OUTRO_SEQ = [18, 19, 20, 21, 22, 23, 24, 24, 25, 26, 27, 28, 29]


def _rgb(r: int, g: int, b: int) -> Tuple[float, float, float]:
    return (r / 255.0, g / 255.0, b / 255.0)


def _rgb_to_hsv(r: int, g: int, b: int) -> Tuple[float, float, float]:
    mx = max(r, g, b)
    mn = min(r, g, b)
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


def sample_crown_at_phase(
    crowns: List[List[Tuple[int, int, int]]], phase: float
) -> List[Tuple[int, int, int]]:
    """Sample smoothly across the 30-frame rainbow crown loop for phase in [0, 1)."""
    n = len(crowns)
    pos = (phase % 1.0) * n
    i0 = int(math.floor(pos)) % n
    i1 = (i0 + 1) % n
    u = pos - math.floor(pos)
    c0, c1 = crowns[i0], crowns[i1]
    return [
        (
            round(R.lerp(c0[j][0], c1[j][0], u)),
            round(R.lerp(c0[j][1], c1[j][1], u)),
            round(R.lerp(c0[j][2], c1[j][2], u)),
        )
        for j in range(len(c0))
    ]


def tint_body_rgb(
    fg_rgb: bytearray,
    head: Tuple[int, int, int],
    body_hue: float,
    body_sat: float = 1.0,
    body_val: float = 1.0,
    rest_sat: float = 1.0,
    rest_val: float = 1.0,
    top_contour: Dict[int, int] | None = None,
    blend: float = 1.0,
) -> None:
    """Recolor Atom's blue body pixels below the rainbow crown while leaving beanie intact."""
    if blend <= 0.0:
        return
    hx0, hx1, _ = head
    if top_contour is None:
        top_contour = R.compute_head_top_contour(fg_rgb, head)
    for y in range(0, 249):
        row_off = y * W
        for x in range(max(0, hx0 - 25), min(W, hx1 + 25)):
            if x in top_contour:
                depth = 15 if (x <= hx0 + 7 or x >= hx1 - 7) else 11
                if y < top_contour[x] + depth:
                    continue  # preserve rainbow beanie
            i = (row_off + x) * 3
            r, g, b = fg_rgb[i], fg_rgb[i + 1], fg_rgb[i + 2]
            if max(r, g, b) < 35:
                continue
            h, s, v = _rgb_to_hsv(r, g, b)
            if 196.0 <= h <= 226.0 and s > 0.35:
                tr, tg, tb = _hsv_to_rgb(body_hue, R.clamp(s * body_sat), R.clamp(v * body_val))
            else:
                tr, tg, tb = _hsv_to_rgb(h, R.clamp(s * rest_sat), R.clamp(v * rest_val))
            if blend >= 1.0:
                fg_rgb[i], fg_rgb[i + 1], fg_rgb[i + 2] = tr, tg, tb
            else:
                # Blend in RGB so hue shifts (e.g. blue -> red) warm cleanly without passing through green.
                fg_rgb[i] = round(R.lerp(r, tr, blend))
                fg_rgb[i + 1] = round(R.lerp(g, tg, blend))
                fg_rgb[i + 2] = round(R.lerp(b, tb, blend))


def tuck_legs(fg_rgb: bytearray, head: Tuple[int, int, int], retract_u: float) -> None:
    """Smoothly pull Atom's pixel legs up into the torso bottom (and back out)."""
    if retract_u <= 0.0:
        return
    hx0, hx1, hy0 = head
    leg_top = hy0 + 85
    leg_bot = hy0 + 103
    shift = round(R.clamp(retract_u) * 16)
    if shift > 0 and retract_u < 1.0:
        for y in range(leg_top, leg_bot - shift):
            sy = y + shift
            if sy >= H:
                continue
            for x in (*range(372, 405), *range(434, 470)):
                si = (sy * W + x) * 3
                _set_px(fg_rgb, x, y, (fg_rgb[si], fg_rgb[si + 1], fg_rgb[si + 2]))
    cutoff = leg_top + max(0, 16 - shift)
    for y in range(cutoff, min(H, leg_bot + 2)):
        for x in range(max(0, hx0 - 10), min(W, hx1 + 10)):
            _set_px(fg_rgb, x, y, (0, 0, 0))
    if retract_u >= 0.85:
        # Clean rounded dark edge along flat torso bottom (matches tucked silhouette)
        for x in range(369, 467):
            i = ((leg_top - 1) * W + x) * 3
            if max(fg_rgb[i], fg_rgb[i + 1], fg_rgb[i + 2]) > 40:
                _set_px(
                    fg_rgb, x, leg_top - 1,
                    (round(fg_rgb[i] * 0.72), round(fg_rgb[i + 1] * 0.72), round(fg_rgb[i + 2] * 0.72)),
                )


def _set_px(fg_rgb: bytearray, x: int, y: int, rgb: Tuple[int, int, int]) -> None:
    if 0 <= x < W and 0 <= y < H:
        idx = (y * W + x) * 3
        fg_rgb[idx] = rgb[0]
        fg_rgb[idx + 1] = rgb[1]
        fg_rgb[idx + 2] = rgb[2]


def paint_eyes(
    fg_rgb: bytearray, head: Tuple[int, int, int], mode: str, dx: int = 0, dy: int = 0
) -> None:
    """Replace open hover eyes on base.gif frames 0..5 with expressive pixel eyes."""
    _, _, hy0 = head
    for y in range(hy0 + 26, hy0 + 47):
        mid = (y * W + 412) * 3
        sr, sg, sb = fg_rgb[mid], fg_rgb[mid + 1], fg_rgb[mid + 2]
        for x in (*range(377, 394), *range(431, 448)):
            _set_px(fg_rgb, x, y, (sr, sg, sb))

    left_cx, right_cx, eye_cy = 385 + dx, 439 + dx, hy0 + 35 + dy

    if mode == "blink":
        for y in range(hy0 + 36, hy0 + 40):
            for x in (*range(378, 393), *range(432, 447)):
                _set_px(fg_rgb, x, y, EYE_RGB)
    elif mode == "sleep":
        for y in range(hy0 + 39, hy0 + 42):
            for x in (*range(378, 393), *range(432, 447)):
                _set_px(fg_rgb, x, y, EYE_RGB)
    elif mode == "look":
        for y in range(hy0 + 28 + dy, hy0 + 43 + dy):
            for x in (*range(378 + dx, 393 + dx), *range(432 + dx, 447 + dx)):
                _set_px(fg_rgb, x, y, EYE_RGB)
    elif mode == "happy":
        for cx in (left_cx, right_cx):
            for ox in range(-6, 7):
                for oy in range(-4, -1):
                    _set_px(fg_rgb, cx + ox, eye_cy + oy, EYE_RGB)
            for oy in range(-1, 3):
                for ox in (*range(-7, -4), *range(5, 8)):
                    _set_px(fg_rgb, cx + ox, eye_cy + oy, EYE_RGB)
    elif mode == "sad":
        for cx, slope in ((left_cx, -1), (right_cx, 1)):
            for ox in range(-7, 8):
                top_cut = max(0, (ox * slope + 7) // 3)
                for oy in range(-3 + top_cut, 6):
                    _set_px(fg_rgb, cx + ox, eye_cy + oy, EYE_RGB)
    elif mode == "angry":
        # Intense narrowed eyes + furrowed \ / pixel brows
        for cx, slope in ((left_cx, 1), (right_cx, -1)):
            for ox in range(-7, 8):
                for oy in range(-1, 8):
                    _set_px(fg_rgb, cx + ox, eye_cy + oy, EYE_RGB)
                brow_y = eye_cy - 6 + round(slope * ox * 0.45)
                for by in range(brow_y, brow_y + 3):
                    _set_px(fg_rgb, cx + ox, by, EYE_RGB)
    elif mode == "error":
        for cx in (left_cx, right_cx):
            for iy in range(15):
                for ix in range(15):
                    if abs(ix - iy) <= 1 or abs(ix + iy - 14) <= 1:
                        _set_px(fg_rgb, cx - 7 + ix, eye_cy - 7 + iy, EYE_RGB)
    elif mode == "surprised":
        for cx in (left_cx, right_cx):
            for iy in range(15):
                for ix in range(15):
                    if ix < 3 or ix >= 12 or iy < 3 or iy >= 12:
                        _set_px(fg_rgb, cx - 7 + ix, eye_cy - 7 + iy, EYE_RGB)
    elif mode == "tired":
        for cx in (left_cx, right_cx):
            for ox in range(-7, 8):
                for oy in range(1, 8):
                    _set_px(fg_rgb, cx + ox, eye_cy + oy, EYE_RGB)
                _set_px(fg_rgb, cx + ox, eye_cy + 10, (32, 82, 130))


def torso_center(head: Tuple[int, int, int]) -> Tuple[float, float]:
    hx0, hx1, hy0 = head
    return 0.5 * (hx0 + hx1), hy0 + 50.0


def head_orbit_center(head: Tuple[int, int, int]) -> Tuple[float, float]:
    hx0, hx1, hy0 = head
    return 0.5 * (hx0 + hx1), hy0 + 28.0


def orbit_point(
    ax: float, ay: float, rx: float, ry: float, tilt_deg: float, theta: float
) -> Tuple[float, float, float]:
    lx = rx * math.cos(theta)
    ly = ry * math.sin(theta)
    ez = math.sin(theta)
    tilt = math.radians(tilt_deg)
    ct, st = math.cos(tilt), math.sin(tilt)
    return ax + lx * ct - ly * st, ay + lx * st + ly * ct, ez


def size_from_ez(ez: float) -> int:
    if ez < -0.25:
        return 0
    if ez < 0.15:
        return 1
    if ez < 0.55:
        return 2
    return 3


def draw_square(
    ctx: cairo.Context, x: float, y: float, size: int, color: Tuple[float, float, float]
) -> None:
    half = size // 2
    ctx.save()
    ctx.set_antialias(cairo.ANTIALIAS_NONE)
    ctx.set_source_rgb(*color)
    ctx.rectangle(R._snap2(x) - half, R._snap2(y) - half, size, size)
    ctx.fill()
    ctx.restore()


def draw_sparkle_plus(
    ctx: cairo.Context, x: float, y: float, arm: int, color: Tuple[float, float, float]
) -> None:
    if arm <= 0:
        return
    cx, cy = R._snap2(x), R._snap2(y)
    ctx.save()
    ctx.set_antialias(cairo.ANTIALIAS_NONE)
    ctx.set_source_rgb(*color)
    ctx.rectangle(cx - 1, cy - arm, 2, arm * 2)
    ctx.fill()
    ctx.rectangle(cx - arm, cy - 1, arm * 2, 2)
    ctx.fill()
    ctx.restore()


def draw_pixel_rect(
    ctx: cairo.Context, x: int, y: int, w: int, h: int, color: Tuple[float, float, float], alpha: float = 1.0
) -> None:
    ctx.save()
    ctx.set_antialias(cairo.ANTIALIAS_NONE)
    ctx.set_source_rgba(color[0], color[1], color[2], alpha)
    ctx.rectangle(x, y, w, h)
    ctx.fill()
    ctx.restore()


def render_frame(
    base_clean: bytearray,
    head: Tuple[int, int, int],
    crown_cols: List[Tuple[int, int, int]],
    blobs: Sequence[Tuple[float, float, float, int, int]] = (),
    trails: Sequence[Tuple[float, float, float, int, int]] = (),
    sparkles: Sequence[Tuple[float, float, float, int, Tuple[float, float, float]]] = (),
    eye_spec: Tuple[str, int, int] | None = None,
    tint: Tuple[float, float, float, float, float] | None = None,
    tint_blend: float = 1.0,
    leg_retract: float = 0.0,
    back_fn=None,
    front_fn=None,
    body_offset: Tuple[int, int] = (0, 0),
    custom_colors: Sequence[Tuple[float, float, float]] | None = None,
    overlay_fn=None,
) -> cairo.ImageSurface:
    """Composite one transparent 640x360 RGBA frame (back -> character -> front -> overlay)."""
    fg_rgb = bytearray(base_clean)
    top_contour = R.compute_head_top_contour(fg_rgb, head) if (tint is not None and tint_blend > 0.0) else None
    R.paint_crown_on_frame(fg_rgb, head, crown_cols)
    if tint is not None and tint_blend > 0.0:
        tint_body_rgb(fg_rgb, head, *tint, top_contour=top_contour, blend=tint_blend)
    if eye_spec is not None:
        paint_eyes(fg_rgb, head, *eye_spec)
    if leg_retract > 0.0:
        tuck_legs(fg_rgb, head, leg_retract)
    fg_mask = R.build_foreground_mask(fg_rgb, head)

    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surf)
    palette = custom_colors if custom_colors is not None else [sp.color for sp in R.ELECTRONS]

    def draw_blob_color(px: float, py: float, sidx: int, col: Tuple[float, float, float]) -> None:
        sp = R.ELECTRONS[0]
        fake = type(sp)(sp.name, col, 0, 0, 0, 1, 0, 0)
        R.draw_pixel_blob(ctx, px, py, sidx, fake)

    # 1. Back pass
    if back_fn is not None:
        back_fn(ctx)
    for pz, k, px, py, size_px in trails:
        if pz < 0.0:
            draw_square(ctx, px, py, size_px, palette[k])
    for pz, k, px, py, size_idx in blobs:
        if pz < 0.0:
            draw_blob_color(px, py, size_idx, palette[k])
    for pz, sx, sy, arm, col in sparkles:
        if pz < 0.0:
            draw_sparkle_plus(ctx, sx, sy, arm, col)

    # 2. Foreground character + thin crown (+ optional offset)
    fg_surf = R.rgb24_to_cairo_bgra(fg_rgb, fg_mask)
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_OVER)
    ctx.set_source_surface(fg_surf, body_offset[0], body_offset[1])
    ctx.paint()
    ctx.restore()

    # 3. Front pass
    for pz, k, px, py, size_px in trails:
        if pz >= 0.0:
            draw_square(ctx, px, py, size_px, palette[k])
    for pz, k, px, py, size_idx in blobs:
        if pz >= 0.0:
            draw_blob_color(px, py, size_idx, palette[k])
    for pz, sx, sy, arm, col in sparkles:
        if pz >= 0.0:
            draw_sparkle_plus(ctx, sx, sy, arm, col)
    if front_fn is not None:
        front_fn(ctx)

    if overlay_fn is not None:
        overlay_fn(ctx)

    return surf


def _safe_copy_surface(surf: cairo.ImageSurface) -> cairo.ImageSurface:
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(out)
    ctx.set_source_surface(surf, 0, 0)
    ctx.paint()
    return out


def render_idle(
    base: List[bytearray],
    clean: List[bytearray],
    heads: List[Tuple[int, int, int]],
    crowns: List[List[Tuple[int, int, int]]],
) -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
    """Authentic base.gif organic revolving electrons on clean hover body + thin beanie."""
    n = len(base)
    anchors = [RI.head_anchor(h) for h in heads]
    pixels = [RI.electron_pixels(f, base[f]) for f in range(n)]
    frame_blobs = [RI.blobs(p) for p in pixels]
    colours = RI.assign_colours(frame_blobs, anchors)
    body_seq = HOVER_10 * 3

    frames: List[cairo.ImageSurface] = []
    for f in range(n):
        bf = body_seq[f]
        rgb = bytearray(clean[bf])
        if f in (14, 15):
            paint_eyes(rgb, heads[bf], "blink")
        crown_cols = sample_crown_at_phase(crowns, f / float(n))
        surf = RI.render_rgba_frame(
            rgb,
            heads[bf],
            crown_cols,
            frame_blobs[f],
            colours[f],
            pixels[f],
            anchors[f],
            anchors[bf],
        )
        frames.append(_safe_copy_surface(surf))
    return frames, (0, n - 1)


def _draw_pixel_gear(
    ctx: cairo.Context, cx: int, cy: int, radius: int, angle: float,
    color: Tuple[float, float, float], alpha: float = 1.0
) -> None:
    """Draw a crisp 8-tooth pixel-art cogwheel with hollow hub."""
    if alpha <= 0.05:
        return
    r_inner = max(3, radius - 3)
    # Draw body pixels within radius, with 8 protruding teeth
    for dy in range(-radius - 2, radius + 3):
        for dx in range(-radius - 2, radius + 3):
            dist = math.hypot(dx, dy)
            if dist <= 2.4:
                continue  # hollow axle hole
            theta = math.atan2(dy, dx) - angle
            tooth = math.cos(8.0 * theta) > 0.25
            r_lim = (radius + 2.0) if tooth else float(r_inner)
            if dist <= r_lim:
                draw_pixel_rect(ctx, cx + dx * 2 - 1, cy + dy * 2 - 1, 2, 2, color, alpha)


def _draw_square_px(
    ctx: cairo.Context, x: float, y: float, size: int,
    color: Tuple[float, float, float], alpha: float = 1.0
) -> None:
    if alpha <= 0.02:
        return
    half = size // 2
    draw_pixel_rect(ctx, R._snap2(x) - half, R._snap2(y) - half, size, size, color, alpha)


def apply_beanie_shimmer(
    crown_cols: List[Tuple[int, int, int]], wave_u: float, intensity: float = 1.0
) -> List[Tuple[int, int, int]]:
    """Sweep a soft left-to-right neural light shimmer across the rainbow beanie."""
    if intensity <= 0.0:
        return crown_cols
    edge = R.smoothstep(0.0, 0.12, wave_u) * R.smoothstep(0.0, 0.12, 1.0 - wave_u)
    if edge <= 0.0:
        return crown_cols
    wave_pos = -0.25 + 1.5 * wave_u
    n = max(1, len(crown_cols) - 1)
    out = []
    for j, col in enumerate(crown_cols):
        x_norm = j / float(n)
        g = math.exp(-((x_norm - wave_pos) / 0.16) ** 2) * intensity * edge
        out.append(tuple(min(255, round(c + (255 - c) * 0.52 * g)) for c in col))
    return out


def _thinking_electron_at(
    k: int, w: float, theta: float, head: Tuple[int, int, int]
) -> Tuple[float, float, float]:
    sp = R.ELECTRONS[k]
    ax0, ay0 = torso_center(head)
    ax1, ay1 = head_orbit_center(head)
    ax = R.lerp(ax0, ax1, w)
    ay = R.lerp(ay0, ay1, w)
    rx = R.lerp(sp.rx, sp.rx + 12.0, w)
    ry = R.lerp(sp.ry, sp.ry + 4.0, w)
    tilt = R.lerp(sp.tilt_deg, THINK_TILTS[k], w)
    return orbit_point(ax, ay, rx, ry, tilt, theta)


def render_thinking(
    clean: List[bytearray],
    heads: List[Tuple[int, int, int]],
    crowns: List[List[Tuple[int, int, int]]],
) -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
    """Sky-blue Atom with tucked legs during thinking, slow elevated orbits, and head sparkles."""
    n_intro, n_loop, n_outro = 7, 30, 7
    total = n_intro + n_loop + n_outro
    body_seq = [0, 1, 2, 3, 3, 4, 5] + (HOVER_10 * 3) + [5, 4, 3, 2, 1, 1, 0]

    frames: List[cairo.ImageSurface] = []
    for f in range(total):
        bf = body_seq[f]
        head = heads[bf]
        if f < n_intro:
            u_in = f / float(n_intro)
            w = R.smoothstep(0.0, 1.0, u_in)
            crown_phase = 0.25 * u_in
            eye_spec = ("look", 4, -5) if f >= 3 else None
        elif f < n_intro + n_loop:
            fl = f - n_intro
            u_loop = fl / float(n_loop)
            w = 1.0
            crown_phase = (0.25 + 1.0 * u_loop) % 1.0
            if fl < 14:
                eye_spec = ("look", 4, -5)
            elif fl == 14:
                eye_spec = ("blink", 0, 0)
            elif fl < 28:
                eye_spec = ("look", -4, -5)
            else:
                eye_spec = ("look", 2, -5)
        else:
            fo = f - (n_intro + n_loop)
            u_out = fo / float(n_outro)
            w = 1.0 - R.smoothstep(0.0, 1.0, u_out)
            crown_phase = (0.25 + 0.75 * u_out) % 1.0
            eye_spec = ("look", 2, -3) if fo < 3 else None

        blobs, trails = [], []
        for k, sp in enumerate(R.ELECTRONS):
            sign = 1.0 if THINK_REV[k] >= 0 else -1.0

            def eval_theta(frame_offset: float) -> float:
                ff = f + frame_offset
                if ff < 0:
                    return sp.phi0 + IDLE_REV[k] * 2.0 * math.pi * (ff / 30.0)
                if ff < n_intro:
                    return sp.phi0 + sign * 0.5 * math.pi * (ff / float(n_intro))
                if ff < n_intro + n_loop:
                    ul = (ff - n_intro) / float(n_loop)
                    return sp.phi0 + sign * 0.5 * math.pi + THINK_REV[k] * 2.0 * math.pi * ul
                if ff < total:
                    uo = (ff - (n_intro + n_loop)) / float(n_outro)
                    return (
                        sp.phi0
                        + sign * 0.5 * math.pi
                        + THINK_REV[k] * 2.0 * math.pi
                        + sign * 0.5 * math.pi * uo
                    )
                return sp.phi0 + sign * 1.0 * math.pi + THINK_REV[k] * 2.0 * math.pi

            px, py, ez = _thinking_electron_at(k, w, eval_theta(0.0), head)
            sidx = 3 if (w > 0.5 and ez > 0.25) else size_from_ez(ez)
            blobs.append((ez, k, px, py, sidx))

            if w >= 0.35:
                for step_idx, (lag_f, dot_sz) in enumerate(((0.4, 8), (0.8, 6), (1.2, 4))):
                    if w < 0.65 and step_idx > 0:
                        continue
                    tx, ty, tez = _thinking_electron_at(k, w, eval_theta(-lag_f), head)
                    trails.append((tez, k, tx, ty, dot_sz))
            else:
                tx, ty, tez = _thinking_electron_at(k, w, eval_theta(-1.2), head)
                trails.append((tez, k, tx, ty, 4))

        blobs.sort(key=lambda item: item[0])
        trails.sort(key=lambda item: item[0])
        crown = sample_crown_at_phase(crowns, crown_phase)
        if n_intro <= f < n_intro + n_loop:
            crown = apply_beanie_shimmer(crown, (f - n_intro) / float(n_loop), intensity=1.0)
        frames.append(
            render_frame(
                clean[bf],
                head,
                crown,
                blobs,
                trails,
                eye_spec=eye_spec,
                leg_retract=w,
            )
        )
    return frames, (n_intro, n_intro + n_loop - 1)


def render_typing(
    clean: List[bytearray],
    heads: List[Tuple[int, int, int]],
    crowns: List[List[Tuple[int, int, int]]],
) -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
    n_intro, n_loop, n_outro = len(TYPING_INTRO_SEQ), len(TYPING_LOOP_SEQ), len(TYPING_OUTRO_SEQ)
    body_seq = TYPING_INTRO_SEQ + TYPING_LOOP_SEQ + TYPING_OUTRO_SEQ
    total = len(body_seq)
    wy = 84.0

    frames: List[cairo.ImageSurface] = []
    for f in range(total):
        bf = body_seq[f]
        head = heads[bf]
        ax, ay = torso_center(head)

        if f < n_intro:
            u_in = f / float(n_intro)
            w = R.smoothstep(0.0, 1.0, u_in)
            crown_phase = 0.35 * u_in
            bar_score_fn = lambda _k: 0.0
            theta_for = lambda sp, k: sp.phi0 + IDLE_REV[k] * 2.0 * math.pi * (0.15 * u_in)
        elif f < n_intro + n_loop:
            u_loop = (f - n_intro) / float(n_loop)
            w = 1.0
            crown_phase = (0.35 + u_loop) % 1.0
            tw = 1.15 + u_loop * 3.0
            bar_score_fn = lambda k: R.loading_bar_score(k, tw)
            theta_for = lambda sp, _k: sp.phi0
        else:
            u_out = (f - (n_intro + n_loop)) / float(n_outro)
            w = 1.0 - R.smoothstep(0.0, 1.0, u_out)
            crown_phase = (0.35 + 0.65 * u_out) % 1.0
            bar_score_fn = lambda _k: 0.0
            theta_for = lambda sp, k: sp.phi0 - IDLE_REV[k] * 2.0 * math.pi * (0.15 * (1.0 - u_out))

        blobs, trails = [], []
        for k, sp in enumerate(R.ELECTRONS):
            theta = theta_for(sp, k)
            ox, oy, ez = orbit_point(ax, ay, sp.rx, sp.ry, sp.tilt_deg, theta)
            dx, dy = ox - ax, oy - ay
            dist = math.hypot(dx, dy) + 1e-6
            side_dir = -1.0 if sp.wave_x < ax else +1.0
            lower_boost = R.clamp((oy - (ay - 20.0)) / 50.0)
            push = (22.0 + 30.0 * lower_boost) * w * (1.0 - w)
            px = R.lerp(ox, sp.wave_x, w) + side_dir * push
            py = R.lerp(oy, wy, w) + (dy / dist) * 12.0 * w * (1.0 - w)
            pz = R.lerp(ez, 1.0, w)

            bar_score = bar_score_fn(k)
            if w <= 0.01:
                sidx = size_from_ez(ez)
            elif w >= 0.99:
                sidx = R.size_index_from_score(bar_score)
            else:
                orbit_score = R.clamp((ez + 0.65) / 1.40)
                sidx = R.size_index_from_score(R.lerp(orbit_score, bar_score, w))
            blobs.append((pz, k, px, py, sidx))

            if w < 0.25:
                tlag = theta - IDLE_REV[k] * 2.0 * math.pi * 0.04
                tx, ty, tez = orbit_point(ax, ay, sp.rx, sp.ry, sp.tilt_deg, tlag)
                trails.append((tez, k, tx, ty, 4))

        blobs.sort(key=lambda item: item[0])
        trails.sort(key=lambda item: item[0])
        frames.append(
            render_frame(
                clean[bf],
                head,
                sample_crown_at_phase(crowns, crown_phase),
                blobs,
                trails,
            )
        )
    return frames, (n_intro, n_intro + n_loop - 1)


def _hover_orbits(
    head: Tuple[int, int, int], phase: float, rev: Sequence[int] = IDLE_REV,
    rx_scale: float = 1.0, ry_scale: float = 1.0, y_shift: float = 0.0, max_size: int = 3
) -> Tuple[list, list]:
    ax, ay = torso_center(head)
    ay += y_shift
    blobs, trails = [], []
    for k, sp in enumerate(R.ELECTRONS):
        theta = sp.phi0 + rev[k] * 2.0 * math.pi * phase
        px, py, ez = orbit_point(ax, ay, sp.rx * rx_scale, sp.ry * ry_scale, sp.tilt_deg, theta)
        blobs.append((ez, k, px, py, min(max_size, size_from_ez(ez))))
        tlag = theta - rev[k] * 2.0 * math.pi * 0.04
        tx, ty, tez = orbit_point(ax, ay, sp.rx * rx_scale, sp.ry * ry_scale, sp.tilt_deg, tlag)
        trails.append((tez, k, tx, ty, 4))
    blobs.sort(key=lambda item: item[0])
    trails.sort(key=lambda item: item[0])
    return blobs, trails


def render_running(
    clean: List[bytearray],
    heads: List[Tuple[int, int, int]],
    crowns: List[List[Tuple[int, int, int]]],
) -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
    """Mini pixel terminal + scrolling emerald lines + blinking cursor."""
    n_intro, n_loop, n_outro = 5, 30, 5
    total = n_intro + n_loop + n_outro
    body_seq = [0, 1, 2, 3, 4] + (HOVER_10 * 3) + [4, 3, 2, 1, 0]
    term_colors = [_rgb(80, 240, 160), _rgb(90, 225, 255), _rgb(140, 250, 180), _rgb(70, 210, 140), _rgb(230, 250, 120)]

    frames = []
    for f in range(total):
        bf = body_seq[f]
        head = heads[bf]
        if f < n_intro:
            alpha = R.smoothstep(0.0, 1.0, f / float(n_intro))
            eye_spec = ("look", 4, 2) if f >= 2 else None
            phase = 0.25 * (f / float(n_intro))
        elif f < n_intro + n_loop:
            alpha = 1.0
            fl = f - n_intro
            eye_spec = ("blink", 0, 0) if fl == 15 else ("look", 4, 2)
            phase = (0.25 + 2.0 * fl / float(n_loop)) % 1.0
        else:
            fo = f - (n_intro + n_loop)
            alpha = 1.0 - R.smoothstep(0.0, 1.0, fo / float(n_outro))
            eye_spec = ("look", 2, 1) if fo < 2 else None
            phase = (0.25 + 0.75 * (fo / float(n_outro))) % 1.0

        blobs, trails = _hover_orbits(head, phase, rev=IDLE_REV, rx_scale=0.95)
        scroll = (f - n_intro) % 10 if f >= n_intro else 0

        def overlay(ctx: cairo.Context, a=alpha, sc=scroll, fr=f) -> None:
            if a <= 0.05:
                return
            tx, ty, tw, th = 486, 134, 62, 56
            draw_pixel_rect(ctx, tx - 2, ty - 2, tw + 4, th + 4, _rgb(45, 72, 96), a)
            draw_pixel_rect(ctx, tx, ty, tw, th, _rgb(14, 22, 32), a)
            draw_pixel_rect(ctx, tx, ty, tw, 10, _rgb(28, 42, 60), a)
            draw_pixel_rect(ctx, tx + 4, ty + 3, 4, 4, _rgb(255, 96, 96), a)
            draw_pixel_rect(ctx, tx + 10, ty + 3, 4, 4, _rgb(255, 210, 80), a)
            draw_pixel_rect(ctx, tx + 16, ty + 3, 4, 4, _rgb(80, 235, 140), a)
            widths = (28, 40, 22, 46, 32)
            for row in range(4):
                ly = ty + 15 + row * 9
                w_line = widths[(row + sc) % len(widths)]
                col = _rgb(80, 240, 150) if (row + sc) % 3 != 1 else _rgb(90, 225, 255)
                draw_pixel_rect(ctx, tx + 6, ly, 4, 4, _rgb(255, 235, 110), a)
                draw_pixel_rect(ctx, tx + 13, ly, w_line, 4, col, a)
            if (fr // 3) % 2 == 0:
                draw_pixel_rect(ctx, tx + 6, ty + 48, 6, 4, _rgb(110, 255, 175), a)

        frames.append(
            render_frame(
                clean[bf], head, sample_crown_at_phase(crowns, phase),
                blobs, trails, eye_spec=eye_spec, custom_colors=term_colors, overlay_fn=overlay
            )
        )
    return frames, (n_intro, n_intro + n_loop - 1)


def render_working(
    clean: List[bytearray],
    heads: List[Tuple[int, int, int]],
    crowns: List[List[Tuple[int, int, int]]],
) -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
    """Spinning interlocking pixel gears + focused eyes + brisk Gemini electrons."""
    n_intro, n_loop, n_outro = 5, 30, 5
    total = n_intro + n_loop + n_outro
    body_seq = [0, 1, 2, 3, 4] + (HOVER_10 * 3) + [4, 3, 2, 1, 0]

    frames = []
    for f in range(total):
        bf = body_seq[f]
        head = heads[bf]
        if f < n_intro:
            alpha = R.smoothstep(0.0, 1.0, f / float(n_intro))
            eye_spec = ("look", 3, -1) if f >= 2 else None
            phase = 0.2 * (f / float(n_intro))
            ang = 0.25 * math.pi * (f / float(n_intro))
        elif f < n_intro + n_loop:
            alpha = 1.0
            fl = f - n_intro
            u_loop = fl / float(n_loop)
            eye_spec = ("blink", 0, 0) if fl == 14 else ("look", 3, -1)
            phase = (0.2 + 2.0 * u_loop) % 1.0
            ang = 0.25 * math.pi + 2.0 * math.pi * u_loop
        else:
            fo = f - (n_intro + n_loop)
            alpha = 1.0 - R.smoothstep(0.0, 1.0, fo / float(n_outro))
            eye_spec = ("look", 2, -1) if fo < 2 else None
            phase = (0.2 + 0.8 * (fo / float(n_outro))) % 1.0
            ang = 0.25 * math.pi + 0.25 * math.pi * (fo / float(n_outro))

        blobs, trails = _hover_orbits(head, phase, rev=IDLE_REV, rx_scale=0.95)

        def overlay(ctx: cairo.Context, a=alpha, th=ang) -> None:
            _draw_pixel_gear(ctx, 502, 138, 7, th, _rgb(92, 232, 255), a)
            _draw_pixel_gear(ctx, 528, 114, 5, -th * 1.4 + 0.3, _rgb(255, 220, 106), a)

        frames.append(
            render_frame(
                clean[bf], head, sample_crown_at_phase(crowns, phase),
                blobs, trails, eye_spec=eye_spec, overlay_fn=overlay
            )
        )
    return frames, (n_intro, n_intro + n_loop - 1)


def render_exploring(
    clean: List[bytearray],
    heads: List[Tuple[int, int, int]],
    crowns: List[List[Tuple[int, int, int]]],
) -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
    """Floating pixel document + sweeping cyan scanner beam + actively scanning eyes."""
    n_intro, n_loop, n_outro = 5, 30, 5
    total = n_intro + n_loop + n_outro
    body_seq = [0, 1, 2, 3, 4] + (HOVER_10 * 3) + [4, 3, 2, 1, 0]

    frames = []
    for f in range(total):
        bf = body_seq[f]
        head = heads[bf]
        if f < n_intro:
            alpha = R.smoothstep(0.0, 1.0, f / float(n_intro))
            eye_spec = ("look", 2, 0) if f >= 2 else None
            phase = 0.2 * (f / float(n_intro))
            scan_u = 0.0
        elif f < n_intro + n_loop:
            alpha = 1.0
            fl = f - n_intro
            phase = (0.2 + fl / float(n_loop)) % 1.0
            scan_u = 0.5 - 0.5 * math.cos(2.0 * math.pi * (fl / 15.0))
            eye_spec = ("look", 4 if (fl % 16) < 8 else -2, -1 if scan_u < 0.5 else 3)
        else:
            fo = f - (n_intro + n_loop)
            alpha = 1.0 - R.smoothstep(0.0, 1.0, fo / float(n_outro))
            eye_spec = ("look", 2, 0) if fo < 2 else None
            phase = (0.2 + 0.8 * (fo / float(n_outro))) % 1.0
            scan_u = 0.0

        blobs, trails = _hover_orbits(head, phase, rev=IDLE_REV, rx_scale=0.9)

        def overlay(ctx: cairo.Context, a=alpha, su=scan_u) -> None:
            if a <= 0.05:
                return
            dx, dy, dw, dh = 488, 128, 52, 62
            draw_pixel_rect(ctx, dx - 2, dy - 2, dw + 4, dh + 4, _rgb(70, 130, 185), a)
            draw_pixel_rect(ctx, dx, dy, dw, dh, _rgb(232, 242, 255), a)
            draw_pixel_rect(ctx, dx + dw - 10, dy, 10, 10, _rgb(168, 200, 232), a)
            for row, lw in enumerate((30, 38, 26, 40, 32, 24)):
                draw_pixel_rect(ctx, dx + 6, dy + 10 + row * 8, lw, 4, _rgb(110, 145, 185), a)
            sy = round(dy + 6 + su * (dh - 14))
            draw_pixel_rect(ctx, dx - 3, sy, dw + 6, 4, _rgb(80, 245, 255), a)

        frames.append(
            render_frame(
                clean[bf], head, sample_crown_at_phase(crowns, phase),
                blobs, trails, eye_spec=eye_spec, overlay_fn=overlay
            )
        )
    return frames, (n_intro, n_intro + n_loop - 1)


def _draw_mini_atom(ctx: cairo.Context, cx: int, cy: int, alpha: float) -> None:
    if alpha <= 0.05:
        return
    # 18x14 pixel mini-Atom buddy with thin rainbow strip + 2x2 eyes
    x0, y0 = cx - 9, cy - 7
    draw_pixel_rect(ctx, x0, y0 + 2, 18, 10, _rgb(46, 161, 244), alpha)
    draw_pixel_rect(ctx, x0 + 3, y0 + 12, 4, 2, _rgb(36, 130, 210), alpha)
    draw_pixel_rect(ctx, x0 + 11, y0 + 12, 4, 2, _rgb(36, 130, 210), alpha)
    # Rainbow strip across top
    strip = (_rgb(90, 230, 255), _rgb(130, 160, 255), _rgb(255, 130, 220), _rgb(255, 230, 100))
    for i, col in enumerate(strip):
        draw_pixel_rect(ctx, x0 + i * 4 + 1, y0, 4, 2, col, alpha)
    draw_pixel_rect(ctx, x0 + 4, y0 + 5, 3, 3, _rgb(10, 14, 20), alpha)
    draw_pixel_rect(ctx, x0 + 11, y0 + 5, 3, 3, _rgb(10, 14, 20), alpha)


def render_delegating(
    clean: List[bytearray],
    heads: List[Tuple[int, int, int]],
    crowns: List[List[Tuple[int, int, int]]],
) -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
    """3 mini-Atom helpers branching out overhead with pulsing link dots."""
    n_intro, n_loop, n_outro = 5, 30, 5
    total = n_intro + n_loop + n_outro
    body_seq = [0, 1, 2, 3, 4] + (HOVER_10 * 3) + [4, 3, 2, 1, 0]

    frames = []
    for f in range(total):
        bf = body_seq[f]
        head = heads[bf]
        hx0, hx1, hy0 = head
        cx = round(0.5 * (hx0 + hx1))
        if f < n_intro:
            w = R.smoothstep(0.0, 1.0, f / float(n_intro))
            phase = 0.25 * (f / float(n_intro))
            eye_spec = ("look", 0, -4) if f >= 2 else None
        elif f < n_intro + n_loop:
            w = 1.0
            fl = f - n_intro
            phase = (0.25 + fl / float(n_loop)) % 1.0
            eye_spec = ("look", -3 if fl < 15 else 3, -4)
        else:
            fo = f - (n_intro + n_loop)
            w = 1.0 - R.smoothstep(0.0, 1.0, fo / float(n_outro))
            phase = (0.25 + 0.75 * (fo / float(n_outro))) % 1.0
            eye_spec = ("look", 0, -3) if fo < 2 else None

        blobs, trails = _hover_orbits(head, phase, rev=IDLE_REV)

        def overlay(ctx: cairo.Context, weight=w, ph=phase, acx=cx, ahy=hy0, fr=f) -> None:
            if weight <= 0.05:
                return
            targets = [(-66, -34), (0, -52), (+66, -34)]
            for idx, (ox, oy) in enumerate(targets):
                bob = round(4.0 * math.sin(2.0 * math.pi * (ph + idx * 0.33)))
                bx = round(R.lerp(acx, acx + ox, weight))
                by = round(R.lerp(ahy + 20, ahy + oy + bob, weight))
                # Pulsing link dots
                for step in (1, 2):
                    u_dot = step / 3.0
                    lx = round(R.lerp(acx, bx, u_dot))
                    ly = round(R.lerp(ahy + 4, by, u_dot))
                    col = R.ELECTRONS[(idx * 2) % len(R.ELECTRONS)].color
                    if (fr + step) % 2 == 0 or weight > 0.8:
                        draw_pixel_rect(ctx, lx - 1, ly - 1, 3, 3, col, weight * 0.85)
                _draw_mini_atom(ctx, bx, by, weight)

        frames.append(
            render_frame(
                clean[bf], head, sample_crown_at_phase(crowns, phase),
                blobs, trails, eye_spec=eye_spec, overlay_fn=overlay
            )
        )
    return frames, (n_intro, n_intro + n_loop - 1)


def render_asking(
    clean: List[bytearray],
    heads: List[Tuple[int, int, int]],
    crowns: List[List[Tuple[int, int, int]]],
) -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
    """Pixel speech bubble with pulsing '?' glyph."""
    n_intro, n_loop, n_outro = 4, 26, 6
    total = n_intro + n_loop + n_outro
    body_seq = [0, 1, 2, 3] + [HOVER_10[i % 10] for i in range(n_loop)] + [3, 2, 1, 1, 0, 0]

    frames = []
    for f in range(total):
        bf = body_seq[f]
        head = heads[bf]
        if f < n_intro:
            alpha = R.smoothstep(0.0, 1.0, f / float(n_intro))
            phase = 0.2 * (f / float(n_intro))
            eye_spec = ("look", 3, -2) if f >= 2 else None
        elif f < n_intro + n_loop:
            alpha = 1.0
            fl = f - n_intro
            phase = (0.2 + fl / float(n_loop)) % 1.0
            eye_spec = ("blink", 0, 0) if fl == 13 else ("look", 3, -2)
        else:
            fo = f - (n_intro + n_loop)
            alpha = 1.0 - R.smoothstep(0.0, 1.0, fo / float(n_outro))
            phase = (0.2 + 0.8 * (fo / float(n_outro))) % 1.0
            eye_spec = ("look", 2, -1) if fo < 3 else None

        blobs, trails = _hover_orbits(head, phase, rev=IDLE_REV)
        bob = round(3.0 * math.sin(2.0 * math.pi * phase))

        def overlay(ctx: cairo.Context, a=alpha, by=bob, ph=phase) -> None:
            if a <= 0.05:
                return
            bx, y0, bw, bh = 486, 66 + by, 44, 46
            draw_pixel_rect(ctx, bx - 2, y0 - 2, bw + 4, bh + 4, _rgb(90, 120, 195), a)
            draw_pixel_rect(ctx, bx, y0, bw, bh, _rgb(245, 248, 255), a)
            draw_pixel_rect(ctx, bx - 6, y0 + bh - 10, 6, 6, _rgb(245, 248, 255), a)
            # Crisp '?' pixel glyph in violet/cyan
            qcol = _rgb(148, 92, 246) if math.sin(2.0 * math.pi * 2.0 * ph) >= 0 else _rgb(60, 185, 245)
            qx, qy = bx + 12, y0 + 8
            draw_pixel_rect(ctx, qx + 4, qy, 12, 4, qcol, a)
            draw_pixel_rect(ctx, qx, qy + 4, 4, 6, qcol, a)
            draw_pixel_rect(ctx, qx + 16, qy + 4, 4, 8, qcol, a)
            draw_pixel_rect(ctx, qx + 8, qy + 12, 8, 4, qcol, a)
            draw_pixel_rect(ctx, qx + 8, qy + 16, 4, 6, qcol, a)
            draw_pixel_rect(ctx, qx + 8, qy + 25, 4, 4, qcol, a)

        frames.append(
            render_frame(
                clean[bf], head, sample_crown_at_phase(crowns, phase),
                blobs, trails, eye_spec=eye_spec, overlay_fn=overlay
            )
        )
    return frames, (n_intro, n_intro + n_loop - 1)


def render_listening(
    clean: List[bytearray],
    heads: List[Tuple[int, int, int]],
    crowns: List[List[Tuple[int, int, int]]],
) -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
    """Eyes looking down at the prompt bar as the user types."""
    n = 20
    body_seq = HOVER_10 * 2
    frames = []
    for f in range(n):
        bf = body_seq[f]
        head = heads[bf]
        phase = f / float(n)
        eye_spec = ("look", 0, 5)
        blobs, trails = _hover_orbits(head, phase, rev=IDLE_REV, rx_scale=0.88, y_shift=6.0, max_size=2)
        frames.append(
            render_frame(
                clean[bf], head, sample_crown_at_phase(crowns, phase),
                blobs, trails, eye_spec=eye_spec
            )
        )
    return frames, (0, n - 1)


def render_watching(
    clean: List[bytearray],
    heads: List[Tuple[int, int, int]],
    crowns: List[List[Tuple[int, int, int]]],
) -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
    """Background task monitor: sweeping eyes + pulsing radar ping above beanie."""
    n = 30
    body_seq = HOVER_10 * 3
    frames = []
    for f in range(n):
        bf = body_seq[f]
        head = heads[bf]
        phase = f / float(n)
        if f < 10:
            eye_spec = ("look", -4, -2)
        elif f < 20:
            eye_spec = ("look", 0, -2)
        else:
            eye_spec = ("look", 4, -2)
        blobs, trails = _hover_orbits(head, phase, rev=IDLE_REV)

        def overlay(ctx: cairo.Context, ph=phase, h=head) -> None:
            cx = round(0.5 * (h[0] + h[1]))
            ry = h[2] - 18
            pulse = (ph * 2.0) % 1.0
            draw_pixel_rect(ctx, cx - 2, ry - 2, 4, 4, _rgb(80, 245, 200), 0.95)
            spread = round(6 + pulse * 18)
            a = 1.0 - pulse
            draw_pixel_rect(ctx, cx - spread, ry - 4, 4, 8, _rgb(80, 245, 200), a)
            draw_pixel_rect(ctx, cx + spread - 4, ry - 4, 4, 8, _rgb(80, 245, 200), a)

        frames.append(
            render_frame(
                clean[bf], head, sample_crown_at_phase(crowns, phase),
                blobs, trails, eye_spec=eye_spec, overlay_fn=overlay
            )
        )
    return frames, (0, n - 1)


def render_done(
    clean: List[bytearray],
    heads: List[Tuple[int, int, int]],
    crowns: List[List[Tuple[int, int, int]]],
) -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
    """Cheerful completion hop, ^ ^ eyes, and rising pixel confetti."""
    n = 20
    confetti_specs = (
        (-52, 108, _rgb(100, 248, 255), 0.0),
        (-28, 86, _rgb(255, 118, 230), 0.15),
        (+26, 84, _rgb(255, 236, 108), 0.10),
        (+54, 104, _rgb(94, 242, 155), 0.25),
        (-40, 128, _rgb(198, 146, 255), 0.20),
        (+42, 124, _rgb(110, 192, 255), 0.05),
    )
    frames = []
    for f in range(n):
        u = f / float(n)
        bf = HOVER_10[f % 10]
        head = heads[bf]
        hop = -round(6.0 * math.sin(math.pi * min(1.0, u * 1.4)))
        blobs, trails = _hover_orbits(head, u, rev=IDLE_REV, rx_scale=1.08, y_shift=hop * 0.5)

        def overlay(ctx: cairo.Context, prog=u) -> None:
            for cx0, cy0, col, delay in confetti_specs:
                t = R.clamp((prog - delay) / 0.75)
                if 0.0 < t < 1.0:
                    px = round(CENTER_X + cx0 + 8.0 * math.sin(t * 6.0))
                    py = round(cy0 - t * 44.0)
                    draw_pixel_rect(ctx, px, py, 5, 5, col, 1.0 - t)

        frames.append(
            render_frame(
                clean[bf], head, sample_crown_at_phase(crowns, u),
                blobs, trails, eye_spec=("happy", 0, 0), body_offset=(0, hop), overlay_fn=overlay
            )
        )
    return frames, (0, n - 1)


def render_happy(
    clean: List[bytearray],
    heads: List[Tuple[int, int, int]],
    crowns: List[List[Tuple[int, int, int]]],
) -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
    """Bright cyan glow, bouncy hop, ^ ^ eyes, and rising pixel hearts."""
    n = 24
    frames = []
    for f in range(n):
        u = f / float(n)
        bf = HOVER_10[f % 10]
        head = heads[bf]
        hop = -round(7.0 * abs(math.sin(2.0 * math.pi * u)))
        blobs, trails = _hover_orbits(head, u, rev=IDLE_REV, rx_scale=1.1, y_shift=hop * 0.5)

        def overlay(ctx: cairo.Context, prog=u) -> None:
            for side, delay in ((-1, 0.05), (+1, 0.25)):
                t = R.clamp((prog - delay) / 0.7)
                if 0.0 < t < 1.0:
                    hx = round(CENTER_X + side * 56)
                    hy = round(112 - t * 44.0)
                    col = _rgb(255, 110, 195)
                    a = 1.0 - t
                    draw_pixel_rect(ctx, hx - 5, hy, 4, 4, col, a)
                    draw_pixel_rect(ctx, hx + 1, hy, 4, 4, col, a)
                    draw_pixel_rect(ctx, hx - 5, hy + 4, 10, 4, col, a)
                    draw_pixel_rect(ctx, hx - 2, hy + 8, 4, 3, col, a)

        frames.append(
            render_frame(
                clean[bf], head, sample_crown_at_phase(crowns, u * 1.4),
                blobs, trails, eye_spec=("happy", 0, 0),
                tint=(188.0, 1.08, 1.08, 1.0, 1.0),
                body_offset=(0, hop),
                overlay_fn=overlay,
            )
        )
    return frames, (0, n - 1)


def _lerp_palette(
    base: Sequence[Tuple[float, float, float]],
    target: Sequence[Tuple[float, float, float]],
    t: float,
) -> List[Tuple[float, float, float]]:
    if t <= 0.0:
        return list(base)
    if t >= 1.0:
        return list(target)
    inv = 1.0 - t
    return [
        (a[0] * inv + b[0] * t, a[1] * inv + b[1] * t, a[2] * inv + b[2] * t)
        for a, b in zip(base, target)
    ]


def _mood_intensity(f: int, n_intro: int = 6, n_loop: int = 30, n_outro: int = 6) -> float:
    """Smooth 0->1->0 mood envelope across 3-phase (intro, loop, outro) sprites."""
    if f < n_intro:
        return R.smoothstep(0.0, 1.0, f / float(max(1, n_intro - 1)))
    if f < n_intro + n_loop:
        return 1.0
    return 1.0 - R.smoothstep(0.0, 1.0, (f - n_intro - n_loop) / float(max(1, n_outro - 1)))


def render_sad(
    clean: List[bytearray],
    heads: List[Tuple[int, int, int]],
    crowns: List[List[Tuple[int, int, int]]],
) -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
    """3-phase sad mood: 6f slump intro, 30f weeping sustain loop, 6f recovery outro."""
    n_intro, n_loop, n_outro = 6, 30, 6
    total = n_intro + n_loop + n_outro
    body_seq = [0, 1, 2, 3, 4, 5] + ([5, 5, 5, 4, 4, 5] * 5) + [5, 4, 3, 2, 1, 0]
    base_colors = [sp.color for sp in R.ELECTRONS]
    sad_colors = [tuple(c * 0.55 + 0.15 for c in col) for col in base_colors]
    frames = []
    for f in range(total):
        bf = body_seq[f]
        head = heads[bf]
        gloom = _mood_intensity(f, n_intro, n_loop, n_outro)
        # Advance linearly across all frames with exactly 1.0 orbit cycle over the 30f loop.
        phase = (f - n_intro) / float(n_loop)
        slump = round(4.0 * gloom)
        blobs, trails = _hover_orbits(
            head,
            phase,
            rev=IDLE_REV,
            ry_scale=1.0 - 0.35 * gloom,
            y_shift=16.0 * gloom,
            max_size=2 if gloom >= 0.5 else 3,
        )
        eye_spec = ("sad", 0, 0) if 2 <= f < (total - 3) else None

        def overlay(ctx: cairo.Context, fr=f, h=head, sl=slump, gl=gloom) -> None:
            if fr < 4 or fr >= n_intro + n_loop:
                return
            if fr < n_intro:
                t = 0.0
                fade = (fr - 3) / 3.0
            else:
                t = ((fr - n_intro) % 15) / 15.0
                fade = 1.0
            tx = 450
            ty = round(h[2] + 42 + sl + t * 28.0)
            a = (1.0 - t * 0.72) * fade * min(1.0, gl + 0.25)
            draw_pixel_rect(ctx, tx, ty, 4, 6, _rgb(100, 230, 255), a)

        frames.append(
            render_frame(
                clean[bf], head, sample_crown_at_phase(crowns, phase),
                blobs, trails, eye_spec=eye_spec,
                tint=(214.0, 0.35, 0.78, 0.35, 0.82),
                tint_blend=gloom,
                body_offset=(0, slump),
                custom_colors=_lerp_palette(base_colors, sad_colors, gloom),
                overlay_fn=overlay,
            )
        )
    return frames, (n_intro, n_intro + n_loop - 1)


def render_angry(
    clean: List[bytearray],
    heads: List[Tuple[int, int, int]],
    crowns: List[List[Tuple[int, int, int]]],
) -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
    """3-phase angry mood: 6f heat-up intro, 30f fuming sustain loop, 6f cool-down outro."""
    n_intro, n_loop, n_outro = 6, 30, 6
    total = n_intro + n_loop + n_outro
    body_seq = [0, 1, 2, 3, 2, 1] + (HOVER_10 * 3) + [1, 2, 3, 2, 1, 0]
    shake_6 = (-2, +2, -2, 0, +2, 0)
    base_colors = [sp.color for sp in R.ELECTRONS]
    angry_colors = [_rgb(255, 85, 65), _rgb(255, 165, 60), _rgb(255, 65, 110), _rgb(255, 225, 80), _rgb(255, 110, 60)]
    frames = []
    for f in range(total):
        bf = body_seq[f]
        head = heads[bf]
        heat = _mood_intensity(f, n_intro, n_loop, n_outro)
        # Two integer revolutions per 30f loop so seams wrap with zero orbital pop.
        phase = ((f - n_intro) / float(n_loop)) * 2.0
        if f < 3 or f >= total - 3:
            shake_x = 0
        elif f < n_intro:
            shake_x = -1 if (f % 2) else +1
        elif f < n_intro + n_loop:
            shake_x = shake_6[(f - n_intro) % 6]
        else:
            shake_x = +1 if (f % 2) else -1
        blobs, trails = _hover_orbits(head, phase, rev=IDLE_REV, rx_scale=1.0 + 0.12 * heat)
        eye_spec = ("angry", 0, 0) if 2 <= f < (total - 3) else None

        def overlay(ctx: cairo.Context, fr=f, h=head, sx=shake_x, ht=heat) -> None:
            if ht <= 0.05:
                return
            # Steam puffs rising from top corners (2 exact cycles per 30f loop)
            steam_phase = ((fr - n_intro) / float(n_loop)) * 2.0
            steam_alpha = min(1.0, ht * 1.15)
            for side, shift in ((-42, 0.0), (+42, 0.35)):
                t = (steam_phase + shift) % 1.0
                px = round(CENTER_X + side + sx)
                py = round(h[2] - 8 - t * 34.0)
                sz = 8 if t < 0.5 else 6
                draw_pixel_rect(ctx, px - sz // 2, py, sz, sz, _rgb(255, 240, 230), (1.0 - t) * steam_alpha)
            # Crisp red/orange anger vein mark at upper-right temple
            mx, my = h[1] + 4 + sx, h[2] - 12
            if ht >= 0.45 and ((fr - n_intro) // 3) % 2 == 0:
                col = _rgb(255, 70, 70)
                draw_pixel_rect(ctx, mx, my, 4, 4, col, min(1.0, ht * 1.2))
                draw_pixel_rect(ctx, mx + 6, my, 4, 4, col, min(1.0, ht * 1.2))
                draw_pixel_rect(ctx, mx, my + 6, 4, 4, col, min(1.0, ht * 1.2))
                draw_pixel_rect(ctx, mx + 6, my + 6, 4, 4, col, min(1.0, ht * 1.2))

        frames.append(
            render_frame(
                clean[bf], head, sample_crown_at_phase(crowns, phase),
                blobs, trails, eye_spec=eye_spec,
                tint=(6.0, 1.05, 0.98, 1.0, 1.0),
                tint_blend=heat,
                body_offset=(shake_x, 0),
                custom_colors=_lerp_palette(base_colors, angry_colors, heat),
                overlay_fn=overlay,
            )
        )
    return frames, (n_intro, n_intro + n_loop - 1)


def _draw_music_note(
    ctx: cairo.Context, x: int, y: int, col: Tuple[float, float, float], alpha: float, double: bool
) -> None:
    """Draw a tiny pixel eighth note or beamed double note within crop bounds."""
    if not double:
        draw_pixel_rect(ctx, x, y + 6, 4, 4, col, alpha)
        draw_pixel_rect(ctx, x + 2, y, 2, 8, col, alpha)
        draw_pixel_rect(ctx, x + 4, y, 4, 2, col, alpha)
        draw_pixel_rect(ctx, x + 6, y + 2, 2, 2, col, alpha)
    else:
        draw_pixel_rect(ctx, x, y + 6, 4, 4, col, alpha)
        draw_pixel_rect(ctx, x + 8, y + 5, 4, 4, col, alpha)
        draw_pixel_rect(ctx, x + 2, y + 1, 2, 7, col, alpha)
        draw_pixel_rect(ctx, x + 10, y, 2, 7, col, alpha)
        draw_pixel_rect(ctx, x + 2, y, 10, 2, col, alpha)


def render_dance(
    clean: List[bytearray],
    heads: List[Tuple[int, int, int]],
    crowns: List[List[Tuple[int, int, int]]],
) -> Tuple[List[cairo.ImageSurface], Tuple[int, int], int]:
    """Silky 3-phase click-to-dance groove: 5f ease-in, 30f eased sway/bounce loop, 5f ease-out."""
    n_intro, n_loop, n_outro = 5, 30, 5
    total = n_intro + n_loop + n_outro
    bf = 0
    head = heads[bf]
    base_clean = clean[bf]
    frames = []
    for f in range(total):
        if f < n_intro:
            env = R.smoothstep(0.0, 1.0, f / 4.0)
        elif f < n_intro + n_loop:
            env = 1.0
        else:
            env = 1.0 - R.smoothstep(0.0, 1.0, (f - (n_intro + n_loop)) / 4.0)

        t = (f - n_intro) / float(n_loop)
        dx = round(5.0 * env * math.sin(2.0 * math.pi * (2.0 * t)))
        dy = -round(5.0 * env * (0.5 - 0.5 * math.cos(2.0 * math.pi * (4.0 * t))))
        blobs, trails = _hover_orbits(
            head,
            t,
            rev=IDLE_REV,
            rx_scale=1.0 + 0.08 * env,
            ry_scale=1.0 + 0.04 * env,
            y_shift=dy * 0.4,
        )
        blobs = [(z, k, px + dx * 0.55, py, sz) for (z, k, px, py, sz) in blobs]
        trails = [(z, k, px + dx * 0.55, py, sz) for (z, k, px, py, sz) in trails]

        if f in (0, 1, 38, 39):
            eye_spec = None
        elif f in (12, 27):
            eye_spec = ("blink", 0, 0)
        else:
            eye_spec = ("happy", 0, 0)

        def overlay(ctx: cairo.Context, fr=f, sx=dx, sy=dy, e=env) -> None:
            if e <= 0.05:
                return
            prog = fr / float(total)
            specs = (
                (-66, 0.08, _rgb(255, 195, 40), False),
                (+58, 0.28, _rgb(55, 215, 255), True),
                (-58, 0.48, _rgb(255, 95, 190), True),
                (+64, 0.68, _rgb(255, 195, 40), False),
            )
            for side, start_u, col, dbl in specs:
                u_note = (prog - start_u) / 0.36
                if 0.0 < u_note < 1.0:
                    fade = e * min(1.0, u_note * 4.0) * (1.0 - u_note)
                    nx = round(CENTER_X + side + sx * 0.5 + 2.5 * math.sin(u_note * math.pi * 2.0))
                    ny = round(112 + sy * 0.5 - 42.0 * u_note)
                    _draw_music_note(ctx, nx, ny, col, fade, dbl)

        frames.append(
            render_frame(
                base_clean,
                head,
                sample_crown_at_phase(crowns, t),
                blobs,
                trails,
                eye_spec=eye_spec,
                tint=(195.0, 1.08, 1.06, 1.0, 1.0),
                tint_blend=env,
                body_offset=(dx, dy),
                overlay_fn=overlay,
            )
        )
    return frames, (n_intro, n_intro + n_loop - 1), 65


def render_error(
    clean: List[bytearray],
    heads: List[Tuple[int, int, int]],
    crowns: List[List[Tuple[int, int, int]]],
) -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
    """Startled jolt, X X eyes, flashing '!' alert badge, and orange/red sparks."""
    n = 20
    err_colors = [_rgb(255, 80, 80), _rgb(255, 195, 70), _rgb(255, 110, 60), _rgb(255, 70, 120), _rgb(255, 235, 100)]
    frames = []
    for f in range(n):
        u = f / float(n)
        bf = 3 if f < 4 else HOVER_10[f % 10]
        head = heads[bf]
        jx = (-3 if f in (1, 3) else (3 if f in (2, 4) else 0))
        blobs, trails = _hover_orbits(head, u * 1.5, rev=IDLE_REV, rx_scale=1.08)

        def overlay(ctx: cairo.Context, fr=f, h=head, j=jx) -> None:
            if (fr // 2) % 2 == 0:
                bx, by = h[1] + 6 + j, h[2] - 28
                draw_pixel_rect(ctx, bx - 2, by - 2, 18, 28, _rgb(255, 70, 70))
                draw_pixel_rect(ctx, bx, by, 14, 24, _rgb(255, 220, 75))
                draw_pixel_rect(ctx, bx + 5, by + 4, 4, 10, _rgb(30, 12, 12))
                draw_pixel_rect(ctx, bx + 5, by + 17, 4, 4, _rgb(30, 12, 12))

        frames.append(
            render_frame(
                clean[bf], head, sample_crown_at_phase(crowns, u),
                blobs, trails, eye_spec=("error", 0, 0),
                tint=(14.0, 0.9, 0.95, 1.0, 1.0),
                body_offset=(jx, 0),
                custom_colors=err_colors,
                overlay_fn=overlay,
            )
        )
    return frames, (0, n - 1)


def render_canceled(
    clean: List[bytearray],
    heads: List[Tuple[int, int, int]],
    crowns: List[List[Tuple[int, int, int]]],
) -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
    """Sudden stop / wide O O surprised eyes + settling muted electrons."""
    n = 18
    muted = [tuple(c * 0.65 + 0.2 for c in sp.color) for sp in R.ELECTRONS]
    frames = []
    for f in range(n):
        u = f / float(n)
        bf = 5 if f < 10 else 4
        head = heads[bf]
        drop = 3 if f < 6 else 1
        blobs, trails = _hover_orbits(head, u * 0.25, rev=IDLE_REV, ry_scale=0.75, max_size=2)
        frames.append(
            render_frame(
                clean[bf], head, sample_crown_at_phase(crowns, u * 0.2),
                blobs, trails, eye_spec=("surprised", 0, 0),
                tint=(210.0, 0.55, 0.85, 0.6, 0.88),
                body_offset=(0, drop),
                custom_colors=muted,
            )
        )
    return frames, (0, n - 1)


def render_tired(
    clean: List[bytearray],
    heads: List[Tuple[int, int, int]],
    crowns: List[List[Tuple[int, int, int]]],
) -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
    """Heavy droop, half-lidded eyes, and sliding temple sweat drop."""
    n = 24
    dim_colors = [tuple(c * 0.6 + 0.1 for c in sp.color) for sp in R.ELECTRONS]
    frames = []
    for f in range(n):
        u = f / float(n)
        bf = 5 if f < 14 else 4
        head = heads[bf]
        droop = 3 if f < 16 else 2
        blobs, trails = _hover_orbits(head, u * 0.4, rev=IDLE_REV, rx_scale=0.9, ry_scale=0.6, y_shift=14.0, max_size=2)

        def overlay(ctx: cairo.Context, prog=u, h=head, dr=droop) -> None:
            t = R.clamp(prog * 1.2)
            sx = h[1] - 4
            sy = round(h[2] + 18 + dr + t * 24.0)
            a = 1.0 - t * 0.5
            draw_pixel_rect(ctx, sx, sy, 5, 8, _rgb(145, 242, 255), a)
            draw_pixel_rect(ctx, sx + 1, sy + 1, 2, 3, _rgb(235, 252, 255), a)

        frames.append(
            render_frame(
                clean[bf], head, sample_crown_at_phase(crowns, u * 0.3),
                blobs, trails, eye_spec=("tired", 0, 0),
                tint=(220.0, 0.55, 0.72, 0.6, 0.78),
                body_offset=(0, droop),
                custom_colors=dim_colors,
                overlay_fn=overlay,
            )
        )
    return frames, (0, n - 1)


def _draw_z_glyph(ctx: cairo.Context, x: int, y: int, scale: int, alpha: float) -> None:
    if alpha <= 0.05:
        return
    col = _rgb(175, 225, 255)
    s = scale
    draw_pixel_rect(ctx, x, y, 4 * s, s, col, alpha)
    draw_pixel_rect(ctx, x + 2 * s, y + s, s, s, col, alpha)
    draw_pixel_rect(ctx, x + s, y + 2 * s, s, s, col, alpha)
    draw_pixel_rect(ctx, x, y + 3 * s, 4 * s, s, col, alpha)


def render_closed(
    clean: List[bytearray],
    heads: List[Tuple[int, int, int]],
    crowns: List[List[Tuple[int, int, int]]],
) -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
    """Sleepy dim Atom with lowered closed eyes, slow breathing, and rising Zzz."""
    n = 30
    sleep_seq = [5, 5, 5, 4, 4, 4, 3, 3, 4, 4] * 3
    dim_colors = [tuple(c * 0.45 + 0.08 for c in sp.color) for sp in R.ELECTRONS]
    frames = []
    for f in range(n):
        u = f / float(n)
        bf = sleep_seq[f]
        head = heads[bf]
        blobs, trails = _hover_orbits(head, u * 0.35, rev=IDLE_REV, rx_scale=0.82, ry_scale=0.55, y_shift=14.0, max_size=1)

        def overlay(ctx: cairo.Context, prog=u, h=head) -> None:
            for offset, scale in ((0.0, 3), (0.33, 2), (0.66, 2)):
                t = (prog + offset) % 1.0
                zx = round(h[1] - 4 + t * 24.0 + 4.0 * math.sin(t * 6.28))
                zy = round(h[2] + 6 - t * 46.0)
                a = math.sin(math.pi * t)
                _draw_z_glyph(ctx, zx, zy, scale, a * 0.95)

        frames.append(
            render_frame(
                clean[bf], head, sample_crown_at_phase(crowns, u * 0.25),
                blobs, trails, eye_spec=("sleep", 0, 0),
                tint=(222.0, 0.55, 0.46, 0.55, 0.52),
                custom_colors=dim_colors,
                overlay_fn=overlay,
            )
        )
    return frames, (0, n - 1)


def save_sheet(
    state: str, frames: List[cairo.ImageSurface], loop: Tuple[int, int], frame_ms: int | None = None
) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    n = len(frames)
    cols = min(COLS, n)
    rows = -(-n // cols)
    sheet = cairo.ImageSurface(cairo.FORMAT_ARGB32, FRAME_W * cols, FRAME_H * rows)
    ctx = cairo.Context(sheet)

    for i, fr in enumerate(frames):
        dx = (i % cols) * FRAME_W
        dy = (i // cols) * FRAME_H
        ctx.save()
        ctx.rectangle(dx, dy, FRAME_W, FRAME_H)
        ctx.clip()
        ctx.translate(dx, dy)
        ctx.scale(FRAME_W / float(CROP_W), FRAME_H / float(CROP_H))
        ctx.set_source_surface(fr, -CROP_LEFT, -CROP_TOP)
        ctx.get_source().set_filter(cairo.FILTER_BEST)
        ctx.paint()
        ctx.restore()

    webp_path = OUT_DIR / f"{state}.webp"
    json_path = OUT_DIR / f"{state}.json"
    with tempfile.TemporaryDirectory(prefix=f"atom_{state}_") as tmp:
        png_path = Path(tmp) / f"{state}.png"
        sheet.write_to_png(str(png_path))
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(png_path),
                "-c:v",
                "libwebp",
                "-lossless",
                "1",
                "-compression_level",
                "6",
                str(webp_path),
            ],
            check=True,
        )

    meta = {
        "w": FRAME_W,
        "h": FRAME_H,
        "cols": cols,
        "durations": [frame_ms or (1000 // FPS)] * n,
        "loop": [loop[0], loop[1]],
    }
    json_path.write_text(json.dumps(meta) + "\n")
    print(
        f"assets/atom/{state}.webp: {n} frames, loop {loop[0]}..{loop[1]}, "
        f"{webp_path.stat().st_size // 1024} KB"
    )


def main() -> None:
    requested = sys.argv[1:]
    base = R.load_gif_frames(R.BASE_GIF)
    gemini = R.load_gif_frames(R.GEMINI_GIF)
    clean, heads = R.clean_base_frames(base)
    crowns = R.sample_gemini_crowns(gemini)

    builders = {
        "idle": lambda: render_idle(base, clean, heads, crowns),
        "thinking": lambda: render_thinking(clean, heads, crowns),
        "typing": lambda: render_typing(clean, heads, crowns),
        "working": lambda: render_working(clean, heads, crowns),
        "exploring": lambda: render_exploring(clean, heads, crowns),
        "running": lambda: render_running(clean, heads, crowns),
        "delegating": lambda: render_delegating(clean, heads, crowns),
        "asking": lambda: render_asking(clean, heads, crowns),
        "listening": lambda: render_listening(clean, heads, crowns),
        "watching": lambda: render_watching(clean, heads, crowns),
        "done": lambda: render_done(clean, heads, crowns),
        "happy": lambda: render_happy(clean, heads, crowns),
        "dance": lambda: render_dance(clean, heads, crowns),
        "sad": lambda: render_sad(clean, heads, crowns),
        "angry": lambda: render_angry(clean, heads, crowns),
        "error": lambda: render_error(clean, heads, crowns),
        "canceled": lambda: render_canceled(clean, heads, crowns),
        "tired": lambda: render_tired(clean, heads, crowns),
        "closed": lambda: render_closed(clean, heads, crowns),
    }
    targets = requested if requested else list(builders.keys())
    for name in targets:
        if name not in builders:
            raise SystemExit(f"Unknown state: {name}")
        res = builders[name]()
        frames, loop, frame_ms = res if len(res) == 3 else (res[0], res[1], None)
        save_sheet(name, frames, loop, frame_ms=frame_ms)


if __name__ == "__main__":
    main()

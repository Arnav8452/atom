#!/usr/bin/env python3
"""Authentic art/base.gif-derived renderer for the `base qt.` skin.

Uses art/base.gif's hand-drawn pixel frames directly (`clean[bf]`) with:
- zero legs (`leg_retract=1.0`, `preserve_laptop=True`),
- zero rainbow beanie (`crown_cols=None`),
- pure white luminous electrons (orbiting in typing too — no overhead 5-dot bar),
- art/base.png's iconic 3-ring dotted orbital loops in `thinking` and dimmed
  matte-grey resting laptop in `closed`,
- full uniform body mood tinting & rich props across all 19 states.

Needs only Python stdlib + python-cairo (via render_all/render_idle/render_gemini_typing).
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Sequence, Tuple

import cairo

import tools.render_gemini_typing as R
import tools.render_idle as RI

RGBFloat = Tuple[float, float, float]


def _rgb(r: int, g: int, b: int) -> RGBFloat:
    return (r / 255.0, g / 255.0, b / 255.0)


WHITE_PALETTE: List[RGBFloat] = [
    _rgb(255, 255, 255),
    _rgb(236, 246, 255),
    _rgb(255, 255, 255),
    _rgb(224, 240, 255),
    _rgb(248, 252, 255),
]
WHITE_IDLE_PALETTE: List[Tuple[int, int, int]] = [
    (255, 255, 255),
    (235, 245, 255),
    (255, 255, 255),
    (225, 240, 255),
]
CLASSIC_RINGS = (
    (90.0, 28.0, 0.0, +1, 0.4),
    (82.0, 32.0, -42.0, -1, 2.3),
    (82.0, 32.0, +42.0, +1, 4.1),
)


def build_renderers(RA, base: List[bytearray], clean: List[bytearray], heads: List[Tuple[int, int, int]]) -> Dict[str, Callable[[], Tuple]]:
    """Build all 19 state renderers using RA (tools.render_all) helpers on legless base.gif frames."""

    def legless_hover_orbits(head, phase, rx_scale=1.0, ry_scale=1.0, y_shift=0.0, max_size=3):
        ax, ay = RA.torso_center(head)
        ay += y_shift
        blobs, trails = [], []
        for k, sp in enumerate(R.ELECTRONS):
            theta = sp.phi0 + RA.IDLE_REV[k] * 2.0 * math.pi * phase
            px, py, ez = RA.orbit_point(ax, ay, sp.rx * rx_scale, sp.ry * ry_scale, sp.tilt_deg, theta)
            blobs.append((ez, k, px, py, min(max_size, RA.size_from_ez(ez))))
            tlag = theta - RA.IDLE_REV[k] * 2.0 * math.pi * 0.04
            tx, ty, tez = RA.orbit_point(ax, ay, sp.rx * rx_scale, sp.ry * ry_scale, sp.tilt_deg, tlag)
            trails.append((tez, k, tx, ty, 4))
        blobs.sort(key=lambda item: item[0])
        trails.sort(key=lambda item: item[0])
        return blobs, trails

    def render_idle() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n = len(base)
        anchors = [RI.head_anchor(h) for h in heads]
        pixels = [RI.electron_pixels(f, base[f]) for f in range(n)]
        frame_blobs = [RI.blobs(p) for p in pixels]
        body_seq = RA.HOVER_10 * 3

        frames: List[cairo.ImageSurface] = []
        for f in range(n):
            bf = body_seq[f]
            rgb = bytearray(clean[bf])
            if f in (14, 15):
                RA.paint_eyes(rgb, heads[bf], "blink")
            RA.tuck_legs(rgb, heads[bf], 1.0, preserve_laptop=True)
            # Assign pure white colour index 0 to every orb so no yellow/tinted pixels sneak in
            white_cols = [0] * len(frame_blobs[f])
            surf = RI.render_rgba_frame(
                rgb,
                heads[bf],
                None,
                frame_blobs[f],
                white_cols,
                pixels[f],
                anchors[f],
                anchors[bf],
                palette=[(255, 255, 255)],
            )
            frames.append(RA._safe_copy_surface(surf))
        return frames, (0, n - 1)

    def render_typing() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        """Authentic art/base.gif typing animation (legless, no beanie, orbiting white electrons)."""
        n_intro = len(RA.TYPING_INTRO_SEQ)
        n_loop = len(RA.TYPING_LOOP_SEQ)
        body_seq = RA.TYPING_INTRO_SEQ + RA.TYPING_LOOP_SEQ + RA.TYPING_OUTRO_SEQ
        total = len(body_seq)
        frames: List[cairo.ImageSurface] = []

        for f in range(total):
            bf = body_seq[f]
            head = heads[bf]
            phase = (f / 30.0) % 1.0
            blobs, trails = legless_hover_orbits(head, phase, rx_scale=0.96, max_size=3)

            def sparks(ctx: cairo.Context, fr=f) -> None:
                if not (n_intro <= fr < n_intro + n_loop):
                    return
                pts = ((484, 170), (498, 160), (512, 168), (522, 174), (492, 152))
                for idx, (sx, sy) in enumerate(pts):
                    ph = (fr + idx * 3) % 10
                    if ph < 7:
                        lift = (ph // 3) * 2
                        a = 0.85 if ph < 4 else 0.45
                        RA.draw_pixel_rect(ctx, sx, sy - lift, 4, 4, _rgb(245, 250, 255), a)

            frames.append(
                RA.render_frame(
                    clean[bf],
                    head,
                    None,
                    blobs,
                    trails,
                    leg_retract=1.0,
                    preserve_laptop=True,
                    custom_colors=WHITE_PALETTE,
                    overlay_fn=sparks,
                )
            )
        return frames, (n_intro, n_intro + n_loop - 1)

    def render_thinking() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        """Legless base.gif body + art/base.png Panel 4 dotted orbital loops + white electrons."""
        n_intro, n_loop, n_outro = 7, 30, 7
        total = n_intro + n_loop + n_outro
        body_seq = [0, 1, 2, 3, 3, 4, 5] + (RA.HOVER_10 * 3) + [5, 4, 3, 2, 1, 1, 0]
        frames: List[cairo.ImageSurface] = []

        for f in range(total):
            bf = body_seq[f]
            head = heads[bf]
            if f < n_intro:
                u_in = f / float(n_intro)
                w = R.smoothstep(0.0, 1.0, u_in)
                ang = 0.25 * math.pi * u_in
                eye_spec = ("look", 4, -4) if f >= 3 else None
            elif f < n_intro + n_loop:
                fl = f - n_intro
                u_loop = fl / float(n_loop)
                w = 1.0
                ang = 0.25 * math.pi + 2.0 * math.pi * u_loop
                if fl < 14:
                    eye_spec = ("look", 4, -4)
                elif fl == 14:
                    eye_spec = ("blink", 0, 0)
                elif fl < 28:
                    eye_spec = ("look", -4, -4)
                else:
                    eye_spec = ("look", 2, -4)
            else:
                fo = f - (n_intro + n_loop)
                u_out = fo / float(n_outro)
                w = 1.0 - R.smoothstep(0.0, 1.0, u_out)
                ang = 0.25 * math.pi + 0.25 * math.pi * u_out
                eye_spec = ("look", 2, -2) if fo < 3 else None

            ax, ay = RA.torso_center(head)
            blobs, trails, sparkles = [], [], []
            for k, (rx, ry, tilt_deg, rev, phi0) in enumerate(CLASSIC_RINGS):
                theta = phi0 + rev * ang
                px, py, ez = RA.orbit_point(ax, ay, rx, ry, tilt_deg, theta)
                blobs.append((ez, k, px, py, min(2, max(1, RA.size_from_ez(ez)))))
                tx, ty, tez = RA.orbit_point(ax, ay, rx, ry, tilt_deg, theta - rev * 0.22)
                trails.append((tez, k, tx, ty, 3))
                if k == 2 and w >= 0.7 and ez >= 0.35:
                    sparkles.append((ez + 0.1, px, py, 8 if (f % 4 < 2) else 5, _rgb(255, 255, 255)))

            def draw_rings(ctx: cairo.Context, front: bool, weight=w, c_ax=ax, c_ay=ay) -> None:
                if weight <= 0.05:
                    return
                col = _rgb(142, 206, 255) if front else _rgb(112, 142, 174)
                alpha = (0.90 if front else 0.72) * weight
                for rx, ry, tilt_deg, _, _ in CLASSIC_RINGS:
                    for i in range(28):
                        th = (2.0 * math.pi * i) / 28.0
                        dx, dy, ez = RA.orbit_point(c_ax, c_ay, rx, ry, tilt_deg, th)
                        if (ez >= 0.0) != front:
                            continue
                        RA.draw_pixel_rect(ctx, round(dx) - 2, round(dy) - 2, 4, 4, col, alpha)

            blobs.sort(key=lambda item: item[0])
            trails.sort(key=lambda item: item[0])
            frames.append(
                RA.render_frame(
                    clean[bf],
                    head,
                    None,
                    blobs,
                    trails,
                    sparkles=sparkles,
                    eye_spec=eye_spec,
                    leg_retract=1.0,
                    custom_colors=WHITE_PALETTE,
                    back_fn=lambda ctx, fn=draw_rings: fn(ctx, False),
                    front_fn=lambda ctx, fn=draw_rings: fn(ctx, True),
                )
            )
        return frames, (n_intro, n_intro + n_loop - 1)

    def render_running() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n_intro, n_loop, n_outro = 5, 30, 5
        total = n_intro + n_loop + n_outro
        body_seq = [0, 1, 2, 3, 4] + (RA.HOVER_10 * 3) + [4, 3, 2, 1, 0]
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
            blobs, trails = legless_hover_orbits(head, phase, rx_scale=0.95)
            scroll = (f - n_intro) % 10 if f >= n_intro else 0

            def overlay(ctx: cairo.Context, a=alpha, sc=scroll, fr=f) -> None:
                if a <= 0.05:
                    return
                tx, ty, tw, th = 486, 134, 62, 56
                RA.draw_pixel_rect(ctx, tx - 2, ty - 2, tw + 4, th + 4, _rgb(45, 72, 96), a)
                RA.draw_pixel_rect(ctx, tx, ty, tw, th, _rgb(14, 22, 32), a)
                RA.draw_pixel_rect(ctx, tx, ty, tw, 10, _rgb(28, 42, 60), a)
                RA.draw_pixel_rect(ctx, tx + 4, ty + 3, 4, 4, _rgb(255, 96, 96), a)
                RA.draw_pixel_rect(ctx, tx + 10, ty + 3, 4, 4, _rgb(255, 210, 80), a)
                RA.draw_pixel_rect(ctx, tx + 16, ty + 3, 4, 4, _rgb(80, 235, 140), a)
                widths = (28, 40, 22, 46, 32)
                for row in range(4):
                    ly = ty + 15 + row * 9
                    w_line = widths[(row + sc) % len(widths)]
                    col = _rgb(80, 240, 150) if (row + sc) % 3 != 1 else _rgb(90, 225, 255)
                    RA.draw_pixel_rect(ctx, tx + 6, ly, 4, 4, _rgb(255, 235, 110), a)
                    RA.draw_pixel_rect(ctx, tx + 13, ly, w_line, 4, col, a)
                if (fr // 3) % 2 == 0:
                    RA.draw_pixel_rect(ctx, tx + 6, ty + 48, 6, 4, _rgb(110, 255, 175), a)

            frames.append(
                RA.render_frame(
                    clean[bf], head, None, blobs, trails, eye_spec=eye_spec,
                    leg_retract=1.0, custom_colors=WHITE_PALETTE, overlay_fn=overlay,
                )
            )
        return frames, (n_intro, n_intro + n_loop - 1)

    def render_working() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n_intro, n_loop, n_outro = 5, 30, 5
        total = n_intro + n_loop + n_outro
        body_seq = [0, 1, 2, 3, 4] + (RA.HOVER_10 * 3) + [4, 3, 2, 1, 0]
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
            blobs, trails = legless_hover_orbits(head, phase, rx_scale=0.95)
            frames.append(
                RA.render_frame(
                    clean[bf], head, None, blobs, trails, eye_spec=eye_spec,
                    leg_retract=1.0, custom_colors=WHITE_PALETTE,
                    overlay_fn=lambda ctx, a=alpha, th=ang: (
                        RA._draw_pixel_gear(ctx, 502, 138, 7, th, _rgb(92, 232, 255), a),
                        RA._draw_pixel_gear(ctx, 528, 114, 5, -th * 1.4 + 0.3, _rgb(255, 220, 106), a),
                    ),
                )
            )
        return frames, (n_intro, n_intro + n_loop - 1)

    def render_exploring() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n_intro, n_loop, n_outro = 5, 30, 5
        total = n_intro + n_loop + n_outro
        body_seq = [0, 1, 2, 3, 4] + (RA.HOVER_10 * 3) + [4, 3, 2, 1, 0]
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
            blobs, trails = legless_hover_orbits(head, phase, rx_scale=0.9)

            def overlay(ctx: cairo.Context, a=alpha, su=scan_u) -> None:
                if a <= 0.05:
                    return
                dx, dy, dw, dh = 488, 128, 52, 62
                RA.draw_pixel_rect(ctx, dx - 2, dy - 2, dw + 4, dh + 4, _rgb(70, 130, 185), a)
                RA.draw_pixel_rect(ctx, dx, dy, dw, dh, _rgb(232, 242, 255), a)
                RA.draw_pixel_rect(ctx, dx + dw - 10, dy, 10, 10, _rgb(168, 200, 232), a)
                for row, lw in enumerate((30, 38, 26, 40, 32, 24)):
                    RA.draw_pixel_rect(ctx, dx + 6, dy + 10 + row * 8, lw, 4, _rgb(110, 145, 185), a)
                sy = round(dy + 6 + su * (dh - 14))
                RA.draw_pixel_rect(ctx, dx - 3, sy, dw + 6, 4, _rgb(80, 245, 255), a)

            frames.append(
                RA.render_frame(
                    clean[bf], head, None, blobs, trails, eye_spec=eye_spec,
                    leg_retract=1.0, custom_colors=WHITE_PALETTE, overlay_fn=overlay,
                )
            )
        return frames, (n_intro, n_intro + n_loop - 1)

    def draw_legless_mini(ctx: cairo.Context, cx: int, cy: int, alpha: float) -> None:
        if alpha <= 0.05:
            return
        x0, y0 = cx - 9, cy - 6
        RA.draw_pixel_rect(ctx, x0, y0, 18, 10, _rgb(46, 161, 244), alpha)
        RA.draw_pixel_rect(ctx, x0 + 1, y0 + 10, 16, 2, _rgb(28, 124, 210), alpha)
        RA.draw_pixel_rect(ctx, x0 + 4, y0 + 3, 3, 3, _rgb(10, 14, 20), alpha)
        RA.draw_pixel_rect(ctx, x0 + 11, y0 + 3, 3, 3, _rgb(10, 14, 20), alpha)

    def render_delegating() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n_intro, n_loop, n_outro = 5, 30, 5
        total = n_intro + n_loop + n_outro
        body_seq = [0, 1, 2, 3, 4] + (RA.HOVER_10 * 3) + [4, 3, 2, 1, 0]
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
            blobs, trails = legless_hover_orbits(head, phase)

            def overlay(ctx: cairo.Context, weight=w, ph=phase, acx=cx, ahy=hy0, fr=f) -> None:
                if weight <= 0.05:
                    return
                for idx, (ox, oy) in enumerate(((-66, -34), (0, -52), (+66, -34))):
                    bob = round(4.0 * math.sin(2.0 * math.pi * (ph + idx * 0.33)))
                    bx = round(R.lerp(acx, acx + ox, weight))
                    by = round(R.lerp(ahy + 20, ahy + oy + bob, weight))
                    for step in (1, 2):
                        u_dot = step / 3.0
                        lx = round(R.lerp(acx, bx, u_dot))
                        ly = round(R.lerp(ahy + 4, by, u_dot))
                        if (fr + step) % 2 == 0 or weight > 0.8:
                            RA.draw_pixel_rect(ctx, lx - 1, ly - 1, 3, 3, WHITE_PALETTE[step], weight * 0.85)
                    draw_legless_mini(ctx, bx, by, weight)

            frames.append(
                RA.render_frame(
                    clean[bf], head, None, blobs, trails, eye_spec=eye_spec,
                    leg_retract=1.0, custom_colors=WHITE_PALETTE, overlay_fn=overlay,
                )
            )
        return frames, (n_intro, n_intro + n_loop - 1)

    def render_asking() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n_intro, n_loop, n_outro = 4, 26, 6
        total = n_intro + n_loop + n_outro
        body_seq = [0, 1, 2, 3] + [RA.HOVER_10[i % 10] for i in range(n_loop)] + [3, 2, 1, 1, 0, 0]
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
            blobs, trails = legless_hover_orbits(head, phase)
            bob = round(3.0 * math.sin(2.0 * math.pi * phase))

            def overlay(ctx: cairo.Context, a=alpha, by=bob, ph=phase) -> None:
                if a <= 0.05:
                    return
                bx, y0, bw, bh = 486, 66 + by, 44, 46
                RA.draw_pixel_rect(ctx, bx - 2, y0 - 2, bw + 4, bh + 4, _rgb(90, 120, 195), a)
                RA.draw_pixel_rect(ctx, bx, y0, bw, bh, _rgb(245, 248, 255), a)
                RA.draw_pixel_rect(ctx, bx - 6, y0 + bh - 10, 6, 6, _rgb(245, 248, 255), a)
                qcol = _rgb(148, 92, 246) if math.sin(4.0 * math.pi * ph) >= 0 else _rgb(60, 185, 245)
                qx, qy = bx + 12, y0 + 8
                RA.draw_pixel_rect(ctx, qx + 4, qy, 12, 4, qcol, a)
                RA.draw_pixel_rect(ctx, qx, qy + 4, 4, 6, qcol, a)
                RA.draw_pixel_rect(ctx, qx + 16, qy + 4, 4, 8, qcol, a)
                RA.draw_pixel_rect(ctx, qx + 8, qy + 12, 8, 4, qcol, a)
                RA.draw_pixel_rect(ctx, qx + 8, qy + 16, 4, 6, qcol, a)
                RA.draw_pixel_rect(ctx, qx + 8, qy + 25, 4, 4, qcol, a)

            frames.append(
                RA.render_frame(
                    clean[bf], head, None, blobs, trails, eye_spec=eye_spec,
                    leg_retract=1.0, custom_colors=WHITE_PALETTE, overlay_fn=overlay,
                )
            )
        return frames, (n_intro, n_intro + n_loop - 1)

    def render_listening() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n = 20
        body_seq = RA.HOVER_10 * 2
        frames = []
        for f in range(n):
            bf = body_seq[f]
            head = heads[bf]
            phase = f / float(n)
            blobs, trails = legless_hover_orbits(head, phase, rx_scale=0.88, y_shift=6.0, max_size=2)
            frames.append(
                RA.render_frame(
                    clean[bf], head, None, blobs, trails, eye_spec=("look", 0, 5),
                    leg_retract=1.0, custom_colors=WHITE_PALETTE,
                )
            )
        return frames, (0, n - 1)

    def render_watching() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n = 30
        body_seq = RA.HOVER_10 * 3
        frames = []
        for f in range(n):
            bf = body_seq[f]
            head = heads[bf]
            phase = f / float(n)
            eye_spec = ("look", -4 if f < 10 else (0 if f < 20 else 4), -2)
            blobs, trails = legless_hover_orbits(head, phase)

            def overlay(ctx: cairo.Context, ph=phase, h=head) -> None:
                cx = round(0.5 * (h[0] + h[1]))
                ry = h[2] - 18
                pulse = (ph * 2.0) % 1.0
                RA.draw_pixel_rect(ctx, cx - 2, ry - 2, 4, 4, _rgb(80, 245, 200), 0.95)
                sp = round(6 + pulse * 18)
                a = 1.0 - pulse
                RA.draw_pixel_rect(ctx, cx - sp, ry - 4, 4, 8, _rgb(80, 245, 200), a)
                RA.draw_pixel_rect(ctx, cx + sp - 4, ry - 4, 4, 8, _rgb(80, 245, 200), a)

            frames.append(
                RA.render_frame(
                    clean[bf], head, None, blobs, trails, eye_spec=eye_spec,
                    leg_retract=1.0, custom_colors=WHITE_PALETTE, overlay_fn=overlay,
                )
            )
        return frames, (0, n - 1)

    def render_done() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n = 20
        confetti = (
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
            bf = RA.HOVER_10[f % 10]
            head = heads[bf]
            hop = -round(6.0 * math.sin(math.pi * min(1.0, u * 1.4)))
            blobs, trails = legless_hover_orbits(head, u, rx_scale=1.08, y_shift=hop * 0.5)

            def overlay(ctx: cairo.Context, prog=u) -> None:
                for cx0, cy0, col, delay in confetti:
                    t = R.clamp((prog - delay) / 0.75)
                    if 0.0 < t < 1.0:
                        px = round(RA.CENTER_X + cx0 + 8.0 * math.sin(t * 6.0))
                        py = round(cy0 - t * 44.0)
                        RA.draw_pixel_rect(ctx, px, py, 5, 5, col, 1.0 - t)

            frames.append(
                RA.render_frame(
                    clean[bf], head, None, blobs, trails, eye_spec=("happy", 0, 0),
                    leg_retract=1.0, body_offset=(0, hop), custom_colors=WHITE_PALETTE, overlay_fn=overlay,
                )
            )
        return frames, (0, n - 1)

    def render_happy() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n = 24
        frames = []
        for f in range(n):
            u = f / float(n)
            bf = RA.HOVER_10[f % 10]
            head = heads[bf]
            hop = -round(7.0 * abs(math.sin(2.0 * math.pi * u)))
            blobs, trails = legless_hover_orbits(head, u, rx_scale=1.1, y_shift=hop * 0.5)

            def overlay(ctx: cairo.Context, prog=u) -> None:
                for side, delay in ((-1, 0.05), (+1, 0.25)):
                    t = R.clamp((prog - delay) / 0.7)
                    if 0.0 < t < 1.0:
                        hx = round(RA.CENTER_X + side * 56)
                        hy = round(112 - t * 44.0)
                        col = _rgb(255, 110, 195)
                        a = 1.0 - t
                        RA.draw_pixel_rect(ctx, hx - 5, hy, 4, 4, col, a)
                        RA.draw_pixel_rect(ctx, hx + 1, hy, 4, 4, col, a)
                        RA.draw_pixel_rect(ctx, hx - 5, hy + 4, 10, 4, col, a)
                        RA.draw_pixel_rect(ctx, hx - 2, hy + 8, 4, 3, col, a)

            frames.append(
                RA.render_frame(
                    clean[bf], head, None, blobs, trails, eye_spec=("happy", 0, 0),
                    tint=(188.0, 1.08, 1.08, 1.0, 1.0), leg_retract=1.0,
                    body_offset=(0, hop), custom_colors=WHITE_PALETTE, overlay_fn=overlay,
                )
            )
        return frames, (0, n - 1)

    def render_dance() -> Tuple[List[cairo.ImageSurface], Tuple[int, int], int]:
        n_intro, n_loop, n_outro = 5, 30, 5
        total = n_intro + n_loop + n_outro
        head = heads[0]
        base_clean = clean[0]
        frames = []
        for f in range(total):
            env = R.smoothstep(0.0, 1.0, f / 4.0) if f < n_intro else (1.0 - R.smoothstep(0.0, 1.0, (f - n_intro - n_loop) / 4.0) if f >= n_intro + n_loop else 1.0)
            t = (f - n_intro) / float(n_loop)
            dx = round(5.0 * env * math.sin(2.0 * math.pi * (2.0 * t)))
            dy = -round(5.0 * env * (0.5 - 0.5 * math.cos(2.0 * math.pi * (4.0 * t))))
            blobs, trails = legless_hover_orbits(head, t, rx_scale=1.0 + 0.08 * env, ry_scale=1.0 + 0.04 * env, y_shift=dy * 0.4)
            blobs = [(z, k, px + dx * 0.55, py, sz) for (z, k, px, py, sz) in blobs]
            trails = [(z, k, px + dx * 0.55, py, sz) for (z, k, px, py, sz) in trails]
            eye_spec = None if f in (0, 1, 38, 39) else (("blink", 0, 0) if f in (12, 27) else ("happy", 0, 0))

            def overlay(ctx: cairo.Context, fr=f, sx=dx, sy=dy, e=env) -> None:
                if e <= 0.05:
                    return
                prog = fr / float(total)
                specs = ((-66, 0.08, _rgb(255, 195, 40), False), (+58, 0.28, _rgb(55, 215, 255), True),
                         (-58, 0.48, _rgb(255, 95, 190), True), (+64, 0.68, _rgb(255, 195, 40), False))
                for side, start_u, col, dbl in specs:
                    un = (prog - start_u) / 0.36
                    if 0.0 < un < 1.0:
                        fade = e * min(1.0, un * 4.0) * (1.0 - un)
                        RA._draw_music_note(
                            ctx,
                            round(RA.CENTER_X + side + sx * 0.5 + 2.5 * math.sin(un * 2.0 * math.pi)),
                            round(112 + sy * 0.5 - 42.0 * un),
                            col, fade, dbl,
                        )

            frames.append(
                RA.render_frame(
                    base_clean, head, None, blobs, trails, eye_spec=eye_spec,
                    tint=(195.0, 1.08, 1.06, 1.0, 1.0), tint_blend=env, leg_retract=1.0,
                    body_offset=(dx, dy), custom_colors=WHITE_PALETTE, overlay_fn=overlay,
                )
            )
        return frames, (n_intro, n_intro + n_loop - 1), 65

    def render_sad() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n_intro, n_loop, n_outro = 6, 30, 6
        total = n_intro + n_loop + n_outro
        body_seq = [0, 1, 2, 3, 4, 5] + ([5, 5, 5, 4, 4, 5] * 5) + [5, 4, 3, 2, 1, 0]
        sad_colors = [tuple(c * 0.55 + 0.15 for c in col) for col in WHITE_PALETTE]
        frames = []
        for f in range(total):
            bf = body_seq[f]
            head = heads[bf]
            gloom = RA._mood_intensity(f, n_intro, n_loop, n_outro)
            phase = (f - n_intro) / float(n_loop)
            slump = round(4.0 * gloom)
            blobs, trails = legless_hover_orbits(
                head, phase, ry_scale=1.0 - 0.35 * gloom, y_shift=16.0 * gloom, max_size=2 if gloom >= 0.5 else 3
            )
            eye_spec = ("sad", 0, 0) if 2 <= f < (total - 3) else None

            def overlay(ctx: cairo.Context, fr=f, h=head, sl=slump, gl=gloom) -> None:
                if fr < 4 or fr >= n_intro + n_loop:
                    return
                t = 0.0 if fr < n_intro else ((fr - n_intro) % 15) / 15.0
                fade = (fr - 3) / 3.0 if fr < n_intro else 1.0
                RA.draw_pixel_rect(
                    ctx, 450, round(h[2] + 42 + sl + t * 28.0), 4, 6, _rgb(100, 230, 255),
                    (1.0 - t * 0.72) * fade * min(1.0, gl + 0.25),
                )

            frames.append(
                RA.render_frame(
                    clean[bf], head, None, blobs, trails, eye_spec=eye_spec,
                    tint=(214.0, 0.35, 0.78, 0.35, 0.82), tint_blend=gloom, leg_retract=1.0,
                    body_offset=(0, slump), custom_colors=RA._lerp_palette(WHITE_PALETTE, sad_colors, gloom),
                    overlay_fn=overlay,
                )
            )
        return frames, (n_intro, n_intro + n_loop - 1)

    def render_angry() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n_intro, n_loop, n_outro = 6, 30, 6
        total = n_intro + n_loop + n_outro
        body_seq = [0, 1, 2, 3, 2, 1] + (RA.HOVER_10 * 3) + [1, 2, 3, 2, 1, 0]
        shake_6 = (-2, +2, -2, 0, +2, 0)
        angry_colors = [_rgb(255, 255, 255), _rgb(255, 255, 255), _rgb(255, 255, 255), _rgb(255, 255, 255), _rgb(255, 255, 255)]
        frames = []
        for f in range(total):
            bf = body_seq[f]
            head = heads[bf]
            heat = RA._mood_intensity(f, n_intro, n_loop, n_outro)
            phase = ((f - n_intro) / float(n_loop)) * 2.0
            sx = 0 if (f < 3 or f >= total - 3) else ((-1 if (f % 2) else 1) if f < n_intro else (shake_6[(f - n_intro) % 6] if f < n_intro + n_loop else (1 if (f % 2) else -1)))
            blobs, trails = legless_hover_orbits(head, phase, rx_scale=1.0 + 0.12 * heat)
            eye_spec = ("angry", 0, 0) if 2 <= f < (total - 3) else None

            def overlay(ctx: cairo.Context, fr=f, h=head, sx_v=sx, ht=heat) -> None:
                if ht <= 0.05:
                    return
                st_ph = ((fr - n_intro) / float(n_loop)) * 2.0
                st_a = min(1.0, ht * 1.15)
                for side, shift in ((-42, 0.0), (+42, 0.35)):
                    t = (st_ph + shift) % 1.0
                    sz = 8 if t < 0.5 else 6
                    RA.draw_pixel_rect(ctx, round(RA.CENTER_X + side + sx_v) - sz // 2, round(h[2] - 8 - t * 34.0), sz, sz, _rgb(255, 240, 230), (1.0 - t) * st_a)
                mx, my = h[1] + 4 + sx_v, h[2] - 12
                if ht >= 0.45 and ((fr - n_intro) // 3) % 2 == 0:
                    col = _rgb(255, 70, 70)
                    a_v = min(1.0, ht * 1.2)
                    RA.draw_pixel_rect(ctx, mx, my, 4, 4, col, a_v)
                    RA.draw_pixel_rect(ctx, mx + 6, my, 4, 4, col, a_v)
                    RA.draw_pixel_rect(ctx, mx, my + 6, 4, 4, col, a_v)
                    RA.draw_pixel_rect(ctx, mx + 6, my + 6, 4, 4, col, a_v)

            frames.append(
                RA.render_frame(
                    clean[bf], head, None, blobs, trails, eye_spec=eye_spec,
                    tint=(6.0, 1.05, 0.98, 1.0, 1.0), tint_blend=heat, leg_retract=1.0,
                    body_offset=(sx, 0), custom_colors=RA._lerp_palette(WHITE_PALETTE, angry_colors, heat),
                    overlay_fn=overlay,
                )
            )
        return frames, (n_intro, n_intro + n_loop - 1)

    def render_error() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n = 20
        err_colors = [_rgb(255, 235, 235), _rgb(255, 245, 210), _rgb(255, 220, 210), _rgb(255, 240, 240), _rgb(255, 250, 225)]
        frames = []
        for f in range(n):
            u = f / float(n)
            bf = 3 if f < 4 else RA.HOVER_10[f % 10]
            head = heads[bf]
            jx = -3 if f in (1, 3) else (3 if f in (2, 4) else 0)
            blobs, trails = legless_hover_orbits(head, u * 1.5, rx_scale=1.08)

            def overlay(ctx: cairo.Context, fr=f, h=head, j=jx) -> None:
                if (fr // 2) % 2 == 0:
                    bx, by = h[1] + 6 + j, h[2] - 28
                    RA.draw_pixel_rect(ctx, bx - 2, by - 2, 18, 28, _rgb(255, 70, 70))
                    RA.draw_pixel_rect(ctx, bx, by, 14, 24, _rgb(255, 220, 75))
                    RA.draw_pixel_rect(ctx, bx + 5, by + 4, 4, 10, _rgb(30, 12, 12))
                    RA.draw_pixel_rect(ctx, bx + 5, by + 17, 4, 4, _rgb(30, 12, 12))

            frames.append(
                RA.render_frame(
                    clean[bf], head, None, blobs, trails, eye_spec=("error", 0, 0),
                    tint=(14.0, 0.9, 0.95, 1.0, 1.0), leg_retract=1.0,
                    body_offset=(jx, 0), custom_colors=err_colors, overlay_fn=overlay,
                )
            )
        return frames, (0, n - 1)

    def render_canceled() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n = 18
        muted = [tuple(c * 0.65 + 0.2 for c in col) for col in WHITE_PALETTE]
        frames = []
        for f in range(n):
            u = f / float(n)
            bf = 5 if f < 10 else 4
            head = heads[bf]
            drop = 3 if f < 6 else 1
            blobs, trails = legless_hover_orbits(head, u * 0.25, ry_scale=0.75, max_size=2)
            frames.append(
                RA.render_frame(
                    clean[bf], head, None, blobs, trails, eye_spec=("surprised", 0, 0),
                    tint=(210.0, 0.55, 0.85, 0.6, 0.88), leg_retract=1.0,
                    body_offset=(0, drop), custom_colors=muted,
                )
            )
        return frames, (0, n - 1)

    def render_tired() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n = 24
        dim_colors = [tuple(c * 0.6 + 0.1 for c in col) for col in WHITE_PALETTE]
        frames = []
        for f in range(n):
            u = f / float(n)
            bf = 5 if f < 14 else 4
            head = heads[bf]
            droop = 3 if f < 16 else 2
            blobs, trails = legless_hover_orbits(head, u * 0.4, rx_scale=0.9, ry_scale=0.6, y_shift=14.0, max_size=2)

            def overlay(ctx: cairo.Context, prog=u, h=head, dr=droop) -> None:
                t = R.clamp(prog * 1.2)
                sx, sy = h[1] - 4, round(h[2] + 18 + dr + t * 24.0)
                a = 1.0 - t * 0.5
                RA.draw_pixel_rect(ctx, sx, sy, 5, 8, _rgb(145, 242, 255), a)
                RA.draw_pixel_rect(ctx, sx + 1, sy + 1, 2, 3, _rgb(235, 252, 255), a)

            frames.append(
                RA.render_frame(
                    clean[bf], head, None, blobs, trails, eye_spec=("tired", 0, 0),
                    tint=(220.0, 0.55, 0.72, 0.6, 0.78), leg_retract=1.0,
                    body_offset=(0, droop), custom_colors=dim_colors, overlay_fn=overlay,
                )
            )
        return frames, (0, n - 1)

    def draw_dim_laptop(ctx: cairo.Context) -> None:
        RA.draw_pixel_rect(ctx, 456, 232, 62, 6, _rgb(96, 102, 112), 0.96)
        RA.draw_pixel_rect(ctx, 456, 230, 56, 2, _rgb(138, 144, 154), 0.96)
        for step, y in enumerate(range(190, 230, 2)):
            lx = 482 - (step // 3)
            RA.draw_pixel_rect(ctx, lx, y, 42, 2, _rgb(132, 138, 148), 0.96)
            RA.draw_pixel_rect(ctx, lx + 42, y, 4, 2, _rgb(92, 98, 108), 0.96)
        RA.draw_pixel_rect(ctx, 482, 188, 46, 2, _rgb(154, 160, 170), 0.96)

    def render_closed() -> Tuple[List[cairo.ImageSurface], Tuple[int, int]]:
        n = 30
        sleep_seq = [5, 5, 5, 4, 4, 4, 3, 3, 4, 4] * 3
        dim_colors = [tuple(c * 0.45 + 0.08 for c in col) for col in WHITE_PALETTE]
        frames = []
        for f in range(n):
            u = f / float(n)
            bf = sleep_seq[f]
            head = heads[bf]
            blobs, trails = legless_hover_orbits(head, u * 0.35, rx_scale=0.82, ry_scale=0.55, y_shift=14.0, max_size=1)

            def overlay(ctx: cairo.Context, prog=u, h=head) -> None:
                for offset, scale in ((0.0, 3), (0.33, 2), (0.66, 2)):
                    t = (prog + offset) % 1.0
                    zx = round(h[1] - 4 + t * 24.0 + 4.0 * math.sin(t * 6.28))
                    zy = round(h[2] + 6 - t * 46.0)
                    RA._draw_z_glyph(ctx, zx, zy, scale, math.sin(math.pi * t) * 0.95)

            frames.append(
                RA.render_frame(
                    clean[bf], head, None, blobs, trails, eye_spec=("sleep", 0, 0),
                    tint=(222.0, 0.55, 0.46, 0.55, 0.52), leg_retract=1.0,
                    front_fn=draw_dim_laptop, custom_colors=dim_colors, overlay_fn=overlay,
                )
            )
        return frames, (0, n - 1)

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

#!/usr/bin/env python3
"""Render Atom's idle loop: base.gif's hover + the gemini beanie + base's own atoms, coloured.

Reuses render_gemini_typing.py (base.gif clean-up, head tracking, rainbow
beanie) without changing it:

  * body: base.gif's hover frames 0-5, ping-ponged (no laptop), cleaned of
    electrons, with the rainbow beanie painted on;
  * electrons: base.gif's real electrons from all 30 frames -- the exact
    pixels, so the same shapes, size and motion -- moved with the head
    onto the hover body. Each electron is tracked across frames and keeps one
    colour (violet, green, yellow, red). For contrast they're lit like the
    thinking electrons: a near-white core and a soft glow in their colour;
  * 30 frames @ 10 fps = 3.0 s, seamless (base.gif's electrons loop).

Writes a 640x360 black-background GIF like the other renders; then
tools/make_sprite.py turns it into assets/atom/idle.webp.

Usage: python3 tools/render_idle.py [--out atom_idle.gif]   (needs python-cairo, ffmpeg)
"""

from __future__ import annotations

import argparse
import math
import shutil
import sys
import tempfile
from pathlib import Path

import cairo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import tools.render_gemini_typing as R  # noqa: E402

W, H, N = R.W, R.H, R.BASE_N_FRAMES
HOVER = [0, 1, 2, 3, 4, 5, 4, 3, 2, 1]  # 1 s up-and-down hover, no laptop
BODY_SEQ = HOVER * 3                    # 30 frames, one per base.gif frame
# violet, green, yellow, red (violet rather than blue: a blue atom vanishes against Atom's body)
PALETTE = [(192, 132, 255), (94, 242, 155), (255, 233, 92), (255, 92, 92)]

WHITE_LO, WHITE_HI = 72, 200   # min(r,g,b): below LO not electron; above HI pure electron core
MIN_BLOB = 15                  # px; smaller specks are render noise
CORE = 200                     # an electron has a white core; grey laptop bits and body highlights don't
TRACK_DIST = 40.0              # px per frame an electron may move (head-relative)
# Contrast like the thinking (gemini.gif) electrons: hot core + coloured glow.
CORE_WHITE = 0.55              # how far an electron's solid core is pushed towards white
EDGE_BOOST = 1.4               # its soft edge, made a little more opaque
GLOW_PX = 7.0                  # glow reach beyond the electron, in render px
GLOW_STRENGTH = 0.85           # glow intensity right at the electron's edge
TOP_Y = 247                    # below this is the mock prompt bar


def head_anchor(head):
    hx0, hx1, hy0 = head
    return (hx0 + hx1) / 2.0, float(hy0)


def electron_pixels(f, rgb):
    """{(x, y): weight} for electron pixels (white core + halo) in base frame f."""
    out = {}
    for y in range(TOP_Y):
        for x in range(W):
            i = (y * W + x) * 3
            r, g, b = rgb[i], rgb[i + 1], rgb[i + 2]
            m = min(r, g, b)
            if m < WHITE_LO or R.is_protected_laptop(f, x, y, r, g, b):
                continue
            out[(x, y)] = min(1.0, (m - WHITE_LO) / float(WHITE_HI - WHITE_LO))
    return out


def blobs(pixels):
    """Electrons as 8-connected components: list of (pixel list, centroid)."""
    seen, comps = set(), []
    for p in pixels:
        if p in seen:
            continue
        seen.add(p)
        stack, pts = [p], []
        while stack:
            x, y = stack.pop()
            pts.append((x, y))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    n = (x + dx, y + dy)
                    if n in pixels and n not in seen:
                        seen.add(n)
                        stack.append(n)
        if len(pts) >= MIN_BLOB and max(pixels[q] for q in pts) >= (CORE - WHITE_LO) / float(WHITE_HI - WHITE_LO):
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            comps.append((pts, (cx, cy)))
    return comps


def assign_colours(frame_blobs, anchors):
    """Track blobs frame to frame (head-relative) so each electron keeps a colour.

    Runs around the loop twice and keeps the second pass, so the colours at
    frame 29 -> 0 match too.
    """
    tracks = []  # dicts: pos, colour, seen
    result = [None] * N
    for lap in range(2):
        for f in range(N):
            ax, ay = anchors[f]
            step = lap * N + f
            live = [t for t in tracks if step - t["seen"] <= 2]
            used, colours = set(), []
            for pts, (cx, cy) in sorted(frame_blobs[f], key=lambda b: -len(b[0])):
                rel = (cx - ax, cy - ay)
                best, bd = None, TRACK_DIST
                for t in live:
                    if id(t) in used:
                        continue
                    d = math.dist(rel, t["pos"])
                    if d < bd:
                        best, bd = t, d
                if best is None:
                    counts = [sum(1 for t in live if t["colour"] == c) for c in range(len(PALETTE))]
                    best = {"colour": counts.index(min(counts)), "pos": rel, "seen": step}
                    tracks.append(best)
                    live.append(best)
                used.add(id(best))
                best["pos"], best["seen"] = rel, step
                colours.append(best["colour"])
            result[f] = colours
    return result


def render_rgba_frame(
    clean_rgb: bytearray,
    head: tuple[int, int, int],
    crown_cols: list[tuple[int, int, int]],
    frame_blobs: list,
    frame_colours: list[int],
    frame_pixels: dict,
    anchor_src: tuple[float, float],
    anchor_dst: tuple[float, float],
) -> cairo.ImageSurface:
    rgb = bytearray(clean_rgb)
    R.paint_crown_on_frame(rgb, head, crown_cols)
    fg_mask = R.build_foreground_mask(rgb, head)
    buf = bytearray(W * H * 4)
    for idx in range(W * H):
        if fg_mask[idx]:
            i3, i4 = idx * 3, idx * 4
            buf[i4] = rgb[i3 + 2]
            buf[i4 + 1] = rgb[i3 + 1]
            buf[i4 + 2] = rgb[i3]
            buf[i4 + 3] = 255

    dx = round(anchor_dst[0] - anchor_src[0])
    dy = round(anchor_dst[1] - anchor_src[1])
    for (pts, (cx, cy)), ci in zip(sorted(frame_blobs, key=lambda b: -len(b[0])), frame_colours):
        colour = PALETTE[ci]
        core = tuple(c + (255 - c) * CORE_WHITE for c in colour)
        radius = math.sqrt(len(pts) / math.pi)
        reach = radius + GLOW_PX
        for ty in range(math.floor(cy - reach), math.ceil(cy + reach) + 1):
            for tx in range(math.floor(cx - reach), math.ceil(cx + reach) + 1):
                d = math.hypot(tx - cx, ty - cy) - radius
                if d <= 0 or d >= GLOW_PX:
                    continue
                g = GLOW_STRENGTH * (1 - d / GLOW_PX) ** 2
                ox, oy = tx + dx, ty + dy
                if not (0 <= ox < W and 0 <= oy < TOP_Y):
                    continue
                j4 = (oy * W + ox) * 4
                pa = buf[j4 + 3]
                if pa == 255:
                    buf[j4] = round(255 - (255 - buf[j4]) * (1 - g * colour[2] / 255))
                    buf[j4 + 1] = round(255 - (255 - buf[j4 + 1]) * (1 - g * colour[1] / 255))
                    buf[j4 + 2] = round(255 - (255 - buf[j4 + 2]) * (1 - g * colour[0] / 255))
                else:
                    inv = 1.0 - g
                    new_a = min(255, round(255.0 * g + pa * inv))
                    buf[j4] = min(new_a, round(colour[2] * g + buf[j4] * inv))
                    buf[j4 + 1] = min(new_a, round(colour[1] * g + buf[j4 + 1] * inv))
                    buf[j4 + 2] = min(new_a, round(colour[0] * g + buf[j4 + 2] * inv))
                    buf[j4 + 3] = new_a

        for x, y in pts:
            tx, ty = x + dx, y + dy
            if not (0 <= tx < W and 0 <= ty < TOP_Y):
                continue
            raw_a = frame_pixels[(x, y)]
            paint = core if raw_a >= 1.0 else colour
            a = min(1.0, raw_a * EDGE_BOOST)
            inv = 1.0 - a
            j4 = (ty * W + tx) * 4
            new_a = min(255, round(255.0 * a + buf[j4 + 3] * inv))
            buf[j4] = min(new_a, round(paint[2] * a + buf[j4] * inv))
            buf[j4 + 1] = min(new_a, round(paint[1] * a + buf[j4 + 1] * inv))
            buf[j4 + 2] = min(new_a, round(paint[0] * a + buf[j4 + 2] * inv))
            buf[j4 + 3] = new_a

    return cairo.ImageSurface.create_for_data(buf, cairo.FORMAT_ARGB32, W, H)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="", help="Output GIF path (default: atom_idle.gif unless --frames-dir is sole output)")
    ap.add_argument("--frames-dir", default="", help="Optional dir to write transparent 32-bit RGBA PNG frames directly")
    args = ap.parse_args()

    out_gif = args.out or ("" if args.frames_dir else str(R.ART_DIR / "atom_idle.gif"))
    base = R.load_gif_frames(R.BASE_GIF)
    gemini = R.load_gif_frames(R.GEMINI_GIF)
    clean, heads = R.clean_base_frames(base)
    crowns = R.sample_gemini_crowns(gemini)
    anchors = [head_anchor(h) for h in heads]

    pixels = [electron_pixels(f, base[f]) for f in range(N)]
    frame_blobs = [blobs(p) for p in pixels]
    colours = assign_colours(frame_blobs, anchors)

    if args.frames_dir:
        frames_dir = Path(args.frames_dir)
        frames_dir.mkdir(parents=True, exist_ok=True)
        for f in range(N):
            bf = BODY_SEQ[f]
            crown_cols = R.interpolate_crown(crowns, f, out_frames=len(BODY_SEQ))
            surf = render_rgba_frame(
                clean[bf], heads[bf], crown_cols,
                frame_blobs[f], colours[f], pixels[f],
                anchors[f], anchors[bf],
            )
            surf.write_to_png(str(frames_dir / f"frame_{f:03d}.png"))
        print(f"Rendered {N} transparent RGBA frames @ {R.FPS} fps -> {args.frames_dir}")

    if not out_gif:
        return

    work = tempfile.mkdtemp(prefix="atom_idle_")
    try:
        for f in range(N):
            bf = BODY_SEQ[f]
            rgb = bytearray(clean[bf])
            R.paint_crown_on_frame(rgb, heads[bf], R.interpolate_crown(crowns, f, out_frames=len(BODY_SEQ)))

            # base.gif frame f's electrons, moved with the head onto body frame bf
            # whole-pixel offset: per-pixel rounding of a .5 offset would leave gaps
            dx = round(anchors[bf][0] - anchors[f][0])
            dy = round(anchors[bf][1] - anchors[f][1])
            for (pts, (cx, cy)), ci in zip(sorted(frame_blobs[f], key=lambda b: -len(b[0])), colours[f]):
                colour = PALETTE[ci]
                core = tuple(c + (255 - c) * CORE_WHITE for c in colour)

                # 1. Glow, like gemini.gif's electrons: a soft halo in the
                #    electron's colour, screen-blended so it lights up whatever
                #    is behind (on black it becomes alpha in the sprite).
                radius = math.sqrt(len(pts) / math.pi)
                reach = radius + GLOW_PX
                for ty in range(math.floor(cy - reach), math.ceil(cy + reach) + 1):
                    for tx in range(math.floor(cx - reach), math.ceil(cx + reach) + 1):
                        d = math.hypot(tx - cx, ty - cy) - radius
                        if d <= 0 or d >= GLOW_PX:
                            continue
                        g = GLOW_STRENGTH * (1 - d / GLOW_PX) ** 2
                        ox, oy = tx + dx, ty + dy
                        if not (0 <= ox < W and 0 <= oy < TOP_Y):
                            continue
                        j = (oy * W + ox) * 3
                        for k, c in enumerate(colour):
                            rgb[j + k] = round(255 - (255 - rgb[j + k]) * (1 - g * c / 255))

                # 2. The electron itself, base's exact pixels: a near-white hot
                #    core, its colour towards the soft edge.
                for x, y in pts:
                    tx, ty = x + dx, y + dy
                    if not (0 <= tx < W and 0 <= ty < TOP_Y):
                        continue
                    a = pixels[f][(x, y)]
                    paint = core if a >= 1.0 else colour
                    a = min(1.0, a * EDGE_BOOST)
                    j = (ty * W + tx) * 3
                    for k, c in enumerate(paint):
                        rgb[j + k] = round(rgb[j + k] * (1 - a) + c * a)

            R.rgb24_to_cairo_bgra(rgb).write_to_png(f"{work}/frame_{f:03d}.png")
        R.encode_gif(work, out_gif)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"Rendered {N} frames @ {R.FPS} fps -> {out_gif}")


if __name__ == "__main__":
    main()

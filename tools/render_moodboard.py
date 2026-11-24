#!/usr/bin/env python3
"""Render an animated 16:9 Atom showcase mood board (GIF + animated WebP).

Usage:
  python3 tools/render_moodboard.py
  python3 tools/render_moodboard.py --proof /tmp/atom_moodboard_proof.png
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import tempfile
from pathlib import Path

import cairo

ROOT = Path(__file__).resolve().parent.parent
ASSETS_ATOM = ROOT / "assets" / "atom"
OUT_GIF = ROOT / "assets" / "moodboard.gif"
OUT_WEBP = ROOT / "assets" / "moodboard.webp"

W, H = 1080, 608
N_FRAMES = 60
FPS = 10

RAINBOW = (
    (0.616, 0.420, 1.000),  # purple
    (0.345, 0.651, 1.000),  # blue
    (0.224, 0.827, 0.325),  # green
    (0.949, 0.800, 0.376),  # yellow
    (1.000, 0.482, 0.447),  # coral
    (1.000, 0.431, 0.706),  # pink
)

CARDS = (
    ("thinking",  "THINKING",  "Tucked legs · shimmer", (0.345, 0.651, 1.000), "BASE"),
    ("typing",    "TYPING",    "Laptop · loading wave", (0.220, 0.780, 0.960), "BASE"),
    ("running",   "RUNNING",   "Terminal commands",     (0.247, 0.851, 0.498), "BASE"),
    ("exploring", "EXPLORING", "Reading & search",      (0.200, 0.820, 0.880), "BASE"),
    ("dance",     "DANCE",     "Click to groove",       (0.953, 0.451, 0.780), "CLICK"),
    ("angry",     "ANGRY",     "Red mood · \\ / eyes",  (0.973, 0.318, 0.286), "MOOD"),
)


def rounded_rect(ctx: cairo.Context, x: float, y: float, w: float, h: float, r: float) -> None:
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r, r, -0.5 * math.pi, 0.0)
    ctx.arc(x + w - r, y + h - r, r, 0.0, 0.5 * math.pi)
    ctx.arc(x + r, y + h - r, r, 0.5 * math.pi, math.pi)
    ctx.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    ctx.close_path()


def draw_text(
    ctx: cairo.Context, text: str, x: float, y: float, size: float,
    color: tuple[float, float, float], alpha: float = 1.0, bold: bool = False,
    align: str = "left",
) -> None:
    ctx.save()
    ctx.select_font_face(
        "sans-serif",
        cairo.FONT_SLANT_NORMAL,
        cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL,
    )
    ctx.set_font_size(size)
    ext = ctx.text_extents(text)
    tx = x
    if align == "center":
        tx = x - (ext.x_bearing + ext.width * 0.5)
    elif align == "right":
        tx = x - (ext.x_bearing + ext.width)
    ctx.set_source_rgba(*color, alpha)
    ctx.move_to(tx, y)
    ctx.show_text(text)
    ctx.restore()


def load_sprite(state: str, tmp_dir: Path) -> tuple[cairo.ImageSurface, dict]:
    meta = json.loads((ASSETS_ATOM / f"{state}.json").read_text())
    png_path = tmp_dir / f"{state}.png"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(ASSETS_ATOM / f"{state}.webp"), str(png_path)],
        check=True,
    )
    surf = cairo.ImageSurface.create_from_png(str(png_path))
    return surf, meta


def paint_sprite_frame(
    ctx: cairo.Context, surf: cairo.ImageSurface, meta: dict, frame_idx: int,
    dx: float, dy: float, scale: float = 1.0,
) -> None:
    fw, fh, cols = meta["w"], meta["h"], meta["cols"]
    fx = (frame_idx % cols) * fw
    fy = (frame_idx // cols) * fh
    ctx.save()
    ctx.translate(dx, dy)
    ctx.scale(scale, scale)
    ctx.rectangle(0, 0, fw, fh)
    ctx.clip()
    ctx.set_source_surface(surf, -fx, -fy)
    ctx.get_source().set_filter(cairo.FILTER_NEAREST)
    ctx.paint()
    ctx.restore()


def render_frame(f: int, sprites: dict[str, tuple[cairo.ImageSurface, dict]]) -> cairo.ImageSurface:
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surf)

    # Background + subtle top-left radial glow behind hero
    ctx.set_source_rgb(0.051, 0.067, 0.090)
    ctx.paint()
    bg_pat = cairo.RadialGradient(216, 260, 20, 216, 260, 320)
    bg_pat.add_color_stop_rgba(0.0, 0.14, 0.30, 0.56, 0.22)
    bg_pat.add_color_stop_rgba(1.0, 0.051, 0.067, 0.090, 0.0)
    ctx.set_source(bg_pat)
    ctx.paint()

    # Header bar
    draw_text(ctx, "ATOM", 32, 46, 26, (0.941, 0.965, 0.988), bold=True)
    # Rainbow Gemini accent strip next to title
    bar_x, bar_y, seg_w = 122, 32, 11
    for i, col in enumerate(RAINBOW):
        ctx.set_source_rgb(*col)
        ctx.rectangle(bar_x + i * seg_w, bar_y, seg_w - 1, 6)
        ctx.fill()
    draw_text(
        ctx,
        "Pixel mascot on Antigravity's prompt bar  ·  19 animated states  ·  sustained moods",
        32, 69, 13.5, (0.545, 0.580, 0.620),
    )
    rounded_rect(ctx, 902, 26, 146, 28, 14)
    ctx.set_source_rgba(0.188, 0.212, 0.239, 0.8)
    ctx.fill_preserve()
    ctx.set_source_rgba(0.345, 0.651, 1.000, 0.45)
    ctx.set_line_width(1.0)
    ctx.stroke()
    draw_text(ctx, "OPEN SOURCE · MIT", 975, 44, 11, (0.76, 0.86, 0.98), bold=True, align="center")

    # Left Hero Card (IDLE main spotlight)
    hx, hy, hw, hh = 32, 92, 368, 484
    rounded_rect(ctx, hx, hy, hw, hh, 14)
    ctx.set_source_rgb(0.086, 0.106, 0.133)
    ctx.fill_preserve()
    hero_glow = cairo.RadialGradient(hx + hw / 2, hy + 185, 16, hx + hw / 2, hy + 185, 180)
    hero_glow.add_color_stop_rgba(0.0, 0.16, 0.36, 0.68, 0.34)
    hero_glow.add_color_stop_rgba(1.0, 0.086, 0.106, 0.133, 0.0)
    ctx.set_source(hero_glow)
    ctx.fill_preserve()
    ctx.set_source_rgba(0.345, 0.651, 1.000, 0.50)
    ctx.set_line_width(1.5)
    ctx.stroke()

    # Hero badge
    rounded_rect(ctx, hx + 18, hy + 16, 98, 22, 11)
    ctx.set_source_rgba(0.122, 0.435, 0.922, 0.22)
    ctx.fill_preserve()
    ctx.set_source_rgba(0.345, 0.651, 1.000, 0.55)
    ctx.set_line_width(1.0)
    ctx.stroke()
    draw_text(ctx, "MAIN · IDLE", hx + 67, hy + 31, 10.5, (0.58, 0.80, 1.0), bold=True, align="center")

    # Mock prompt bar below Atom's feet (idle feet sit around frame y=106 -> 2x y=212 below sprite top)
    idle_surf, idle_meta = sprites["idle"]
    idle_f = f % len(idle_meta["durations"])
    sp_x = hx + (hw - 300) / 2  # 66
    sp_y = hy + 48               # 140 -> feet land at y = 140 + 212 = 352
    bar_bx, bar_by, bar_bw, bar_bh = hx + 20, 351, hw - 40, 56
    rounded_rect(ctx, bar_bx, bar_by, bar_bw, bar_bh, 12)
    ctx.set_source_rgb(0.051, 0.067, 0.090)
    ctx.fill_preserve()
    ctx.set_source_rgba(0.345, 0.651, 1.000, 0.45)
    ctx.set_line_width(1.2)
    ctx.stroke()
    draw_text(ctx, "Ask Antigravity anything...", bar_bx + 16, bar_by + 32, 12.5, (0.48, 0.52, 0.57))
    rounded_rect(ctx, bar_bx + bar_bw - 42, bar_by + 15, 28, 26, 8)
    ctx.set_source_rgba(0.122, 0.435, 0.922, 0.85)
    ctx.fill()
    draw_text(ctx, "→", bar_bx + bar_bw - 28, bar_by + 33, 14, (1.0, 1.0, 1.0), bold=True, align="center")

    # Paint Atom standing cleanly on the mock prompt bar
    paint_sprite_frame(ctx, idle_surf, idle_meta, idle_f, sp_x, sp_y, scale=2.0)

    # Hero description & feature chips
    draw_text(ctx, "Lives on the prompt bar", hx + hw / 2, 437, 16, (0.941, 0.965, 0.988), bold=True, align="center")
    draw_text(ctx, "Zero DOM clutter · smooth 60fps crossfades", hx + hw / 2, 458, 12, (0.545, 0.580, 0.620), align="center")

    chips = ("19 states", "Angry & Sad moods", "Click to dance", "Linux · macOS · Win")
    chip_w, chip_h = 156, 28
    for idx, label in enumerate(chips):
        cx = hx + 22 + (idx % 2) * (chip_w + 12)
        cy = 482 + (idx // 2) * (chip_h + 10)
        rounded_rect(ctx, cx, cy, chip_w, chip_h, 8)
        ctx.set_source_rgb(0.118, 0.145, 0.184)
        ctx.fill_preserve()
        ctx.set_source_rgba(0.30, 0.35, 0.42, 0.55)
        ctx.set_line_width(1.0)
        ctx.stroke()
        draw_text(ctx, label, cx + chip_w / 2, cy + 18, 11.5, (0.82, 0.87, 0.93), align="center")

    # Right 3x2 State Grid
    gx0, gy0 = 416, 92
    cw, ch = 200, 234
    gap = 16
    for idx, (state, title, subtitle, accent, tag) in enumerate(CARDS):
        col_i = idx % 3
        row_i = idx // 3
        x = gx0 + col_i * (cw + gap)
        y = gy0 + row_i * (ch + gap)

        rounded_rect(ctx, x, y, cw, ch, 12)
        ctx.set_source_rgb(0.086, 0.106, 0.133)
        ctx.fill_preserve()
        # Subtle card backdrop glow
        glow = cairo.RadialGradient(x + cw / 2, y + 84, 8, x + cw / 2, y + 84, 86)
        glow.add_color_stop_rgba(0.0, *accent, 0.18)
        glow.add_color_stop_rgba(1.0, 0.086, 0.106, 0.133, 0.0)
        ctx.set_source(glow)
        ctx.fill_preserve()
        ctx.set_source_rgba(*accent, 0.38)
        ctx.set_line_width(1.2)
        ctx.stroke()

        # Top-right tag pill
        rounded_rect(ctx, x + cw - 62, y + 10, 50, 18, 9)
        ctx.set_source_rgba(*accent, 0.16)
        ctx.fill()
        draw_text(ctx, tag, x + cw - 37, y + 22.5, 9.5, accent, bold=True, align="center")

        # Sprite at 1:1 native resolution inside loop
        sp_surf, sp_meta = sprites[state]
        lo, hi = sp_meta.get("loop", [0, len(sp_meta["durations"]) - 1])
        loop_len = max(1, hi - lo + 1)
        fi = lo + (f % loop_len)
        paint_sprite_frame(ctx, sp_surf, sp_meta, fi, x + (cw - sp_meta["w"]) / 2, y + 28, scale=1.0)

        # Title dot + label + subtitle
        ctx.set_source_rgb(*accent)
        ctx.arc(x + 22, y + 178, 4.0, 0, 2 * math.pi)
        ctx.fill()
        draw_text(ctx, title, x + 33, y + 183, 13.5, (0.941, 0.965, 0.988), bold=True)
        draw_text(ctx, subtitle, x + 22, y + 204, 11.5, (0.545, 0.580, 0.620))

    return surf


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proof", default="", help="Optional PNG frame proof path (frame 18)")
    args = ap.parse_args()

    OUT_GIF.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="atom_moodboard_") as tmp:
        tmp_dir = Path(tmp)
        frames_dir = tmp_dir / "frames"
        frames_dir.mkdir()
        sprites = {st: load_sprite(st, tmp_dir) for st in ("idle", *(c[0] for c in CARDS))}

        for f in range(N_FRAMES):
            surf = render_frame(f, sprites)
            out_png = frames_dir / f"frame_{f:03d}.png"
            surf.write_to_png(str(out_png))
            if args.proof and f == 18:
                Path(args.proof).write_bytes(out_png.read_bytes())

        pattern = str(frames_dir / "frame_%03d.png")
        palette = str(tmp_dir / "palette.png")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", pattern, "-vf", "palettegen=stats_mode=diff", palette],
            check=True,
        )
        subprocess.run(
            [
                "ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", pattern, "-i", palette,
                "-lavfi", "paletteuse=dither=bayer:bayer_scale=3", "-loop", "0", str(OUT_GIF),
            ],
            check=True,
        )
        subprocess.run(
            [
                "ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", pattern,
                "-c:v", "libwebp", "-lossless", "0", "-q:v", "90", "-loop", "0", str(OUT_WEBP),
            ],
            check=True,
        )

    print(f"{OUT_GIF.relative_to(ROOT)}: {OUT_GIF.stat().st_size // 1024} KB")
    print(f"{OUT_WEBP.relative_to(ROOT)}: {OUT_WEBP.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()

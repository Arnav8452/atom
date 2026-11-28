#!/usr/bin/env python3
"""Render a clean, social-marketing 16:9 Atom showcase mood board (GIF + animated WebP).

Usage:
  python3 tools/render_moodboard.py
  python3 tools/render_moodboard.py --proof /tmp/atom_moodboard_proof.png
  python3 tools/render_moodboard.py --typing-gif --typing-proof /tmp/atom_typing_proof.png
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
OUT_TYPING_GIF = ROOT / "assets" / "typing_showcase.gif"

W, H = 1080, 608
TYPING_W, TYPING_H = 560, 380
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
    ("typing",   "TYPING",   (0.220, 0.780, 0.960)),
    ("angry",    "ANGRY",    (0.973, 0.318, 0.286)),
    ("sad",      "SAD",      (0.431, 0.584, 0.780)),
    ("dance",    "DANCE",    (0.953, 0.451, 0.780)),
    ("thinking", "THINKING", (0.345, 0.651, 1.000)),
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


def draw_dot_label(
    ctx: cairo.Context, label: str, cx: float, y: float, size: float,
    accent: tuple[float, float, float], text_color: tuple[float, float, float],
) -> None:
    ctx.save()
    ctx.select_font_face("sans-serif", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(size)
    ext = ctx.text_extents(label)
    dot_r = 4.0
    gap = 9.0
    total_w = dot_r * 2 + gap + ext.width
    x0 = cx - total_w * 0.5
    ctx.set_source_rgb(*accent)
    ctx.arc(x0 + dot_r, y - size * 0.34, dot_r, 0, 2 * math.pi)
    ctx.fill()
    ctx.set_source_rgb(*text_color)
    ctx.move_to(x0 + dot_r * 2 + gap - ext.x_bearing, y)
    ctx.show_text(label)
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
    dx: float, dy: float, scale: float = 1.0, alpha: float = 1.0,
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
    if alpha >= 0.999:
        ctx.paint()
    elif alpha > 0.001:
        ctx.paint_with_alpha(alpha)
    ctx.restore()


def build_complete_sequence(state: str, meta: dict) -> list[int]:
    """Return output-tick frame indices playing the complete intro -> loop -> outro sequence."""
    n = len(meta["durations"])
    if state == "dance":
        lo, hi = meta.get("loop", [5, 34])
        src_seq = list(range(0, lo)) + list(range(lo, hi + 1)) * 2 + list(range(hi + 1, n))
        tick_seq: list[int] = []
        f = 0
        while True:
            src_idx = int(f * 100 / 65)
            if src_idx >= len(src_seq):
                break
            tick_seq.append(src_seq[src_idx])
            f += 1
        return tick_seq
    return list(range(n))


def paint_complete_animation(
    ctx: cairo.Context, state: str, f: int,
    sprites: dict[str, tuple[cairo.ImageSurface, dict]],
    seqs: dict[str, list[int]],
    dx: float, dy: float, scale: float = 1.0,
) -> None:
    sp_surf, sp_meta = sprites[state]
    idle_surf, idle_meta = sprites["idle"]
    idle_fi = f % len(idle_meta["durations"])
    seq = seqs[state]
    n_act = len(seq)

    if f < n_act:
        paint_sprite_frame(ctx, sp_surf, sp_meta, seq[f], dx, dy, scale=scale, alpha=1.0)
    elif f == n_act:
        paint_sprite_frame(ctx, sp_surf, sp_meta, seq[-1], dx, dy, scale=scale, alpha=0.67)
        paint_sprite_frame(ctx, idle_surf, idle_meta, idle_fi, dx, dy, scale=scale, alpha=0.33)
    elif f == n_act + 1:
        paint_sprite_frame(ctx, sp_surf, sp_meta, seq[-1], dx, dy, scale=scale, alpha=0.33)
        paint_sprite_frame(ctx, idle_surf, idle_meta, idle_fi, dx, dy, scale=scale, alpha=0.67)
    elif f == N_FRAMES - 2:
        paint_sprite_frame(ctx, idle_surf, idle_meta, idle_fi, dx, dy, scale=scale, alpha=0.67)
        paint_sprite_frame(ctx, sp_surf, sp_meta, seq[0], dx, dy, scale=scale, alpha=0.33)
    elif f == N_FRAMES - 1:
        paint_sprite_frame(ctx, idle_surf, idle_meta, idle_fi, dx, dy, scale=scale, alpha=0.33)
        paint_sprite_frame(ctx, sp_surf, sp_meta, seq[0], dx, dy, scale=scale, alpha=0.67)
    else:
        paint_sprite_frame(ctx, idle_surf, idle_meta, idle_fi, dx, dy, scale=scale, alpha=1.0)


def draw_prompt_bar(
    ctx: cairo.Context, x: float, y: float, w: float, h: float, f: int, radius: float = 12.0,
) -> None:
    rounded_rect(ctx, x, y, w, h, radius)
    ctx.set_source_rgb(0.051, 0.067, 0.090)
    ctx.fill_preserve()
    ctx.set_source_rgba(0.345, 0.651, 1.000, 0.52)
    ctx.set_line_width(1.2)
    ctx.stroke()
    if (f % 10) < 6:
        ctx.set_source_rgba(0.58, 0.80, 1.0, 0.78)
        ctx.rectangle(x + 18, y + (h - 22) * 0.5, 2.5, 22)
        ctx.fill()
    btn_h = max(24.0, h - 28.0)
    btn_w = max(28.0, btn_h + 2.0)
    btn_x = x + w - btn_w - 14.0
    btn_y = y + (h - btn_h) * 0.5
    rounded_rect(ctx, btn_x, btn_y, btn_w, btn_h, 8)
    ctx.set_source_rgba(0.122, 0.435, 0.922, 0.88)
    ctx.fill()
    draw_text(ctx, "→", btn_x + btn_w * 0.5, btn_y + btn_h * 0.68, 14, (1.0, 1.0, 1.0), bold=True, align="center")


def render_frame(
    f: int,
    sprites: dict[str, tuple[cairo.ImageSurface, dict]],
    seqs: dict[str, list[int]],
) -> cairo.ImageSurface:
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surf)

    # Background + subtle top-left radial glow behind hero
    ctx.set_source_rgb(0.051, 0.067, 0.090)
    ctx.paint()
    bg_pat = cairo.RadialGradient(218, 270, 20, 218, 270, 340)
    bg_pat.add_color_stop_rgba(0.0, 0.14, 0.30, 0.56, 0.22)
    bg_pat.add_color_stop_rgba(1.0, 0.051, 0.067, 0.090, 0.0)
    ctx.set_source(bg_pat)
    ctx.paint()

    # Clean minimal header (y = 0..86)
    draw_text(ctx, "Atom", 36, 44, 30, (0.941, 0.965, 0.988), bold=True)
    bar_x, bar_y, seg_w = 126, 29, 11
    for i, col in enumerate(RAINBOW):
        ctx.set_source_rgb(*col)
        ctx.rectangle(bar_x + i * seg_w, bar_y, seg_w - 1, 6)
        ctx.fill()
    draw_text(ctx, "Version 1, 19 states", 36, 70, 15, (0.545, 0.580, 0.620))

    # Left Hero Card (IDLE full loop at 2.2x)
    hx, hy, hw, hh = 36, 92, 364, 484
    rounded_rect(ctx, hx, hy, hw, hh, 14)
    ctx.set_source_rgb(0.086, 0.106, 0.133)
    ctx.fill_preserve()
    hero_glow = cairo.RadialGradient(hx + hw / 2, hy + 210, 18, hx + hw / 2, hy + 210, 190)
    hero_glow.add_color_stop_rgba(0.0, 0.16, 0.36, 0.68, 0.34)
    hero_glow.add_color_stop_rgba(1.0, 0.086, 0.106, 0.133, 0.0)
    ctx.set_source(hero_glow)
    ctx.fill_preserve()
    ctx.set_source_rgba(0.345, 0.651, 1.000, 0.50)
    ctx.set_line_width(1.5)
    ctx.stroke()

    # Minimalist prompt-bar silhouette beneath Hero Atom's feet (no placeholder text)
    draw_prompt_bar(ctx, hx + 24, 398, hw - 48, 54, f)

    idle_surf, idle_meta = sprites["idle"]
    idle_f = f % len(idle_meta["durations"])
    scale = 2.2
    sp_x = hx + (hw - idle_meta["w"] * scale) / 2
    sp_y = 166.0
    paint_sprite_frame(ctx, idle_surf, idle_meta, idle_f, sp_x, sp_y, scale=scale)

    draw_dot_label(
        ctx,
        "IDLE",
        hx + hw / 2,
        508,
        15,
        (0.345, 0.651, 1.000),
        (0.941, 0.965, 0.988),
    )

    # Right 3x2 State Grid
    gx0, gy0 = 416, 92
    cw, ch = 198, 234
    gap = 16
    for idx, (state, title, accent) in enumerate(CARDS):
        col_i = idx % 3
        row_i = idx // 3
        x = gx0 + col_i * (cw + gap)
        y = gy0 + row_i * (ch + gap)

        rounded_rect(ctx, x, y, cw, ch, 12)
        ctx.set_source_rgb(0.086, 0.106, 0.133)
        ctx.fill_preserve()
        glow = cairo.RadialGradient(x + cw / 2, y + 92, 8, x + cw / 2, y + 92, 86)
        glow.add_color_stop_rgba(0.0, *accent, 0.18)
        glow.add_color_stop_rgba(1.0, 0.086, 0.106, 0.133, 0.0)
        ctx.set_source(glow)
        ctx.fill_preserve()
        ctx.set_source_rgba(*accent, 0.40)
        ctx.set_line_width(1.2)
        ctx.stroke()

        _, sp_meta = sprites[state]
        paint_complete_animation(
            ctx,
            state,
            f,
            sprites,
            seqs,
            x + (cw - sp_meta["w"]) / 2,
            y + 34,
        )

        draw_dot_label(
            ctx,
            title,
            x + cw / 2,
            y + 196,
            13.5,
            accent,
            (0.941, 0.965, 0.988),
        )

    # 6th Grid Tile (col=2, row=1): minimal CTA card
    tx = gx0 + 2 * (cw + gap)
    ty = gy0 + 1 * (ch + gap)
    rounded_rect(ctx, tx, ty, cw, ch, 12)
    ctx.set_source_rgb(0.071, 0.090, 0.122)
    ctx.fill_preserve()
    ctx.set_source_rgba(0.30, 0.35, 0.42, 0.45)
    ctx.set_line_width(1.2)
    ctx.stroke()

    strip_x = tx + (cw - 66) / 2
    strip_y = ty + 74
    for i, col in enumerate(RAINBOW):
        ctx.set_source_rgb(*col)
        ctx.rectangle(strip_x + i * 11, strip_y, 10, 5)
        ctx.fill()

    cta_color = (0.86, 0.91, 0.96)
    draw_text(ctx, "Use to explore", tx + cw / 2, ty + 114, 15.5, cta_color, align="center")
    draw_text(ctx, "more states", tx + cw / 2, ty + 138, 15.5, cta_color, align="center")
    draw_text(ctx, "and behaviours", tx + cw / 2, ty + 162, 15.5, cta_color, align="center")

    return surf


def render_typing_frame(
    f: int,
    sprites: dict[str, tuple[cairo.ImageSurface, dict]],
    seqs: dict[str, list[int]],
) -> cairo.ImageSurface:
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, TYPING_W, TYPING_H)
    ctx = cairo.Context(surf)
    ctx.set_source_rgb(0.051, 0.067, 0.090)
    ctx.paint()

    glow = cairo.RadialGradient(362.0, 156.0, 16, 362.0, 156.0, 175)
    glow.add_color_stop_rgba(0.0, 0.14, 0.34, 0.62, 0.30)
    glow.add_color_stop_rgba(1.0, 0.051, 0.067, 0.090, 0.0)
    ctx.set_source(glow)
    ctx.paint()

    # Right-side snap of the full-scale Antigravity prompt bar extending off the left edge
    bar_x, bar_y, bar_w, bar_h = -40.0, 224.0, 556.0, 132.0
    rounded_rect(ctx, bar_x, bar_y, bar_w, bar_h, 22.0)
    ctx.set_source_rgb(0.086, 0.106, 0.133)
    ctx.fill_preserve()
    ctx.set_source_rgba(0.345, 0.651, 1.000, 0.42)
    ctx.set_line_width(1.5)
    ctx.stroke()

    # Subtle muted circular icon silhouette left of send button for prompt-bar scale cue
    ctx.set_source_rgba(0.30, 0.36, 0.44, 0.28)
    ctx.arc(424.0, 316.0, 14.0, 0, 2 * math.pi)
    ctx.fill()

    # Crisp blue send button bottom-right (44x44)
    rounded_rect(ctx, 452.0, 294.0, 44.0, 44.0, 12.0)
    ctx.set_source_rgba(0.122, 0.435, 0.922, 0.92)
    ctx.fill()
    draw_text(ctx, "→", 474.0, 323.0, 19.0, (1.0, 1.0, 1.0), bold=True, align="center")

    paint_complete_animation(ctx, "typing", f, sprites, seqs, dx=212.0, dy=12.0, scale=2.0)
    return surf


def _encode_sequence(
    frames_dir: Path, tmp_dir: Path, name: str, out_gif: Path, out_webp: Path | None = None,
) -> None:
    pattern = str(frames_dir / "frame_%03d.png")
    palette = str(tmp_dir / f"{name}_palette.png")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", pattern, "-vf", "palettegen=stats_mode=diff", palette],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", pattern, "-i", palette,
            "-lavfi", "paletteuse=dither=bayer:bayer_scale=3", "-loop", "0", str(out_gif),
        ],
        check=True,
    )
    print(f"{out_gif.relative_to(ROOT)}: {out_gif.stat().st_size // 1024} KB")
    if out_webp is not None:
        subprocess.run(
            [
                "ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", pattern,
                "-c:v", "libwebp", "-lossless", "0", "-q:v", "90", "-loop", "0", str(out_webp),
            ],
            check=True,
        )
        print(f"{out_webp.relative_to(ROOT)}: {out_webp.stat().st_size // 1024} KB")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proof", default="", help="Optional moodboard PNG frame proof path (frame 18)")
    ap.add_argument("--typing-gif", action="store_true", help="Render standalone zoomed typing showcase GIF")
    ap.add_argument("--typing-proof", default="", help="Optional typing showcase PNG frame proof path (frame 18)")
    args = ap.parse_args()

    OUT_GIF.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="atom_moodboard_") as tmp:
        tmp_dir = Path(tmp)
        sprites = {st: load_sprite(st, tmp_dir) for st in ("idle", *(c[0] for c in CARDS))}
        seqs = {c[0]: build_complete_sequence(c[0], sprites[c[0]][1]) for c in CARDS}

        if not args.typing_gif or args.proof:
            frames_dir = tmp_dir / "moodboard_frames"
            frames_dir.mkdir()
            for f in range(N_FRAMES):
                surf = render_frame(f, sprites, seqs)
                out_png = frames_dir / f"frame_{f:03d}.png"
                surf.write_to_png(str(out_png))
                if args.proof and f == 18:
                    Path(args.proof).write_bytes(out_png.read_bytes())
            _encode_sequence(frames_dir, tmp_dir, "moodboard", OUT_GIF, OUT_WEBP)

        if args.typing_gif or args.typing_proof:
            t_dir = tmp_dir / "typing_frames"
            t_dir.mkdir()
            for f in range(N_FRAMES):
                surf = render_typing_frame(f, sprites, seqs)
                out_png = t_dir / f"frame_{f:03d}.png"
                surf.write_to_png(str(out_png))
                if args.typing_proof and f == 18:
                    Path(args.typing_proof).write_bytes(out_png.read_bytes())
            _encode_sequence(t_dir, tmp_dir, "typing", OUT_TYPING_GIF)


if __name__ == "__main__":
    main()

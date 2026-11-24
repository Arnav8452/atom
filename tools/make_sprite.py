#!/usr/bin/env python3
"""Turn a 640x360 black-background mascot render into a transparent sprite sheet.

The renders (base.gif, gemini.gif, gemini_typing.gif, ...) are full mock-up
scenes: black background, mascot, and a fake prompt bar underneath. Atom needs
just the mascot with real alpha, so this:

  1. crops a fixed 300x240 box whose bottom-centre sits under the mascot's
     feet (every state shares it, so Atom doesn't jump when it switches);
  2. flood-fills "background" inwards from the crop border through dark
     pixels and converts those to alpha (colour-to-alpha from black), so
     glows and trails fade out instead of leaving a black halo, while dark
     pixels enclosed by the body (eyes) stay opaque;
  3. scales each frame once to FRAME_W x FRAME_H and lays them out in a grid,
     written as assets/<skin>/<state>.webp (lossless) + <state>.json timings.
     The page draws frames itself so it can finish a loop before switching.

Usage:
  uv run --with pillow tools/make_sprite.py SRC.gif SKIN STATE --center-x 417
See tools/build_assets.sh for the current assets.
"""

from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path

from PIL import Image, ImageSequence

ASSETS = Path(__file__).resolve().parent.parent / "assets"
FRAME_W, FRAME_H = 200, 160   # one downscale only; the page draws at <= this size
COLS = 10

CROP_W, CROP_H = 300, 240
FEET_Y = 222          # y of the mascot's feet in the 640x360 renders
FEET_MARGIN = 18      # transparent space kept below the feet
DARK = 96             # max(r,g,b) below this is background or glow falloff
FLOOR = 24            # max(r,g,b) at or below this is render noise/haze -> fully clear


def key_frame(frame: Image.Image, floor: int) -> Image.Image:
    rgb = frame.convert("RGB")
    w, h = rgb.size
    px = rgb.load()
    out = Image.new("RGBA", (w, h))
    opx = out.load()

    # Flood from the border through dark pixels: that region is background.
    bg = bytearray(w * h)
    q: deque[tuple[int, int]] = deque()
    for x in range(w):
        q.append((x, 0))
        q.append((x, h - 1))
    for y in range(h):
        q.append((0, y))
        q.append((w - 1, y))
    while q:
        x, y = q.popleft()
        i = y * w + x
        if bg[i] or max(px[x, y]) >= DARK:
            continue
        bg[i] = 1
        if x > 0:
            q.append((x - 1, y))
        if x < w - 1:
            q.append((x + 1, y))
        if y > 0:
            q.append((x, y - 1))
        if y < h - 1:
            q.append((x, y + 1))

    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            if not bg[y * w + x]:
                opx[x, y] = (r, g, b, 255)
                continue
            m = max(r, g, b)
            if m <= floor:
                opx[x, y] = (0, 0, 0, 0)
                continue
            a = (m - floor) * 255 // (DARK - floor)
            # Un-premultiply against black so the glow keeps its hue.
            k = 255 / a
            opx[x, y] = (min(255, int(r * k)), min(255, int(g * k)), min(255, int(b * k)), a)
    return out


def has_alpha(frame: Image.Image) -> bool:
    if frame.mode not in ("RGBA", "LA", "PA"):
        return False
    lo, _ = frame.getchannel("A").getextrema()
    return lo < 255


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", help="Source GIF path or directory of sorted RGBA PNG frames")
    ap.add_argument("skin", help="skin name, e.g. gemini or base")
    ap.add_argument("state", help="idle, typing, thinking, sad, angry, happy or closed")
    ap.add_argument("--center-x", type=int, required=True, help="x of the mascot body's centre in the render")
    ap.add_argument("--feet-y", type=int, default=FEET_Y)
    ap.add_argument("--floor", type=int, default=FLOOR,
                    help="background noise level to clear (raise it if a haze shows around the sprite)")
    ap.add_argument("--duration-ms", type=int, default=100, help="Frame duration in ms when src is a PNG directory")
    ap.add_argument("--fps", type=float, default=0.0, help="Optional FPS override when src is a PNG directory")
    args = ap.parse_args()

    if args.floor >= DARK:
        ap.error(f"--floor must be < {DARK}")

    left = args.center_x - CROP_W // 2
    bottom = args.feet_y + FEET_MARGIN
    box = (left, bottom - CROP_H, left + CROP_W, bottom)

    src_path = Path(args.src)
    frames, durations = [], []
    if src_path.is_dir():
        pngs = sorted(src_path.glob("*.png"))
        if not pngs:
            ap.error(f"No PNG frames found in {src_path}")
        dur = round(1000.0 / args.fps) if args.fps > 0 else args.duration_ms
        for p in pngs:
            with Image.open(p) as im:
                cropped = im.crop(box)
                keyed = cropped.convert("RGBA") if has_alpha(im) else key_frame(cropped, args.floor)
                frames.append(keyed.resize((FRAME_W, FRAME_H), Image.LANCZOS))
                durations.append(dur)
    else:
        src = Image.open(src_path)
        for frame in ImageSequence.Iterator(src):
            cropped = frame.crop(box)
            keyed = cropped.convert("RGBA") if has_alpha(frame) else key_frame(cropped, args.floor)
            frames.append(keyed.resize((FRAME_W, FRAME_H), Image.LANCZOS))
            durations.append(frame.info.get("duration", 100) or 100)

    cols = min(COLS, len(frames))
    rows = -(-len(frames) // cols)
    sheet = Image.new("RGBA", (FRAME_W * cols, FRAME_H * rows))
    for i, f in enumerate(frames):
        sheet.paste(f, ((i % cols) * FRAME_W, (i // cols) * FRAME_H))

    out = ASSETS / args.skin
    out.mkdir(parents=True, exist_ok=True)
    sheet.save(out / f"{args.state}.webp", lossless=True, method=6)
    meta = {"w": FRAME_W, "h": FRAME_H, "cols": cols, "durations": durations}
    (out / f"{args.state}.json").write_text(json.dumps(meta) + "\n")
    print(f"assets/{args.skin}/{args.state}.webp: {len(frames)} frames, {sum(durations)} ms, crop {box}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build the website gallery: one GIF per state for every skin, plus web-sized
copies of the artwork listed in site/gallery.json.

  python3 tools/render_gallery.py --out _site/gallery
  python3 tools/render_gallery.py --out /tmp/gallery --src ~/Work/Atom   # read assets/ and art/ from another checkout

Skins are the folders in assets/ that hold <state>.webp + <state>.json sprite
sheets (150x120 frames). A folder's skin.json gives its name, tagline, accent
and order; assets/atom has none and is the classic skin. Each GIF plays the
state's loop section on the site's panel colour, scaled 2x with crisp pixels.

Artwork entries whose file doesn't exist (e.g. not committed yet) are skipped.
Originals in art/ are only read, never changed.

Writes <out>/skins/<skin>/<state>.gif, <out>/art/<name>.(webp|gif) and
<out>/gallery.json. Needs Pillow (asset tooling only; Atom itself is stdlib-only).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover - tooling dependency
    sys.exit("render_gallery.py needs Pillow: python3 -m pip install Pillow")

ROOT = Path(__file__).resolve().parent.parent
REPO_URL = "https://github.com/Arnav8452/atom/blob/main/"
BG = (15, 22, 48)  # site --panel
SCALE = 2
ART_MAX = 900  # px, longest side of web copies
GIF_MAX_BYTES = 2_500_000  # animated art larger than this is skipped
# The classic skin has no skin.json.
DEFAULT_SKIN = {"name": "Atom", "tagline": "The classic box Atom with a rainbow crown", "accent": "#3aa2f6", "order": 0}


def skin_dirs(assets: Path) -> list[tuple[str, dict, Path]]:
    out = []
    for d in sorted(p for p in assets.iterdir() if p.is_dir()):
        states = sorted(f.stem for f in d.glob("*.webp") if (d / f"{f.stem}.json").is_file())
        if not states:
            continue
        meta = dict(DEFAULT_SKIN) if d.name == "atom" else {"name": d.name, "tagline": "", "accent": "#3aa2f6", "order": 50}
        try:
            meta.update(json.loads((d / "skin.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        out.append((d.name, meta, d))
    out.sort(key=lambda t: (t[1].get("order", 50), t[0]))
    return out


def state_gif(sheet: Path, meta: dict, dest: Path) -> None:
    w, h, cols = meta["w"], meta["h"], meta["cols"]
    durations = meta["durations"]
    first, last = meta.get("loop") or [0, len(durations) - 1]
    with Image.open(sheet) as im:
        im = im.convert("RGBA")
        frames, times = [], []
        for i in range(first, last + 1):
            x, y = (i % cols) * w, (i // cols) * h
            tile = im.crop((x, y, x + w, y + h))
            flat = Image.new("RGBA", (w, h), BG + (255,))
            flat.alpha_composite(tile)
            flat = flat.convert("RGB").resize((w * SCALE, h * SCALE), Image.NEAREST)
            frames.append(flat.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
            times.append(max(20, int(durations[i])))
    dest.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(dest, save_all=True, append_images=frames[1:], duration=times, loop=0, optimize=True, disposal=1)


def art_copy(src: Path, dest_dir: Path) -> tuple[str, int, int] | None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        animated = getattr(im, "is_animated", False)
        w, h = im.size
        if animated:
            if src.stat().st_size > GIF_MAX_BYTES:
                print(f"  skip {src.name}: animated and over {GIF_MAX_BYTES // 1_000_000} MB", file=sys.stderr)
                return None
            dest = dest_dir / f"{src.stem}.gif"
            shutil.copyfile(src, dest)
            return dest.name, w, h
        im = im.convert("RGB")
        im.thumbnail((ART_MAX, ART_MAX), Image.LANCZOS)
        dest = dest_dir / f"{src.stem}.webp"
        im.save(dest, "WEBP", quality=86, method=6)
        return dest.name, im.width, im.height


def build(src: Path, out: Path, manifest_path: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    data: dict = {"skins": [], "art": []}

    for skin_id, meta, d in skin_dirs(src / "assets"):
        states = []
        for f in sorted(d.glob("*.webp")):
            meta_file = d / f"{f.stem}.json"
            if not meta_file.is_file():
                continue
            state_gif(f, json.loads(meta_file.read_text(encoding="utf-8")), out / "skins" / skin_id / f"{f.stem}.gif")
            states.append(f.stem)
        data["skins"].append({
            "id": skin_id, "name": meta.get("name", skin_id), "tagline": meta.get("tagline", ""),
            "accent": meta.get("accent", "#3aa2f6"), "states": states,
        })
        print(f"{skin_id}: {len(states)} GIFs")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    for entry in manifest.get("art", []):
        rel = entry.get("file", "")
        path = (src / rel).resolve()
        if not rel or not path.is_relative_to((src / "art").resolve()) or not path.is_file():
            print(f"  skip {rel or '?'}: not found under art/", file=sys.stderr)
            continue
        copied = art_copy(path, out / "art")
        if not copied:
            continue
        name, w, h = copied
        data["art"].append({
            "src": f"art/{name}", "w": w, "h": h, "original": REPO_URL + rel,
            "title": entry.get("title", path.stem), "kind": "fan" if entry.get("kind") == "fan" else "ai",
            "by": entry.get("by", ""), "link": entry.get("link", ""),
        })
    print(f"art: {len(data['art'])} pieces")

    (out / "gallery.json").write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True, type=Path, help="output folder (e.g. _site/gallery)")
    ap.add_argument("--src", type=Path, default=ROOT, help="checkout to read assets/ and art/ from (default: this repo)")
    ap.add_argument("--manifest", type=Path, default=ROOT / "site" / "gallery.json", help="artwork list")
    args = ap.parse_args()
    build(args.src.expanduser().resolve(), args.out, args.manifest)


if __name__ == "__main__":
    main()

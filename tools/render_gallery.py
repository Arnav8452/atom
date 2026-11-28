#!/usr/bin/env python3
"""Build the website gallery: one GIF per state for every skin, plus web-sized
copies of the artwork listed in site/gallery.json.

  python3 tools/render_gallery.py --out _site/gallery
  python3 tools/render_gallery.py --out /tmp/gallery --src ~/Work/Atom   # read assets/ and art/ from another checkout

Skins are the folders in assets/ that hold <state>.webp + <state>.json sprite
sheets (150x120 frames). A folder's skin.json gives its name, tagline, accent
and order; assets/atom has none and is the classic skin. Each GIF plays the
state's loop section on the site's panel colour, scaled 2x with crisp pixels.

Artwork ("art"), manga pages ("manga") and memes ("memes") come from art/ (originals) or
site/art/ (web-sized copies of large pieces kept outside the repo). Entries
whose file doesn't exist (e.g. not committed yet) are skipped. Sources are only
read, never changed.

Writes <out>/skins/<skin>/<state>.gif, <out>/art/<name>.(webp|gif) (a
thumbnail plus a full-size copy) and <out>/gallery.json. Needs Pillow (asset tooling only; Atom itself is stdlib-only).
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
ART_ROOTS = ("art", "site/art")
BG = (15, 22, 48)  # site --panel
SCALE = 2
THUMB_MAX = 900  # px, longest side of gallery thumbnails
FULL_MAX = 1800  # px, longest side of the full-size view
GIF_MAX_BYTES = 2_500_000  # animated art larger than this is skipped
# The classic skin has no skin.json.
DEFAULT_SKIN = {"name": "Atom", "tagline": "The classic box Atom with a rainbow crown", "accent": "#3aa2f6", "order": 0}


def _has_sheets(d: Path) -> bool:
    return any((d / f"{f.stem}.json").is_file() for f in d.glob("*.webp"))


def skin_dirs(assets: Path) -> list[tuple[str, dict, Path]]:
    """Every skin, plus one entry per outfit for skins with variants/ (e.g. v2-wardrobe)."""
    out = []
    for d in sorted(p for p in assets.iterdir() if p.is_dir()):
        if not _has_sheets(d):
            continue
        meta = dict(DEFAULT_SKIN) if d.name == "atom" else {"name": d.name, "tagline": "", "accent": "#3aa2f6", "order": 50}
        try:
            meta.update(json.loads((d / "skin.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        variants = [v for v in meta.get("variants", []) if isinstance(v, str)]
        default = meta.get("defaultVariant")
        if not variants or not default:
            out.append((d.name, meta, d))
            continue
        for i, v in enumerate(variants):
            vdir = d if v == default else d / "variants" / v
            if not _has_sheets(vdir):
                continue
            vmeta = {**meta, "name": v.capitalize(), "order": meta.get("order", 50) + i / 100,
                     "tagline": f"{meta.get('name', d.name)}: {v.capitalize()}" + (f" · {meta['tagline']}" if meta.get("tagline") else "")}
            out.append((f"{d.name}-{v}", vmeta, vdir))
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


def art_copy(src: Path, dest_dir: Path, name: str) -> dict | None:
    """Thumbnail + full-size web copies of one piece, named after `name`."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        if getattr(im, "is_animated", False):
            if src.stat().st_size > GIF_MAX_BYTES:
                print(f"  skip {src.name}: animated and over {GIF_MAX_BYTES // 1_000_000} MB", file=sys.stderr)
                return None
            dest = dest_dir / f"{name}.gif"
            shutil.copyfile(src, dest)
            return {"src": dest.name, "full": dest.name, "w": im.width, "h": im.height}
        im = im.convert("RGB")
        full = im.copy()
        full.thumbnail((FULL_MAX, FULL_MAX), Image.LANCZOS)
        full.save(dest_dir / f"{name}.webp", "WEBP", quality=86, method=6)
        im.thumbnail((THUMB_MAX, THUMB_MAX), Image.LANCZOS)
        im.save(dest_dir / f"{name}.thumb.webp", "WEBP", quality=84, method=6)
        return {"src": f"{name}.thumb.webp", "full": f"{name}.webp", "w": im.width, "h": im.height}


def _source(src: Path, rel: str) -> Path | None:
    if not rel:
        return None
    path = (src / rel).resolve()
    if not any(path.is_relative_to((src / root).resolve()) for root in ART_ROOTS) or not path.is_file():
        return None
    return path


def build(src: Path, out: Path, manifest_path: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    data: dict = {"skins": [], "art": [], "manga": [], "memes": []}

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
    for section in ("art", "manga", "memes"):
        for i, entry in enumerate(manifest.get(section, [])):
            rel = entry.get("file", "")
            path = _source(src, rel)
            if not path:
                print(f"  skip {rel or '?'}: not found under {' or '.join(ART_ROOTS)}/", file=sys.stderr)
                continue
            name = f"manga-{i + 1:02d}" if section == "manga" else path.stem.lower().replace("_", "-")
            copied = art_copy(path, out / "art", name)
            if not copied:
                continue
            data[section].append({
                "src": "art/" + copied["src"], "full": "art/" + copied["full"], "w": copied["w"], "h": copied["h"],
                "title": entry.get("title", path.stem), "kind": "fan" if entry.get("kind") == "fan" else "ai",
                "by": entry.get("by", ""), "link": entry.get("link", ""), "caption": entry.get("caption", ""),
            })
    print(f"art: {len(data['art'])} pieces, manga: {len(data['manga'])} pages, memes: {len(data['memes'])}")

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

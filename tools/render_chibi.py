#!/usr/bin/env python3
"""Render the 'chibi' (Cozy Chibi) skin directly from the 4 art/chibi_*.png sheets.

Extracts the pixel-art Chibi poses from:
  - art/chibi_idle.png      (sitting pose)
  - art/chibi_idle_2.png    (standing pose)
  - art/chibi_states_1.png  (chill_sit, aww_heart)
  - art/chibi_states_2.png  (typing, angry, sad_sit, thinking, dance)

Cleanly strips dark/warm-orange/purple background halos and stray corner glow
pixels, splits beanie cyan vs. blue skin HSV so atom_inject.js runtime mood
tinting recolours only face/hands/feet while keeping the rainbow beanie, pink
ears, white hair, and cream hoodie intact, and drives the larger sprites with
asymmetric breathing, anticipation-squash hops, head tilts, eased gazes, and
natural blink curves across all 19 states.
"""
from __future__ import annotations

import math
import os
import sys
from collections import deque

import cairo

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_TOOLS_DIR)
_ART_DIR = os.path.join(_ROOT_DIR, "art")
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

import tools.render_gemini_typing as R
import tools.render_v2 as RV2

FW, FH, FPS = RV2.FW, RV2.FH, RV2.FPS

# Source specs: (filename, (x0, y0, x1, y1), glow_strip, strip_bl_pink)
_EXTRACT_SPECS = {
    "sit":       ("chibi_idle.png",     (15,   25,  305,  365), False,    True),
    "stand":     ("chibi_idle_2.png",   (15,   30,  310,  385), "warm",   True),
    "typing":    ("chibi_states_2.png", (1020, 355, 1480, 725), False,    False),
    "sad_sit":   ("chibi_states_2.png", (1035, 920, 1485, 1345), False,   True),
    "angry":     ("chibi_states_2.png", (2185, 345, 2655, 735), "strong", False),
    "thinking":  ("chibi_states_2.png", (1615, 920, 2065, 1345), False,   False),
    "dance":     ("chibi_states_2.png", (2185, 910, 2655, 1345), False,   False),
    "aww":       ("chibi_states_1.png", (1615, 895, 2065, 1295), False,   False),
    "chill_sit": ("chibi_states_1.png", (1615, 225, 2065, 695), False,    False),
}

_IS_LE = sys.byteorder == "little"
_PNG_CACHE: dict[str, cairo.ImageSurface] = {}
_SPRITE_CACHE: dict[str, dict] = {}


def _efloat(idx: int) -> tuple[float, float, float]:
    """Return 0..1 float RGB tuple for Electron idx."""
    return R.ELECTRONS[idx].color


def _e255(idx: int) -> tuple[int, int, int]:
    """Return 0..255 int RGB tuple for Electron idx."""
    c = R.ELECTRONS[idx].color
    return (round(c[0] * 255), round(c[1] * 255), round(c[2] * 255))


def _load_png(filename: str) -> cairo.ImageSurface:
    surf = _PNG_CACHE.get(filename)
    if surf is None:
        path = os.path.join(_ART_DIR, filename)
        surf = cairo.ImageSurface.create_from_png(path)
        _PNG_CACHE[filename] = surf
    return surf


def _read_px(buf: bytearray, idx: int) -> tuple[int, int, int, int]:
    """Return unpremultiplied (r, g, b, a) in 0..255 from an ARGB32 buffer."""
    if _IS_LE:
        b, g, r, a = buf[idx], buf[idx + 1], buf[idx + 2], buf[idx + 3]
    else:
        a, r, g, b = buf[idx], buf[idx + 1], buf[idx + 2], buf[idx + 3]
    if a == 0:
        return (0, 0, 0, 0)
    if a == 255:
        return (r, g, b, 255)
    inv = 255.0 / a
    return (
        min(255, int(r * inv + 0.5)),
        min(255, int(g * inv + 0.5)),
        min(255, int(b * inv + 0.5)),
        a,
    )


def _write_px(buf: bytearray, idx: int, r: int, g: int, b: int, a: int) -> None:
    """Write premultiplied ARGB32 pixel from unpremultiplied 0..255 (r, g, b, a)."""
    if a <= 0:
        buf[idx] = buf[idx + 1] = buf[idx + 2] = buf[idx + 3] = 0
        return
    if a < 255:
        af = a / 255.0
        pr = int(r * af + 0.5)
        pg = int(g * af + 0.5)
        pb = int(b * af + 0.5)
    else:
        pr, pg, pb = r, g, b
    if _IS_LE:
        buf[idx], buf[idx + 1], buf[idx + 2], buf[idx + 3] = pb, pg, pr, a
    else:
        buf[idx], buf[idx + 1], buf[idx + 2], buf[idx + 3] = a, pr, pg, pb


def _is_bg_candidate(r: int, g: int, b: int, a: int, glow_strip) -> bool:
    """Return True if pixel belongs to the dark panel or warm/purple ambient halo."""
    if a < 18:
        return True
    if r < 68 and g < 70 and b < 100:
        return True
    if glow_strip == "warm":
        if r < 145 and g < 88 and b < 84 and r >= g + 6:
            return True
        if r < 126 and g < 86 and b < 130 and g <= min(r, b) + 4:
            return True
    elif glow_strip == "strong":
        if r < 176 and g < 102 and b < 95 and r >= g + 8:
            return True
        if r < 132 and g < 86 and b < 126 and g <= min(r, b) + 4:
            return True
    return False


def _detect_eyes(rgba: list[tuple[int, int, int, int]], w: int, h: int):
    """Locate (left_eye_box, right_eye_box, skin_rgb_float) in tight sprite coords."""
    x_lo = int(w * 0.24)
    x_hi = int(w * 0.76)
    y_lo = int(h * 0.39)
    y_hi = int(h * 0.63)
    mid_x = w * 0.5

    left_pts = []
    right_pts = []
    for y in range(y_lo, y_hi):
        row = y * w
        for x in range(x_lo, x_hi):
            r, g, b, a = rgba[row + x]
            if a > 220 and r < 55 and g < 55 and b < 55:
                if x < mid_x:
                    left_pts.append((x, y))
                else:
                    right_pts.append((x, y))

    def _cluster_box(pts: list[tuple[int, int]]):
        if len(pts) < 12:
            return None
        pt_set = set(pts)
        seen = set()
        best = []
        for p in pts:
            if p in seen:
                continue
            q = deque([p])
            seen.add(p)
            comp = []
            while q:
                cx, cy = q.popleft()
                comp.append((cx, cy))
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1),
                               (cx + 2, cy), (cx - 2, cy), (cx, cy + 2), (cx - 1, cy - 1),
                               (cx + 1, cy + 1)):
                    if (nx, ny) in pt_set and (nx, ny) not in seen:
                        seen.add((nx, ny))
                        q.append((nx, ny))
            if len(comp) > len(best):
                best = comp
        if len(best) < 12:
            return None
        xs = [p[0] for p in best]
        ys = [p[1] for p in best]
        box = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)
        if (box[3] - box[1]) > int(h * 0.14):
            return None
        return box

    lbox = _cluster_box(left_pts)
    rbox = _cluster_box(right_pts)
    if lbox is None or rbox is None:
        return None, None, (0.24, 0.72, 0.94)

    mx0 = lbox[2] + 3
    mx1 = max(mx0 + 1, rbox[0] - 3)
    my0 = max(lbox[1], rbox[1]) + 2
    my1 = min(lbox[3], rbox[3])
    sr = sg = sb = sc = 0
    for y in range(my0, max(my0 + 1, my1)):
        row = y * w
        for x in range(mx0, mx1):
            r, g, b, a = rgba[row + x]
            if a > 220 and b > r + 15 and r < 140:
                sr += r
                sg += g
                sb += b
                sc += 1
    skin = (sr / (sc * 255.0), sg / (sc * 255.0), sb / (sc * 255.0)) if sc else (0.24, 0.72, 0.94)
    return lbox, rbox, skin


def _extract_sprite(name: str) -> dict:
    """Extract, clean, HSV-normalize, and pack sprite surface + metadata."""
    cached = _SPRITE_CACHE.get(name)
    if cached is not None:
        return cached

    fn, (x0, y0, x1, y1), glow_strip, strip_bl_pink = _EXTRACT_SPECS[name]
    src = _load_png(fn)
    src_w, src_h = src.get_width(), src.get_height()
    src_buf = bytearray(src.get_data())
    src_stride = src.get_stride()

    cw = min(x1, src_w) - max(0, x0)
    ch = min(y1, src_h) - max(0, y0)
    sx0, sy0 = max(0, x0), max(0, y0)

    raw = [(0, 0, 0, 0)] * (cw * ch)
    for y in range(ch):
        row_off = (sy0 + y) * src_stride
        out_off = y * cw
        for x in range(cw):
            raw[out_off + x] = _read_px(src_buf, row_off + (sx0 + x) * 4)

    if strip_bl_pink:
        cut_x = int(cw * 0.30)
        cut_y = int(ch * 0.70)
        for y in range(cut_y, ch):
            row = y * cw
            for x in range(cut_x):
                r, g, b, a = raw[row + x]
                if a > 0 and r > g + 4 and b > g + 4 and g < 165:
                    raw[row + x] = (0, 0, 0, 0)

    bg = bytearray(cw * ch)
    q: deque[int] = deque()

    def _try_seed(idx: int) -> None:
        if not bg[idx]:
            r, g, b, a = raw[idx]
            if _is_bg_candidate(r, g, b, a, glow_strip):
                bg[idx] = 1
                q.append(idx)

    for x in range(cw):
        _try_seed(x)
        _try_seed((ch - 1) * cw + x)
    for y in range(1, ch - 1):
        _try_seed(y * cw)
        _try_seed(y * cw + cw - 1)

    while q:
        idx = q.popleft()
        x = idx % cw
        y = idx // cw
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < cw and 0 <= ny < ch:
                nidx = ny * cw + nx
                if not bg[nidx]:
                    r, g, b, a = raw[nidx]
                    if _is_bg_candidate(r, g, b, a, glow_strip):
                        bg[nidx] = 1
                        q.append(nidx)

    for y in range(ch):
        row = y * cw
        for x in range(cw):
            idx = row + x
            if bg[idx]:
                raw[idx] = (0, 0, 0, 0)
                continue
            r, g, b, a = raw[idx]
            if a == 0:
                continue
            touches_bg = False
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if nx < 0 or nx >= cw or ny < 0 or ny >= ch or bg[ny * cw + nx]:
                    touches_bg = True
                    break
            if touches_bg:
                if glow_strip in ("warm", "strong") and r < 178 and g < 110 and b < 110 and r >= g + 8:
                    raw[idx] = (0, 0, 0, 0)
                elif r < 80 and g < 80 and b < 112:
                    raw[idx] = (r, g, b, int(a * 0.45))

    comp_id = [-1] * (cw * ch)
    comps: list[list[int]] = []
    for idx in range(cw * ch):
        if comp_id[idx] != -1 or raw[idx][3] <= 32:
            continue
        cid = len(comps)
        cq = deque([idx])
        comp_id[idx] = cid
        members = []
        while cq:
            cur = cq.popleft()
            members.append(cur)
            cx = cur % cw
            cy = cur // cw
            for ny in range(max(0, cy - 1), min(ch, cy + 2)):
                nrow = ny * cw
                for nx in range(max(0, cx - 1), min(cw, cx + 2)):
                    nidx = nrow + nx
                    if comp_id[nidx] == -1 and raw[nidx][3] > 32:
                        comp_id[nidx] = cid
                        cq.append(nidx)
        comps.append(members)

    if comps:
        main_cid = max(range(len(comps)), key=lambda i: len(comps[i]))
        keep = set(comps[main_cid])
        for idx in range(cw * ch):
            if idx not in keep:
                raw[idx] = (0, 0, 0, 0)

    min_x, min_y = cw, ch
    max_x, max_y = -1, -1
    for y in range(ch):
        row = y * cw
        for x in range(cw):
            if raw[row + x][3] > 0:
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y

    tw = max(1, max_x - min_x + 1)
    th = max(1, max_y - min_y + 1)
    cropped = [(0, 0, 0, 0)] * (tw * th)
    for y in range(th):
        s_off = (min_y + y) * cw + min_x
        d_off = y * tw
        for x in range(tw):
            cropped[d_off + x] = raw[s_off + x]

    lbox, rbox, skin_rgb = _detect_eyes(cropped, tw, th)
    eye_top = min(lbox[1], rbox[1]) if (lbox and rbox) else int(th * 0.44)
    beanie_cut = min(int(th * 0.42), max(int(th * 0.30), eye_top - max(6, int(th * 0.04))))

    for y in range(th):
        row = y * tw
        in_beanie = y < beanie_cut
        for x in range(tw):
            r, g, b, a = cropped[row + x]
            if a == 0:
                continue
            h, s, v = RV2._rgb_to_hsv(r, g, b)
            if in_beanie:
                if 186.0 <= h <= 232.0 and s > 0.25 and v > 0.14:
                    nr, ng, nb = RV2._hsv_to_rgb(180.0, s, v)
                    cropped[row + x] = (nr, ng, nb, a)
            else:
                if 182.0 <= h <= 228.0 and s > 0.26 and v > 0.25:
                    nh = max(204.0, min(216.0, h))
                    if nh != h:
                        nr, ng, nb = RV2._hsv_to_rgb(nh, max(0.38, s), v)
                        cropped[row + x] = (nr, ng, nb, a)

    if lbox and rbox:
        _, _, skin_rgb = _detect_eyes(cropped, tw, th)

    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, tw, th)
    out_buf = out.get_data()
    out_stride = out.get_stride()
    for y in range(th):
        row_off = y * out_stride
        src_off = y * tw
        for x in range(tw):
            r, g, b, a = cropped[src_off + x]
            _write_px(out_buf, row_off + x * 4, r, g, b, a)
    out.mark_dirty()

    face_cx = (lbox[2] + rbox[0]) * 0.5 if (lbox and rbox) else tw * 0.5

    res = {
        "surf": out,
        "w": tw,
        "h": th,
        "face_cx": face_cx,
        "lbox": lbox,
        "rbox": rbox,
        "skin_rgb": skin_rgb,
    }
    _SPRITE_CACHE[name] = res
    return res


def _new_surface() -> tuple[cairo.ImageSurface, cairo.Context]:
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, FW, FH)
    return surf, cairo.Context(surf)


def _tint_surface(surf: cairo.ImageSurface, mood: str | None, amount: float = 1.0) -> cairo.ImageSurface:
    """Apply RV2._tint_rgb (0..255 int API) across an entire rendered 150x120 frame."""
    if not mood or amount <= 0.0:
        return surf
    buf = surf.get_data()
    stride = surf.get_stride()
    for y in range(FH):
        row = y * stride
        for x in range(FW):
            idx = row + x * 4
            r, g, b, a = _read_px(buf, idx)
            if a == 0:
                continue
            tr, tg, tb = RV2._tint_rgb((r, g, b), mood, amount)
            _write_px(buf, idx, tr, tg, tb, a)
    surf.mark_dirty()
    return surf


# ---------------------------------------------------------------------------
# Organic easing & kinematics helpers (human breath, hops, eased gaze, notes)
# ---------------------------------------------------------------------------
def _smooth(t: float) -> float:
    t = RV2._clamp(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _breath(u: float) -> float:
    """Asymmetric human breath curve: gentle inhale (0..0.38), slower exhale (0.38..0.84), calm rest."""
    u = u % 1.0
    if u < 0.38:
        return _smooth(u / 0.38)
    if u < 0.84:
        return 1.0 - _smooth((u - 0.38) / 0.46)
    return 0.0


def _hop_arc(p: float) -> tuple[float, float, float]:
    """Return (dy_px, sx_scale, sy_scale) for a jump with anticipation squash, hang & cushion landing."""
    p = p % 1.0
    if p < 0.18:
        t = _smooth(p / 0.18)
        return 0.6 * t, 1.0 + 0.055 * t, 1.0 - 0.065 * t
    if p < 0.74:
        air = (p - 0.18) / 0.56
        # Parabolic arc with brief apex hang
        arc = math.sin(air * math.pi) ** 0.85
        stretch = math.cos(air * math.pi) * 0.045
        return -4.6 * arc, 1.0 - abs(stretch) * 0.45, 1.0 + abs(stretch) * 0.55
    t = (p - 0.74) / 0.26
    land = math.sin(t * math.pi)
    return 0.5 * land, 1.0 + 0.05 * land, 1.0 - 0.055 * land


def _map_sprite_pt(x: float, y: float, cx: float, foot_y: float,
                   face_cx: float, sp_h: float, sc_x: float, sc_y: float,
                   rot_deg: float, skew_x: float) -> tuple[float, float]:
    """Map source sprite pixel coordinate through bottom-pivoted scale/skew/rotate."""
    lx = (x - face_cx) * sc_x
    ly = (y - sp_h) * sc_y
    if skew_x:
        lx = lx - skew_x * ly
    if rot_deg:
        rad = math.radians(rot_deg)
        c, s = math.cos(rad), math.sin(rad)
        lx, ly = lx * c - ly * s, lx * s + ly * c
    return cx + lx, foot_y + ly


def _transform_box(box: tuple[int, int, int, int], sp: dict,
                   cx: float, foot_y: float, sc_x: float, sc_y: float,
                   rot_deg: float, skew_x: float) -> tuple[float, float, float, float]:
    """Return axis-aligned canvas bounding box of a transformed sprite-space rectangle."""
    corners = (
        _map_sprite_pt(box[0], box[1], cx, foot_y, sp["face_cx"], sp["h"], sc_x, sc_y, rot_deg, skew_x),
        _map_sprite_pt(box[2], box[1], cx, foot_y, sp["face_cx"], sp["h"], sc_x, sc_y, rot_deg, skew_x),
        _map_sprite_pt(box[0], box[3], cx, foot_y, sp["face_cx"], sp["h"], sc_x, sc_y, rot_deg, skew_x),
        _map_sprite_pt(box[2], box[3], cx, foot_y, sp["face_cx"], sp["h"], sc_x, sc_y, rot_deg, skew_x),
    )
    xs = [pt[0] for pt in corners]
    ys = [pt[1] for pt in corners]
    return min(xs), min(ys), max(xs), max(ys)


def _sharpen_neutral_eyes(surf: cairo.ImageSurface, rect_l: tuple[float, float, float, float],
                          rect_r: tuple[float, float, float, float]) -> None:
    """Keep extracted PNG eyes crisp & detectable by atom_inject.js tiltMoodEyes()."""
    buf = surf.get_data()
    stride = surf.get_stride()
    for x0f, y0f, x1f, y1f in (rect_l, rect_r):
        x0 = max(0, int(math.floor(x0f)))
        y0 = max(0, int(math.floor(y0f)))
        x1 = min(FW, int(math.ceil(x1f)))
        y1 = min(FH, int(math.ceil(y1f)))
        cx = (x0f + x1f) * 0.5
        cy = (y0f + y1f) * 0.5
        half_w = max(2.8, (x1f - x0f) * 0.5 + 0.35)
        half_h = max(3.2, (y1f - y0f) * 0.5 + 0.35)
        for y in range(y0, y1):
            row = y * stride
            for x in range(x0, x1):
                idx = row + x * 4
                r, g, b, a = _read_px(buf, idx)
                if a < 180:
                    continue
                if r > 188 and g > 188 and b > 195:
                    continue
                lum = 0.299 * r + 0.587 * g + 0.114 * b
                if lum < 120.0 and abs((x + 0.5) - cx) <= half_w and abs((y + 0.5) - cy) <= half_h:
                    _write_px(buf, idx, 14, 16, 22, a)
    surf.mark_dirty()


def _draw_eye_override(ctx: cairo.Context, lrect: tuple[float, float, float, float],
                       rrect: tuple[float, float, float, float],
                       skin_rgb: tuple[float, float, float],
                       eye_mode: str, *,
                       eye_dx: float = 0.0, eye_dy: float = 0.0) -> None:
    """Draw curved blinks, drowsy lids, soft sleep curves, X X, and eased pupil gazes."""
    if not eye_mode or (eye_mode == "neutral" and eye_dx == 0.0 and eye_dy == 0.0):
        return

    dark = (0.06, 0.07, 0.10)
    white = (0.98, 0.99, 1.0)
    r_, g_, b_ = skin_rgb

    for _is_left, (x0, y0, x1, y1) in ((True, lrect), (False, rrect)):
        ew = max(4.2, x1 - x0)
        eh = max(4.4, y1 - y0)
        cx = (x0 + x1) * 0.5
        cy = (y0 + y1) * 0.5
        ctx.set_source_rgb(r_, g_, b_)
        ctx.rectangle(x0 - 1.0, y0 - 1.0, ew + 2.0, eh + 2.0)
        ctx.fill()

        if eye_mode == "blink_half":
            # Soft mid-blink: half-height pupil + gentle top lid
            pw = max(4.4, ew * 0.92)
            ph = max(2.2, eh * 0.45)
            ctx.set_source_rgb(*dark)
            ctx.rectangle(round(cx - pw * 0.5), round(cy - 0.4), round(pw), round(ph))
            ctx.fill()
            ctx.set_source_rgba(dark[0], dark[1], dark[2], 0.95)
            ctx.set_line_width(1.6)
            ctx.move_to(cx - ew * 0.48, cy - 0.8)
            ctx.curve_to(cx - ew * 0.15, cy - 0.1, cx + ew * 0.15, cy - 0.1, cx + ew * 0.48, cy - 0.8)
            ctx.stroke()
        elif eye_mode in ("blink", "sleep"):
            # Warm gently curved eyelid (relaxed closed blink or peaceful sleep arc)
            ctx.set_source_rgb(*dark)
            ctx.set_line_cap(cairo.LINE_CAP_ROUND)
            ctx.set_line_width(1.7)
            mid_y = cy + (0.8 if eye_mode == "sleep" else 0.4)
            dip = 1.4 if eye_mode == "sleep" else 0.9
            ctx.move_to(cx - ew * 0.46, mid_y - 0.4)
            ctx.curve_to(cx - ew * 0.15, mid_y + dip, cx + ew * 0.15, mid_y + dip, cx + ew * 0.46, mid_y - 0.4)
            ctx.stroke()
        elif eye_mode == "tired":
            # Heavy drooping upper lid + soft drowsy iris peek beneath
            pw = max(3.6, ew * 0.72)
            ctx.set_source_rgba(dark[0], dark[1], dark[2], 0.88)
            ctx.rectangle(round(cx - pw * 0.5), round(cy + 0.6), round(pw), 2.0)
            ctx.fill()
            ctx.set_source_rgb(*dark)
            ctx.set_line_cap(cairo.LINE_CAP_ROUND)
            ctx.set_line_width(1.7)
            ctx.move_to(cx - ew * 0.50, cy + 0.2)
            ctx.curve_to(cx - ew * 0.15, cy + 0.8, cx + ew * 0.15, cy + 0.8, cx + ew * 0.50, cy + 0.2)
            ctx.stroke()
        elif eye_mode == "error":
            ctx.set_source_rgb(*dark)
            ctx.set_line_cap(cairo.LINE_CAP_ROUND)
            ctx.set_line_width(1.7)
            rx = ew * 0.34
            ry = eh * 0.32
            ctx.move_to(cx - rx, cy - ry)
            ctx.line_to(cx + rx, cy + ry)
            ctx.move_to(cx - rx, cy + ry)
            ctx.line_to(cx + rx, cy - ry)
            ctx.stroke()
        else:
            dx, dy = eye_dx, eye_dy
            if eye_mode == "look_l" and dx == 0.0:
                dx = -1.5
            elif eye_mode == "look_r" and dx == 0.0:
                dx = 1.5
            elif eye_mode == "look_ul" and dx == 0.0 and dy == 0.0:
                dx, dy = -1.2, -1.0
            elif eye_mode == "look_ur" and dx == 0.0 and dy == 0.0:
                dx, dy = 1.2, -1.0
            pw = max(4.6, min(6.2, ew * (1.06 if eye_mode == "wide" else 0.92)))
            ph = max(5.0, min(6.8, eh * (1.10 if eye_mode == "wide" else 0.94)))
            px = cx + dx - pw * 0.5
            py = cy + dy - ph * 0.5
            # Softly rounded dark eye box + crisp top-left glint
            ctx.set_source_rgb(*dark)
            ctx.rectangle(round(px), round(py) + 0.5, round(pw), max(2.0, round(ph) - 1.0))
            ctx.rectangle(round(px) + 0.5, round(py), max(2.0, round(pw) - 1.0), round(ph))
            ctx.fill()
            ctx.set_source_rgb(*white)
            ctx.rectangle(round(px + 1.0), round(py + 1.0), 1.5, 1.5)
            ctx.fill()


def _draw_chibi(ctx: cairo.Context, surf: cairo.ImageSurface, sprite_name: str, *,
                cx: float = 75.0, foot_y: float = 115.0, target_h: float = 96.0,
                sx_scale: float = 1.0, sy_scale: float = 1.0,
                rot_deg: float = 0.0, skew_x: float = 0.0,
                eye_mode: str = "neutral", eye_dx: float = 0.0, eye_dy: float = 0.0,
                alpha: float = 1.0) -> None:
    """Blit Chibi anchored by feet at (cx, foot_y) with optional tilt & lean around feet."""
    sp = _extract_sprite(sprite_name)
    base_scale = target_h / sp["h"]
    sc_x = base_scale * sx_scale
    sc_y = base_scale * sy_scale

    ctx.save()
    ctx.translate(cx, foot_y)
    if rot_deg:
        ctx.rotate(math.radians(rot_deg))
    if skew_x:
        ctx.transform(cairo.Matrix(1.0, 0.0, -skew_x, 1.0, 0.0, 0.0))
    ctx.scale(sc_x, sc_y)
    ctx.translate(-sp["face_cx"], -sp["h"])
    ctx.set_source_surface(sp["surf"], 0.0, 0.0)
    ctx.get_source().set_filter(cairo.FILTER_BILINEAR)
    if alpha < 1.0:
        ctx.paint_with_alpha(alpha)
    else:
        ctx.paint()
    ctx.restore()

    if sp["lbox"] and sp["rbox"]:
        lrect = _transform_box(sp["lbox"], sp, cx, foot_y, sc_x, sc_y, rot_deg, skew_x)
        rrect = _transform_box(sp["rbox"], sp, cx, foot_y, sc_x, sc_y, rot_deg, skew_x)
        if eye_mode == "neutral" and eye_dx == 0.0 and eye_dy == 0.0 and alpha >= 0.95:
            _sharpen_neutral_eyes(surf, lrect, rrect)
        elif eye_mode != "neutral" or eye_dx != 0.0 or eye_dy != 0.0:
            _draw_eye_override(ctx, lrect, rrect, sp["skin_rgb"], eye_mode, eye_dx=eye_dx, eye_dy=eye_dy)


def _draw_shadow(ctx: cairo.Context, cx: float, y: float, rx: float = 21.0, alpha: float = 0.28) -> None:
    ctx.save()
    ctx.translate(cx, y)
    ctx.scale(max(8.0, rx), 3.3)
    ctx.set_source_rgba(0.03, 0.05, 0.10, alpha)
    ctx.arc(0.0, 0.0, 1.0, 0.0, math.tau)
    ctx.fill()
    ctx.restore()


# ---------------------------------------------------------------------------
# Prop helpers (Gemini wave bar, thought dots, music notes, hearts, etc.)
# ---------------------------------------------------------------------------
def _draw_gemini_typing_bar(ctx: cairo.Context, t_wave: float, wy: float = 9.0, alpha: float = 1.0) -> None:
    """5-dot horizontal Gemini loading wave bar cleanly above Chibi's pom-pom."""
    size_radii = (1.4, 2.2, 3.0, 3.8)
    for k, (bx, spec) in enumerate(zip(RV2.ATOM_WAVE_X, R.ELECTRONS)):
        sc = R.loading_bar_score(k, t_wave)
        si = R.size_index_from_score(sc)
        r = size_radii[si]
        col = spec.color
        ctx.set_source_rgba(col[0], col[1], col[2], alpha * 0.25)
        ctx.rectangle(round(bx - r - 1), round(wy - r - 1), round((r + 1) * 2), round((r + 1) * 2))
        ctx.fill()
        ctx.set_source_rgba(col[0], col[1], col[2], alpha)
        ctx.rectangle(round(bx - r), round(wy - r), round(r * 2), round(r * 2))
        ctx.fill()
        ctx.set_source_rgba(1.0, 1.0, 1.0, 0.55 * alpha)
        ctx.rectangle(round(bx - r + 1), round(wy - r + 1), max(1, round(r * 0.65)), max(1, round(r * 0.65)))
        ctx.fill()


def _draw_thought_dots(ctx: cairo.Context, x0: float, y0: float, u: float, alpha: float = 1.0) -> None:
    """3 gently rising organic thought-bubble dots leading outward."""
    for i in range(3):
        phase = (u + i * 0.25) % 1.0
        a = alpha * (0.45 + 0.55 * math.sin(phase * math.pi))
        dx = x0 - i * 4.2
        dy = y0 + i * 4.5 - math.sin(phase * math.tau) * 1.2
        r = 2.6 - i * 0.55
        col = _efloat((i + 1) % 5)
        ctx.set_source_rgba(col[0], col[1], col[2], a)
        ctx.arc(dx, dy, r, 0.0, math.tau)
        ctx.fill()


def _draw_music_note(ctx: cairo.Context, cx: float, cy: float,
                     rgb: tuple[int, int, int], alpha: float = 1.0) -> None:
    """Crisp pixel-art eighth note for dance."""
    rows = (
        "..##.",
        "..#.#",
        "..#..",
        ".##..",
        "###..",
        ".#...",
    )
    RV2._draw_pixel_glyph(ctx, rows, cx - 2.5, cy - 3.0, 1, rgb, alpha)


def _draw_heart(ctx: cairo.Context, cx: float, cy: float, scale: float = 1.0,
                rgb: tuple[int, int, int] = (250, 115, 174), alpha: float = 1.0) -> None:
    rows = (
        ".##.##.",
        "#######",
        "#######",
        ".#####.",
        "..###..",
        "...#...",
    )
    px = max(1, round(1.4 * scale))
    RV2._draw_pixel_glyph(ctx, rows, cx - 3.5 * px, cy - 3.0 * px, px, rgb, alpha)


def _draw_butterfly(ctx: cairo.Context, cx: float, cy: float, flap: float,
                    rgb: tuple[float, float, float] = (0.55, 0.85, 0.99), alpha: float = 1.0) -> None:
    spread = 2.0 + 2.5 * abs(flap)
    ctx.set_source_rgba(rgb[0], rgb[1], rgb[2], alpha)
    ctx.rectangle(round(cx - spread - 1.5), round(cy - 2.5), round(spread), 3.0)
    ctx.rectangle(round(cx + 1.5), round(cy - 2.5), round(spread), 3.0)
    ctx.rectangle(round(cx - spread * 0.7 - 1.0), round(cy + 0.5), max(1.5, round(spread * 0.7)), 2.2)
    ctx.rectangle(round(cx + 1.0), round(cy + 0.5), max(1.5, round(spread * 0.7)), 2.2)
    ctx.fill()
    ctx.set_source_rgba(0.98, 0.95, 0.75, alpha)
    ctx.rectangle(round(cx - 0.5), round(cy - 2.0), 1.5, 4.5)
    ctx.fill()


def _draw_soundwaves(ctx: cairo.Context, cx: float, cy: float, phase: float, alpha: float = 1.0) -> None:
    col = _efloat(0)
    for side in (-1.0, 1.0):
        for ring in range(2):
            p = (phase + ring * 0.5) % 1.0
            a = alpha * (1.0 - p) * 0.92
            dist = 31.0 + p * 14.0
            ctx.set_source_rgba(col[0], col[1], col[2], a)
            if side > 0:
                ctx.arc(cx + 21.0, cy, dist - 14.0, -0.52, 0.52)
            else:
                ctx.arc(cx - 21.0, cy, dist - 14.0, math.pi - 0.52, math.pi + 0.52)
            ctx.set_line_width(2.0)
            ctx.stroke()


def _draw_sweat_drop(ctx: cairo.Context, cx: float, cy: float, alpha: float = 1.0) -> None:
    rows = (
        "..#..",
        ".###.",
        "#####",
        "#####",
        ".###.",
    )
    RV2._draw_pixel_glyph(ctx, rows, cx - 2.5, cy - 2.5, 1, (115, 218, 255), alpha)


def _draw_exclamation(ctx: cairo.Context, cx: float, cy: float,
                      rgb: tuple[int, int, int] = (252, 184, 64), alpha: float = 1.0) -> None:
    rows = (
        "##",
        "##",
        "##",
        "##",
        "..",
        "##",
    )
    RV2._draw_pixel_glyph(ctx, rows, cx - 1.5, cy - 4.5, 2, rgb, alpha)


def _draw_question_mark(ctx: cairo.Context, cx: float, cy: float,
                        rgb: tuple[int, int, int] = (115, 208, 252), alpha: float = 1.0) -> None:
    rows = (
        ".###.",
        "##.##",
        "...##",
        "..##.",
        "..##.",
        ".....",
        "..##.",
    )
    RV2._draw_pixel_glyph(ctx, rows, cx - 3.5, cy - 5.0, 2, rgb, alpha)


def _draw_zzz(ctx: cairo.Context, cx: float, cy: float, size: float = 1.0, alpha: float = 1.0) -> None:
    rows = (
        "####",
        "..#.",
        ".#..",
        "####",
    )
    RV2._draw_pixel_glyph(ctx, rows, cx, cy, max(1, round(1.4 * size)), (134, 174, 245), alpha)


def _draw_speech_bubble(ctx: cairo.Context, cx: float, cy: float, u: float = 0.0, alpha: float = 1.0) -> None:
    ctx.set_source_rgba(0.95, 0.97, 1.0, 0.95 * alpha)
    ctx.rectangle(cx - 10, cy - 6, 20, 11)
    ctx.rectangle(cx - 11, cy - 5, 22, 9)
    ctx.fill()
    ctx.rectangle(cx - 4, cy + 5, 3, 3)
    ctx.rectangle(cx - 5, cy + 8, 2, 2)
    ctx.fill()
    for i in range(3):
        pulse = math.sin(max(0.0, math.sin((u * 2.0 - i * 0.22) * math.pi)))
        col = _efloat(i)
        ctx.set_source_rgba(col[0], col[1], col[2], alpha * (0.45 + 0.55 * pulse))
        ctx.rectangle(cx - 6 + i * 5, cy - 2 - pulse * 1.2, 2.5, 2.5)
        ctx.fill()


def _draw_butterfly_electron(ctx: cairo.Context, x: float, y: float, size_idx: int,
                             rgb: tuple[float, float, float], flap: float,
                             morph: float, alpha: float = 1.0) -> None:
    """Morph a Gemini electron orb (morph=0) into a flapping pixel butterfly (morph=1)."""
    if morph <= 0.08:
        RV2._draw_atom_blob(ctx, x, y, size_idx, rgb, alpha=alpha, glow=True)
        return
    r, g, b = rgb
    scale = 0.72 + 0.16 * max(0, min(3, size_idx))
    spread = RV2._lerp(0.6, (2.2 + 2.4 * abs(flap)) * scale, morph)
    wing_h = RV2._lerp(1.8, 3.0 * scale, morph)
    low_w = RV2._lerp(0.4, spread * 0.68, morph)
    low_h = RV2._lerp(1.4, 2.0 * scale, morph)

    ctx.save()
    # Soft electron aura behind wings
    ctx.set_source_rgba(r, g, b, alpha * 0.24)
    ctx.rectangle(round(x - spread - 2.0), round(y - wing_h), round((spread + 2.0) * 2.0), round(wing_h + low_h + 1.5))
    ctx.fill()

    # Crisp left & right upper/lower pixel wings
    ctx.set_source_rgba(r, g, b, alpha)
    ctx.rectangle(round(x - spread - 1.0), round(y - wing_h * 0.85), round(spread), round(wing_h))
    ctx.rectangle(round(x + 1.0), round(y - wing_h * 0.85), round(spread), round(wing_h))
    if morph > 0.25:
        ctx.rectangle(round(x - low_w - 0.8), round(y + 0.6), max(1.5, round(low_w)), round(low_h))
        ctx.rectangle(round(x + 0.8), round(y + 0.6), max(1.5, round(low_w)), round(low_h))
    ctx.fill()

    # Wing glint pixels + warm center body
    ctx.set_source_rgba(1.0, 1.0, 1.0, 0.55 * alpha)
    ctx.rectangle(round(x - spread), round(y - wing_h * 0.7), 1.4, 1.4)
    ctx.rectangle(round(x + spread - 0.4), round(y - wing_h * 0.7), 1.4, 1.4)
    ctx.fill()
    ctx.set_source_rgba(0.98, 0.96, 0.80, alpha * RV2._lerp(0.5, 1.0, morph))
    ctx.rectangle(round(x - 0.6), round(y - 2.0 * scale), 1.4, max(2.5, 4.2 * scale))
    ctx.fill()
    ctx.restore()


def _render_butterfly_orbits(ctx: cairo.Context, blobs, trails, *, front: bool,
                             u: float, morph: float, alpha: float = 1.0) -> None:
    """Render 3D depth-sorted orbits whose electrons morph into fluttering Gemini butterflies."""
    pal = [sp.color for sp in R.ELECTRONS]
    trail_alpha = alpha * max(0.0, 1.0 - morph * 1.15)
    if trail_alpha > 0.02:
        for pz, k, px, py, sz in trails:
            if (pz >= 0.0) == front:
                RV2._draw_trail_sq(ctx, px, py, sz, pal[k], alpha=trail_alpha)
    for pz, k, px, py, sidx in blobs:
        if (pz >= 0.0) == front:
            flutter_y = math.sin((u * 3.0 + k * 0.37) * math.tau) * 1.5 * morph
            flap = math.sin((u * 6.0 + k * 0.21) * math.tau)
            bx = max(7.0, min(FW - 7.0, px))
            by = max(7.0, min(FH - 7.0, py + flutter_y))
            _draw_butterfly_electron(ctx, bx, by, sidx, pal[k], flap, morph, alpha=alpha)


def _draw_heart_electron(ctx: cairo.Context, x: float, y: float, size_idx: int,
                         rgb: tuple[float, float, float], morph: float, alpha: float = 1.0) -> None:
    """Morph a Gemini electron orb (morph=0) into a crisp glowing pixel heart (morph=1)."""
    if morph <= 0.12:
        RV2._draw_atom_blob(ctx, x, y, size_idx, rgb, alpha=alpha, glow=True)
        return
    r, g, b = rgb
    rgb255 = (round(r * 255), round(g * 255), round(b * 255))
    # Gentle orb aura while morphing
    ctx.save()
    ctx.set_source_rgba(r, g, b, alpha * 0.26)
    rad = 3.6 if size_idx >= 2 else 2.8
    ctx.rectangle(round(x - rad), round(y - rad), round(rad * 2), round(rad * 2))
    ctx.fill()
    ctx.restore()

    if size_idx <= 1:
        rows = (
            ".#.#.",
            "#####",
            "#####",
            ".###.",
            "..#..",
        )
        px = 1
        hx = max(3.0, min(FW - 6.0, x - 2.5))
        hy = max(3.0, min(FH - 6.0, y - 2.5))
    else:
        rows = (
            ".##.##.",
            "#######",
            "#######",
            ".#####.",
            "..###..",
            "...#...",
        )
        px = 1
        hx = max(4.0, min(FW - 8.0, x - 3.5))
        hy = max(4.0, min(FH - 7.0, y - 3.0))

    RV2._draw_pixel_glyph(ctx, rows, hx, hy, px, rgb255, alpha * min(1.0, morph * 1.15))
    ctx.set_source_rgba(1.0, 1.0, 1.0, 0.55 * alpha * morph)
    ctx.rectangle(round(hx + 1), round(hy + 1), 1.3, 1.3)
    ctx.fill()


def _render_heart_orbits(ctx: cairo.Context, blobs, trails, *, front: bool,
                         morph: float, alpha: float = 1.0) -> None:
    """Render 3D depth-sorted orbits whose electrons morph into glowing Gemini pixel hearts."""
    pal = [sp.color for sp in R.ELECTRONS]
    trail_alpha = alpha * max(0.0, 1.0 - morph * 1.2)
    if trail_alpha > 0.02:
        for pz, k, px, py, sz in trails:
            if (pz >= 0.0) == front:
                RV2._draw_trail_sq(ctx, px, py, sz, pal[k], alpha=trail_alpha)
    for pz, k, px, py, sidx in blobs:
        if (pz >= 0.0) == front:
            _draw_heart_electron(ctx, px, py, sidx, pal[k], morph, alpha=alpha)


# ---------------------------------------------------------------------------
# 19 State Renderers (bigger scale + steady human motion)
# ---------------------------------------------------------------------------
def render_idle():
    """65f [35, 64]: stand breathe + soft blink -> expressive plop -> cozy seated breathe."""
    frames = []
    # Stand phase (0..29): relaxed breathing + very gentle weight shift + 3f blink at 23..25
    for f in range(30):
        surf, ctx = _new_surface()
        u = f / 30.0
        br = _breath(u)
        sway = math.sin(u * math.tau)
        blobs, trails = RV2._hover_orbits(u, ax=75.0, ay=71.0 - br * 0.7, rev=RV2.IDLE_REV,
                                          rx_scale=1.18, ry_scale=1.08, max_size=2)
        _draw_shadow(ctx, 75.0, 115.5, 22.0, 0.26)
        RV2._render_orbit_layer(ctx, blobs, trails, front=False, alpha=0.82)
        eye = "blink" if f == 24 else ("blink_half" if f in (23, 25) else "neutral")
        _draw_chibi(ctx, surf, "stand", cx=75.0, foot_y=115.0, target_h=96.0,
                    sx_scale=1.0 + br * 0.012, sy_scale=1.0 + br * 0.014,
                    rot_deg=sway * 0.4, skew_x=sway * 0.005, eye_mode=eye)
        RV2._render_orbit_layer(ctx, blobs, trails, front=True, alpha=0.90)
        frames.append(surf)

    # Plop crouch transition (30..34)
    for k in range(5):
        surf, ctx = _new_surface()
        p = (k + 1) / 5.0
        _draw_shadow(ctx, 75.0, 115.5, RV2._lerp(22.0, 25.0, p), 0.28)
        if k < 2:
            sq_y = 1.0 - 0.11 * (k + 1)
            sq_x = 1.0 + 0.08 * (k + 1)
            _draw_chibi(ctx, surf, "stand", cx=75.0, foot_y=115.5 + k * 0.5, target_h=96.0,
                        sx_scale=sq_x, sy_scale=sq_y, rot_deg=-1.2 * (k + 1), eye_mode="blink_half" if k == 0 else "blink")
        elif k == 2:
            _draw_chibi(ctx, surf, "stand", cx=75.0, foot_y=116.5, target_h=96.0,
                        sx_scale=1.12, sy_scale=0.84, rot_deg=-1.5, eye_mode="blink", alpha=0.38)
            _draw_chibi(ctx, surf, "sit", cx=75.0, foot_y=116.5, target_h=94.0,
                        sx_scale=1.09, sy_scale=0.88, rot_deg=-1.0, eye_mode="blink", alpha=0.88)
        else:
            rebound = 1.0 + (0.045 if k == 3 else -0.018)
            _draw_chibi(ctx, surf, "sit", cx=75.0, foot_y=115.5, target_h=94.0,
                        sx_scale=1.0 / math.sqrt(rebound), sy_scale=rebound,
                        rot_deg=(0.6 if k == 3 else 0.0), eye_mode="blink_half" if k == 3 else "neutral")
        frames.append(surf)

    # Seated loop (35..64): cozy breathing + tiny gentle sway + natural 3f blink at 20..22
    for k in range(30):
        surf, ctx = _new_surface()
        u = k / 30.0
        br = _breath(u)
        sway = math.sin(u * math.tau)
        blobs, trails = RV2._hover_orbits(u, ax=75.0, ay=75.0 - br * 0.6, rev=RV2.IDLE_REV,
                                          rx_scale=1.18, ry_scale=1.04, max_size=2)
        _draw_shadow(ctx, 75.0, 116.0, 25.0, 0.28)
        RV2._render_orbit_layer(ctx, blobs, trails, front=False, alpha=0.82)
        eye = "blink" if k == 21 else ("blink_half" if k in (20, 22) else "neutral")
        _draw_chibi(ctx, surf, "sit", cx=75.0, foot_y=115.5, target_h=94.0,
                    sx_scale=1.0 + br * 0.014, sy_scale=1.0 + br * 0.016,
                    rot_deg=sway * 0.4, skew_x=sway * 0.005, eye_mode=eye)
        RV2._render_orbit_layer(ctx, blobs, trails, front=True, alpha=0.90)
        frames.append(surf)

    return frames, [35, 64]


def render_thinking():
    """44f [7, 36]: 5 Gemini electrons morph smoothly into fluttering butterflies around Chibi."""
    frames = []
    for f in range(44):
        surf, ctx = _new_surface()
        ph, pu = RV2._phase_3(f, 7, 30, 7)
        morph = pu if ph in ("in", "out") else 1.0
        u = ((f - 7) / 30.0) if ph == "loop" else (f / 44.0)
        br = _breath(f / 36.0)
        tilt = -1.0 * math.sin((f / 36.0) * math.tau)
        blobs, trails = RV2._hover_orbits(u, ax=75.0, ay=69.0 - br * 0.7, rev=RV2.THINK_REV,
                                          rx_scale=1.18, ry_scale=1.10, max_size=3,
                                          trail_steps=((0.035, 3), (0.07, 2)))
        _draw_shadow(ctx, 75.0, 115.5, 24.0, 0.26)
        _render_butterfly_orbits(ctx, blobs, trails, front=False, u=f / 30.0, morph=morph, alpha=0.92)
        _draw_chibi(ctx, surf, "thinking", cx=75.0, foot_y=115.5, target_h=95.0,
                    sy_scale=1.0 + br * 0.015, rot_deg=tilt, skew_x=tilt * 0.005)
        _render_butterfly_orbits(ctx, blobs, trails, front=True, u=f / 30.0, morph=morph, alpha=0.98)
        _draw_thought_dots(ctx, 111.0, 29.0, f / 36.0, alpha=0.90 * (0.4 + 0.6 * morph))
        _draw_question_mark(ctx, 121.0, 18.0 - br * 1.8, rgb=_e255(0), alpha=0.92 * morph)
        frames.append(surf)
    return frames, [7, 36]


def _extract_typing_laptop() -> dict:
    """Segment the silver pixel laptop out of the extracted 'typing' sprite for pull-out/put-away."""
    cached = _SPRITE_CACHE.get("_typing_laptop")
    if cached is not None:
        return cached

    sp = _extract_sprite("typing")
    w, h = sp["w"], sp["h"]
    buf = bytearray(sp["surf"].get_data())
    stride = sp["surf"].get_stride()

    raw = [(0, 0, 0, 0)] * (w * h)
    for y in range(h):
        row_off = y * stride
        dst_off = y * w
        for x in range(w):
            raw[dst_off + x] = _read_px(buf, row_off + x * 4)

    def _is_laptop_cand(x: int, y: int) -> bool:
        if x < 150 or y < 224:
            return False
        r, g, b, a = raw[y * w + x]
        if a <= 32:
            return False
        if x < 215 and max(r, g, b) < 42:
            return False
        is_warm_hoodie = (r > b + 22 and r > 125 and g > 105)
        is_blue_skin = (b > r + 45 and g > 100)
        return not is_warm_hoodie and not is_blue_skin

    mask = bytearray(w * h)
    q: deque[tuple[int, int]] = deque()

    # Seed flood-fill on laptop lid/deck around (300, 250)
    seed = None
    for sy in range(235, min(h, 285)):
        for sx in range(275, min(w, 325)):
            if _is_laptop_cand(sx, sy):
                seed = (sx, sy)
                break
        if seed is not None:
            break
    if seed is not None:
        mask[seed[1] * w + seed[0]] = 1
        q.append(seed)
    while q:
        cx, cy = q.popleft()
        for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1),
                       (cx + 1, cy + 1), (cx - 1, cy - 1), (cx + 1, cy - 1), (cx - 1, cy + 1)):
            if 0 <= nx < w and 0 <= ny < h:
                nidx = ny * w + nx
                if not mask[nidx] and _is_laptop_cand(nx, ny):
                    mask[nidx] = 1
                    q.append((nx, ny))

    # Also include all opaque pixels on the right lid/corner (e.g. cyan lid logo dot)
    for y in range(216, h):
        row = y * w
        for x in range(215, w):
            if raw[row + x][3] > 32 and not (raw[row + x][0] > raw[row + x][2] + 22 and raw[row + x][0] > 125 and raw[row + x][1] > 105):
                mask[row + x] = 1

    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    out_buf = out.get_data()
    out_st = out.get_stride()
    lap_ys = []
    lap_pts = []
    for y in range(h):
        ro = y * out_st
        so = y * w
        for x in range(w):
            if mask[so + x]:
                r, g, b, a = raw[so + x]
                _write_px(out_buf, ro + x * 4, r, g, b, a)
                lap_ys.append(y)
                lap_pts.append((x, y))
    out.mark_dirty()

    max_ly = max(lap_ys) if lap_ys else h - 1
    min_ly = min(lap_ys) if lap_ys else int(h * 0.65)
    bot_cut = max_ly - max(4, int((max_ly - min_ly) * 0.15))
    bot_xs = [x for x, y in lap_pts if y >= bot_cut]
    hinge_x = (sum(bot_xs) / len(bot_xs)) if bot_xs else (w * 0.72)
    hinge_y = float(max_ly)

    res = {
        "surf": out,
        "w": w,
        "h": h,
        "face_cx": sp["face_cx"],
        "hinge_x": hinge_x,
        "hinge_y": hinge_y,
    }
    _SPRITE_CACHE["_typing_laptop"] = res
    return res


def _draw_typing_laptop(ctx: cairo.Context, *, cx: float = 75.0, foot_y: float = 116.0,
                        target_h: float = 92.0, dx: float = 0.0, dy: float = 0.0,
                        sx_lap: float = 1.0, sy_lap: float = 1.0,
                        rot_deg: float = 0.0, alpha: float = 1.0) -> None:
    """Draw the extracted typing laptop pivoted at its bottom-center hinge point."""
    if alpha <= 0.01:
        return
    lap = _extract_typing_laptop()
    base_scale = target_h / lap["h"]
    ox = cx - lap["face_cx"] * base_scale
    oy = foot_y - target_h
    hx = ox + lap["hinge_x"] * base_scale
    hy = oy + lap["hinge_y"] * base_scale

    ctx.save()
    ctx.translate(hx + dx, hy + dy)
    if rot_deg:
        ctx.rotate(math.radians(rot_deg))
    ctx.scale(base_scale * sx_lap, base_scale * sy_lap)
    ctx.translate(-lap["hinge_x"], -lap["hinge_y"])
    ctx.set_source_surface(lap["surf"], 0.0, 0.0)
    ctx.get_source().set_filter(cairo.FILTER_BILINEAR)
    if alpha < 1.0:
        ctx.paint_with_alpha(alpha)
    else:
        ctx.paint()
    ctx.restore()


def _typing_electron_orbits(w: float, mode: str, f: int, n_in: int, n_loop: int,
                            k_loop: float, wy: float = 9.0):
    """Fly 5 Gemini electrons along smooth outward arcs between sit orbits (w=0) and wave bar (w=1)."""
    ax, ay = 75.0, 75.0
    tw = 2.0 * k_loop if mode == "loop" else 0.0
    blobs, trails = [], []
    for idx, sp in enumerate(R.ELECTRONS):
        if mode == "in":
            u_in = f / max(1.0, float(n_in - 1))
            th = sp.phi0 + RV2.IDLE_REV[idx] * math.tau * (0.15 * u_in)
        elif mode == "loop":
            th = sp.phi0
        else:
            u_out = (f - (n_in + n_loop)) / 12.0
            th = sp.phi0 - RV2.IDLE_REV[idx] * math.tau * (0.15 * (1.0 - u_out))
        ox_o, oy_o, ez = RV2._orbit_point(ax, ay, sp.rx * 0.5 * 1.18, sp.ry * 0.5 * 1.04, sp.tilt_deg, th)
        dx, dy = ox_o - ax, oy_o - ay
        dist = math.hypot(dx, dy) + 1e-6
        side_dir = -1.0 if RV2.ATOM_WAVE_X[idx] < ax else +1.0
        lower_boost = RV2._clamp((oy_o - (ay - 10.0)) / 25.0)
        push = (11.0 + 15.0 * lower_boost) * w * (1.0 - w)
        px = max(5.0, min(FW - 5.0, RV2._lerp(ox_o, RV2.ATOM_WAVE_X[idx], w) + side_dir * push))
        py = max(5.0, min(FH - 5.0, RV2._lerp(oy_o, wy, w) + (dy / dist) * 6.0 * w * (1.0 - w)))
        pz = RV2._lerp(ez, 1.0, w)

        bar_score = R.loading_bar_score(idx, tw) if mode == "loop" else 0.0
        if w <= 0.01:
            sidx = RV2._size_from_ez(ez)
        elif w >= 0.99:
            sidx = R.size_index_from_score(bar_score)
        else:
            orbit_score = RV2._clamp((ez + 0.65) / 1.40)
            sidx = R.size_index_from_score(RV2._lerp(orbit_score, bar_score, w))
        blobs.append((pz, idx, px, py, sidx))
        if w < 0.35:
            tlag = th - RV2.IDLE_REV[idx] * math.tau * 0.04
            tx, ty, tez = RV2._orbit_point(ax, ay, sp.rx * 0.5 * 1.18, sp.ry * 0.5 * 1.04, sp.tilt_deg, tlag)
            trails.append((tez, idx, max(4.0, min(FW - 4.0, tx)), max(4.0, min(FH - 4.0, ty)), 2))
    blobs.sort(key=lambda it: it[0])
    trails.sort(key=lambda it: it[0])
    return blobs, trails


def render_typing():
    """50f [7, 36]: physically pulls out/opens laptop (0..6), types (7..36), closes/puts away (37..49)."""
    frames = []

    # 1) Intro (0..6): sit -> glance & pull out folded laptop opening -> hands land on keyboard + wave bar
    intro_lap = [
        None,
        (11.0, -2.5, 0.72, 0.28, -16.0, 0.80),
        (6.5,  -1.5, 0.86, 0.56, -10.0, 1.00),
        (2.5,  -0.5, 0.96, 0.84,  -4.0, 1.00),
        None,
        None,
        None,
    ]
    for f in range(7):
        w = _smooth(f / 6.0)
        surf, ctx = _new_surface()
        blobs, trails = _typing_electron_orbits(w, "in", f, 7, 30, 0.0, wy=9.0)
        _draw_shadow(ctx, 75.0, 116.0, RV2._lerp(25.0, 29.0, w), 0.27)
        RV2._render_orbit_layer(ctx, blobs, trails, front=False, alpha=0.88, glow=True)
        if f <= 3:
            sit_rot = (0.0, -0.8, -1.5, -1.5)[f]
            sit_sy = (1.0, 0.985, 0.96, 0.95)[f]
            edx, edy = ((0.0, 0.0), (1.2, 1.1), (1.5, 1.4), (1.5, 1.5))[f]
            _draw_chibi(ctx, surf, "sit", cx=75.0, foot_y=115.5, target_h=94.0,
                        sy_scale=sit_sy, rot_deg=sit_rot, skew_x=sit_rot * 0.008,
                        eye_mode="neutral", eye_dx=edx, eye_dy=edy)
            lap_p = intro_lap[f]
            if lap_p is not None:
                dx, dy, sxl, syl, rdeg, la = lap_p
                _draw_typing_laptop(ctx, cx=75.0, foot_y=116.0, target_h=92.0,
                                    dx=dx, dy=dy, sx_lap=sxl, sy_lap=syl, rot_deg=rdeg, alpha=la)
        else:
            t_fy, t_sy, t_rot = {
                4: (115.4, 1.020, -0.3),
                5: (116.2, 0.985, -0.7),
                6: (116.0, 1.000, -0.6),
            }[f]
            _draw_chibi(ctx, surf, "typing", cx=75.0, foot_y=t_fy, target_h=92.0,
                        sy_scale=t_sy, rot_deg=t_rot, skew_x=t_rot * 0.004)
        RV2._render_orbit_layer(ctx, blobs, trails, front=True, alpha=0.95, glow=True)
        frames.append(surf)

    # 2) Sustained loop (7..36, 30 frames): bursty human typing cadence + brief read-screen pause
    for k in range(30):
        surf, ctx = _new_surface()
        u = k / 30.0
        if k <= 11:
            keystroke = abs(math.sin((k / 12.0) * math.tau * 2.0))
            lean = -0.6
            sy = 1.0 - 0.015 * keystroke
            dy = -0.5 * keystroke
        elif k <= 17:
            p = (k - 12) / 5.0
            read = math.sin(p * math.pi)
            lean = RV2._lerp(-0.6, 0.7, read)
            sy = 1.0 + 0.013 * read
            dy = 0.0
        elif k <= 27:
            keystroke = abs(math.sin(((k - 18) / 10.0) * math.tau * 2.0))
            lean = -0.6
            sy = 1.0 - 0.015 * keystroke
            dy = -0.5 * keystroke
        else:
            lean = -0.6
            sy = 1.0
            dy = 0.0
        blobs, trails = _typing_electron_orbits(1.0, "loop", 7 + k, 7, 30, u, wy=9.0)
        _draw_shadow(ctx, 75.0, 116.5, 29.0, 0.28)
        _draw_chibi(ctx, surf, "typing", cx=75.0, foot_y=116.0 + dy, target_h=92.0,
                    sy_scale=sy, rot_deg=lean, skew_x=lean * 0.004)
        RV2._render_orbit_layer(ctx, blobs, trails, front=True, alpha=0.95, glow=True)
        frames.append(surf)

    # 3) Outro (37..49, 13 frames): finish typing -> close & put laptop away -> settle in sit + orbits
    outro_lap = {
        3: (2.0,  -0.5, 0.96, 0.82,  -4.0, 1.00),
        4: (5.5,  -1.2, 0.90, 0.58, -10.0, 1.00),
        5: (9.0,  -2.0, 0.82, 0.38, -14.0, 0.88),
        6: (12.0, -2.5, 0.74, 0.24, -18.0, 0.52),
        7: (14.0, -3.0, 0.68, 0.16, -21.0, 0.18),
    }
    for fo in range(13):
        f = 37 + fo
        w_elec = 1.0 - _smooth(fo / 12.0)
        surf, ctx = _new_surface()
        blobs, trails = _typing_electron_orbits(w_elec, "out", f, 7, 30, 0.0, wy=9.0)
        sh_rx = 29.0 if fo <= 2 else (RV2._lerp(29.0, 25.0, (fo - 2) / 5.0) if fo <= 7 else 25.0)
        _draw_shadow(ctx, 75.0, 116.0, sh_rx, 0.27)
        RV2._render_orbit_layer(ctx, blobs, trails, front=False, alpha=0.88, glow=True)
        if fo <= 2:
            p_lean = _smooth(fo / 2.0)
            rot_t = RV2._lerp(-0.6, 0.8, p_lean)
            sy_t = RV2._lerp(1.0, 1.015, p_lean)
            _draw_chibi(ctx, surf, "typing", cx=75.0, foot_y=116.0, target_h=92.0,
                        sy_scale=sy_t, rot_deg=rot_t, skew_x=rot_t * 0.004)
        else:
            s_rots = (-1.4, -0.8, -0.3, 0.0, 0.0)
            s_rot = s_rots[fo - 3] if fo <= 7 else 0.0
            s_sy = (0.96, 0.98, 1.01, 1.015, 1.0)[fo - 3] if fo <= 7 else 1.0
            blink = "blink" if fo == 6 else ("blink_half" if fo in (5, 7) else "neutral")
            edx, edy = ((1.4, 1.3), (1.0, 0.9), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0))[fo - 3] if fo <= 7 else (0.0, 0.0)
            _draw_chibi(ctx, surf, "sit", cx=75.0, foot_y=115.5, target_h=94.0,
                        sy_scale=s_sy, rot_deg=s_rot, skew_x=s_rot * 0.008,
                        eye_mode=blink, eye_dx=edx, eye_dy=edy)
            lap_p = outro_lap.get(fo)
            if lap_p is not None:
                dx, dy, sxl, syl, rdeg, la = lap_p
                _draw_typing_laptop(ctx, cx=75.0, foot_y=116.0, target_h=92.0,
                                    dx=dx, dy=dy, sx_lap=sxl, sy_lap=syl, rot_deg=rdeg, alpha=la)
        RV2._render_orbit_layer(ctx, blobs, trails, front=True, alpha=0.95, glow=True)
        frames.append(surf)

    return frames, [7, 36]


def render_working():
    """40f [5, 34]: 3-part engaged stance (5f intro, 30f steady loop, 5f outro; 40/40 neutral eyes)."""
    n_in, n_loop, n_out = 5, 30, 5
    frames = []
    for f in range(n_in + n_loop + n_out):
        surf, ctx = _new_surface()
        ph, pu = RV2._phase_3(f, n_in, n_loop, n_out)
        amp = pu if ph in ("in", "out") else 1.0
        u = pu if ph == "loop" else (f / float(n_in + n_loop + n_out))
        br = _breath(u)
        nod = (0.5 - 0.5 * math.cos(u * math.tau * 2.0)) * amp
        tilt = 0.4 * math.sin(u * math.tau) * amp
        blobs, trails = RV2._hover_orbits(u, ax=75.0, ay=70.0 - br * 0.8, rev=RV2.IDLE_REV,
                                          rx_scale=1.18, ry_scale=1.10, max_size=3,
                                          trail_steps=((0.04, 2), (0.08, 1)))
        _draw_shadow(ctx, 75.0, 115.5, 22.0, 0.26)
        RV2._render_orbit_layer(ctx, blobs, trails, front=False, alpha=0.86)
        _draw_chibi(ctx, surf, "stand", cx=75.0, foot_y=115.0, target_h=96.0,
                    sx_scale=1.0 + nod * 0.010, sy_scale=1.0 + br * 0.014 - nod * 0.015,
                    rot_deg=tilt, skew_x=0.004 * amp, eye_mode="neutral")
        RV2._render_orbit_layer(ctx, blobs, trails, front=True, alpha=0.95)
        if amp > 0.05:
            sp_a = (0.45 + 0.55 * abs(math.sin(u * math.tau))) * amp
            RV2._draw_plus_sparkle(ctx, 121.0, 25.0 - br * 2.0, _e255(2), alpha=sp_a)
            RV2._draw_plus_sparkle(ctx, 29.0, 32.0 + br * 1.5, _e255(0), alpha=min(1.0, (1.1 - sp_a * 0.5) * amp))
        frames.append(surf)
    return frames, [n_in, n_in + n_loop - 1]


def render_exploring():
    """40f [5, 34]: 3-part gaze scan (5f intro center->left, 30f scan loop w/ blink, 5f outro->center)."""
    n_in, n_loop, n_out = 5, 30, 5
    frames = []
    for f in range(n_in + n_loop + n_out):
        surf, ctx = _new_surface()
        ph, pu = RV2._phase_3(f, n_in, n_loop, n_out)
        amp = pu if ph in ("in", "out") else 1.0
        eye = "neutral"
        if ph == "in":
            gaze = -pu
        elif ph == "out":
            gaze = -pu  # loop ends back at -1 (left), so outro smoothly returns -1 -> 0
        else:
            k = f - n_in  # 0..29
            if k < 8:
                gaze = -1.0
            elif k < 14:
                gaze = -1.0 + 2.0 * _smooth((k - 8) / 6.0)
                if k == 11:
                    eye = "blink"
                elif k in (10, 12):
                    eye = "blink_half"
            elif k < 23:
                gaze = 1.0
            else:
                gaze = 1.0 - 2.0 * _smooth((k - 23) / 7.0)
        u = pu if ph == "loop" else (f / 40.0)
        br = _breath(u)
        blobs, trails = RV2._hover_orbits(u, ax=75.0, ay=70.0, rev=RV2.IDLE_REV,
                                          rx_scale=1.18, ry_scale=1.10, max_size=2)
        _draw_shadow(ctx, 75.0 + gaze * 0.4, 115.5, 22.0, 0.26)
        RV2._render_orbit_layer(ctx, blobs, trails, front=False, alpha=0.85)
        _draw_chibi(ctx, surf, "stand", cx=75.0 + gaze * 0.4, foot_y=115.0, target_h=96.0,
                    sy_scale=1.0 + br * 0.012, rot_deg=gaze * 0.9, skew_x=gaze * 0.008,
                    eye_mode=eye, eye_dx=gaze * 1.7, eye_dy=-0.2 * abs(gaze))
        RV2._render_orbit_layer(ctx, blobs, trails, front=True, alpha=0.92)
        if amp > 0.05:
            sp_l = (0.35 + 0.65 * max(0.0, -gaze)) * amp
            sp_r = (0.35 + 0.65 * max(0.0, gaze)) * amp
            RV2._draw_plus_sparkle(ctx, 27.0, 27.0, _e255(2), alpha=sp_l)
            RV2._draw_plus_sparkle(ctx, 123.0, 31.0, _e255(0), alpha=sp_r)
        frames.append(surf)
    return frames, [n_in, n_in + n_loop - 1]


def render_running():
    """40f [5, 34]: 3-part terminal run (5f Gemini->emerald ramp, 30f bounce loop, 5f emerald->Gemini)."""
    n_in, n_loop, n_out = 5, 30, 5
    term_palette = (
        RV2._rgb(52, 211, 153),
        RV2._rgb(16, 185, 129),
        RV2._rgb(110, 231, 183),
        RV2._rgb(5, 150, 105),
        RV2._rgb(167, 243, 208),
    )
    frames = []
    for f in range(n_in + n_loop + n_out):
        surf, ctx = _new_surface()
        ph, pu = RV2._phase_3(f, n_in, n_loop, n_out)
        amp = pu if ph in ("in", "out") else 1.0
        u = pu if ph == "loop" else (f / 40.0)
        dy_raw, sx_raw, sy_raw = _hop_arc((u * 2.0) % 1.0)
        dy = dy_raw * 0.65 * amp
        sx = RV2._lerp(1.0, sx_raw, amp)
        sy = RV2._lerp(1.0, sy_raw, amp)
        lean = math.sin(u * math.tau) * 0.8 * amp
        pal = tuple(
            (
                RV2._lerp(R.ELECTRONS[i].color[0], term_palette[i][0], amp),
                RV2._lerp(R.ELECTRONS[i].color[1], term_palette[i][1], amp),
                RV2._lerp(R.ELECTRONS[i].color[2], term_palette[i][2], amp),
            )
            for i in range(5)
        )
        blobs, trails = RV2._hover_orbits(u * 1.5, ax=75.0, ay=69.0 + dy, rev=RV2.IDLE_REV,
                                          rx_scale=1.20, ry_scale=1.12, max_size=3,
                                          trail_steps=((0.04, 3), (0.08, 2)))
        _draw_shadow(ctx, 75.0, 115.5, 21.0 + dy * 0.6, 0.25)
        RV2._render_orbit_layer(ctx, blobs, trails, front=False, palette=pal, alpha=0.90, glow=True)
        _draw_chibi(ctx, surf, "stand", cx=75.0, foot_y=115.0 + dy, target_h=96.0,
                    sx_scale=sx, sy_scale=sy, rot_deg=lean, skew_x=0.004 * amp, eye_mode="neutral")
        RV2._render_orbit_layer(ctx, blobs, trails, front=True, palette=pal, alpha=0.95, glow=True)
        frames.append(surf)
    return frames, [n_in, n_in + n_loop - 1]


def render_delegating():
    """40f [5, 34]: 3-part handoff (5f intro, 30f speech-bubble handoff loop, 5f outro back to neutral)."""
    n_in, n_loop, n_out = 5, 30, 5
    frames = []
    for f in range(n_in + n_loop + n_out):
        surf, ctx = _new_surface()
        ph, pu = RV2._phase_3(f, n_in, n_loop, n_out)
        amp = pu if ph in ("in", "out") else 1.0
        u = pu if ph == "loop" else (f / 40.0)
        br = _breath(u)
        nod = math.sin(u * math.tau * 2.0) * 0.9 * amp
        blobs, trails = RV2._hover_orbits(u, ax=75.0, ay=69.0, rev=RV2.IDLE_REV,
                                          rx_scale=1.18, ry_scale=1.08, max_size=2)
        _draw_shadow(ctx, RV2._lerp(75.0, 74.8, amp), 115.5, 22.0, 0.26)
        RV2._render_orbit_layer(ctx, blobs, trails, front=False, alpha=0.85)
        _draw_chibi(ctx, surf, "stand", cx=RV2._lerp(75.0, 74.8, amp), foot_y=115.0, target_h=96.0,
                    sy_scale=1.0 + br * 0.012 - max(0.0, nod) * 0.010,
                    rot_deg=(1.0 + nod * 0.3) * amp, skew_x=0.006 * amp,
                    eye_mode="neutral", eye_dx=1.35 * amp, eye_dy=-0.9 * amp)
        RV2._render_orbit_layer(ctx, blobs, trails, front=True, alpha=0.92)
        if amp > 0.05:
            by = RV2._lerp(31.0 if ph == "in" else 19.0, 25.0 - math.sin(u * math.tau) * 1.6, amp)
            _draw_speech_bubble(ctx, 121.0, by, u=u, alpha=0.95 * amp)
        frames.append(surf)
    return frames, [n_in, n_in + n_loop - 1]


def render_asking():
    """36f [4, 29]: 3-part inquisitive ask (4f intro, 26f loop, 6f outro; matches atom/v2 timing)."""
    n_in, n_loop, n_out = 4, 26, 6
    frames = []
    for f in range(n_in + n_loop + n_out):
        surf, ctx = _new_surface()
        ph, pu = RV2._phase_3(f, n_in, n_loop, n_out)
        amp = pu if ph in ("in", "out") else 1.0
        u = pu if ph == "loop" else (f / 36.0)
        br = _breath(u)
        curious = (1.1 + 0.4 * math.sin(u * math.tau)) * amp
        blobs, trails = RV2._hover_orbits(u, ax=75.0, ay=70.0, rev=RV2.IDLE_REV,
                                          rx_scale=1.18, ry_scale=1.08, max_size=2)
        _draw_shadow(ctx, 75.0, 115.5, 24.0, 0.26)
        RV2._render_orbit_layer(ctx, blobs, trails, front=False, alpha=0.82)
        _draw_chibi(ctx, surf, "thinking", cx=75.0, foot_y=115.5, target_h=95.0,
                    sy_scale=1.0 + br * 0.014, rot_deg=curious, skew_x=0.006 * amp)
        RV2._render_orbit_layer(ctx, blobs, trails, front=True, alpha=0.90)
        if amp > 0.05:
            qy_base = RV2._lerp(24.0 if ph == "in" else 14.0, 19.0 - _hop_arc((u * 2.0) % 1.0)[0] * -0.45, amp)
            _draw_question_mark(ctx, 118.0, qy_base, rgb=_e255(2), alpha=0.98 * amp)
        frames.append(surf)
    return frames, [n_in, n_in + n_loop - 1]


def render_listening():
    """30f [0, 29]: warm prompt-attentive stance, downward prompt gaze, calm electrons & ear-perk sparkles."""
    frames = []
    for f in range(30):
        surf, ctx = _new_surface()
        u = f / 30.0
        br = _breath(u)
        # Attentive slight toe-perk bounce + soft downward gaze tracking the user's typing
        perk = -0.6 * br
        tilt = 0.5 + 0.3 * math.sin(u * math.tau)
        eye = "blink" if f == 23 else ("blink_half" if f in (22, 24) else "neutral")
        track_x = math.sin(u * math.tau) * 0.9
        blobs, trails = RV2._hover_orbits(u * 0.7, ax=75.0, ay=71.0 + perk * 0.5, rev=RV2.IDLE_REV,
                                          rx_scale=1.16, ry_scale=1.06, max_size=2)
        _draw_shadow(ctx, 75.0, 115.5, 22.0, 0.25)
        RV2._render_orbit_layer(ctx, blobs, trails, front=False, alpha=0.76)
        _draw_chibi(ctx, surf, "stand", cx=75.0, foot_y=115.0 + perk, target_h=96.0,
                    sy_scale=1.0 + br * 0.014, rot_deg=tilt, skew_x=0.005,
                    eye_mode=eye, eye_dx=track_x, eye_dy=1.3)
        RV2._render_orbit_layer(ctx, blobs, trails, front=True, alpha=0.84)
        # Soft pastel sparkles beside pink cat ears + live chat bubble
        ear_a = 0.35 + 0.65 * abs(math.sin(u * math.tau * 1.5))
        RV2._draw_plus_sparkle(ctx, 41.0, 27.0 - br * 1.0, (250, 165, 210), alpha=ear_a * 0.85)
        RV2._draw_plus_sparkle(ctx, 107.0, 30.0 - br * 1.0, _e255(0), alpha=(1.1 - ear_a * 0.6) * 0.80)
        _draw_speech_bubble(ctx, 118.0, 24.0 - br * 1.5, u=u * 1.5, alpha=0.92)
        frames.append(surf)
    return frames, [0, 29]


def render_watching():
    """36f [0, 35]: sitting Chibi tracking butterflies cleanly with eased gaze & minimal sway."""
    frames = []
    for f in range(36):
        surf, ctx = _new_surface()
        u = f / 36.0
        br = _breath(u)
        gaze = -math.cos(u * math.tau)
        eye = "blink" if f == 18 else ("blink_half" if f in (17, 19) else "neutral")
        _draw_shadow(ctx, 75.0, 116.0, 25.0, 0.28)
        _draw_chibi(ctx, surf, "sit", cx=75.0, foot_y=115.5, target_h=94.0,
                    sy_scale=1.0 + br * 0.014, rot_deg=gaze * 0.7, skew_x=gaze * 0.005,
                    eye_mode=eye, eye_dx=gaze * 1.5, eye_dy=-0.7)
        bx1 = 27.0 + math.sin(u * math.tau) * 5.0
        by1 = 24.0 + math.cos(u * math.tau * 2.0) * 3.5
        bx2 = 123.0 + math.cos(u * math.tau) * 4.5
        by2 = 30.0 + math.sin(u * math.tau * 2.0) * 4.0
        _draw_butterfly(ctx, bx1, by1, math.sin(u * math.tau * 6.0), _efloat(0))
        _draw_butterfly(ctx, bx2, by2, math.cos(u * math.tau * 6.0), _efloat(2))
        frames.append(surf)
    return frames, [0, 35]


def render_done():
    """42f [6, 35]: chill_sit with 5 Gemini electrons morphing into glowing orbiting pixel hearts."""
    frames = []
    for f in range(42):
        surf, ctx = _new_surface()
        ph, pu = RV2._phase_3(f, 6, 30, 6)
        morph = pu if ph in ("in", "out") else 1.0
        u = ((f - 6) / 30.0) if ph == "loop" else (f / 42.0)
        br = _breath(f / 30.0)
        sway = math.sin((f / 30.0) * math.tau)
        pop_sx = RV2._lerp(1.05, 1.0, pu) if ph == "in" else 1.0
        pop_sy = RV2._lerp(0.93, 1.0 + 0.025 * math.sin(pu * math.pi), pu) if ph == "in" else 1.0 + br * 0.015
        blobs, trails = RV2._hover_orbits(u, ax=75.0, ay=70.0 - br * 0.6, rev=RV2.IDLE_REV,
                                          rx_scale=1.18, ry_scale=1.08, max_size=2,
                                          trail_steps=((0.04, 2),))
        _draw_shadow(ctx, 75.0, 116.5, 26.0, 0.28)
        _render_heart_orbits(ctx, blobs, trails, front=False, morph=morph, alpha=0.90)
        _draw_chibi(ctx, surf, "chill_sit", cx=75.0, foot_y=116.0, target_h=100.0,
                    sx_scale=pop_sx, sy_scale=pop_sy, rot_deg=sway * 0.8, skew_x=sway * 0.006)
        _render_heart_orbits(ctx, blobs, trails, front=True, morph=morph, alpha=0.96)
        RV2._draw_plus_sparkle(ctx, 123.0, 23.0 + math.sin(u * math.tau) * 1.8, _e255(3), alpha=0.90 * morph)
        frames.append(surf)
    return frames, [6, 35]


def render_happy():
    """42f [6, 35]: aww-heart joyful squash-and-stretch double hop + mild wiggle & rising hearts."""
    frames = []
    for f in range(42):
        surf, ctx = _new_surface()
        u = f / 30.0
        dy, sx, sy = _hop_arc((u * 2.0) % 1.0)
        wiggle = math.sin(u * math.tau * 2.0) * 1.1
        _draw_shadow(ctx, 75.0, 116.0, 24.0 + dy * 0.7, 0.28)
        _draw_chibi(ctx, surf, "aww", cx=75.0, foot_y=115.5 + dy, target_h=95.0,
                    sx_scale=sx, sy_scale=sy, rot_deg=wiggle, skew_x=0.0)
        for i in range(2):
            hp = (u + i * 0.5) % 1.0
            hx = 27.0 if i == 0 else 123.0
            hy = 38.0 - hp * 22.0
            ha = math.sin(hp * math.pi)
            _draw_heart(ctx, hx + math.sin(hp * math.tau) * 2.2, hy,
                        scale=0.85, rgb=(250, 115, 174), alpha=ha * 0.95)
        frames.append(surf)
    return frames, [6, 35]


def render_dance():
    """40f [5, 34] at 65ms: controlled hip-sway groove, beat squash-and-stretch, sparkles & music notes."""
    frames = []
    for f in range(40):
        surf, ctx = _new_surface()
        u = f / 30.0
        sway = math.sin(u * math.tau)
        dy, sx, sy = _hop_arc((u * 2.0) % 1.0)
        dy *= 0.85
        rot = sway * 2.2
        skew = sway * 0.020
        blobs, trails = RV2._hover_orbits(u * 2.0, ax=75.0 + sway * 1.0, ay=69.0 + dy, rev=RV2.IDLE_REV,
                                          rx_scale=1.22, ry_scale=1.12, max_size=3,
                                          trail_steps=((0.04, 2),))
        _draw_shadow(ctx, 75.0 + sway * 0.9, 115.5, 24.0 + dy * 0.6, 0.26)
        RV2._render_orbit_layer(ctx, blobs, trails, front=False, alpha=0.88, glow=True)
        _draw_chibi(ctx, surf, "dance", cx=75.0 + sway * 1.1, foot_y=115.0 + dy, target_h=96.0,
                    sx_scale=sx, sy_scale=sy, rot_deg=rot, skew_x=skew)
        RV2._render_orbit_layer(ctx, blobs, trails, front=True, alpha=0.95, glow=True)
        RV2._draw_plus_sparkle(ctx, 25.0, 22.0 - dy * 0.8, _e255(2), alpha=0.95)
        RV2._draw_plus_sparkle(ctx, 125.0, 25.0 + dy * 0.6, _e255(0), alpha=0.95)
        np1 = (u + 0.15) % 1.0
        _draw_music_note(ctx, 24.0 + math.sin(np1 * math.tau) * 1.8, 48.0 - np1 * 14.0,
                         _e255(3), alpha=math.sin(np1 * math.pi) * 0.92)
        np2 = (u + 0.65) % 1.0
        _draw_music_note(ctx, 126.0 - math.sin(np2 * math.tau) * 1.8, 46.0 - np2 * 14.0,
                         _e255(0), alpha=math.sin(np2 * math.pi) * 0.92)
        frames.append(surf)
    return frames, [5, 34], 65


def render_sad():
    """42f [6, 35]: heavy slouch intro + periodic human sigh & subtle sniffle + teardrops."""
    frames = []
    for f in range(42):
        surf, ctx = _new_surface()
        ph, pu = RV2._phase_3(f, 6, 30, 6)
        amt = 0.65 * (pu if ph == "in" else (1.0 - pu if ph == "out" else 1.0))
        u = f / 30.0
        sigh = _breath(u)
        sniffle = 0.6 * math.sin(f * 2.6) if (f % 15 in (11, 12)) else 0.0
        slouch_sy = (RV2._lerp(1.0, 0.97, pu) if ph == "in" else 0.97) + sigh * 0.015
        droop = -0.9 * (pu if ph == "in" else 1.0) + sigh * 0.4
        _draw_shadow(ctx, 75.0, 116.5, 25.0, 0.25)
        _draw_chibi(ctx, surf, "sad_sit", cx=75.0 + sniffle, foot_y=116.0, target_h=95.0,
                    sx_scale=1.02, sy_scale=slouch_sy, rot_deg=droop, skew_x=-0.004)
        for side in (-1.0, 1.0):
            tp = (u + (0.0 if side < 0 else 0.5)) % 1.0
            tx = 75.0 + side * 12.5
            ty = 72.0 + tp * 14.0
            _draw_sweat_drop(ctx, tx, ty, alpha=0.88 * math.sin(tp * math.pi))
        _tint_surface(surf, "sad", amt)
        frames.append(surf)
    return frames, [6, 35]


def render_angry():
    """42f [6, 35]: indignant puff-up intro + huffing breath + tight frustration tremors."""
    frames = []
    for f in range(42):
        surf, ctx = _new_surface()
        ph, pu = RV2._phase_3(f, 6, 30, 6)
        amp = pu if ph == "in" else (1.0 - pu if ph == "out" else 1.0)
        u = f / 30.0
        huff = abs(math.sin(u * math.tau * 2.0))
        burst = math.sin(f * 3.1) * (1.1 if (f % 12) < 5 else 0.2) * amp
        puff_sy = (RV2._lerp(0.95, 1.03, pu) if ph == "in" else 1.0 + huff * 0.025)
        puff_sx = 1.0 + huff * 0.022
        _draw_shadow(ctx, 75.0, 116.0, 25.0, 0.28)
        _draw_chibi(ctx, surf, "angry", cx=75.0 + burst, foot_y=115.5, target_h=96.0,
                    sx_scale=puff_sx, sy_scale=puff_sy, rot_deg=burst * 0.4)
        if amp > 0.2:
            _draw_exclamation(ctx, 122.0, 22.0 - huff * 2.8, rgb=(252, 92, 46), alpha=0.95 * amp)
            _draw_exclamation(ctx, 28.0, 25.0 + huff * 2.0, rgb=(252, 144, 56), alpha=0.82 * amp)
        frames.append(surf)
    return frames, [6, 35]


def render_error():
    """42f [6, 35]: startled recoil-flinch intro + mild dazed sway with X X eyes."""
    frames = []
    for f in range(42):
        surf, ctx = _new_surface()
        ph, pu = RV2._phase_3(f, 6, 30, 6)
        amp = pu if ph == "in" else (1.0 - pu if ph == "out" else 1.0)
        u = f / 30.0
        if ph == "in":
            flinch = math.sin(pu * math.pi)
            dx = -1.8 * flinch
            dy = -2.2 * flinch
            rot = -1.8 * flinch
            sx, sy = 1.0 - 0.025 * flinch, 1.0 + 0.035 * flinch
        else:
            sway = math.sin(u * math.tau * 2.0)
            dx = sway * 0.6 * amp
            dy = 0.0
            rot = sway * 1.3 * amp
            sx, sy = 1.0, 1.0
        _draw_shadow(ctx, 75.0 + dx * 0.5, 116.0, 25.0, 0.28)
        _draw_chibi(ctx, surf, "sit", cx=75.0 + dx, foot_y=115.5 + dy, target_h=94.0,
                    sx_scale=sx, sy_scale=sy, rot_deg=rot, eye_mode="error")
        _draw_exclamation(ctx, 122.0, 22.0 - abs(math.sin(u * math.tau * 2.0)) * 2.5,
                          rgb=(246, 72, 72), alpha=0.95)
        _tint_surface(surf, "error", 0.72 * amp)
        frames.append(surf)
    return frames, [6, 35]


def render_canceled():
    """36f [6, 29]: deflated shoulder-drop sigh + mild droop & sliding sweat drop."""
    frames = []
    for f in range(36):
        surf, ctx = _new_surface()
        ph, pu = RV2._phase_3(f, 6, 24, 6)
        amp = pu if ph == "in" else (1.0 - pu if ph == "out" else 1.0)
        u = f / 24.0
        sigh = _breath(u)
        sy = 1.0 - 0.045 * amp + sigh * 0.015
        sx = 1.0 + 0.03 * amp
        tilt = -0.8 * amp + sigh * 0.3
        _draw_shadow(ctx, 75.0, 115.5, 23.0, 0.26)
        _draw_chibi(ctx, surf, "stand", cx=75.0, foot_y=115.0 + 1.0 * amp, target_h=96.0,
                    sx_scale=sx, sy_scale=sy, rot_deg=tilt, skew_x=-0.006 * amp, eye_mode="tired")
        _draw_sweat_drop(ctx, 108.0, 42.0 + ((u * 9.0) % 8.0), alpha=0.92)
        _tint_surface(surf, "canceled", 0.72 * amp)
        frames.append(surf)
    return frames, [6, 29]


def render_tired():
    """42f [6, 35]: steady drowsy nod-off droop -> sudden wake-up head-jerk -> nodding off again."""
    frames = []
    for f in range(42):
        surf, ctx = _new_surface()
        ph, pu = RV2._phase_3(f, 6, 30, 6)
        amp = pu if ph == "in" else (1.0 - pu if ph == "out" else 1.0)
        u = f / 30.0
        cycle = u % 1.0
        if cycle < 0.72:
            droop = _smooth(cycle / 0.72)
        elif cycle < 0.84:
            droop = 1.0 - _smooth((cycle - 0.72) / 0.12) * 0.85
        else:
            droop = 0.15 + 0.15 * _smooth((cycle - 0.84) / 0.16)
        nod_rot = 2.4 * droop * amp
        nod_sy = 1.0 - 0.035 * droop * amp
        eye = "sleep" if (droop > 0.65 and cycle < 0.72) else ("neutral" if 0.76 <= cycle <= 0.85 else "tired")
        _draw_shadow(ctx, 75.0, 116.0, 25.0, 0.26)
        _draw_chibi(ctx, surf, "sit", cx=75.0 + droop * 0.4, foot_y=115.5, target_h=94.0,
                    sx_scale=1.0 + 0.018 * droop * amp, sy_scale=nod_sy,
                    rot_deg=nod_rot, skew_x=0.010 * droop * amp, eye_mode=eye)
        zp = u % 1.0
        _draw_zzz(ctx, 115.0 + zp * 6.0, 34.0 - zp * 14.0, size=1.0, alpha=math.sin(zp * math.pi) * 0.90)
        _tint_surface(surf, "tired", 0.75 * amp)
        frames.append(surf)
    return frames, [6, 35]


def render_closed():
    """42f [6, 35]: peaceful sleeping tilt + deep belly breathing + curved lids + rising Zzz."""
    frames = []
    for f in range(42):
        surf, ctx = _new_surface()
        ph, pu = RV2._phase_3(f, 6, 30, 6)
        amp = pu if ph == "in" else (1.0 - pu if ph == "out" else 1.0)
        u = f / 30.0
        br = _breath(u)
        _draw_shadow(ctx, 75.0, 116.0, 25.0, 0.25)
        _draw_chibi(ctx, surf, "sit", cx=75.0, foot_y=115.5, target_h=94.0,
                    sx_scale=1.0 + br * 0.020, sy_scale=1.0 - 0.022 * amp + br * 0.022,
                    rot_deg=1.5 * amp + br * 0.3, skew_x=0.006 * amp, eye_mode="sleep")
        for i in range(2):
            zp = (u + i * 0.5) % 1.0
            _draw_zzz(ctx, 113.0 + zp * 8.0, 36.0 - zp * 17.0,
                      size=0.85 + 0.35 * zp, alpha=math.sin(zp * math.pi) * 0.95)
        _tint_surface(surf, "closed", 0.75 * amp)
        frames.append(surf)
    return frames, [6, 35]


def build_renderers(_RA=None):
    """Return mapping of all 19 state names to zero-arg renderers."""
    return {
        "idle":       render_idle,
        "thinking":   render_thinking,
        "typing":     render_typing,
        "working":    render_working,
        "exploring":  render_exploring,
        "running":    render_running,
        "delegating": render_delegating,
        "asking":     render_asking,
        "listening":  render_listening,
        "watching":   render_watching,
        "done":       render_done,
        "happy":      render_happy,
        "dance":      render_dance,
        "sad":        render_sad,
        "angry":      render_angry,
        "error":      render_error,
        "canceled":   render_canceled,
        "tired":      render_tired,
        "closed":     render_closed,
    }


if __name__ == "__main__":
    for name in _EXTRACT_SPECS:
        sp = _extract_sprite(name)
        print(f"{name:10s}: {sp['w']:3d}x{sp['h']:3d} lbox={sp['lbox']} rbox={sp['rbox']} skin={tuple(round(c, 2) for c in sp['skin_rgb'])}")

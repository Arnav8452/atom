// Atom Lab skin selector modal and right-click context menu; lazily injected by
// atom_launch.py and mounted via window.__atom.__mountLab(factory).
(() => {
  const CATALOG = __ATOM_SKIN_CATALOG__;
  const rootApi = window.__atom;
  if (!rootApi || typeof rootApi.__mountLab !== "function") return;

  const HEX_RE = /^#[0-9a-fA-F]{3,8}$/;
  const safeAccent = (v) => (typeof v === "string" && HEX_RE.test(v.trim()) ? v.trim() : "#38bdf8");

  rootApi.__mountLab((bridge) => {
    const host = document.createElement("div");
    host.id = "atom-lab";
    host.style.display = "none";
    const shadow = host.attachShadow({ mode: "closed" });
    shadow.innerHTML = `<style>
      :host { all: initial; position: fixed; inset: 0; z-index: 2147483100; display: none;
              pointer-events: none; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif;
              color: #e2e8f0; }
      * { box-sizing: border-box; }
      .menu { position: fixed; min-width: 168px; padding: 5px; border-radius: 11px; display: none;
              flex-direction: column; gap: 2px; pointer-events: auto;
              background: linear-gradient(180deg, rgba(20, 25, 38, 0.98), rgba(13, 17, 26, 0.98));
              border: 1px solid rgba(148, 163, 184, 0.22);
              box-shadow: 0 14px 36px rgba(0, 0, 0, 0.55), 0 0 0 1px rgba(56, 189, 248, 0.08);
              font-size: 12px; color: #e2e8f0; }
      .menu button { all: unset; box-sizing: border-box; display: flex; align-items: center;
                     justify-content: space-between; gap: 10px; padding: 7px 10px; border-radius: 7px;
                     cursor: pointer; white-space: nowrap; font-family: inherit; font-size: 12px; }
      .menu button:hover:not(:disabled) { background: rgba(56, 189, 248, 0.16); color: #f8fafc; }
      .menu button:disabled { opacity: 0.42; cursor: default; }
      .mLeft { display: flex; align-items: center; gap: 7px; }
      .mb { font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 999px;
            background: rgba(56, 189, 248, 0.18); color: #7dd3fc; }
      .backdrop { position: fixed; inset: 0; background: rgba(6, 9, 15, 0.72);
                  backdrop-filter: blur(8px); display: none; align-items: center;
                  justify-content: center; padding: 20px; pointer-events: auto; }
      .panel { width: min(640px, 100%); max-height: min(82vh, 620px); display: flex;
               flex-direction: column; border-radius: 16px;
               background: linear-gradient(180deg, rgba(20, 25, 38, 0.98), rgba(13, 17, 26, 0.98));
               border: 1px solid rgba(148, 163, 184, 0.18);
               box-shadow: 0 24px 70px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(56, 189, 248, 0.08);
               overflow: hidden; }
      .hdr { display: flex; align-items: center; justify-content: space-between; gap: 12px;
             padding: 14px 18px; border-bottom: 1px solid rgba(148, 163, 184, 0.12); }
      .titleWrap { display: flex; align-items: center; gap: 10px; min-width: 0; }
      .icon { width: 28px; height: 28px; border-radius: 8px; display: grid; place-items: center;
              background: rgba(56, 189, 248, 0.12); border: 1px solid rgba(56, 189, 248, 0.28);
              color: #38bdf8; flex: none; }
      .title { font-size: 14px; font-weight: 600; color: #f8fafc; margin: 0; line-height: 1.2; }
      .sub { font-size: 11px; color: #94a3b8; margin-top: 2px; }
      .hdrRight { display: flex; align-items: center; gap: 8px; }
      .search { width: 170px; padding: 5px 10px; border-radius: 8px; font-size: 12px;
                color: #e2e8f0; background: rgba(15, 23, 42, 0.85);
                border: 1px solid rgba(148, 163, 184, 0.22); outline: none; }
      .search:focus { border-color: rgba(56, 189, 248, 0.65); }
      .closeBtn { width: 28px; height: 28px; border-radius: 8px; border: 1px solid transparent;
                  background: transparent; color: #94a3b8; font-size: 16px; line-height: 1;
                  cursor: pointer; display: grid; place-items: center; }
      .closeBtn:hover { background: rgba(148, 163, 184, 0.14); color: #f8fafc; }
      .body { padding: 16px 18px; overflow-y: auto; flex: 1; }
      .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; }
      .card { position: relative; display: flex; flex-direction: column; align-items: center;
              text-align: center; padding: 14px 10px 12px; border-radius: 12px;
              background: rgba(255, 255, 255, 0.03);
              border: 1px solid rgba(148, 163, 184, 0.14);
              color: inherit; cursor: pointer; font-family: inherit;
              transition: transform 140ms ease, border-color 140ms ease, background 140ms ease; }
      .card:hover { transform: translateY(-2px); background: rgba(255, 255, 255, 0.06);
                    border-color: rgba(148, 163, 184, 0.34); }
      .card.equipped { border-color: var(--accent, #38bdf8);
                       background: rgba(56, 189, 248, 0.09);
                       box-shadow: 0 0 0 1px var(--accent, #38bdf8) inset; }
      .pill { position: absolute; top: 8px; right: 8px; padding: 2px 7px; border-radius: 999px;
              font-size: 10px; font-weight: 600; letter-spacing: 0.02em;
              background: rgba(56, 189, 248, 0.18); color: #7dd3fc; display: none; }
      .card.equipped .pill { display: inline-block; }
      .stage { width: 96px; height: 77px; display: flex; align-items: center; justify-content: center;
               margin: 4px 0 8px; position: relative; }
      .stage canvas { display: block; width: 96px; height: 77px; }
      .shimmer { position: absolute; inset: 12px 18px; border-radius: 999px;
                 background: rgba(148, 163, 184, 0.14); }
      .card.ready .shimmer { display: none; }
      .cname { font-size: 13px; font-weight: 600; color: #f1f5f9; }
      .ctag { font-size: 11px; color: #94a3b8; margin-top: 2px; min-height: 14px; }
      .cmeta { font-size: 10px; color: #64748b; margin-top: 6px; }
      .vpills { display: flex; flex-wrap: wrap; justify-content: center; gap: 4px; margin-top: 6px; }
      .vpill { font-size: 9px; font-weight: 600; padding: 1px 6px; border-radius: 999px;
               background: rgba(148, 163, 184, 0.14); color: #cbd5e1; text-transform: capitalize; }
      .vpill[data-v="carbon"] { background: rgba(148, 163, 184, 0.24); color: #e2e8f0; }
      .vpill[data-v="neon"] { background: rgba(255, 58, 182, 0.20); color: #67e8f9; }
      .vpill[data-v="hydrogen"] { background: rgba(94, 226, 186, 0.20); color: #99f6e4; }
      .vpill[data-v="orchestrator"] { background: rgba(248, 198, 58, 0.24); color: #fde68a; }
      .slot { display: flex; flex-direction: column; align-items: center; justify-content: center;
              text-align: center; padding: 14px 12px; border-radius: 12px; min-height: 158px;
              border: 1px dashed rgba(148, 163, 184, 0.22); color: #64748b; font-size: 12px; }
      .slotTitle { color: #94a3b8; font-weight: 600; margin-bottom: 4px; }
      .ftr { display: flex; align-items: center; justify-content: space-between; gap: 12px;
             padding: 12px 18px; border-top: 1px solid rgba(148, 163, 184, 0.12);
             background: rgba(9, 12, 20, 0.45); font-size: 11px; color: #94a3b8; }
      .doneBtn { padding: 6px 14px; border-radius: 8px; border: 1px solid rgba(56, 189, 248, 0.35);
                 background: rgba(56, 189, 248, 0.16); color: #e0f2fe; font-size: 12px;
                 font-weight: 600; cursor: pointer; }
      .doneBtn:hover { background: rgba(56, 189, 248, 0.26); }
    </style>
    <div class="menu"></div>
    <div class="backdrop">
      <div class="panel" role="dialog" aria-modal="true" aria-label="Atom Lab">
        <div class="hdr">
          <div class="titleWrap">
            <div class="icon">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M9 3h6"/><path d="M10 3v6l-5 8a2 2 0 0 0 1.7 3h10.6a2 2 0 0 0 1.7-3l-5-8V3"/>
              </svg>
            </div>
            <div>
              <div class="title">Atom Lab</div>
              <div class="sub">Pick your companion skin · hover to preview dance</div>
            </div>
          </div>
          <div class="hdrRight">
            <input class="search" type="search" placeholder="Search skins..." hidden />
            <button class="closeBtn" type="button" aria-label="Close">×</button>
          </div>
        </div>
        <div class="body"><div class="grid"></div></div>
        <div class="ftr">
          <span class="hint">Shift+click Atom anytime to cycle skins</span>
          <button class="doneBtn" type="button">Done</button>
        </div>
      </div>
    </div>`;

    const menuEl = shadow.querySelector(".menu");
    const backdrop = shadow.querySelector(".backdrop");
    const closeBtn = shadow.querySelector(".closeBtn");
    const doneBtn = shadow.querySelector(".doneBtn");
    const searchInput = shadow.querySelector(".search");
    const grid = shadow.querySelector(".grid");

    const list = (Array.isArray(CATALOG) && CATALOG.length
      ? CATALOG
      : (bridge.skinNames || []).map((id) => ({ id, name: id, tagline: "", accent: "#38bdf8", states: 0 })));

    const mkMenuBtn = (label, badgeText) => {
      const b = document.createElement("button");
      b.type = "button";
      const left = document.createElement("span");
      left.className = "mLeft";
      left.textContent = label;
      b.appendChild(left);
      if (badgeText != null) {
        const sp = document.createElement("span");
        sp.className = "mb";
        sp.textContent = badgeText;
        b.appendChild(sp);
      }
      menuEl.appendChild(b);
      return { b, left };
    };
    const mLab = mkMenuBtn("Atom Lab", String(list.length));
    const mDance = mkMenuBtn("Dance");
    const mAlign = mkMenuBtn("Move to Left");

    if (list.length > 6 && searchInput) {
      searchInput.hidden = false;
    }

    const cards = [];
    for (const item of list) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "card";
      btn.style.setProperty("--accent", safeAccent(item.accent));
      btn.dataset.skin = item.id;

      const pill = document.createElement("span");
      pill.className = "pill";
      pill.textContent = "Equipped";

      const stage = document.createElement("div");
      stage.className = "stage";
      const shimmer = document.createElement("div");
      shimmer.className = "shimmer";
      const cv = document.createElement("canvas");
      stage.appendChild(shimmer);
      stage.appendChild(cv);

      const nameEl = document.createElement("div");
      nameEl.className = "cname";
      nameEl.textContent = item.name || item.id;

      const tagEl = document.createElement("div");
      tagEl.className = "ctag";
      tagEl.textContent = item.tagline || "";

      const hasVars = Array.isArray(item.variants) && item.variants.length > 0;
      const metaEl = document.createElement("div");
      metaEl.className = "cmeta";
      metaEl.textContent = hasVars
        ? `${item.variants.length} model outfits · ${item.states || 0} states`
        : (item.states ? `${item.states} states` : "Preview");

      btn.appendChild(pill);
      btn.appendChild(stage);
      btn.appendChild(nameEl);
      btn.appendChild(tagEl);
      btn.appendChild(metaEl);
      if (hasVars) {
        const vp = document.createElement("div");
        vp.className = "vpills";
        for (const v of item.variants) {
          const sp = document.createElement("span");
          sp.className = "vpill";
          sp.dataset.v = String(v);
          sp.textContent = String(v);
          vp.appendChild(sp);
        }
        btn.appendChild(vp);
      }

      const rec = {
        id: item.id,
        label: `${item.id} ${item.name || ""} ${item.tagline || ""}`.toLowerCase(),
        el: btn,
        cv,
        ctx: cv.getContext("2d"),
        hovered: false,
        sheet: null,
        frame: 0,
        nextAt: 0,
        visible: true,
      };
      btn.addEventListener("mouseenter", () => {
        rec.hovered = true;
        syncCardSheet(rec);
      });
      btn.addEventListener("mouseleave", () => {
        rec.hovered = false;
        syncCardSheet(rec);
      });
      btn.addEventListener("click", () => {
        const changed = rec.id !== bridge.getSkin();
        bridge.selectSkin(rec.id);
        refresh();
        if (changed) close();
      });
      grid.appendChild(btn);
      cards.push(rec);
    }

    if (list.length === 1) {
      const slot = document.createElement("div");
      slot.className = "slot";
      const t = document.createElement("div");
      t.className = "slotTitle";
      t.textContent = "More skins soon";
      const d = document.createElement("div");
      d.textContent = "Drop new skin packs in assets/ and pick them right here.";
      slot.appendChild(t);
      slot.appendChild(d);
      grid.appendChild(slot);
    }

    let isOpen = false;
    let menuOpen = false;
    let destroyed = false;
    let rafId = 0;

    function syncHostDisplay() {
      host.style.display = isOpen || menuOpen ? "block" : "none";
      backdrop.style.display = isOpen ? "flex" : "none";
      menuEl.style.display = menuOpen ? "flex" : "none";
    }

    function loopBounds(s) {
      if (!s || !s.durations || !s.durations.length) return [0, 0];
      if (Array.isArray(s.loop) && s.loop.length === 2) {
        const lo = Math.max(0, Math.min(s.durations.length - 1, s.loop[0] | 0));
        const hi = Math.max(lo, Math.min(s.durations.length - 1, s.loop[1] | 0));
        return [lo, hi];
      }
      return [0, s.durations.length - 1];
    }

    function drawCard(rec) {
      const s = rec.sheet;
      if (!s || !s.bitmap || !rec.ctx) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const cw = 96;
      const ch = Math.round((cw * s.h) / s.w);
      const pw = Math.round(cw * dpr);
      const ph = Math.round(ch * dpr);
      if (rec.cv.width !== pw || rec.cv.height !== ph) {
        rec.cv.width = pw;
        rec.cv.height = ph;
        rec.cv.style.width = `${cw}px`;
        rec.cv.style.height = `${ch}px`;
      }
      rec.ctx.imageSmoothingEnabled = true;
      rec.ctx.imageSmoothingQuality = "low";
      rec.ctx.clearRect(0, 0, pw, ph);
      const sx = (rec.frame % s.cols) * s.w;
      const sy = Math.floor(rec.frame / s.cols) * s.h;
      rec.ctx.drawImage(s.bitmap, sx, sy, s.w, s.h, 0, 0, pw, ph);
    }

    function syncCardSheet(rec) {
      const next = bridge.getSheet(rec.id, rec.hovered ? "dance" : "idle");
      if (next !== rec.sheet) {
        rec.sheet = next;
        rec.frame = 0;
        rec.nextAt = 0;
        if (next) {
          rec.el.classList.add("ready");
          drawCard(rec);
        } else {
          rec.el.classList.remove("ready");
        }
      }
    }

    function refresh() {
      const active = bridge.getSkin();
      for (const rec of cards) {
        if (rec.id === active) rec.el.classList.add("equipped");
        else rec.el.classList.remove("equipped");
        syncCardSheet(rec);
      }
    }

    function stopRaf() {
      if (rafId) {
        cancelAnimationFrame(rafId);
        rafId = 0;
      }
    }

    function tick(now) {
      rafId = 0;
      if (destroyed || !isOpen || document.hidden) return;
      for (const rec of cards) {
        const s = rec.sheet;
        if (!rec.visible || !s || !s.durations || !s.durations.length) continue;
        if (rec.nextAt === 0) {
          drawCard(rec);
          rec.nextAt = now + s.durations[rec.frame];
          continue;
        }
        if (now >= rec.nextAt) {
          const [lo, hi] = loopBounds(s);
          rec.frame = rec.frame >= hi ? lo : rec.frame + 1;
          if (rec.frame >= s.durations.length) rec.frame = lo;
          drawCard(rec);
          const dur = s.durations[rec.frame] || 80;
          rec.nextAt = now - rec.nextAt > 250 ? now + dur : rec.nextAt + dur;
        }
      }
      rafId = requestAnimationFrame(tick);
    }

    function startRaf() {
      if (!rafId && isOpen && !destroyed && !document.hidden) {
        rafId = requestAnimationFrame(tick);
      }
    }

    function mount() {
      if (!destroyed && !host.isConnected && document.documentElement) {
        document.documentElement.appendChild(host);
      }
    }

    function openMenu(x, y) {
      if (destroyed) return;
      mount();
      menuOpen = true;
      mDance.b.disabled = !bridge.canDance();
      mAlign.left.textContent = bridge.getAlign() === "left" ? "Move to Right" : "Move to Left";
      const vw = window.innerWidth || document.documentElement?.clientWidth || 1280;
      const vh = window.innerHeight || document.documentElement?.clientHeight || 800;
      let px = x, py = y;
      if (!(Number.isFinite(px) && Number.isFinite(py) && (px || py))) {
        const hr = bridge.host?.getBoundingClientRect?.();
        px = hr ? hr.left + hr.width * 0.5 : 16;
        py = hr ? hr.top + 8 : 16;
      }
      const left = Math.max(8, Math.min(vw - 176, Math.round(px)));
      const top = py > vh - 140 ? Math.max(8, Math.round(py - 124)) : Math.max(8, Math.round(py + 6));
      menuEl.style.left = `${left}px`;
      menuEl.style.top = `${top}px`;
      syncHostDisplay();
    }

    function closeMenu() {
      if (!menuOpen) return;
      menuOpen = false;
      syncHostDisplay();
    }

    function toggleMenu(x, y) {
      if (menuOpen) closeMenu();
      else openMenu(x, y);
    }

    function requestClose() {
      close();
      if (typeof bridge.onClose === "function") bridge.onClose();
    }

    function open() {
      if (destroyed) return;
      mount();
      menuOpen = false;
      isOpen = true;
      syncHostDisplay();
      refresh();
      startRaf();
    }

    function close() {
      isOpen = false;
      syncHostDisplay();
      stopRaf();
    }

    function onVisibility() {
      if (document.hidden) stopRaf();
      else startRaf();
    }

    function onDocPointerDown(e) {
      if (menuOpen && e && e.target !== host && e.target !== bridge.host) closeMenu();
    }

    function onDocKeyDown(e) {
      if (!e || e.key !== "Escape") return;
      if (menuOpen) closeMenu();
      else if (isOpen) requestClose();
    }

    mLab.b.addEventListener("click", (e) => { e.stopPropagation(); closeMenu(); open(); });
    mDance.b.addEventListener("click", (e) => { e.stopPropagation(); closeMenu(); bridge.dance(); });
    mAlign.b.addEventListener("click", (e) => { e.stopPropagation(); closeMenu(); bridge.toggleAlign(); });

    if (searchInput) {
      searchInput.addEventListener("input", () => {
        const q = String(searchInput.value || "").trim().toLowerCase();
        for (const rec of cards) {
          rec.visible = !q || rec.label.includes(q);
          rec.el.style.display = rec.visible ? "" : "none";
        }
      });
    }

    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) requestClose();
    });
    closeBtn.addEventListener("click", requestClose);
    doneBtn.addEventListener("click", requestClose);
    document.addEventListener("pointerdown", onDocPointerDown, { capture: true, passive: true });
    document.addEventListener("keydown", onDocKeyDown, { capture: true, passive: true });
    document.addEventListener("visibilitychange", onVisibility);

    function drawStar(ctx, cx, cy, r, rot, col, alpha) {
      if (alpha <= 0.02 || r <= 0.3) return;
      ctx.save();
      ctx.globalAlpha *= alpha;
      ctx.translate(cx, cy);
      if (rot) ctx.rotate(rot);
      ctx.fillStyle = col;
      ctx.beginPath();
      for (let i = 0; i < 4; i++) {
        const a0 = (i * Math.PI) / 2;
        const a1 = a0 + Math.PI / 4;
        const a2 = a0 + Math.PI / 2;
        const px0 = Math.cos(a0) * r, py0 = Math.sin(a0) * r;
        const cxm = Math.cos(a1) * r * 0.22, cym = Math.sin(a1) * r * 0.22;
        const px2 = Math.cos(a2) * r, py2 = Math.sin(a2) * r;
        if (i === 0) ctx.moveTo(px0, py0);
        ctx.quadraticCurveTo(cxm, cym, px2, py2);
      }
      ctx.closePath();
      ctx.fill();
      ctx.restore();
    }

    function drawCurtain(ctx, w, h, st) {
      if (!ctx || !ctx.fillRect) return;
      const sx = w / 150, sy = h / 120;

      // Minimal mock-canvas fallback for headless unit tests without Canvas 2D path APIs
      if (!ctx.bezierCurveTo || !ctx.quadraticCurveTo || !ctx.arc || !ctx.createLinearGradient) {
        const px = (x, y, rw, rh, col) => {
          ctx.fillStyle = col;
          ctx.fillRect(Math.round(x * sx), Math.round(y * sy), Math.max(1, Math.round(rw * sx)), Math.max(1, Math.round(rh * sy)));
        };
        ctx.globalAlpha = st.rodA;
        px(16, 26, 118, 3, "#d4a238");
        const cw = 130 - st.edge;
        if (cw > 1) {
          px(st.edge, 31, cw, 76, "#d41c2c");
          px(st.edge, 105, cw, 2, "#f6c945");
        }
        ctx.globalAlpha = 1;
        return;
      }

      const rightX = 131.5;
      const rodY = 26.5;
      const topY = 29.0;
      const baseHemY = 106.5;
      const u = Math.max(0, Math.min(1, (124 - st.edge) / 104));
      const swing = Math.sin(u * Math.PI);
      const isOpen = Boolean(st.open);
      const isHold = !isOpen && st.edge <= 20.5;
      const holdDt = Math.max(0, (st.el || 0) - 540);
      // Damped cloth follow-through settle when curtain slams shut at t = 540ms
      const settle = isHold ? -5.0 * Math.exp(-holdDt / 95) * Math.cos(holdDt * 0.042) : 0;
      const dir = isOpen ? 1 : -1;
      // Classic theatre tieback cinch when gathered open on the right (u -> 0)
      const cinch = Math.max(0, 1 - u * 4.0);

      // Leading edge profile x(t) for vertical normalized t in [0..1]:
      // Waist leads where Atom's paw pulls/pushes; heavy velvet hem billows & swings!
      const leadAt = (t) => {
        const topOff = -dir * 2.8 * swing - 1.2 * cinch;
        const midOff = dir * 3.4 * swing + 2.8 * cinch + (isHold ? Math.sin(holdDt * 0.02 + t * 3.1) * 1.3 : 0);
        const hemOff = -dir * 10.5 * swing - 2.6 * cinch + settle;
        const a = (1 - t) * (1 - t);
        const b = 2 * (1 - t) * t;
        const c = t * t;
        return st.edge + a * topOff + b * midOff + c * hemOff;
      };

      ctx.save();
      ctx.globalAlpha = st.rodA;

      const cw = rightX - st.edge;
      if (cw > 1.2) {
        // 1. Soft curved stage drop-shadow cast by the leading velvet drape
        ctx.save();
        ctx.fillStyle = "rgba(8, 10, 22, 0.30)";
        ctx.beginPath();
        ctx.moveTo((leadAt(0) - 2.5) * sx, (topY + 1) * sy);
        ctx.quadraticCurveTo((leadAt(0.52) - 4.0) * sx, 68 * sy, (leadAt(1) - 2.5) * sx, (baseHemY + 2.5) * sy);
        ctx.lineTo((leadAt(1) + 3.5) * sx, (baseHemY + 2.5) * sy);
        ctx.quadraticCurveTo((leadAt(0.52) + 3.0) * sx, 68 * sy, (leadAt(0) + 2.5) * sx, (topY + 1) * sy);
        ctx.closePath();
        ctx.fill();
        ctx.restore();

        // 2. Draped cylindrical crimson velvet pleats with curved motion & scalloped hem
        // Slightly fuller folds near the center/leading edge, tighter gathered folds on the right
        const weights = [1.18, 1.12, 1.06, 1.0, 0.94, 0.88, 0.82];
        const wSum = 7.0;
        const N = weights.length;
        const fracs = [0];
        let acc = 0;
        for (let i = 0; i < N; i++) {
          acc += weights[i] / wSum;
          fracs.push(acc);
        }

        const seamAt = (idx, t) => {
          const f = fracs[idx];
          const lx = leadAt(t);
          // Interior pleats inherit attenuated billow + subtle dressing-room rustle ripple
          const rustleWave = isHold
            ? Math.sin(holdDt * 0.018 + idx * 1.15 + t * 2.4) * (1.6 * Math.sin(f * Math.PI) * (0.35 + 0.65 * t))
            : Math.sin((st.el || 0) * 0.014 + idx * 0.9) * (0.6 * swing * Math.sin(f * Math.PI));
          return lx + (rightX - lx) * f + rustleWave;
        };

        const ringXs = [];
        for (let i = 0; i < N; i++) {
          const tx0 = seamAt(i, 0), tx1 = seamAt(i + 1, 0);
          const mx0 = seamAt(i, 0.52), mx1 = seamAt(i + 1, 0.52);
          const bx0 = seamAt(i, 1), bx1 = seamAt(i + 1, 1);
          const pw = Math.max(0.8, (mx1 - mx0));
          ringXs.push((tx0 + tx1) * 0.5);

          const rustleY = isHold ? Math.sin(holdDt * 0.022 + i * 1.3) * 1.4 : 0;
          const yBot0 = baseHemY - 1.2 + rustleY * 0.6;
          const yBot1 = baseHemY - 1.2 - rustleY * 0.6;
          const yScallop = baseHemY + 2.6 + rustleY;

          // Cylindrical velvet fold gradient: deep valley -> rich crimson -> plush sheen -> valley
          const g = ctx.createLinearGradient(mx0 * sx, 0, mx1 * sx, 0);
          g.addColorStop(0, i === 0 ? "#5a0610" : "#6b0814");
          g.addColorStop(0.24, "#b81426");
          g.addColorStop(0.50, i % 2 === 0 ? "#f23d50" : "#e32f42");
          g.addColorStop(0.78, "#a81122");
          g.addColorStop(1, "#590610");

          ctx.fillStyle = g;
          ctx.beginPath();
          ctx.moveTo(tx0 * sx, topY * sy);
          // Top pinched header dip between rings
          ctx.quadraticCurveTo(((tx0 + tx1) * 0.5) * sx, (topY + 1.4) * sy, tx1 * sx, topY * sy);
          // Right pleat crease curve down to hem
          ctx.quadraticCurveTo(mx1 * sx, 68 * sy, bx1 * sx, yBot1 * sy);
          // Rounded theatre scallop along bottom hem
          ctx.quadraticCurveTo(((bx0 + bx1) * 0.5) * sx, yScallop * sy, bx0 * sx, yBot0 * sy);
          // Left pleat crease curve back up to rod
          ctx.quadraticCurveTo(mx0 * sx, 68 * sy, tx0 * sx, topY * sy);
          ctx.closePath();
          ctx.fill();

          // Soft vertical velvet sheen & valley crease stroke when pleat is wide enough
          if (pw * sx >= 4 && ctx.stroke) {
            ctx.strokeStyle = "rgba(255, 160, 170, 0.18)";
            ctx.lineWidth = Math.max(0.75, 0.85 * sx);
            ctx.beginPath();
            ctx.moveTo((tx0 + (tx1 - tx0) * 0.46) * sx, (topY + 3) * sy);
            ctx.quadraticCurveTo((mx0 + (mx1 - mx0) * 0.46) * sx, 68 * sy, (bx0 + (bx1 - bx0) * 0.46) * sx, (yScallop - 2.5) * sy);
            ctx.stroke();
          }

          // Scalloped gold bullion trim & mini swaying fringe tassel at each scallop peak
          if (ctx.stroke) {
            ctx.strokeStyle = "#f9d86a";
            ctx.lineWidth = Math.max(1.1, 1.5 * sy);
            ctx.lineCap = "round";
            ctx.beginPath();
            ctx.moveTo(bx0 * sx, (yBot0 - 0.6) * sy);
            ctx.quadraticCurveTo(((bx0 + bx1) * 0.5) * sx, (yScallop - 0.4) * sy, bx1 * sx, (yBot1 - 0.6) * sy);
            ctx.stroke();

            ctx.strokeStyle = "#b57912";
            ctx.lineWidth = Math.max(0.7, 0.8 * sy);
            const midBx = (bx0 + bx1) * 0.5;
            const fringeTipX = midBx - dir * swing * 1.6 + rustleY * 0.4;
            ctx.beginPath();
            ctx.moveTo(midBx * sx, (yScallop - 0.5) * sy);
            ctx.lineTo(fringeTipX * sx, (yScallop + 2.2) * sy);
            ctx.stroke();
          }
        }

        // 3. Plush Scalloped Top Pelmet / Valance Swags (breaks up the top edge into theatre swags!)
        const topLeft = leadAt(0);
        const topSpan = Math.max(1, rightX - topLeft);
        const swagN = Math.max(1, Math.min(4, Math.round(topSpan / 26)));
        for (let s = 0; s < swagN; s++) {
          const sx0 = topLeft + (topSpan * s) / swagN;
          const sx1 = topLeft + (topSpan * (s + 1)) / swagN;
          const smid = (sx0 + sx1) * 0.5;
          const dip = 33.8 + Math.min(2.6, topSpan * 0.022);
          const vg = ctx.createLinearGradient(0, (topY - 1) * sy, 0, (dip + 1) * sy);
          vg.addColorStop(0, "#7a0917");
          vg.addColorStop(0.55, "#c9172b");
          vg.addColorStop(1, "#8d0d1c");
          ctx.fillStyle = vg;
          ctx.beginPath();
          ctx.moveTo(sx0 * sx, (topY - 0.8) * sy);
          ctx.lineTo(sx1 * sx, (topY - 0.8) * sy);
          ctx.quadraticCurveTo(smid * sx, (dip + 1.6) * sy, sx0 * sx, (topY - 0.8) * sy);
          ctx.closePath();
          ctx.fill();
          if (ctx.stroke) {
            ctx.strokeStyle = "#f6c945";
            ctx.lineWidth = Math.max(0.9, 1.15 * sy);
            ctx.beginPath();
            ctx.moveTo(sx0 * sx, (topY - 0.3) * sy);
            ctx.quadraticCurveTo(smid * sx, (dip + 1.4) * sy, sx1 * sx, (topY - 0.3) * sy);
            ctx.stroke();
          }
        }

        // 4. Swaying Gold Cord & Teardrop Tassel on the leading edge
        if (ctx.stroke) {
          const anchorX = leadAt(0.48) + 1.4;
          const anchorY = 66;
          const swayTassel = -dir * swing * 4.2 + settle * 0.55 + (isHold ? Math.sin(holdDt * 0.026) * 1.8 : 0);
          const bobX = anchorX + swayTassel;
          const bobY = 79;
          ctx.strokeStyle = "#fbd968";
          ctx.lineWidth = Math.max(1.0, 1.2 * sx);
          ctx.beginPath();
          ctx.moveTo(anchorX * sx, anchorY * sy);
          ctx.quadraticCurveTo((anchorX + swayTassel * 0.4) * sx, 73 * sy, bobX * sx, bobY * sy);
          ctx.stroke();

          ctx.fillStyle = "#f6c945";
          ctx.beginPath();
          ctx.arc(bobX * sx, bobY * sy, Math.max(1.3, 1.7 * sx), 0, Math.PI * 2);
          ctx.fill();
          ctx.beginPath();
          ctx.moveTo((bobX - 1.8) * sx, (bobY + 1) * sy);
          ctx.quadraticCurveTo(bobX * sx, (bobY - 0.5) * sy, (bobX + 1.8) * sx, (bobY + 1) * sy);
          ctx.lineTo((bobX + 2.3 + swayTassel * 0.15) * sx, (bobY + 5.2) * sy);
          ctx.quadraticCurveTo(bobX * sx, (bobY + 6.2) * sy, (bobX - 2.3 + swayTassel * 0.15) * sx, (bobY + 5.2) * sy);
          ctx.closePath();
          ctx.fill();
        }

        // 5. Sliding Brass Curtain Rings along the rod
        if (ctx.stroke) {
          ctx.strokeStyle = "#fde07a";
          ctx.lineWidth = Math.max(1.0, 1.25 * sx);
          for (const rx of ringXs) {
            ctx.beginPath();
            ctx.arc(rx * sx, (rodY + 0.6) * sy, Math.max(1.4, 1.9 * sy), 0, Math.PI * 2);
            ctx.stroke();
          }
        }
      }

      // 6. Cylindrical Brushed Brass Curtain Rod & Turned Spherical Finials
      const rodGrad = ctx.createLinearGradient(0, (rodY - 1.8) * sy, 0, (rodY + 1.8) * sy);
      rodGrad.addColorStop(0, "#fff2a6");
      rodGrad.addColorStop(0.45, "#e5b036");
      rodGrad.addColorStop(1, "#8c5810");
      ctx.fillStyle = rodGrad;
      ctx.beginPath();
      ctx.moveTo(15 * sx, (rodY - 1.5) * sy);
      ctx.lineTo(135 * sx, (rodY - 1.5) * sy);
      ctx.arc(135 * sx, rodY * sy, 1.5 * sy, -Math.PI / 2, Math.PI / 2);
      ctx.lineTo(15 * sx, (rodY + 1.5) * sy);
      ctx.arc(15 * sx, rodY * sy, 1.5 * sy, Math.PI / 2, -Math.PI / 2);
      ctx.closePath();
      ctx.fill();

      for (const fx of [13.5, 136.5]) {
        ctx.fillStyle = "#c98b1d";
        ctx.beginPath();
        ctx.arc(fx * sx, rodY * sy, Math.max(2.2, 3.1 * sy), 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "#fff3b0";
        ctx.beginPath();
        ctx.arc((fx - 0.8) * sx, (rodY - 0.9) * sy, Math.max(0.9, 1.2 * sy), 0, Math.PI * 2);
        ctx.fill();
      }

      // 7. Smooth Plump Rounded Blue Paw gripping the curtain waist
      if (st.hand) {
        const gripX = leadAt(0.55);
        const handY = 73.5 + (st.ady || 0) * 0.45;
        const shX = 75 + (st.adx || 0) + 19;
        if (gripX > shX - 2 && gripX - shX <= 24 && ctx.stroke) {
          ctx.strokeStyle = "#0c4b85";
          ctx.lineWidth = Math.max(3.2, 5.4 * sy);
          ctx.lineCap = "round";
          ctx.beginPath();
          ctx.moveTo(shX * sx, (handY + 1) * sy);
          ctx.quadraticCurveTo(((shX + gripX) * 0.5) * sx, (handY - 1.2) * sy, gripX * sx, handY * sy);
          ctx.stroke();

          ctx.strokeStyle = "#299cf6";
          ctx.lineWidth = Math.max(2.0, 3.4 * sy);
          ctx.beginPath();
          ctx.moveTo(shX * sx, (handY + 0.6) * sy);
          ctx.quadraticCurveTo(((shX + gripX) * 0.5) * sx, (handY - 1.5) * sy, gripX * sx, (handY - 0.2) * sy);
          ctx.stroke();
        }
        const pr = Math.max(2.6, 3.6 * Math.min(sx, sy));
        ctx.fillStyle = "#0c4b85";
        ctx.beginPath();
        ctx.arc((gripX - 0.8) * sx, handY * sy, pr + Math.max(0.9, 1.1 * sx), 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "#29a0f8";
        ctx.beginPath();
        ctx.arc((gripX - 0.8) * sx, handY * sy, pr, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "#8ce8ff";
        ctx.beginPath();
        ctx.arc((gripX - 1.9) * sx, (handY - 1.1) * sy, pr * 0.38, 0, Math.PI * 2);
        ctx.fill();
      }

      // 8. Smooth Curved 4-Point Star Sparkles during hold & reveal
      const spRot = ((st.el || 0) * 0.0025) % (Math.PI * 2);
      if (st.spark === 1) {
        const pulse = 0.80 + 0.25 * Math.sin((st.el || 0) * 0.016);
        const pulse2 = 0.80 + 0.25 * Math.cos((st.el || 0) * 0.016);
        drawStar(ctx, 54 * sx, 16 * sy, 4.8 * sx * pulse, spRot * 0.35, "#fde07a", 0.96);
        drawStar(ctx, 94 * sx, 14 * sy, 4.0 * sx * pulse2, -spRot * 0.4, "#ffffff", 0.92);
        drawStar(ctx, 74 * sx, 18 * sy, 3.3 * sx * pulse2, spRot * 0.25, "#fde07a", 0.85);
      } else if (st.spark === 2) {
        drawStar(ctx, 44 * sx, 18 * sy, 4.6 * sx, spRot * 0.3, "#ffffff", st.rodA);
        drawStar(ctx, 104 * sx, 16 * sy, 5.0 * sx, -spRot * 0.3, "#fde07a", st.rodA);
        drawStar(ctx, 74 * sx, 12 * sy, 4.0 * sx, 0, "#ffffff", st.rodA);
      }

      ctx.restore();
    }

    return {
      open,
      close,
      openMenu,
      closeMenu,
      toggleMenu,
      refresh,
      drawCurtain,
      isOpen: () => isOpen,
      isMenuOpen: () => menuOpen,
      destroy() {
        destroyed = true;
        isOpen = false;
        menuOpen = false;
        stopRaf();
        document.removeEventListener("pointerdown", onDocPointerDown, { capture: true });
        document.removeEventListener("keydown", onDocKeyDown, { capture: true });
        document.removeEventListener("visibilitychange", onVisibility);
        host.remove();
      },
    };
  });
})();

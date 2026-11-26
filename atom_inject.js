// Atom prompt-bar mascot overlay; atom_launch.py inlines __ATOM_SKIN_NAMES__ and pushes
// sprites on demand via window.__atom.__loadState / setBase / setMood / react.
(() => {
  if (window.__atom) return;

  const SKIN_NAMES = __ATOM_SKIN_NAMES__;
  const SIZE = { min: 72, max: 132, ofBar: 0.09 };
  const INSET = 20;
  const SINK = 0.015;
  const MIN_DWELL_MS = 1200;
  const INSTANT_EXIT = new Set(["idle", "listening", "closed"]);
  const BLEND_MS = 140;
  const MOOD_RAMP_MS = 650;
  const FIDGET_AFTER_MS = 7000;
  const LISTEN_MS = 2000;
  const REACTIONS = new Set(["happy", "sad", "angry", "error", "canceled", "tired", "done", "dance"]);
  const MF_RE = /\b(gemini|claude|gpt|opus|sonnet|haiku|flash)\b/i;
  const DQ_RE = /(?:reached.*quota|quota\s*(?:limit|exhaust|exceed)|(?:rate|usage|5[-\s]?h(?:ou)?r|weekly)\s*limit|resume using this model|0% remaining)/i;
  const CHAT_RE = /message|conversation|chat|transcript|history|turn|log/i;
  const MOOD_LOOK = {
    angry: { body: { hue: 6, sat: 1.05, val: 0.98 }, eyes: "angry" },
    sad:   { body: { hue: 214, sat: 0.32, val: 0.78 }, eyes: "sad" },
  };

  // Lazy recolour presets for states without custom sheets.
  const FALLBACK_LOOK = {
    idle:     { speed: 1 },
    typing:   { speed: 1.6 },
    thinking: { speed: 0.8, body: { hue: 252, sat: 1.0, val: 1.0 } },
    sad:      { speed: 0.6, body: { hue: 214, sat: 0.3, val: 0.8 }, rest: { sat: 0.3, val: 0.85 } },
    angry:    { speed: 1.8, body: { hue: 6, sat: 1.05, val: 1.0 } },
    happy:    { speed: 1.4, body: { hue: 186, sat: 1.1, val: 1.08 } },
    dance:    { speed: 1.5, body: { hue: 195, sat: 1.08, val: 1.06 } },
    closed:   { speed: 0.4, body: { hue: 222, sat: 0.55, val: 0.42 }, rest: { sat: 0.5, val: 0.5 } },
  };

  function readStorage(key) {
    try { return localStorage.getItem(key); } catch { return null; }
  }
  function writeStorage(key, value) {
    try { localStorage.setItem(key, value); } catch {}
  }

  const skinNames = [...SKIN_NAMES].sort((a, b) => (a === "atom" ? -1 : b === "atom" ? 1 : a.localeCompare(b)));
  const savedSkin = readStorage("atom.skin");
  let skin = skinNames.includes(savedSkin) ? savedSkin : skinNames[0];
  const savedAlign = readStorage("atom.align");
  let align = savedAlign === "left" ? "left" : "right";

  const sheets = {};
  const recolouring = new Set();
  let loadingSkin = null;
  const closeBmp = (b) => { if (b && typeof b.close === "function") b.close(); };

  function yieldToMain() {
    if (typeof MessageChannel === "function") {
      return new Promise((resolve) => {
        const ch = new MessageChannel();
        ch.port1.onmessage = () => resolve();
        ch.port2.postMessage(null);
      });
    }
    return new Promise((resolve) => setTimeout(resolve, 0));
  }

  async function decode(b64) {
    const bytes = typeof Uint8Array.fromBase64 === "function"
      ? Uint8Array.fromBase64(b64)
      : (() => {
          const bin = atob(b64);
          const out = new Uint8Array(bin.length);
          for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
          return out;
        })();
    // createImageBitmap, unlike <img src=data:...>, isn't subject to the page's CSP.
    return createImageBitmap(new Blob([bytes], { type: "image/webp" }));
  }

  // Tilt neutral eyes in-place per sprite cell into angry (\ /) or sad (/ \) brows.
  function tiltMoodEyes(d, W, H, fw, fh, mode) {
    const cols = Math.floor(W / fw), rows = Math.floor(H / fh);
    const xEnd = Math.min(fw, 104), yEnd = Math.min(fh, 87);
    for (let r = 0; r < rows; r++) {
      const fy = r * fh;
      for (let c = 0; c < cols; c++) {
        const fx = c * fw;
        const runs = [];
        let cur = null;
        for (let x = 50; x < xEnd; x++) {
          let lo = 999, hi = -1;
          for (let y = 58; y < yEnd; y++) {
            const o = ((fy + y) * W + (fx + x)) * 4;
            if (d[o + 3] > 200 && d[o] < 35 && d[o + 1] < 35 && d[o + 2] < 35) {
              if (y < lo) lo = y;
              if (y > hi) hi = y;
            }
          }
          if (hi >= lo) {
            if (!cur) cur = { x0: x, x1: x, y0: lo, y1: hi };
            else { cur.x1 = x; if (lo < cur.y0) cur.y0 = lo; if (hi > cur.y1) cur.y1 = hi; }
          } else if (cur) {
            runs.push(cur);
            cur = null;
          }
        }
        if (cur) runs.push(cur);
        const eyes = runs.filter((e) => {
          const w = e.x1 - e.x0 + 1, h = e.y1 - e.y0 + 1;
          return w >= 4 && w <= 10 && h >= 4 && h <= 10;
        });
        let pair = null;
        for (let i = 0; i < eyes.length && !pair; i++) {
          for (let j = i + 1; j < eyes.length; j++) {
            const dx = (eyes[j].x0 + eyes[j].x1 - eyes[i].x0 - eyes[i].x1) * 0.5;
            const dy = Math.abs((eyes[j].y0 + eyes[j].y1 - eyes[i].y0 - eyes[i].y1) * 0.5);
            if (dx >= 22 && dx <= 32 && dy <= 3) { pair = [eyes[i], eyes[j]]; break; }
          }
        }
        if (!pair) continue;
        const [L, R] = pair;
        const mo = ((fy + L.y0 + 1) * W + (fx + ((L.x1 + R.x0) >> 1))) * 4;
        if (d[mo + 3] <= 200) continue;
        const fr = d[mo], fg = d[mo + 1], fb = d[mo + 2];
        for (let idx = 0; idx < 2; idx++) {
          const e = pair[idx], isL = idx === 0, span = Math.max(1, e.x1 - e.x0);
          for (let x = e.x0; x <= e.x1; x++) {
            const u = mode === "angry"
              ? (isL ? (x - e.x0) / span : (e.x1 - x) / span)
              : (isL ? (e.x1 - x) / span : (x - e.x0) / span);
            const cut = Math.round(u * (mode === "angry" ? 3.2 : 3.5));
            const endY = Math.min(e.y1, e.y0 + cut - 1);
            for (let y = e.y0; y <= endY; y++) {
              const o = ((fy + y) * W + (fx + x)) * 4;
              d[o] = fr; d[o + 1] = fg; d[o + 2] = fb; d[o + 3] = 255;
            }
            if (mode === "angry" && u < 0.45 && fy + e.y0 - 1 >= 0) {
              const bo = ((fy + e.y0 - 1) * W + (fx + x)) * 4;
              if (d[bo + 3] > 200) { d[bo] = 10; d[bo + 1] = 14; d[bo + 2] = 20; }
            }
          }
        }
      }
    }
  }

  // Atom's body is the saturated blue (hue ~204); electrons and beanie are other hues.
  async function recolour(bitmap, look, fw, fh) {
    const cv = new OffscreenCanvas(bitmap.width, bitmap.height);
    const c = cv.getContext("2d");
    c.drawImage(bitmap, 0, 0);
    const img = c.getImageData(0, 0, cv.width, cv.height);
    const d = img.data;
    const len = d.length;
    const body = look.body;
    const rest = look.rest;
    for (let i = 0; i < len; i += 4) {
      // Yield every 32,768 pixels without per-pixel array allocations.
      if (i > 0 && (i & 131071) === 0) {
        await yieldToMain();
        if (destroyed) return null;
      }
      if (!d[i + 3]) continue;
      const r = d[i], g = d[i + 1], b = d[i + 2];
      const max = r > g ? (r > b ? r : b) : (g > b ? g : b);
      const min = r < g ? (r < b ? r : b) : (g < b ? g : b);
      const delta = max - min;
      let h = 0;
      if (delta) {
        if (max === r) h = ((g - b) / delta) % 6;
        else if (max === g) h = (b - r) / delta + 2;
        else h = (r - g) / delta + 4;
        h *= 60;
        if (h < 0) h += 360;
      }
      let s = max ? delta / max : 0;
      let v = max / 255;
      if (body && h >= 196 && h <= 226 && s > 0.35) {
        h = body.hue;
        s = Math.max(0, Math.min(1, s * body.sat));
        v = Math.max(0, Math.min(1, v * body.val));
      } else if (rest) {
        s = Math.max(0, Math.min(1, s * rest.sat));
        v = Math.max(0, Math.min(1, v * rest.val));
      } else {
        continue;
      }
      const ch = v * s;
      const x = ch * (1 - Math.abs(((h / 60) % 2) - 1));
      const m = v - ch;
      let rr, gg, bb;
      if (h < 60) { rr = ch; gg = x; bb = 0; }
      else if (h < 120) { rr = x; gg = ch; bb = 0; }
      else if (h < 180) { rr = 0; gg = ch; bb = x; }
      else if (h < 240) { rr = 0; gg = x; bb = ch; }
      else if (h < 300) { rr = x; gg = 0; bb = ch; }
      else { rr = ch; gg = 0; bb = x; }
      d[i] = (rr + m) * 255;
      d[i + 1] = (gg + m) * 255;
      d[i + 2] = (bb + m) * 255;
    }
    if (look.eyes && fw >= 104 && fh >= 87) tiltMoodEyes(d, cv.width, cv.height, fw, fh, look.eyes);
    c.putImageData(img, 0, 0);
    return createImageBitmap(cv);
  }

  async function cachedRecolour(key, srcBmp, look, fw, fh, onDone) {
    if (recolouring.has(key)) return;
    recolouring.add(key);
    try {
      const bitmap = await recolour(srcBmp, look, fw, fh);
      if (!bitmap) return;
      if (destroyed) { closeBmp(bitmap); return; }
      onDone(bitmap);
    } finally {
      recolouring.delete(key);
    }
  }

  function ensureStandIn(skinName, state, source, look) {
    return cachedRecolour(`${skinName}:${state}`, source.bitmap, look, source.w, source.h, (bitmap) => {
      const own = sheets[skinName];
      if (!own) { closeBmp(bitmap); return; }
      const nextEntry = { ...source, bitmap, look: { speed: look.speed } };
      own[state] = nextEntry;
      if (moodColor) ensureMoodBitmap(skinName, state, nextEntry, moodColor);
      if (skinName === skin && playing === state) {
        sheet = nextEntry;
        draw();
      }
    });
  }

  function ensureMoodBitmap(skinName, state, entry, moodName) {
    const look = MOOD_LOOK[moodName];
    if (!entry || !entry.bitmap || !look) return;
    if (entry._moodSrc === entry.bitmap && entry._mood && entry._mood[moodName]) return;
    return cachedRecolour(`mood:${skinName}:${state}:${moodName}`, entry.bitmap, look, entry.w, entry.h, (bitmap) => {
      if (entry._moodSrc !== entry.bitmap) {
        if (entry._mood) Object.values(entry._mood).forEach(closeBmp);
        entry._mood = {};
        entry._moodSrc = entry.bitmap;
      }
      entry._mood[moodName] = bitmap;
      if (skinName === skin && moodColor === moodName) paintVisible();
    });
  }

  async function decodeState(s) {
    if (!s || !s.webp) return null;
    const b64 = s.webp;
    s.webp = null;
    const bitmap = await decode(b64);
    if (destroyed) { closeBmp(bitmap); return null; }
    const { webp: _drop, ...meta } = s;
    return { ...meta, bitmap, look: { speed: 1 } };
  }

  async function loadState(name, state, s) {
    if (destroyed || !s || typeof s !== "object") return;
    const prevLoad = loadingSkin;
    if (state === "idle") loadingSkin = name;
    try {
      const entry = await decodeState(s);
      if (!entry || destroyed) return;
      const own = sheets[name] || (sheets[name] = {});
      own[state] = entry;
      if (name === skin && activated && (!playing || (playing === state && sheet !== entry))) {
        start(playing || effectiveBase(), { isOneShot: oneShot });
        place();
        paintVisible();
      } else if (name === skin && moodColor && playing === state) {
        ensureMoodBitmap(name, state, entry, moodColor);
      }
    } finally {
      if (state === "idle" && loadingSkin === name) loadingSkin = prevLoad === name ? null : prevLoad;
    }
  }

  async function loadSkin(name, states) {
    if (destroyed || !states || typeof states !== "object") return;
    loadingSkin = name;
    try {
      const decoded = {};
      for (const [state, s] of Object.entries(states)) {
        const entry = await decodeState(s);
        if (!entry) {
          if (destroyed) return;
          continue;
        }
        decoded[state] = entry;
      }
      sheets[name] = decoded;
      if (name === skin && activated) {
        start(playing || effectiveBase());
        place();
        paintVisible();
      }
    } finally {
      if (loadingSkin === name) loadingSkin = null;
    }
  }

  // --- element -------------------------------------------------------------------
  const host = document.createElement("div");
  host.id = "atom-mascot";
  host.style.display = "none";
  const shadow = host.attachShadow({ mode: "closed" });
  shadow.innerHTML = `<style>
    :host { all: initial; position: fixed; z-index: 2147483000; pointer-events: none;
            display: none; left: 0; top: 0; }
    canvas { display: block; }
    #hit { position: absolute; left: 28%; width: 44%; top: 34%; height: 52%;
           pointer-events: auto; cursor: pointer; }
  </style><canvas></canvas><div id="hit"></div>`;
  const canvas = shadow.querySelector("canvas");
  const hit = shadow.querySelector("#hit");
  const ctx = canvas.getContext("2d");
  const paintVisible = (now) => {
    if (host.style.display !== "none") {
      draw(now);
      scheduleTick();
    }
  };

  const updateTitle = () => {
    const skinInfo = skinNames.length >= 2 ? ` · ${skin || "atom"} skin` : "";
    hit.title = `Atom${skinInfo} (click to dance, Alt+click to switch side${skinNames.length >= 2 ? ", Shift+click to switch skin" : ""})`;
  };

  hit.addEventListener("click", (e) => {
    e.stopPropagation();
    if (e.altKey) {
      align = align === "left" ? "right" : "left";
      writeStorage("atom.align", align);
      updateTitle();
      place();
      return;
    }
    if (e.shiftKey && skinNames.length >= 2) {
      skin = skinNames[(skinNames.indexOf(skin) + 1) % skinNames.length];
      writeStorage("atom.skin", skin);
      updateTitle();
      if (sheets[skin] && playing) {
        start(playing);
        paintVisible();
      }
      return;
    }
    if (moodBlocksDance() || limitSleep) return;
    if (INSTANT_EXIT.has(playing) && sheet) {
      start("dance", { isOneShot: true });
      paintVisible();
    } else {
      window.__atom.react("dance");
    }
  });
  updateTitle();

  let base = "idle";
  let playing = null;
  let oneShot = false;
  let pending = null;
  let reaction = null;
  let lastReactId = null;
  let sheet = null;
  let blend = null;
  let frame = 0;
  let nextAt = 0;
  let widthCss = SIZE.min;
  let idleSince = performance.now();
  let stateSince = 0;
  let activated = false;
  let destroyed = false;
  let timerId = 0;
  let rafId = 0;
  let placeTimer = 0;
  let waitTimer = 0;
  let listenTimer = 0;
  let dwellTimer = 0;
  let listening = false;
  let mood = null;
  let moodColor = null;
  let moodFrom = 0;
  let moodTo = 0;
  let moodAt = 0;
  let hookModel = "";
  let hookLimited = false;
  const limitedModels = new Set();
  let uiModel = "";
  let domLimited = false;
  let limitSleep = false;
  let limitScanTimer = 0;
  let prevDomBanner = "";
  const moodBlocksDance = () => Boolean(mood || playing === "angry" || playing === "sad");

  const mNorm = (s) => String(s || "").toLowerCase().replace(/^models\//, "").replace(/[^a-z0-9]+/g, " ").trim();
  const mKey = (s) => mNorm(s).replace(/\b(?:high|low|medium|fast|thinking|preview|experimental|exp|latest|auto)\b/g, "").replace(/\s+/g, " ").trim() || mNorm(s);
  const mMatch = (a, b) => { const ka = mKey(a); return Boolean(ka && ka === mKey(b)); };
  const hasLim = (u) => [...limitedModels].some((m) => mMatch(m, u));
  const hasM = (nq, m) => { const k = mKey(m); return k.includes(" ") && ` ${nq} `.includes(` ${k} `); };
  const attr = (el, k) => el?.getAttribute?.(k) || "";
  const txt = (el) => String(el?.textContent || "").trim();
  const isEd = (el) => Boolean(el && (el.tagName === "TEXTAREA" || el.tagName === "INPUT" || (attr(el, "contenteditable") && attr(el, "contenteditable") !== "false")));
  const isChat = (el) => CHAT_RE.test(`${attr(el, "data-testid")} ${attr(el, "role")} ${el?.className || ""}`);
  function queueBase(target) {
    if (!sheet) return;
    if (!reaction) {
      const [, hi] = loopRange(sheet);
      if (target === playing && frame <= hi) { oneShot = false; pending = null; } else pending = target;
    }
    scheduleExit();
  }
  function syncLimitSleep() {
    const next = Boolean(domLimited || hookLimited);
    if (next === limitSleep) return;
    limitSleep = next;
    if (next) { listening = false; if (listenTimer) { clearTimeout(listenTimer); listenTimer = 0; } }
    queueBase(effectiveBase());
  }
  function scanQuotaDom(apply = true) {
    if (destroyed || !activated) return;
    const found = currentBar(), box = found?.box || null;
    let nextUi = "", fb = "", qt = "";
    const chkQ = (el) => {
      if (qt || !el || isEd(el) || isChat(el)) return;
      const t = txt(el);
      if (t && t.length <= 400 && DQ_RE.test(t)) qt = t;
    };
    if (box) {
      const q = [box];
      for (let i = 0; i < q.length && i < 80; i++) {
        const el = q[i];
        if (!el || isEd(el)) continue;
        for (const c of el.children || []) q.push(c);
        if (el === box) continue;
        const tid = attr(el, "data-testid"), aria = attr(el, "aria-label"), role = attr(el, "role"), t = txt(el);
        if (!nextUi && /model/i.test(tid + aria)) {
          const cl = (t || aria.replace(/^(?:model|select\s+model)\s*[:\-]?\s*/i, "")).trim();
          if (cl && cl.length <= 64 && !DQ_RE.test(cl)) nextUi = cl;
        }
        if (!fb && (/^(?:BUTTON|SELECT)$/.test(el.tagName) || role === "button" || role === "combobox") && t && t.length <= 48 && MF_RE.test(t) && !DQ_RE.test(t)) fb = t;
        chkQ(el);
      }
      nextUi = nextUi || fb;
      if (!qt) for (const el of box.parentElement?.children || []) if (el !== box) chkQ(el);
    }
    if (!qt && document.querySelectorAll) {
      try {
        for (const el of document.querySelectorAll('[role="alert"],[role="status"],[data-testid*="quota" i],[data-testid*="limit" i]')) {
          let bad = false;
          for (let p = el; p && p !== document.body; p = p.parentElement) if (isChat(p)) { bad = true; break; }
          if (!bad) chkQ(el);
          if (qt) break;
        }
      } catch {}
    }
    const prevUi = uiModel, switched = Boolean(nextUi && prevUi && !mMatch(nextUi, prevUi));
    if (nextUi) uiModel = nextUi;
    if (qt) {
      const nq = mNorm(qt);
      const rec = [...limitedModels].find((m) => hasM(nq, m)) || (uiModel && hasM(nq, uiModel) ? uiModel : "") || (prevUi && switched && hasM(nq, prevUi) ? prevUi : "") || (!switched && !hookModel ? uiModel : "");
      if (rec) limitedModels.add(rec);
      domLimited = uiModel && hasLim(uiModel) ? true : uiModel && [...limitedModels].some((m) => hasM(nq, m) && !mMatch(m, uiModel)) ? false : !(switched && qt === prevDomBanner);
    } else domLimited = false;
    prevDomBanner = qt;
    if (uiModel) {
      if (hasLim(uiModel)) hookLimited = true;
      else if (switched || (hookModel && !mMatch(hookModel, uiModel))) hookLimited = false;
    }
    if (apply) syncLimitSleep();
  }
  function scheduleLimitScan() {
    if (destroyed || !activated || limitScanTimer) return;
    limitScanTimer = setTimeout(() => { limitScanTimer = 0; scanQuotaDom(true); }, 120);
  }

  function smooth01(t) {
    return t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t);
  }
  function moodMixAt(now) {
    if (!moodColor) return 0;
    const u = smooth01((now - moodAt) / MOOD_RAMP_MS);
    const v = moodFrom + (moodTo - moodFrom) * u;
    if (moodTo === 0 && u >= 1) {
      moodColor = null;
      return 0;
    }
    return v;
  }
  function moodRamping(now) {
    return Boolean(moodColor && moodFrom !== moodTo && now - moodAt < MOOD_RAMP_MS);
  }

  function effectiveBase() {
    if (limitSleep && (base === "idle" || base === "closed")) return "closed";
    return listening && (base === "idle" || base === "closed") ? "listening" : base;
  }

  function stopListening() {
    listenTimer = 0;
    if (!listening) return;
    listening = false;
    if (playing === "listening" && !reaction) {
      pending = effectiveBase();
      scheduleTick();
    }
  }

  function onPromptInput(e) {
    if (destroyed || !activated || !e || !e.target) return;
    const boxes = document.querySelectorAll('[data-testid="agent-input-box"]');
    let inside = false;
    for (let i = 0; i < boxes.length; i++) {
      if (boxes[i] === e.target || boxes[i].contains(e.target)) {
        inside = true;
        break;
      }
    }
    if (!inside) return;
    if (listenTimer) clearTimeout(listenTimer);
    listenTimer = setTimeout(stopListening, LISTEN_MS);
    if (limitSleep || (base !== "idle" && base !== "closed")) return;
    if (!listening) {
      listening = true;
      if (!reaction && !REACTIONS.has(playing) && playing !== "listening") {
        pending = "listening";
        scheduleTick();
      }
    }
  }

  function loopRange(s) {
    if (!s || !s.durations || !s.durations.length) return [0, 0];
    if (Array.isArray(s.loop) && s.loop.length === 2) {
      const lo = Math.max(0, Math.min(s.durations.length - 1, s.loop[0] | 0));
      const hi = Math.max(lo, Math.min(s.durations.length - 1, s.loop[1] | 0));
      return [lo, hi];
    }
    return [0, s.durations.length - 1];
  }

  function currentPhase() {
    if (!sheet) return null;
    const [lo, hi] = loopRange(sheet);
    if (frame < lo) return "intro";
    if (frame > hi) return "outro";
    return "loop";
  }

  const sheetFor = (state) => {
    const own = sheets[skin];
    if (!own) return null;
    if (own[state]) return own[state];
    if (state === "reading" && own.exploring) return own.exploring;
    const source = own.idle || Object.values(own)[0] || null;
    if (!source) return null;
    const look = FALLBACK_LOOK[state];
    if (!look) return source;
    const standIn = { ...source, look: { speed: look.speed } };
    own[state] = standIn;
    if (look.body) ensureStandIn(skin, state, source, look);
    return standIn;
  };

  function start(state, opts = {}) {
    const nextSheet = sheetFor(state);
    const isOneShot = Boolean(opts.isOneShot);
    if (sheet && nextSheet && sheet !== nextSheet && host.style.display !== "none" && !document.hidden) {
      blend = { sheet, frame, startedAt: performance.now(), ms: BLEND_MS };
    } else if (!nextSheet || sheet === nextSheet) {
      blend = null;
    }
    stateSince = performance.now();
    if (dwellTimer) { clearTimeout(dwellTimer); dwellTimer = 0; }
    if (state === "idle" && playing !== "idle") idleSince = stateSince;
    playing = state;
    oneShot = isOneShot;
    if (pending === state) pending = null;
    sheet = nextSheet;
    frame = 0;
    nextAt = 0;
    if (moodColor && sheet) ensureMoodBitmap(skin, state, sheet, moodColor);
  }

  function finishState() {
    if (reaction) {
      const r = reaction;
      reaction = null;
      pending = null;
      start(r, { isOneShot: true });
    } else {
      const next = pending || effectiveBase();
      pending = null;
      start(next, { isOneShot: false });
    }
  }

  function advanceFrame(now) {
    const [lo, hi] = loopRange(sheet);
    const hasOutro = hi < sheet.durations.length - 1;
    const dwellHold = !reaction && !oneShot && !INSTANT_EXIT.has(playing) && now - stateSince < MIN_DWELL_MS;

    if (frame >= lo && frame <= hi) {
      if (!oneShot && (reaction || (pending && !dwellHold))) {
        if (hasOutro) {
          if (host.style.display !== "none" && !document.hidden) {
            blend = { sheet, frame, startedAt: now, ms: BLEND_MS };
          }
          frame = hi + 1;
          return false;
        }
        finishState();
        return true;
      }
      if (frame === hi) {
        if (!oneShot && !pending && !reaction) {
          if (effectiveBase() === "idle" && playing === "idle" && now - idleSince >= FIDGET_AFTER_MS) {
            start("typing", { isOneShot: true });
            return true;
          }
          frame = lo;
          return false;
        }
        if (!oneShot) {
          frame = lo;
          return false;
        }
        if (hasOutro) {
          frame = hi + 1;
          return false;
        }
        finishState();
        return true;
      }
    }

    frame += 1;
    if (frame >= sheet.durations.length) {
      finishState();
      return true;
    }
    return false;
  }

  function frameMs() {
    return sheet.durations[frame] / sheet.look.speed;
  }

  function cancelTick() {
    if (timerId) {
      clearTimeout(timerId);
      timerId = 0;
    }
    if (rafId) {
      cancelAnimationFrame(rafId);
      rafId = 0;
    }
  }

  function scheduleTick() {
    cancelTick();
    if (destroyed || !activated || document.hidden || !sheet || host.style.display === "none") {
      return;
    }
    if (blend || moodRamping(performance.now())) {
      rafId = requestAnimationFrame(tick);
      return;
    }
    const delay = nextAt ? Math.max(0, nextAt - performance.now()) : 0;
    if (delay <= 20) {
      rafId = requestAnimationFrame(tick);
    } else {
      timerId = setTimeout(() => {
        timerId = 0;
        if (!destroyed && !document.hidden && host.style.display !== "none") {
          rafId = requestAnimationFrame(tick);
        }
      }, Math.max(0, delay - 16));
    }
  }

  function tick(now) {
    rafId = 0;
    if (destroyed || !activated || document.hidden || !sheet || host.style.display === "none") {
      return;
    }
    if (now - lastPlaceAt >= 1000) {
      place();
      if (host.style.display === "none") return;
    }
    let needsDraw = Boolean(blend) || moodRamping(now);
    if (nextAt === 0) {
      nextAt = now + frameMs();
      needsDraw = true;
    } else if (now >= nextAt) {
      // Catch up modestly after a single frame boundary while skipping multi-frame rush stalls.
      for (let steps = 0; now >= nextAt && steps < 4; steps++) {
        if (advanceFrame(now)) {
          nextAt = now + frameMs();
          break;
        }
        nextAt += frameMs();
      }
      if (now - nextAt > 250) nextAt = now + frameMs(); // tab was hidden: don't fast-forward
      needsDraw = true;
    }
    if (needsDraw) draw(now);
    scheduleTick();
  }

  function scheduleExit() {
    if (!sheet) return;
    if (dwellTimer) { clearTimeout(dwellTimer); dwellTimer = 0; }
    if (oneShot && REACTIONS.has(playing)) return;
    if (!oneShot && !INSTANT_EXIT.has(playing)) {
      const rem = MIN_DWELL_MS - (performance.now() - stateSince);
      if (rem > 0) {
        dwellTimer = setTimeout(() => {
          dwellTimer = 0;
          if (!destroyed && (pending || reaction)) scheduleTick();
        }, rem);
        return;
      }
    }
    scheduleTick();
  }

  function drawSheetFrame(s, f, w, h, alpha, now) {
    const sx = (f % s.cols) * s.w;
    const sy = Math.floor(f / s.cols) * s.h;
    const mix = moodMixAt(now);
    const mb = moodColor && mix > 0.01 && s._mood && s._moodSrc === s.bitmap ? s._mood[moodColor] : null;
    if (mb && mix >= 0.99 && alpha >= 0.99) {
      ctx.globalAlpha = alpha;
      ctx.drawImage(mb, sx, sy, s.w, s.h, 0, 0, w, h);
      return;
    }
    ctx.globalAlpha = alpha;
    ctx.drawImage(s.bitmap, sx, sy, s.w, s.h, 0, 0, w, h);
    if (mb && mix > 0.01) {
      ctx.globalAlpha = alpha * mix;
      ctx.drawImage(mb, sx, sy, s.w, s.h, 0, 0, w, h);
    }
  }

  function draw(now = performance.now()) {
    if (!sheet) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.round(widthCss * dpr);
    const h = Math.round(((widthCss * sheet.h) / sheet.w) * dpr);
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
      canvas.style.width = `${w / dpr}px`;
      canvas.style.height = `${h / dpr}px`;
    }
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "low";
    ctx.clearRect(0, 0, w, h);

    if (blend) {
      const t = Math.max(0, Math.min(1, (now - blend.startedAt) / blend.ms));
      if (t < 1) {
        drawSheetFrame(blend.sheet, blend.frame, w, h, 1 - t, now);
        drawSheetFrame(sheet, frame, w, h, t, now);
        ctx.globalAlpha = 1;
        return;
      }
      blend = null;
    }
    ctx.globalAlpha = 1;
    drawSheetFrame(sheet, frame, w, h, 1, now);
  }

  // The prompt box is [data-testid="agent-input-box"]; find the rounded-border bar around its editor.
  const barCache = new WeakMap();
  let observedBar = null;
  let observedNodes = [];
  let lastPlaceAt = 0;
  let domObserver = null;
  let waitObserver = null;

  const barResizeObserver = typeof ResizeObserver === "function"
    ? new ResizeObserver(() => place())
    : null;

  function observeBar(bar, box) {
    if (!barResizeObserver || bar === observedBar) return;
    for (const el of observedNodes) barResizeObserver.unobserve(el);
    observedNodes = [];
    observedBar = bar;
    const seen = new Set();
    const watch = (el) => {
      if (!el || seen.has(el)) return;
      seen.add(el);
      observedNodes.push(el);
      barResizeObserver.observe(el);
    };
    watch(bar);
    watch(box);
    // Watch pane/layout ancestors too so closing the side panel shifts Atom promptly even if bar width stays fixed.
    for (let el = (box || bar).parentElement, i = 0; el && i < 6 && el !== document.documentElement; el = el.parentElement, i++) {
      watch(el);
      if (el === document.body) break;
    }
  }

  function barOf(box) {
    const cached = barCache.get(box);
    if (cached && cached.isConnected && box.contains(cached)) return cached;
    const editor = box.querySelector('[contenteditable]:not([contenteditable="false"]), textarea');
    let bar = null;
    for (let el = editor && editor.parentElement; el && el !== box; el = el.parentElement) {
      const cs = getComputedStyle(el);
      if (parseFloat(cs.borderTopWidth) > 0 || parseFloat(cs.borderTopLeftRadius) >= 8) bar = el;
    }
    bar = bar || editor || box;
    barCache.set(box, bar);
    return bar;
  }

  function currentBar() {
    const boxes = [...document.querySelectorAll('[data-testid="agent-input-box"]')].filter(
      (b) => b.getClientRects().length && b.getBoundingClientRect().width > 120,
    );
    if (!boxes.length) return null;
    const focused = boxes.find((b) => b.contains(document.activeElement));
    const box = focused || boxes[boxes.length - 1];
    return { box, bar: barOf(box) };
  }

  function hideHost() {
    if (host.style.display !== "none") {
      host.style.display = "none";
      cancelTick();
    }
  }

  let shownAt = "";
  function place() {
    if (destroyed || !activated) return;
    lastPlaceAt = performance.now();
    const found = currentBar();
    scanQuotaDom(true);
    if (!found || !sheet) {
      hideHost();
      return;
    }
    const { box, bar } = found;
    observeBar(bar, box);
    const r = bar.getBoundingClientRect();
    const vw = window.innerWidth || document.documentElement.clientWidth || 0;
    const vh = window.innerHeight || document.documentElement.clientHeight || 0;
    if (r.width <= 120 || r.height <= 0 || r.bottom <= 0 || r.top >= vh || r.right <= 0 || r.left >= vw) {
      hideHost();
      return;
    }
    const width = Math.round(Math.min(SIZE.max, Math.max(SIZE.min, r.width * SIZE.ofBar)));
    const height = (width * sheet.h) / sheet.w;

    // Lightweight modal occlusion check (avoids elementFromPoint forced reflows).
    const modal = typeof document.querySelector === "function"
      ? document.querySelector('[role="dialog"][aria-modal="true"], dialog[open]')
      : null;
    if (modal && modal !== box && !box.contains(modal) && (typeof modal.contains !== "function" || !modal.contains(box))) {
      const mr = modal.getBoundingClientRect();
      if (mr.left < r.right && mr.right > r.left && mr.top < r.bottom && mr.bottom > r.top) {
        hideHost();
        return;
      }
    }

    if (width !== widthCss) {
      widthCss = width;
      draw();
    }
    // Detect compact stacked cards directly above the prompt box (e.g. Queued Messages),
    // while ignoring tall scrollable chat transcript containers.
    let topAnchor = r.top;
    for (let el = (bar !== box ? bar : box); el && el !== document.body && el !== document.documentElement; el = el.parentElement) {
      const prev = el.previousElementSibling;
      if (prev && typeof prev.getBoundingClientRect === "function") {
        const pr = prev.getBoundingClientRect();
        if (
          pr.height > 20 &&
          pr.height < 260 &&
          pr.width > 120 &&
          Math.abs(pr.left - r.left) < 32 &&
          Math.abs(pr.right - r.right) < 32 &&
          pr.bottom <= topAnchor + 8 &&
          topAnchor - pr.bottom < 24
        ) {
          topAnchor = pr.top;
          if (barResizeObserver) barResizeObserver.observe(prev);
        }
      }
      if (el === box.parentElement) break;
    }
    const x = align === "left" ? Math.round(r.left + INSET) : Math.round(r.right - INSET - width);
    const y = Math.max(0, Math.round(topAnchor - height * (1 - SINK)));
    const key = `${x},${y}`;
    if (key !== shownAt) {
      host.style.transform = `translate(${x}px, ${y}px)`;
      shownAt = key;
    }
    const wasHidden = host.style.display === "none";
    host.style.display = "block";
    if (wasHidden) {
      draw();
      scheduleTick();
    }
  }

  function schedulePlace() {
    if (destroyed || !activated || placeTimer) return;
    placeTimer = setTimeout(() => {
      placeTimer = 0;
      place();
    }, 150);
  }

  function onVisibilityChange() {
    if (document.hidden) {
      cancelTick();
    } else {
      place();
      scheduleTick();
    }
  }

  // --- API for the launcher -------------------------------------------------------------
  window.__atom = {
    needSkin() {
      if (destroyed || !activated || !skin || (sheets[skin] && sheets[skin].idle) || loadingSkin === skin) {
        return null;
      }
      return skin;
    },
    setBase(state) {
      if (state === base) return;
      base = state;
      if (state !== "idle" && state !== "closed") {
        listening = false;
        if (listenTimer) { clearTimeout(listenTimer); listenTimer = 0; }
      }
      queueBase(effectiveBase());
    },
    setMood(nextMood) {
      const next = nextMood === "angry" || nextMood === "sad" ? nextMood : null;
      if (next === mood) return;
      const now = performance.now();
      const cur = moodMixAt(now);
      mood = next;
      moodAt = now;
      if (next) {
        moodColor = next;
        moodFrom = cur;
        moodTo = 1;
        if (sheet) ensureMoodBitmap(skin, playing, sheet, next);
      } else {
        moodFrom = cur;
        moodTo = 0;
      }
      paintVisible(now);
    },
    setLimit(info, modelName) {
      const obj = typeof info === "object" && info ? info : null;
      hookModel = String((obj ? obj.activeModel : modelName) || hookModel || "").trim();
      limitedModels.clear();
      if (obj && Array.isArray(obj.limitedModels)) for (const m of obj.limitedModels) if (m) limitedModels.add(String(m));
      else if (info === true && hookModel) limitedModels.add(hookModel);
      const next = obj ? Boolean(obj.activeLimited) : Boolean(info);
      if (uiModel && limitedModels.size) {
        if (hasLim(uiModel)) hookLimited = true;
        else if (next && hookModel && !mMatch(hookModel, uiModel)) hookLimited = false;
        else hookLimited = next;
      } else hookLimited = next;
      if (typeof document !== "undefined") scanQuotaDom(false);
      syncLimitSleep();
    },
    checkLimit() {
      scanQuotaDom(true);
    },
    react(state, id) {
      if (state === "dance" && (moodBlocksDance() || limitSleep)) return;
      if (id != null) {
        if (id === lastReactId) return;
        lastReactId = id;
      }
      reaction = state;
      scheduleTick();
    },
    __loadState: loadState,
    __loadSkin: loadSkin,
    destroy() {
      destroyed = true;
      blend = null;
      listening = false;
      mood = null;
      moodColor = null;
      hookLimited = false;
      domLimited = false;
      limitSleep = false;
      cancelTick();
      if (placeTimer) { clearTimeout(placeTimer); placeTimer = 0; }
      if (waitTimer) { clearTimeout(waitTimer); waitTimer = 0; }
      if (listenTimer) { clearTimeout(listenTimer); listenTimer = 0; }
      if (dwellTimer) { clearTimeout(dwellTimer); dwellTimer = 0; }
      if (limitScanTimer) { clearTimeout(limitScanTimer); limitScanTimer = 0; }
      if (waitObserver) { waitObserver.disconnect(); waitObserver = null; }
      if (domObserver) { domObserver.disconnect(); domObserver = null; }
      if (barResizeObserver) barResizeObserver.disconnect();
      observedBar = null;
      observedNodes = [];
      document.removeEventListener("DOMContentLoaded", onReadyCheck);
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", schedulePlace, { capture: true });
      window.removeEventListener("transitionend", schedulePlace);
      document.removeEventListener("focusin", place);
      document.removeEventListener("click", scheduleLimitScan, { capture: true });
      document.removeEventListener("input", onPromptInput, { capture: true });
      document.removeEventListener("keydown", onPromptInput, { capture: true });
      document.removeEventListener("visibilitychange", onVisibilityChange);
      for (const own of Object.values(sheets)) {
        for (const entry of Object.values(own)) {
          if (!entry) continue;
          closeBmp(entry.bitmap);
          if (entry._mood) Object.values(entry._mood).forEach(closeBmp);
        }
      }
      host.remove();
      delete window.__atom;
    },
    get state() {
      return {
        skin,
        align,
        playing,
        phase: currentPhase(),
        loop: sheet ? loopRange(sheet) : null,
        base,
        mood,
        listening,
        limitSleep,
        uiModel,
        pending,
        reaction,
        widthCss,
        frame,
        frames: sheet && sheet.durations.length,
        activated,
      };
    },
  };

  const hasPromptBox = () =>
    typeof document.querySelector === "function" &&
    Boolean(document.querySelector('[data-testid="agent-input-box"]'));

  const mount = () => {
    if (!destroyed && !host.isConnected && document.documentElement) {
      document.documentElement.appendChild(host);
    }
  };

  function onReadyCheck() {
    if (!destroyed && !activated && hasPromptBox()) activate();
  }

  function activate() {
    if (destroyed || activated) return;
    activated = true;
    if (waitObserver) {
      waitObserver.disconnect();
      waitObserver = null;
    }
    if (waitTimer) {
      clearTimeout(waitTimer);
      waitTimer = 0;
    }
    document.removeEventListener("DOMContentLoaded", onReadyCheck);
    mount();
    domObserver = new MutationObserver(() => {
      mount();
      schedulePlace();
      scheduleLimitScan();
    });
    domObserver.observe(document.documentElement || document, { childList: true });
    window.addEventListener("resize", place, { passive: true });
    window.addEventListener("scroll", schedulePlace, { capture: true, passive: true });
    window.addEventListener("transitionend", schedulePlace, { passive: true });
    document.addEventListener("focusin", place, { passive: true });
    document.addEventListener("click", scheduleLimitScan, { capture: true, passive: true });
    document.addEventListener("input", onPromptInput, { capture: true, passive: true });
    document.addEventListener("keydown", onPromptInput, { capture: true, passive: true });
    document.addEventListener("visibilitychange", onVisibilityChange);
    scanQuotaDom(false);
  }

  if (hasPromptBox()) {
    activate();
  } else {
    document.addEventListener("DOMContentLoaded", onReadyCheck, { once: true });
    waitObserver = new MutationObserver(() => {
      if (waitTimer) return;
      waitTimer = setTimeout(() => {
        waitTimer = 0;
        onReadyCheck();
      }, 100);
    });
    waitObserver.observe(document, { childList: true, subtree: true });
  }
})();

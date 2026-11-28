import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const INJECT_SRC = fs.readFileSync(path.join(ROOT, "atom_inject.js"), "utf8");
const LAB_SRC = fs.readFileSync(path.join(ROOT, "atom_lab.js"), "utf8");

function makeHarness({
  withPromptBox = true,
  preDom = false,
  skinNames = ["atom"],
  defaultSkin = "",
  initialStorage = null,
  imageSize = { w: 200, h: 160 },
  onSeedPixels = null,
  capturedBuffers = null,
} = {}) {
  let nowMs = 1000;
  let nextTimerId = 1;
  let nextRafId = 1;
  const timers = new Map();
  const rafs = new Map();
  const listeners = new Map();
  const mutationObservers = [];
  const resizeObservers = [];
  const drawCalls = [];
  const fillCalls = [];
  const createdBitmaps = [];
  const offscreenCount = { count: 0 };
  let occludedModal = null;
  const alertNodes = [];
  let barRect = { left: 100, right: 1000, top: 600, bottom: 680, width: 900, height: 80 };

  class MockElement {
    constructor(tag) {
      this.tagName = tag.toUpperCase();
      this.id = "";
      this.className = "";
      this.style = { display: "", transform: "", setProperty: () => {} };
      this.children = [];
      this.parentElement = null;
      this.shadow = null;
      this.width = 0;
      this.height = 0;
      this.title = "";
      this.disabled = false;
      this.value = "";
      this.dataset = {};
      this._classes = new Set();
      this.classList = {
        add: (c) => this._classes.add(c),
        remove: (c) => this._classes.delete(c),
        contains: (c) => this._classes.has(c),
      };
      this.listeners = new Map();
      this.isConnected = false;
      this._attrs = new Map();
      this._text = "";
    }
    get previousElementSibling() {
      if (!this.parentElement) return null;
      const idx = this.parentElement.children.indexOf(this);
      return idx > 0 ? this.parentElement.children[idx - 1] : null;
    }
    get textContent() {
      if (this._text) return this._text;
      return this.children.map((c) => c.textContent).join(" ").trim();
    }
    set textContent(v) { this._text = String(v ?? ""); }
    setAttribute(k, v) { this._attrs.set(k, String(v)); }
    getAttribute(k) { return this._attrs.get(k) ?? null; }
    appendChild(child) {
      child.parentElement = this;
      child.isConnected = this.isConnected;
      this.children.push(child);
      return child;
    }
    remove() {
      this.removed = true;
      if (this.parentElement) {
        this.parentElement.children = this.parentElement.children.filter((c) => c !== this);
        this.parentElement = null;
      }
      this.isConnected = false;
    }
    contains(other) {
      let cur = other;
      while (cur) {
        if (cur === this) return true;
        cur = cur.parentElement;
      }
      return false;
    }
    attachShadow() {
      const root = new MockElement("shadow-root");
      root.innerHTML = "";
      root._q = {};
      root.querySelector = (sel) => {
        if (sel === "canvas") return root._canvas || (root._canvas = new MockElement("canvas"));
        if (sel === "#hit") return root._hit || (root._hit = new MockElement("div"));
        if (root._q[sel]) return root._q[sel];
        if ([".menu", ".backdrop", ".closeBtn", ".doneBtn", ".search", ".grid"].includes(sel)) {
          const el = new MockElement(sel.includes("Btn") ? "button" : sel === ".search" ? "input" : "div");
          root._q[sel] = el;
          return el;
        }
        return null;
      };
      this.shadow = root;
      return root;
    }
    addEventListener(type, fn) {
      if (!this.listeners.has(type)) this.listeners.set(type, []);
      this.listeners.get(type).push(fn);
    }
    getContext() {
      const ctxObj = {
        imageSmoothingEnabled: false,
        imageSmoothingQuality: "low",
        globalAlpha: 1,
        fillStyle: "#000000",
        save() {},
        restore() {},
        beginPath() {},
        rect() {},
        clip() {},
        translate() {},
        rotate() {},
        clearRect() {},
        fillRect(x, y, w, h) { fillCalls.push({ x, y, w, h, fillStyle: ctxObj.fillStyle, alpha: ctxObj.globalAlpha }); },
        drawImage(_bmp, sx, sy) { drawCalls.push({ sx, sy, alpha: ctxObj.globalAlpha }); },
      };
      return ctxObj;
    }
    getClientRects() { return [this.getBoundingClientRect()]; }
    getBoundingClientRect() { return { ...barRect }; }
    querySelector(sel) {
      if (sel.includes("contenteditable") || sel.includes("textarea")) return this._editor || null;
      return null;
    }
  }

  const docEl = new MockElement("html");
  docEl.isConnected = true;
  docEl.clientWidth = 1280;
  docEl.clientHeight = 800;
  const body = new MockElement("body");
  docEl.appendChild(body);
  const panel = new MockElement("div");
  const pane = new MockElement("div");
  panel.appendChild(pane);
  body.appendChild(panel);

  let boxes = [];
  function createPromptBox() {
    const box = new MockElement("div");
    box.setAttribute("data-testid", "agent-input-box");
    const bar = new MockElement("div");
    const editor = new MockElement("textarea");
    bar.appendChild(editor);
    box.appendChild(bar);
    box._editor = editor;
    box._bar = bar;
    pane.appendChild(box);
    boxes.push(box);
    return box;
  }
  if (withPromptBox) createPromptBox();

  const storage = new Map(Object.entries(initialStorage || {}));
  const document = {
    documentElement: preDom ? null : docEl,
    body,
    activeElement: null,
    hidden: false,
    createElement: (tag) => new MockElement(tag),
    querySelector: (sel) => {
      if (sel === '[data-testid="agent-input-box"]') return boxes[0] || null;
      if (sel.includes('role="dialog"')) return occludedModal;
      return null;
    },
    querySelectorAll: (sel) => {
      if (sel === '[data-testid="agent-input-box"]') return boxes;
      if (sel.includes("alert") || sel.includes("quota") || sel.includes("limit")) return alertNodes;
      return [];
    },
    addEventListener: (type, fn) => {
      if (!listeners.has(type)) listeners.set(type, new Set());
      listeners.get(type).add(fn);
    },
    removeEventListener: (type, fn) => {
      listeners.get(type)?.delete(fn);
    },
  };

  const windowObj = {
    document,
    innerWidth: 1280,
    innerHeight: 800,
    devicePixelRatio: 1,
    localStorage: {
      getItem: (k) => (storage.has(k) ? storage.get(k) : null),
      setItem: (k, v) => storage.set(k, String(v)),
    },
    getComputedStyle: () => ({ borderTopWidth: "1px", borderTopLeftRadius: "12px" }),
    performance: { now: () => nowMs },
    setTimeout: (fn, delay = 0) => {
      const id = nextTimerId++;
      timers.set(id, { at: nowMs + Math.max(0, delay), fn });
      return id;
    },
    clearTimeout: (id) => timers.delete(id),
    requestAnimationFrame: (fn) => {
      const id = nextRafId++;
      rafs.set(id, { at: nowMs + 16, fn });
      return id;
    },
    cancelAnimationFrame: (id) => rafs.delete(id),
    addEventListener: (type, fn) => {
      if (!listeners.has(`win:${type}`)) listeners.set(`win:${type}`, new Set());
      listeners.get(`win:${type}`).add(fn);
    },
    removeEventListener: (type, fn) => {
      listeners.get(`win:${type}`)?.delete(fn);
    },
    atob: (s) => Buffer.from(s, "base64").toString("binary"),
    Blob: class MockBlob {},
    createImageBitmap: async (arg) => {
      const bmp = {
        width: (arg && arg.width) || imageSize.w,
        height: (arg && arg.height) || imageSize.h,
        closed: false,
        close() { this.closed = true; },
      };
      createdBitmaps.push(bmp);
      return bmp;
    },
    OffscreenCanvas: class MockOffscreenCanvas {
      constructor(w, h) {
        this.width = w;
        this.height = h;
        offscreenCount.count += 1;
      }
      getContext() {
        const data = new Uint8ClampedArray(this.width * this.height * 4);
        if (onSeedPixels) {
          onSeedPixels(data, this.width, this.height);
        } else {
          // Seed one saturated blue pixel (r=20, g=130, b=230, a=255)
          data[0] = 20; data[1] = 130; data[2] = 230; data[3] = 255;
        }
        return {
          drawImage() {},
          getImageData: () => ({ data }),
          putImageData(img) {
            if (capturedBuffers && img && img.data) {
              capturedBuffers.push(new Uint8ClampedArray(img.data));
            }
          },
        };
      }
    },
    MessageChannel: class MockMessageChannel {
      constructor() {
        this.port1 = { onmessage: null };
        this.port2 = { postMessage: () => queueMicrotask(() => this.port1.onmessage?.({ data: null })) };
      }
    },
    MutationObserver: class MockMutationObserver {
      constructor(cb) {
        this.cb = cb;
        this.disconnected = false;
        mutationObservers.push(this);
      }
      observe() {}
      disconnect() { this.disconnected = true; }
      trigger() { if (!this.disconnected) this.cb([]); }
    },
    ResizeObserver: class MockResizeObserver {
      constructor(cb) {
        this.cb = cb;
        this.targets = new Set();
        resizeObservers.push(this);
      }
      observe(el) { this.targets.add(el); }
      unobserve(el) { this.targets.delete(el); }
      disconnect() { this.targets.clear(); }
    },
    Uint8Array,
    WeakMap,
    Set,
    Map,
    Object,
    Math,
    JSON,
    Promise,
  };
  windowObj.window = windowObj;
  windowObj.globalThis = windowObj;

  const source = INJECT_SRC
    .replace("const SKIN_NAMES = __ATOM_SKIN_NAMES__;", `const SKIN_NAMES = ${JSON.stringify(skinNames)};`)
    .replace('"__ATOM_DEFAULT_SKIN__"', JSON.stringify(defaultSkin));
  vm.runInNewContext(source, windowObj);

  async function flushMicrotasks() {
    for (let i = 0; i < 6; i++) await Promise.resolve();
  }

  async function advance(ms) {
    const target = nowMs + ms;
    while (true) {
      let nextTime = Infinity;
      let kind = null;
      let key = null;
      for (const [id, t] of timers) {
        if (t.at <= target && t.at < nextTime) { nextTime = t.at; kind = "timer"; key = id; }
      }
      for (const [id, r] of rafs) {
        if (r.at <= target && r.at < nextTime) { nextTime = r.at; kind = "raf"; key = id; }
      }
      if (!kind) break;
      nowMs = nextTime;
      if (kind === "timer") {
        const t = timers.get(key);
        timers.delete(key);
        t.fn();
      } else {
        const r = rafs.get(key);
        rafs.delete(key);
        r.fn(nowMs);
      }
      await flushMicrotasks();
    }
    nowMs = target;
  }

  return {
    window: windowObj,
    document,
    docEl,
    panel,
    pane,
    boxes,
    timers,
    rafs,
    mutationObservers,
    resizeObservers,
    drawCalls,
    fillCalls,
    createdBitmaps,
    offscreenCount,
    createPromptBox,
    attachDocEl: () => { document.documentElement = docEl; },
    triggerDomContentLoaded: () => {
      for (const fn of [...(listeners.get("DOMContentLoaded") || [])]) fn();
    },
    triggerClick: () => {
      for (const fn of [...(listeners.get("click") || [])]) fn({});
    },
    alertNodes,
    createEl: (tag) => new MockElement(tag),
    triggerInput: (target = boxes[0]?._editor) => {
      for (const fn of [...(listeners.get("input") || [])]) fn({ target });
    },
    setOccludedModal: (modal) => { occludedModal = modal; },
    setBarRect: (r) => { barRect = { ...barRect, ...r }; },
    triggerResize: () => {
      for (const fn of listeners.get("win:resize") || []) fn();
    },
    triggerResizeObserver: () => {
      for (const ro of resizeObservers) ro.cb([]);
    },
    triggerTransitionEnd: () => {
      for (const fn of listeners.get("win:transitionend") || []) fn();
    },
    triggerHitClick: (opts = {}) => {
      const host = docEl.children.find((c) => c.id === "atom-mascot");
      const hit = host?.shadow?.querySelector("#hit");
      const fns = hit?.listeners.get("click") || [];
      for (const fn of fns) fn({ stopPropagation() {}, shiftKey: Boolean(opts.shiftKey), altKey: Boolean(opts.altKey) });
      return hit;
    },
    triggerHitContextMenu: (opts = {}) => {
      const host = docEl.children.find((c) => c.id === "atom-mascot");
      const hit = host?.shadow?.querySelector("#hit");
      const fns = hit?.listeners.get("contextmenu") || [];
      for (const fn of fns) fn({ preventDefault() {}, stopPropagation() {}, clientX: opts.clientX ?? 200, clientY: opts.clientY ?? 300 });
      return hit;
    },
    triggerDocEvent: (type, evt = {}) => {
      for (const fn of [...(listeners.get(type) || [])]) fn(evt);
    },
    mountLab: (catalog = skinNames.map((id) => ({ id, name: id, tagline: "", accent: "#38bdf8", states: 19 }))) => {
      const labCode = LAB_SRC.replace(
        "const CATALOG = __ATOM_SKIN_CATALOG__;",
        `const CATALOG = ${JSON.stringify(catalog)};`,
      );
      vm.runInNewContext(labCode, windowObj);
      return docEl.children.find((c) => c.id === "atom-lab") || null;
    },
    storage,
    advance,
    flushMicrotasks,
  };
}

function fakeSkinPayload() {
  const b64 = Buffer.from("webp").toString("base64");
  return {
    idle: { webp: b64, w: 200, h: 160, cols: 4, durations: [100, 100, 100, 100] },
    typing: { webp: b64, w: 200, h: 160, cols: 4, durations: [100, 100, 100, 100] },
    thinking: { webp: b64, w: 200, h: 160, cols: 4, durations: [100, 100, 100, 100] },
  };
}

test("stays inert without prompt box, then activates when mounted", async () => {
  const h = makeHarness({ withPromptBox: false });
  assert.equal(h.window.__atom.needSkin(), null);
  assert.equal(h.timers.size, 0);
  assert.equal(h.rafs.size, 0);
  assert.equal(h.window.__atom.state.activated, false);

  h.createPromptBox();
  h.mutationObservers[0].trigger();
  await h.advance(120);

  assert.equal(h.window.__atom.state.activated, true);
  assert.equal(h.window.__atom.needSkin(), "atom");

  const payload = fakeSkinPayload();
  await h.window.__atom.__loadSkin("atom", payload);
  assert.equal(h.window.__atom.needSkin(), null);
  assert.equal(payload.idle.webp, null);
  assert.equal(h.offscreenCount.count, 0);
  assert.ok(h.docEl.children.some((c) => c.id === "atom-mascot"));
});

test("survives pre-DOM injection when documentElement is initially null", async () => {
  const h = makeHarness({ withPromptBox: false, preDom: true });
  assert.equal(h.window.__atom.state.activated, false);
  assert.equal(h.window.__atom.needSkin(), null);

  h.attachDocEl();
  h.createPromptBox();
  h.triggerDomContentLoaded();

  assert.equal(h.window.__atom.state.activated, true);
  assert.equal(h.window.__atom.needSkin(), "atom");
  await h.window.__atom.__loadSkin("atom", fakeSkinPayload());
  assert.ok(h.docEl.children.some((c) => c.id === "atom-mascot"));
});

test("active reaction is not rushed by setBase, while normal states are rushed", async () => {
  const h = makeHarness();
  await h.window.__atom.__loadSkin("atom", fakeSkinPayload());
  await h.advance(20);

  h.window.__atom.react("happy", 1);
  await h.advance(150);
  assert.equal(h.window.__atom.state.playing, "happy");

  const startMs = Date.now();
  void startMs;
  h.window.__atom.setBase("typing");
  // Happy has 4 frames * 100ms / 1.4 speed ~= 286ms total; verify after 100ms it is still playing happy cleanly
  await h.advance(100);
  assert.equal(h.window.__atom.state.playing, "happy");

  // Once happy finishes its loop naturally (~290ms total), it transitions to typing
  await h.advance(300);
  assert.equal(h.window.__atom.state.playing, "typing");
});

test("modal occlusion hides mascot and top-edge clamping keeps y >= 0", async () => {
  const h = makeHarness();
  await h.window.__atom.__loadSkin("atom", fakeSkinPayload());
  await h.advance(20);

  const host = h.docEl.children.find((c) => c.id === "atom-mascot");
  assert.equal(host.style.display, "block");

  // Ancestor container around box must NOT count as modal occlusion
  h.setOccludedModal({ contains: (el) => el === h.boxes[0], getBoundingClientRect: () => ({ left: 0, right: 1280, top: 0, bottom: 800 }) });
  h.triggerResize();
  assert.equal(host.style.display, "block");

  // Occlude with an overlapping aria-modal dialog outside prompt box
  h.setOccludedModal({ contains: () => false, getBoundingClientRect: () => ({ left: 200, right: 1100, top: 300, bottom: 720 }) });
  h.triggerResize();
  assert.equal(host.style.display, "none");
  assert.equal(h.timers.size, 0);
  assert.equal(h.rafs.size, 0);

  // Restore bar visibility near top of viewport -> y clamps to >= 0
  h.setOccludedModal(null);
  h.setBarRect({ top: 10, bottom: 90 });
  h.triggerResize();
  assert.equal(host.style.display, "block");
  assert.match(host.style.transform, /translate\(\d+px, 0px\)/);
});

test("idle fidget plays typing after 7s and lazy fallback recolours once", async () => {
  const h = makeHarness();
  await h.window.__atom.__loadSkin("atom", fakeSkinPayload());
  await h.advance(20);
  assert.equal(h.window.__atom.state.playing, "idle");

  await h.advance(7300);
  assert.equal(h.window.__atom.state.playing, "typing");

  await h.advance(500);
  assert.equal(h.window.__atom.state.playing, "idle");

  // Trigger lazy fallback state "sad" -> OffscreenCanvas runs once and caches
  h.window.__atom.react("sad", 2);
  await h.advance(600);
  assert.equal(h.window.__atom.state.playing, "sad");
  assert.equal(h.offscreenCount.count, 1);

  h.window.__atom.react("sad", 3);
  await h.advance(900);
  assert.equal(h.offscreenCount.count, 1);
});

test("destroy cleans up host, observers, timers, and global API", async () => {
  const h = makeHarness();
  await h.window.__atom.__loadSkin("atom", fakeSkinPayload());
  await h.advance(20);

  h.window.__atom.destroy();
  assert.equal(h.window.__atom, undefined);
  assert.equal(h.timers.size, 0);
  assert.equal(h.rafs.size, 0);
  assert.ok(!h.docEl.children.some((c) => c.id === "atom-mascot"));
  assert.ok(h.mutationObservers.every((m) => m.disconnected));
});

function phasedSkinPayload() {
  const b64 = Buffer.from("webp").toString("base64");
  return {
    idle: { webp: b64, w: 200, h: 160, cols: 10, durations: [100, 100, 100, 100], loop: [0, 3] },
    typing: {
      webp: b64,
      w: 200,
      h: 160,
      cols: 10,
      durations: [100, 100, 100, 100, 100, 100, 100, 100],
      loop: [2, 5],
    },
    thinking: {
      webp: b64,
      w: 200,
      h: 160,
      cols: 10,
      durations: [100, 100, 100, 100, 100, 100],
      loop: [1, 4],
    },
  };
}

test("sustained 3-phase typing stays in loop without closing laptop and cancels exit cleanly", async () => {
  const h = makeHarness();
  await h.window.__atom.__loadSkin("atom", phasedSkinPayload());
  await h.advance(20);

  const seenFrames = [];
  h.window.__atom.setBase("typing");
  // Wait for idle to rush/exit into typing
  await h.advance(500);
  assert.equal(h.window.__atom.state.playing, "typing");

  // Sample across 1.5s: typing must enter loop [2..5] and NEVER play outro [6..7]
  for (let i = 0; i < 15; i++) {
    await h.advance(100);
    seenFrames.push(h.window.__atom.state.frame);
    assert.equal(h.window.__atom.state.playing, "typing");
  }
  assert.ok(seenFrames.some((f) => f >= 2 && f <= 5));
  assert.ok(seenFrames.every((f) => f <= 5), `unexpected outro frames: ${seenFrames}`);

  // Start exiting toward idle, then return to typing before outro begins -> cancels exit
  h.window.__atom.setBase("idle");
  assert.equal(h.window.__atom.state.pending, "idle");
  h.window.__atom.setBase("typing");
  assert.equal(h.window.__atom.state.pending, null);
  await h.advance(600);
  assert.equal(h.window.__atom.state.playing, "typing");
  assert.ok(h.window.__atom.state.frame <= 5);
});

test("leaving 3-phase typing plays outro before crossfading into thinking", async () => {
  const h = makeHarness();
  await h.window.__atom.__loadSkin("atom", phasedSkinPayload());
  await h.advance(20);

  h.window.__atom.setBase("typing");
  await h.advance(800);
  assert.equal(h.window.__atom.state.playing, "typing");
  assert.equal(h.window.__atom.state.phase, "loop");

  h.window.__atom.setBase("thinking");
  let sawOutro = false;
  let switchedAt = -1;
  h.drawCalls.length = 0;
  for (let step = 0; step < 50; step++) {
    await h.advance(60);
    const st = h.window.__atom.state;
    if (st.playing === "typing" && st.phase === "outro") sawOutro = true;
    if (st.playing === "thinking" && switchedAt < 0) {
      switchedAt = step;
      break;
    }
  }
  assert.ok(sawOutro, "expected typing outro frames before switching to thinking");
  assert.ok(switchedAt >= 0, "expected transition to thinking");

  // Advance across the 140ms blend window and verify blended alpha draws then full opacity
  await h.advance(80);
  assert.ok(h.drawCalls.some((d) => d.alpha > 0 && d.alpha < 1), "expected crossfade alpha draws");
  await h.advance(160);
  assert.equal(h.drawCalls[h.drawCalls.length - 1].alpha, 1);
});

test("idle fidget plays 3-phase typing intro -> 1 loop -> outro and returns to idle", async () => {
  const h = makeHarness();
  await h.window.__atom.__loadSkin("atom", phasedSkinPayload());
  await h.advance(20);

  await h.advance(7500);
  assert.equal(h.window.__atom.state.playing, "typing");

  let sawOutro = false;
  for (let i = 0; i < 16; i++) {
    await h.advance(100);
    const st = h.window.__atom.state;
    if (st.playing === "typing" && st.phase === "outro") sawOutro = true;
    if (st.playing === "idle") break;
  }
  assert.ok(sawOutro, "expected fidget to play typing outro");
  assert.equal(h.window.__atom.state.playing, "idle");
});

test("__loadState loads per-state sprites on demand and upgrades active fallback", async () => {
  const h = makeHarness();
  const base = fakeSkinPayload();
  await h.window.__atom.__loadState("atom", "idle", base.idle);
  assert.equal(h.window.__atom.needSkin(), null);
  await h.advance(20);
  assert.equal(h.window.__atom.state.playing, "idle");

  // Switch to "running" before its sheet loads -> plays fallback, then upgrades seamlessly
  h.window.__atom.setBase("running");
  await h.advance(450);
  assert.equal(h.window.__atom.state.playing, "running");

  const runSheet = {
    webp: Buffer.from("webp").toString("base64"),
    w: 200,
    h: 160,
    cols: 10,
    durations: [100, 100, 100, 100, 100, 100],
    loop: [1, 4],
  };
  await h.window.__atom.__loadState("atom", "running", runSheet);
  assert.equal(runSheet.webp, null);
  assert.equal(h.window.__atom.state.frames, 6);
  assert.deepEqual([...h.window.__atom.state.loop], [1, 4]);
});

test("client-side listening triggers on prompt input and returns to idle after 2s", async () => {
  const h = makeHarness();
  const payload = {
    ...fakeSkinPayload(),
    listening: {
      webp: Buffer.from("webp").toString("base64"),
      w: 200,
      h: 160,
      cols: 10,
      durations: [100, 100, 100, 100],
      loop: [0, 3],
    },
  };
  await h.window.__atom.__loadSkin("atom", payload);
  await h.advance(20);
  assert.equal(h.window.__atom.state.playing, "idle");

  h.triggerInput();
  assert.equal(h.window.__atom.state.listening, true);
  await h.advance(450);
  assert.equal(h.window.__atom.state.playing, "listening");

  // After 2s of no typing, listening expires and Atom returns to idle
  await h.advance(2600);
  assert.equal(h.window.__atom.state.listening, false);
  assert.equal(h.window.__atom.state.playing, "idle");

  // Busy agent states are never overridden by prompt input
  h.window.__atom.setBase("typing");
  await h.advance(500);
  assert.equal(h.window.__atom.state.playing, "typing");
  h.triggerInput();
  assert.equal(h.window.__atom.state.playing, "typing");
});

test("new one-shot reactions (error, done, canceled, tired) are not rushed by setBase", async () => {
  for (const [idx, emo] of ["error", "done", "canceled", "tired"].entries()) {
    const h = makeHarness();
    const payload = {
      ...fakeSkinPayload(),
      [emo]: {
        webp: Buffer.from("webp").toString("base64"),
        w: 200,
        h: 160,
        cols: 10,
        durations: [200, 200, 200, 200],
        loop: [0, 3],
      },
    };
    await h.window.__atom.__loadSkin("atom", payload);
    await h.advance(20);

    h.window.__atom.react(emo, idx + 1);
    await h.advance(450);
    assert.equal(h.window.__atom.state.playing, emo);

    h.window.__atom.setBase("typing");
    await h.advance(300);
    // 4 frames * 200ms = 800ms natural loop -> still playing reaction after 300ms
    assert.equal(h.window.__atom.state.playing, emo);

    await h.advance(700);
    assert.equal(h.window.__atom.state.playing, "typing");
  }
});

test("click plays dance one-shot even with one skin; Shift+click switches with multiple skins", async () => {
  const makePayload = () => ({
    ...fakeSkinPayload(),
    dance: {
      webp: Buffer.from("webp").toString("base64"),
      w: 200,
      h: 160,
      cols: 4,
      durations: Array(8).fill(65),
      loop: [1, 6],
    },
  });
  const h1 = makeHarness({ skinNames: ["atom"] });
  await h1.window.__atom.__loadSkin("atom", makePayload());
  await h1.advance(20);

  const hit1 = h1.triggerHitClick();
  assert.ok(hit1 && !hit1.removed);
  await h1.advance(20);
  assert.equal(h1.window.__atom.state.playing, "dance");

  let sawOutro = false;
  for (let i = 0; i < 12; i++) {
    await h1.advance(60);
    const st = h1.window.__atom.state;
    if (st.playing === "dance" && st.phase === "outro") sawOutro = true;
    if (st.playing === "idle") break;
  }
  assert.ok(sawOutro, "expected dance to play outro cleanly back to idle");
  assert.equal(h1.window.__atom.state.playing, "idle");

  // Multi-skin: plain click starts dance immediately; Shift+click switches skin
  const h2 = makeHarness({ skinNames: ["atom", "alt"] });
  await h2.window.__atom.__loadSkin("atom", makePayload());
  await h2.window.__atom.__loadSkin("alt", makePayload());
  await h2.advance(20);
  assert.equal(h2.window.__atom.state.skin, "atom");
  h2.triggerHitClick({ shiftKey: false });
  await h2.advance(20);
  assert.equal(h2.window.__atom.state.playing, "dance");
  h2.triggerHitClick({ shiftKey: true });
  assert.equal(h2.window.__atom.state.skin, "alt");
});

test("fresh install defaults to Atom V2; a saved or injected choice still wins", () => {
  const fresh = makeHarness({ skinNames: ["atom", "base-qt", "v2"] });
  assert.equal(fresh.window.__atom.state.skin, "v2");
  fresh.window.__atom.destroy();

  const saved = makeHarness({ skinNames: ["atom", "v2"], initialStorage: { "atom.skin": "atom" } });
  assert.equal(saved.window.__atom.state.skin, "atom");
  saved.window.__atom.destroy();

  const injected = makeHarness({ skinNames: ["atom", "v2"], defaultSkin: "atom" });
  assert.equal(injected.window.__atom.state.skin, "atom");
  injected.window.__atom.destroy();

  const noV2 = makeHarness({ skinNames: ["atom", "chibi"] });
  assert.equal(noV2.window.__atom.state.skin, "atom");
  noV2.window.__atom.destroy();
});

test("Alt+click switches mascot side (left/right) and persists in storage", async () => {
  const h = makeHarness({ skinNames: ["atom"] });
  await h.window.__atom.__loadSkin("atom", fakeSkinPayload());
  await h.advance(20);
  const host = h.docEl.children.find((c) => c.id === "atom-mascot");
  const rightX = parseInt(host.style.transform.match(/translate\((-?\d+)px/)[1], 10);

  assert.equal(h.window.__atom.state.align, "right");
  h.triggerHitClick({ altKey: true });
  assert.equal(h.window.__atom.state.align, "left");
  assert.equal(h.window.localStorage.getItem("atom.align"), "left");
  const leftX = parseInt(host.style.transform.match(/translate\((-?\d+)px/)[1], 10);
  assert.equal(leftX, 120); // barRect.left (100) + INSET (20)
  assert.ok(leftX < rightX);

  h.triggerHitClick({ altKey: true });
  assert.equal(h.window.__atom.state.align, "right");
  assert.equal(h.window.localStorage.getItem("atom.align"), "right");
});

test("automatically hoists above compact stacked cards (e.g. Queued Messages) but ignores tall chat panes", async () => {
  const h = makeHarness({ skinNames: ["atom"] });
  await h.window.__atom.__loadSkin("atom", fakeSkinPayload());
  await h.advance(20);

  const host = h.docEl.children.find((c) => c.id === "atom-mascot");
  assert.ok(host.style.transform.includes("translate("));
  const normalY = parseInt(host.style.transform.match(/,\s*(\d+)px\)/)[1], 10);

  // Tall chat transcript above the prompt box should NOT hoist Atom
  const chatPane = h.createEl("div");
  chatPane.getBoundingClientRect = () => ({ top: 50, bottom: 600, left: 100, right: 1000, width: 900, height: 550 });
  chatPane.parentElement = h.pane;
  chatPane.isConnected = true;
  h.pane.children.unshift(chatPane);
  h.triggerResize();
  await h.advance(200);
  assert.equal(parseInt(host.style.transform.match(/,\s*(\d+)px\)/)[1], 10), normalY);

  // Compact queued-messages card directly above the prompt box SHOULD hoist Atom
  h.pane.children.shift();
  const queueCard = h.createEl("div");
  queueCard.getBoundingClientRect = () => ({ top: 540, bottom: 600, left: 100, right: 1000, width: 900, height: 60 });
  queueCard.parentElement = h.pane;
  queueCard.isConnected = true;
  h.pane.children.unshift(queueCard);

  h.triggerResize();
  await h.advance(200);

  const hoistedY = parseInt(host.style.transform.match(/,\s*(\d+)px\)/)[1], 10);
  assert.ok(hoistedY < normalY, `Expected hoisted Y (${hoistedY}) to be above normal Y (${normalY})`);
  assert.equal(normalY - hoistedY, 60);
});

test("hoists over nested/multi-stacked/inset cards on mutation and after switching skins", async () => {
  const b64 = Buffer.from("webp").toString("base64");
  const skin150 = () => ({
    idle: { webp: b64, w: 150, h: 120, cols: 10, durations: Array(10).fill(100), loop: [0, 9] },
    listening: { webp: b64, w: 150, h: 120, cols: 10, durations: Array(10).fill(100), loop: [0, 9] },
  });
  const h = makeHarness({ skinNames: ["atom", "chibi", "v2"], imageSize: { w: 150, h: 120 } });
  await h.window.__atom.__loadSkin("atom", skin150());
  await h.window.__atom.__loadSkin("chibi", skin150());
  await h.window.__atom.__loadSkin("v2", skin150());
  await h.advance(20);

  const host = h.docEl.children.find((c) => c.id === "atom-mascot");
  const normalY = parseInt(host.style.transform.match(/,\s*(\d+)px\)/)[1], 10);

  // Stacked cards placed on ancestor h.panel (above wrapper h.pane) with a 0px spacer & inset width
  const spacer = h.createEl("div");
  spacer.getBoundingClientRect = () => ({ top: 600, bottom: 600, left: 100, right: 1000, width: 900, height: 0 });
  const queueCard = h.createEl("div");
  queueCard.getBoundingClientRect = () => ({ top: 550, bottom: 600, left: 120, right: 980, width: 860, height: 50 });
  const stepsCard = h.createEl("div");
  stepsCard.getBoundingClientRect = () => ({ top: 510, bottom: 550, left: 120, right: 980, width: 860, height: 40 });
  const chatTranscript = h.createEl("div");
  chatTranscript.className = "conversation-messages";
  chatTranscript.getBoundingClientRect = () => ({ top: 410, bottom: 510, left: 100, right: 1000, width: 900, height: 100 });

  h.panel.children.unshift(chatTranscript, stepsCard, queueCard, spacer);
  for (const c of [chatTranscript, stepsCard, queueCard, spacer]) c.parentElement = h.panel;

  // Fire footer MutationObserver (last observer created by observeBar) -> schedules & runs place()
  h.mutationObservers.forEach((m) => m.trigger());
  await h.advance(200);

  const multiHoistedY = parseInt(host.style.transform.match(/,\s*(\d+)px\)/)[1], 10);
  assert.equal(normalY - multiHoistedY, 90, "should hoist over both 50px + 40px stacked cards, skip 0px spacer, ignore chatTranscript");

  // Switch skins (atom -> chibi -> v2) while stacked cards stay mounted -> hoisted Y stays intact
  for (const nextSkin of ["chibi", "v2"]) {
    h.window.__atom.setSkin(nextSkin);
    await h.advance(1400);
    const y = parseInt(host.style.transform.match(/,\s*(\d+)px\)/)[1], 10);
    assert.equal(y, multiHoistedY, `expected ${nextSkin} to stay hoisted at ${multiHoistedY}`);
  }
  h.window.__atom.destroy();
});

test("sustained angry base holds in 30f loop and exits cleanly via 6f outro on idle", async () => {
  const h = makeHarness();
  const payload = {
    ...fakeSkinPayload(),
    angry: {
      webp: Buffer.from("webp").toString("base64"),
      w: 200,
      h: 160,
      cols: 10,
      durations: Array(12).fill(80), // 0..1 intro, 2..8 loop, 9..11 outro
      loop: [2, 8],
    },
  };
  await h.window.__atom.__loadSkin("atom", payload);
  await h.advance(20);

  h.window.__atom.setBase("angry");
  await h.advance(500);
  assert.equal(h.window.__atom.state.playing, "angry");

  // Stays looping across several loop cycles until Stop resets base to idle
  await h.advance(1400);
  assert.equal(h.window.__atom.state.playing, "angry");
  assert.equal(h.window.__atom.state.phase, "loop");

  h.window.__atom.setBase("idle");
  let sawOutro = false;
  for (let i = 0; i < 30; i++) {
    await h.advance(60);
    const st = h.window.__atom.state;
    if (st.playing === "angry" && st.phase === "outro") sawOutro = true;
    if (st.playing === "idle") break;
  }
  assert.ok(sawOutro, "expected sustained angry mood to play outro on return to idle");
  assert.equal(h.window.__atom.state.playing, "idle");
});

test("side-panel shift repositions Atom via ancestor ResizeObserver, transitionend, and 1Hz tick", async () => {
  const h = makeHarness();
  await h.window.__atom.__loadSkin("atom", fakeSkinPayload());
  await h.advance(20);
  const host = h.docEl.children.find((c) => c.id === "atom-mascot");
  assert.equal(host.style.transform, "translate(899px, 536px)");

  // Ancestor layout containers (pane/panel) are observed along with bar/box
  const watched = h.resizeObservers[0]?.targets;
  assert.ok(watched && watched.has(h.pane) && watched.has(h.panel));

  // Side panel closes: bar keeps width 900 but shifts right to 1200 -> ancestor ResizeObserver updates Atom
  h.setBarRect({ left: 300, right: 1200, width: 900 });
  h.triggerResizeObserver();
  assert.equal(host.style.transform, "translate(1099px, 536px)");

  // Animated panel close via transitionend also repositions
  h.setBarRect({ left: 200, right: 1100, width: 900 });
  h.triggerTransitionEnd();
  await h.advance(180);
  assert.equal(host.style.transform, "translate(999px, 536px)");

  // Even without events, 1Hz visible tick check catches silent bar displacement
  h.setBarRect({ left: 100, right: 1000, width: 900 });
  await h.advance(1100);
  assert.equal(host.style.transform, "translate(899px, 536px)");
});

test("setMood tints across active work states lazily and cools smoothly on clear", async () => {
  const h = makeHarness();
  await h.window.__atom.__loadSkin("atom", fakeSkinPayload());
  await h.advance(20);

  h.window.__atom.setBase("thinking");
  h.window.__atom.setMood("angry");
  assert.equal(h.window.__atom.state.mood, "angry");
  await h.advance(450);
  assert.equal(h.window.__atom.state.playing, "thinking");
  const countAfterThinking = h.offscreenCount.count;
  assert.ok(countAfterThinking >= 1, "expected angry mood tint bitmap for thinking");

  // During 650ms climb, blended overlay alphas (0 < a < 1) are drawn
  assert.ok(h.drawCalls.some((d) => d.alpha > 0 && d.alpha < 1));

  // Switching to typing keeps angry mood alive and tints typing too
  await h.advance(1000);
  h.window.__atom.setBase("typing");
  await h.advance(800);
  assert.equal(h.window.__atom.state.playing, "typing");
  assert.equal(h.window.__atom.state.mood, "angry");
  assert.ok(h.offscreenCount.count > countAfterThinking, "expected angry mood tint bitmap for typing");

  // Clearing mood + returning to idle plays smooth 650ms cool-down then single-layer draws
  h.drawCalls.length = 0;
  h.window.__atom.setMood(null);
  h.window.__atom.setBase("idle");
  assert.equal(h.window.__atom.state.mood, null);
  await h.advance(300);
  assert.ok(h.drawCalls.some((d) => d.alpha > 0 && d.alpha < 1));
  await h.advance(1500);
  assert.equal(h.window.__atom.state.playing, "idle");
  assert.equal(h.drawCalls[h.drawCalls.length - 1].alpha, 1);

  h.window.__atom.destroy();
  assert.ok(h.createdBitmaps.length >= 4 && h.createdBitmaps.every((b) => b.closed));
});

test("anti-blitz MIN_DWELL_MS prevents rapid busy-state flicker while keeping idle wakeups fast", async () => {
  const h = makeHarness();
  const sheetSpec = (n = 4) => ({
    webp: Buffer.from("webp").toString("base64"),
    w: 200,
    h: 160,
    cols: 4,
    durations: Array(n).fill(100),
    loop: [0, n - 1],
  });
  await h.window.__atom.__loadSkin("atom", {
    ...fakeSkinPayload(),
    exploring: sheetSpec(),
    working: sheetSpec(),
  });
  await h.advance(20);

  // Idle wakeup is immediate (< 1200ms dwell does not delay leaving idle)
  h.window.__atom.setBase("exploring");
  await h.advance(450);
  assert.equal(h.window.__atom.state.playing, "exploring");

  // Rapid busy switches within 300ms hold exploring for >= 1200ms and jump straight to newest pending ("typing")
  const seenStates = [];
  h.window.__atom.setBase("working");
  await h.advance(150);
  h.window.__atom.setBase("typing");
  for (let i = 0; i < 6; i++) {
    await h.advance(100);
    seenStates.push(h.window.__atom.state.playing);
  }
  assert.ok(seenStates.every((s) => s === "exploring"), `expected dwell hold in exploring, got ${seenStates}`);

  await h.advance(1400);
  assert.equal(h.window.__atom.state.playing, "typing");
});

test("mood tilts neutral eyes into angry (\\ /) and sad (/ \\) across work states", async () => {
  const W = 150, H = 120;
  const capturedBuffers = [];
  const paintRect = (d, x0, x1, y0, y1, r, g, b) => {
    for (let y = y0; y <= y1; y++) {
      for (let x = x0; x <= x1; x++) {
        const o = (y * W + x) * 4;
        d[o] = r; d[o + 1] = g; d[o + 2] = b; d[o + 3] = 255;
      }
    }
  };
  const h = makeHarness({
    imageSize: { w: W, h: H },
    capturedBuffers,
    onSeedPixels: (d) => {
      paintRect(d, 45, 108, 50, 95, 20, 145, 240);
      paintRect(d, 55, 61, 65, 71, 10, 14, 20);
      paintRect(d, 82, 88, 65, 71, 10, 14, 20);
    },
  });
  const sheetSpec = {
    webp: Buffer.from("webp").toString("base64"),
    w: W,
    h: H,
    cols: 1,
    durations: [100],
    loop: [0, 0],
  };
  await h.window.__atom.__loadSkin("atom", {
    idle: { ...sheetSpec },
    thinking: { ...sheetSpec },
    typing: { ...sheetSpec },
  });
  await h.advance(20);

  const px = (d, x, y) => {
    const o = (y * W + x) * 4;
    return [d[o], d[o + 1], d[o + 2], d[o + 3]];
  };

  h.window.__atom.setBase("thinking");
  h.window.__atom.setMood("angry");
  await h.advance(80);
  assert.ok(capturedBuffers.length >= 1);
  const angryBuf = capturedBuffers[capturedBuffers.length - 1];
  for (const [x, y] of [[61, 65], [82, 65]]) {
    const [r, , b] = px(angryBuf, x, y);
    assert.ok(r > 180 && b < 80, `expected inner-top (${x},${y}) to tilt angry red, got (${r},${b})`);
  }
  for (const [x, y] of [[55, 71], [88, 71]]) {
    const [r, g, b] = px(angryBuf, x, y);
    assert.ok(r < 35 && g < 35 && b < 35, `expected outer-bottom (${x},${y}) to remain dark eye`);
  }

  h.window.__atom.setMood("sad");
  await h.advance(80);
  const sadBuf = capturedBuffers[capturedBuffers.length - 1];
  for (const [x, y] of [[55, 65], [88, 65]]) {
    const [r, , b] = px(sadBuf, x, y);
    assert.ok(b > r && b - r < 80 && r > 90, `expected outer-top (${x},${y}) to tilt sad grey-blue`);
  }
  for (const [x, y] of [[61, 65], [82, 65]]) {
    const [r, g, b] = px(sadBuf, x, y);
    assert.ok(r < 35 && g < 35 && b < 35, `expected inner-top (${x},${y}) to remain dark eye`);
  }
});

test("click and react('dance') do not dance while angry or sad mood is active", async () => {
  const h = makeHarness({ skinNames: ["atom"] });
  const sheetSpec = {
    webp: Buffer.from("webp").toString("base64"),
    w: 200,
    h: 160,
    cols: 4,
    durations: [65, 65, 65, 65],
    loop: [0, 3],
  };
  await h.window.__atom.__loadSkin("atom", {
    ...fakeSkinPayload(),
    dance: sheetSpec,
    angry: sheetSpec,
    sad: sheetSpec,
  });
  await h.advance(20);

  // Blocked while mood === "angry" or "sad"
  h.window.__atom.setBase("thinking");
  h.window.__atom.setMood("angry");
  await h.advance(450);
  assert.equal(h.window.__atom.state.playing, "thinking");
  h.triggerHitClick();
  h.window.__atom.react("dance");
  await h.advance(100);
  assert.equal(h.window.__atom.state.playing, "thinking");

  h.window.__atom.setMood("sad");
  h.triggerHitClick();
  await h.advance(100);
  assert.equal(h.window.__atom.state.playing, "thinking");

  // Also blocked when playing angry reaction directly
  h.window.__atom.setMood(null);
  h.window.__atom.setBase("idle");
  await h.advance(1500);
  h.window.__atom.react("angry", 5);
  await h.advance(150);
  assert.equal(h.window.__atom.state.playing, "angry");
  h.triggerHitClick();
  assert.equal(h.window.__atom.state.reaction, null);

  // Once calm and idle again, click triggers dance immediately
  await h.advance(400);
  assert.equal(h.window.__atom.state.playing, "idle");
  h.triggerHitClick();
  await h.advance(20);
  assert.equal(h.window.__atom.state.playing, "dance");
});

test("crossfade blend schedules rAF directly at 60fps and long loops exit mid-loop into outro cleanly", async () => {
  const h = makeHarness();
  const b64 = Buffer.from("webp").toString("base64");
  const longTyping = {
    webp: b64,
    w: 200,
    h: 160,
    cols: 10,
    durations: Array(36).fill(100), // 0..2 intro, 3..32 loop (30f), 33..35 outro
    loop: [3, 32],
  };
  await h.window.__atom.__loadSkin("atom", {
    ...fakeSkinPayload(),
    typing: longTyping,
  });
  await h.advance(20);

  // Verify idle -> typing crossfade runs purely on requestAnimationFrame (no 33ms blend timer)
  h.drawCalls.length = 0;
  h.window.__atom.setBase("typing");
  await h.advance(120);
  assert.equal(h.window.__atom.state.playing, "typing");
  assert.ok(h.rafs.size >= 1 && h.timers.size === 0, "expected rAF-driven blend without setTimeout");
  for (let i = 0; i < 6; i++) await h.advance(16);
  const blendAlphas = h.drawCalls.filter((d) => d.alpha > 0 && d.alpha < 1).length;
  assert.ok(blendAlphas >= 4, `expected >= 4 60fps crossfade draws, got ${blendAlphas}`);

  // Dwell past MIN_DWELL_MS (~1200ms) while still early in the 30-frame loop
  await h.advance(1200);
  assert.equal(h.window.__atom.state.playing, "typing");
  assert.equal(h.window.__atom.state.phase, "loop");
  const midLoopFrame = h.window.__atom.state.frame;
  assert.ok(midLoopFrame >= 3 && midLoopFrame < 25, `expected early/mid loop frame, got ${midLoopFrame}`);

  // Exit mid-loop: switches straight into outro within 1 frame boundary (never steps 25+ loop frames)
  h.drawCalls.length = 0;
  h.window.__atom.setBase("thinking");
  await h.advance(150);
  assert.equal(h.window.__atom.state.playing, "typing");
  assert.equal(h.window.__atom.state.phase, "outro");
  assert.ok(h.drawCalls.some((d) => d.alpha > 0 && d.alpha < 1), "expected mid-loop -> outro blend");

  // Outro plays its 3 frames cleanly and transitions into thinking
  await h.advance(400);
  assert.equal(h.window.__atom.state.playing, "thinking");
});

test("setLimit puts Atom into closed sleep and suppresses listening and dance", async () => {
  const h = makeHarness();
  const sheetSpec = {
    webp: Buffer.from("webp").toString("base64"),
    w: 200,
    h: 160,
    cols: 4,
    durations: [100, 100, 100, 100],
    loop: [0, 3],
  };
  await h.window.__atom.__loadSkin("atom", {
    ...fakeSkinPayload(),
    closed: { ...sheetSpec },
    listening: { ...sheetSpec },
    dance: { ...sheetSpec },
  });
  await h.advance(20);
  assert.equal(h.window.__atom.state.playing, "idle");

  h.window.__atom.setLimit({ activeModel: "gemini-3-pro", activeLimited: true, limitedModels: ["gemini-3-pro"] });
  await h.advance(250);
  assert.equal(h.window.__atom.state.limitSleep, true);
  assert.equal(h.window.__atom.state.playing, "closed");

  // Typing or clicking does not wakeAtom from limit sleep
  h.triggerInput();
  h.triggerHitClick();
  h.window.__atom.react("dance");
  await h.advance(150);
  assert.equal(h.window.__atom.state.playing, "closed");
  assert.equal(h.window.__atom.state.listening, false);
});

test("switching prompt-box model selector wakes Atom from limit sleep and returning re-sleeps", async () => {
  const h = makeHarness();
  const modelBtn = h.createEl("button");
  modelBtn.setAttribute("data-testid", "model-selector");
  modelBtn.textContent = "Gemini 3 Pro (High)";
  h.boxes[0]._bar.appendChild(modelBtn);

  // Simulate lingering UI banner mentioning the exhausted model
  const banner = h.createEl("div");
  banner.setAttribute("role", "alert");
  banner.textContent = "You have reached the quota limit for Gemini 3 Pro. You can resume using this model at 6:00 PM.";
  h.alertNodes.push(banner);

  await h.window.__atom.__loadSkin("atom", {
    ...fakeSkinPayload(),
    closed: { webp: Buffer.from("webp").toString("base64"), w: 200, h: 160, cols: 4, durations: [100, 100, 100, 100], loop: [0, 3] },
  });
  await h.advance(20);

  h.window.__atom.setLimit({ activeModel: "gemini-3-pro", activeLimited: true, limitedModels: ["gemini-3-pro"] });
  await h.advance(250);
  assert.equal(h.window.__atom.state.uiModel, "Gemini 3 Pro (High)");
  assert.equal(h.window.__atom.state.limitSleep, true);
  assert.equal(h.window.__atom.state.playing, "closed");

  // Switching to an available model wakes Atom immediately even if Pro banner remains visible
  modelBtn.textContent = "Gemini 3 Flash";
  h.triggerClick();
  await h.advance(300);
  assert.equal(h.window.__atom.state.uiModel, "Gemini 3 Flash");
  assert.equal(h.window.__atom.state.limitSleep, false);
  assert.equal(h.window.__atom.state.playing, "idle");

  // Switching back to the exhausted model immediately puts Atom back to sleep
  modelBtn.textContent = "Gemini 3 Pro (High)";
  h.triggerClick();
  await h.advance(300);
  assert.equal(h.window.__atom.state.limitSleep, true);
  assert.equal(h.window.__atom.state.playing, "closed");
});

test("DOM quota alert sleeps Atom while chat transcript text does not false-trigger", async () => {
  const h = makeHarness();
  const chatFeed = h.createEl("div");
  chatFeed.setAttribute("data-testid", "chat-messages");
  chatFeed.textContent = "We hit the 5-hour limit and weekly quota earlier in this project.";
  h.pane.appendChild(chatFeed);

  const inTranscriptStatus = h.createEl("span");
  inTranscriptStatus.setAttribute("role", "status");
  inTranscriptStatus.textContent = "Rate limit reached";
  const convWrap = h.createEl("div");
  convWrap.className = "conversation-turn";
  convWrap.appendChild(inTranscriptStatus);
  h.alertNodes.push(inTranscriptStatus);

  await h.window.__atom.__loadSkin("atom", {
    ...fakeSkinPayload(),
    closed: { webp: Buffer.from("webp").toString("base64"), w: 200, h: 160, cols: 4, durations: [100, 100, 100, 100], loop: [0, 3] },
  });
  await h.advance(20);
  h.window.__atom.checkLimit();
  await h.advance(200);
  assert.equal(h.window.__atom.state.limitSleep, false);
  assert.equal(h.window.__atom.state.playing, "idle");

  // A genuine outside-transcript quota alert puts Atom to sleep
  const quotaAlert = h.createEl("div");
  quotaAlert.setAttribute("role", "alert");
  quotaAlert.textContent = "Weekly limit reached · 0% remaining";
  h.alertNodes.push(quotaAlert);
  h.window.__atom.checkLimit();
  await h.advance(300);
  assert.equal(h.window.__atom.state.limitSleep, true);
  assert.equal(h.window.__atom.state.playing, "closed");
});

test("right-click opens lazy context menu, toggles side, and opens Atom Lab to switch animated skins", async () => {
  const h = makeHarness({ skinNames: ["atom", "cyber"] });
  await h.window.__atom.__loadSkin("atom", fakeSkinPayload());
  await h.advance(30);
  assert.equal(h.window.__atom.needSkin(), null);

  // Right-click before atom_lab.js is loaded queues the menu request and asks needSkin for lab
  h.triggerHitContextMenu({ clientX: 900, clientY: 500 });
  assert.equal(h.window.__atom.state.menuOpen, true);
  assert.deepEqual(JSON.parse(JSON.stringify(h.window.__atom.needSkin())), { lab: true, previews: [] });

  // Mounting atom_lab.js immediately displays the context menu
  const labHost = h.mountLab([
    { id: "atom", name: "Atom", tagline: "Original", accent: "#38bdf8", states: 19 },
    { id: "cyber", name: "Cyber", tagline: "Neon", accent: "#22d3ee", states: 19 },
  ]);
  assert.ok(labHost);
  assert.equal(labHost.style.display, "block");
  const menuEl = labHost.shadow.querySelector(".menu");
  assert.equal(menuEl.style.display, "flex");
  assert.equal(menuEl.children.length, 3);

  // Clicking "Move to Left" updates alignment and closes the menu
  const alignBtn = menuEl.children[2];
  for (const fn of alignBtn.listeners.get("click") || []) fn({ stopPropagation() {} });
  assert.equal(h.window.__atom.state.align, "left");
  assert.equal(h.window.__atom.state.menuOpen, false);
  assert.equal(labHost.style.display, "none");

  // Re-opening menu then clicking outside closes it; Escape closes too
  h.triggerHitContextMenu({ clientX: 120, clientY: 500 });
  assert.equal(h.window.__atom.state.menuOpen, true);
  h.triggerDocEvent("pointerdown", { target: h.pane });
  assert.equal(h.window.__atom.state.menuOpen, false);

  h.triggerHitContextMenu({ clientX: 120, clientY: 500 });
  const labBtn = menuEl.children[0];
  for (const fn of labBtn.listeners.get("click") || []) fn({ stopPropagation() {} });
  assert.equal(h.window.__atom.state.menuOpen, false);
  assert.equal(h.window.__atom.state.labOpen, true);
  assert.deepEqual(JSON.parse(JSON.stringify(h.window.__atom.needSkin())), { lab: false, previews: ["cyber"] });

  // Preview load makes the second card ready & animated via Lab's shared rAF loop
  await h.window.__atom.__loadState("cyber", "idle", fakeSkinPayload().idle, true);
  assert.equal(h.window.__atom.needSkin(), null);
  const grid = labHost.shadow.querySelector(".grid");
  const cyberCard = grid.children[1];
  assert.equal(cyberCard.classList.contains("ready"), true);
  const drawsBefore = h.drawCalls.length;
  await h.advance(140);
  assert.ok(h.drawCalls.length > drawsBefore, "Lab rAF should animate card canvases");

  // Closing Lab via Escape hides #atom-lab and cancels Lab's rAF immediately
  const rafsWhileOpen = h.rafs.size;
  h.triggerDocEvent("keydown", { key: "Escape" });
  assert.equal(h.window.__atom.state.labOpen, false);
  assert.equal(labHost.style.display, "none");
  assert.equal(h.rafs.size, rafsWhileOpen - 1);

  // Re-opening Lab and clicking Cyber card equips it, closes Lab, requests sync, and starts red curtain
  h.window.__atom.openLab();
  assert.equal(h.window.__atom.state.labOpen, true);
  for (const fn of cyberCard.listeners.get("click") || []) fn({});
  assert.equal(h.window.__atom.state.skin, "cyber");
  assert.equal(h.storage.get("atom.skin"), "cyber");
  assert.equal(cyberCard.classList.contains("equipped"), true);
  assert.equal(h.window.__atom.state.labOpen, false);
  assert.equal(labHost.style.display, "none");
  assert.equal(h.window.__atom.needSkin(), "cyber");
  assert.equal(h.window.__atom.state.skinTransition, "closing");

  h.window.__atom.destroy();
  assert.equal(labHost.removed, true);
  assert.equal(h.rafs.size, 0);
});

test("skin switch plays red curtain transition (loaded, deferred-load, and fallback)", async () => {
  // 1. Loaded path with Atom Lab rich right-to-left pulling curtain mounted
  const h = makeHarness({ skinNames: ["atom", "alt", "cyber"] });
  await h.window.__atom.__loadSkin("atom", fakeSkinPayload());
  await h.window.__atom.__loadSkin("alt", fakeSkinPayload());
  await h.advance(30);
  h.mountLab([
    { id: "atom", name: "Atom", tagline: "", accent: "#38bdf8", states: 19 },
    { id: "alt", name: "Alt", tagline: "", accent: "#38bdf8", states: 19 },
    { id: "cyber", name: "Cyber", tagline: "", accent: "#22d3ee", states: 19 },
  ]);

  const width = h.window.__atom.state.widthCss;
  h.fillCalls.length = 0;
  assert.equal(h.window.__atom.setSkin("alt"), true);
  assert.equal(h.window.__atom.state.skin, "alt");
  assert.equal(h.window.__atom.state.skinTransition, "closing");

  // Early closing (~220ms) -> anchored on RIGHT half, pulling leftward
  await h.advance(220);
  assert.equal(h.window.__atom.state.skinTransition, "closing");
  const earlyXs = h.fillCalls.filter((c) => c.fillStyle === "#d41c2c").map((c) => c.x);
  assert.ok(earlyXs.length > 0, "expected crimson curtain folds during closing");
  assert.ok(Math.min(...earlyXs) > width * 0.5, "expected curtain to start on the right side");

  // Late closing (~460ms total) -> pulled across to LEFT half
  h.fillCalls.length = 0;
  await h.advance(240);
  assert.equal(h.window.__atom.state.skinTransition, "closing");
  const lateXs = h.fillCalls.filter((c) => c.fillStyle === "#d41c2c").map((c) => c.x);
  assert.ok(Math.min(...lateXs) < width * 0.35, "expected Atom to pull curtain right-to-left across stage");

  // Around 620ms total -> holding closed while changing skins + gold sparkles
  await h.advance(160);
  assert.equal(h.window.__atom.state.skinTransition, "holding");

  // Around 880ms total -> pulling open left-to-right to unveil new skin
  await h.advance(260);
  assert.equal(h.window.__atom.state.skinTransition, "opening");

  h.fillCalls.length = 0;
  await h.advance(220);
  assert.equal(h.window.__atom.state.skinTransition, "opening");
  const openXs = h.fillCalls.filter((c) => c.fillStyle === "#d41c2c").map((c) => c.x);
  assert.ok(Math.max(...openXs) > width * 0.5, "expected curtain to pull open back toward the right");

  // Around 1340ms total -> fading out brass rod & reveal sparkles
  await h.advance(240);
  assert.equal(h.window.__atom.state.skinTransition, "fading");

  // By ~1550ms -> transition completed cleanly with no stray 60fps loop
  await h.advance(220);
  assert.equal(h.window.__atom.state.skinTransition, null);

  // 2. Deferred-load path: switching to unloaded "cyber" holds curtain closed until idle sheet arrives
  assert.equal(h.window.__atom.setSkin("cyber"), true);
  await h.advance(700);
  assert.equal(h.window.__atom.state.skinTransition, "holding");
  await h.window.__atom.__loadState("cyber", "idle", fakeSkinPayload().idle, false);
  await h.advance(160);
  assert.equal(h.window.__atom.state.skinTransition, "opening");
  await h.advance(700);
  assert.equal(h.window.__atom.state.skinTransition, null);

  // 3. Compact fallback path (before atom_lab.js mounts) also renders red curtain & completes
  const h2 = makeHarness({ skinNames: ["atom", "alt"] });
  await h2.window.__atom.__loadSkin("atom", fakeSkinPayload());
  await h2.window.__atom.__loadSkin("alt", fakeSkinPayload());
  await h2.advance(30);
  h2.fillCalls.length = 0;
  assert.equal(h2.window.__atom.setSkin("alt"), true);
  assert.equal(h2.window.__atom.state.skinTransition, "closing");
  await h2.advance(240);
  assert.ok(h2.fillCalls.some((c) => c.fillStyle === "#d41c2c"), "expected compact red curtain fallback");
  await h2.advance(1400);
  assert.equal(h2.window.__atom.state.skinTransition, null);

  // Injected DEFAULT_SKIN wins over empty/stale localStorage on fresh localhost origin
  const h3 = makeHarness({ skinNames: ["atom", "base-qt"], defaultSkin: "base-qt" });
  assert.equal(h3.window.__atom.state.skin, "base-qt");
  assert.equal(h3.window.__atom.needSkin(), "base-qt");

  h.window.__atom.destroy();
  h2.window.__atom.destroy();
  h3.window.__atom.destroy();
});

test("switching skin during idle typing fidget does not get stuck in typing", async () => {
  const b64 = Buffer.from("webp").toString("base64");
  const makeThreePhaseSkin = () => ({
    idle: { webp: b64, w: 150, h: 120, cols: 10, durations: Array(10).fill(100), loop: [0, 9] },
    typing: { webp: b64, w: 150, h: 120, cols: 10, durations: Array(50).fill(100), loop: [7, 36] },
  });
  const h = makeHarness({ skinNames: ["atom", "base-qt", "cyber"] });
  await h.window.__atom.__loadSkin("atom", makeThreePhaseSkin());
  await h.window.__atom.__loadSkin("base-qt", makeThreePhaseSkin());
  await h.advance(30);
  assert.equal(h.window.__atom.state.playing, "idle");

  // Trigger idle fidget into 3-phase typing loop, then switch to preloaded base-qt
  await h.advance(7200);
  assert.equal(h.window.__atom.state.playing, "typing");
  h.window.__atom.setSkin("base-qt");
  assert.equal(h.window.__atom.state.skin, "base-qt");
  assert.equal(h.window.__atom.state.playing, "idle");
  await h.advance(2000);
  assert.equal(h.window.__atom.state.playing, "idle");

  // Trigger idle fidget again on base-qt, then switch to unloaded cyber
  await h.advance(7200);
  assert.equal(h.window.__atom.state.playing, "typing");
  h.window.__atom.setSkin("cyber");
  await h.advance(600);
  await h.window.__atom.__loadState("cyber", "idle", makeThreePhaseSkin().idle, false);
  await h.advance(1200);
  assert.equal(h.window.__atom.state.skin, "cyber");
  assert.equal(h.window.__atom.state.playing, "idle");
  h.window.__atom.destroy();
});

test("idle sheet with stand-then-sit intro enters loop and interrupts immediately on base/listening", async () => {
  const b64 = Buffer.from("webp").toString("base64");
  const h = makeHarness({ skinNames: ["atom", "chibi"], defaultSkin: "chibi" });
  await h.window.__atom.__loadSkin("chibi", {
    idle: { webp: b64, w: 150, h: 120, cols: 10, durations: Array(65).fill(100), loop: [35, 64] },
    listening: { webp: b64, w: 150, h: 120, cols: 10, durations: Array(30).fill(100), loop: [0, 29] },
    thinking: { webp: b64, w: 150, h: 120, cols: 10, durations: Array(44).fill(100), loop: [7, 36] },
  });
  await h.advance(30);
  assert.equal(h.window.__atom.state.playing, "idle");
  assert.equal(h.window.__atom.state.phase, "intro");

  // Advances smoothly past frame 35 into sitting loop without getting stuck
  await h.advance(3600);
  assert.equal(h.window.__atom.state.playing, "idle");
  assert.equal(h.window.__atom.state.phase, "loop");

  // Re-entering idle from thinking starts at standing intro, and listening interrupts intro promptly
  h.window.__atom.setBase("thinking");
  await h.advance(150);
  assert.equal(h.window.__atom.state.playing, "thinking");
  await h.advance(1250);
  h.window.__atom.setBase("idle");
  await h.advance(800);
  assert.equal(h.window.__atom.state.playing, "idle");
  assert.equal(h.window.__atom.state.phase, "intro");

  h.triggerInput();
  await h.advance(250);
  assert.equal(h.window.__atom.state.playing, "listening");
  h.window.__atom.destroy();
});

test("tiltMoodEyes handles 3/4 tilted work eyes (dx>=12, dy<=5) and skips reaction/closed sheets", async () => {
  const W = 150, H = 120;
  const capturedBuffers = [];
  const paintRect = (d, x0, x1, y0, y1, r, g, b) => {
    for (let y = y0; y <= y1; y++) {
      for (let x = x0; x <= x1; x++) {
        const o = (y * W + x) * 4;
        d[o] = r; d[o + 1] = g; d[o + 2] = b; d[o + 3] = 255;
      }
    }
  };
  const h = makeHarness({
    imageSize: { w: W, h: H },
    capturedBuffers,
    onSeedPixels: (d) => {
      paintRect(d, 45, 108, 50, 95, 20, 145, 240);
      // 3/4 tilted eye pair: dx = 78.5 - 65.5 = 13px, dy = |62 - 66| = 4px
      paintRect(d, 63, 68, 63, 69, 10, 14, 20);
      paintRect(d, 76, 81, 59, 65, 10, 14, 20);
    },
  });
  const sheetSpec = {
    webp: Buffer.from("webp").toString("base64"),
    w: W,
    h: H,
    cols: 1,
    durations: [100],
    loop: [0, 0],
  };
  await h.window.__atom.__loadSkin("atom", {
    idle: { ...sheetSpec },
    thinking: { ...sheetSpec },
    done: { ...sheetSpec },
    closed: { ...sheetSpec },
  });
  await h.advance(20);

  const px = (d, x, y) => {
    const o = (y * W + x) * 4;
    return [d[o], d[o + 1], d[o + 2]];
  };

  // Work state tilts 3/4 eyes
  h.window.__atom.setBase("thinking");
  h.window.__atom.setMood("angry");
  await h.advance(80);
  const workBuf = capturedBuffers[capturedBuffers.length - 1];
  assert.ok(px(workBuf, 68, 63)[0] > 180, "expected inner-top of left 3/4 eye to tilt angry red");
  assert.ok(px(workBuf, 76, 59)[0] > 180, "expected inner-top of right 3/4 eye to tilt angry red");

  // Closed & done reaction sheets keep custom eye pixels intact without tiltMoodEyes slicing
  h.window.__atom.setBase("closed");
  await h.advance(80);
  const closedBuf = capturedBuffers[capturedBuffers.length - 1];
  assert.ok(px(closedBuf, 68, 63)[0] < 35 && px(closedBuf, 76, 59)[0] < 35, "closed eyes must not be cut by tiltMoodEyes");

  h.window.__atom.setBase("idle");
  h.window.__atom.react("done", "d1");
  await h.advance(120);
  const doneBuf = capturedBuffers[capturedBuffers.length - 1];
  assert.ok(px(doneBuf, 68, 63)[0] < 35 && px(doneBuf, 76, 59)[0] < 35, "reaction (done) eyes must not be cut by tiltMoodEyes");
  h.window.__atom.destroy();
});

test("detects Carbon/Neon/Hydrogen/Orchestrator uiModel and swaps wardrobe via __resetSkin", async () => {
  const h = makeHarness();
  await h.window.__atom.__loadSkin("atom", fakeSkinPayload());
  await h.advance(20);

  // Attach a model-picker BUTTON matching MF_RE without needing "model" in data-testid
  const picker = h.createEl("BUTTON");
  picker.textContent = "Orchestrator";
  h.boxes[0]._bar.appendChild(picker);
  h.window.__atom.checkLimit();
  assert.equal(h.window.__atom.state.uiModel, "Orchestrator");

  for (const label of ["Carbon", "Neon", "Hydrogen"]) {
    picker.textContent = label;
    h.window.__atom.checkLimit();
    assert.equal(h.window.__atom.state.uiModel, label);
  }

  // Switching outfits on the active skin via __resetSkin closes curtain & requests fresh sprites
  h.window.__atom.__resetSkin("atom");
  assert.equal(h.window.__atom.state.skinTransition, "closing");
  assert.equal(h.window.__atom.needSkin(), "atom");

  await h.window.__atom.__loadState("atom", "idle", fakeSkinPayload().idle);
  assert.equal(h.window.__atom.needSkin(), null);
  h.window.__atom.destroy();
});

test("vector drawCurtain renders curved billowing velvet pleats, brass rings, and 4-point stars", async () => {
  const h = makeHarness({ skinNames: ["atom", "alt"] });
  let capturedApi = null;
  const origMount = h.window.__atom.__mountLab.bind(h.window.__atom);
  h.window.__atom.__mountLab = (factory) => {
    origMount((bridge) => {
      capturedApi = factory(bridge);
      return capturedApi;
    });
  };
  h.mountLab([
    { id: "atom", name: "Atom", tagline: "", accent: "#38bdf8", states: 19 },
    { id: "alt", name: "Alt", tagline: "", accent: "#38bdf8", states: 19 },
  ]);
  assert.ok(capturedApi && typeof capturedApi.drawCurtain === "function");

  const runCapture = (st) => {
    const quads = [], arcs = [], grads = [];
    const ctx = {
      globalAlpha: 1, fillStyle: "", strokeStyle: "", lineWidth: 1, lineCap: "butt",
      fillRect() {}, save() {}, restore() {}, translate() {}, rotate() {},
      beginPath() {}, closePath() {}, moveTo() {}, lineTo() {},
      bezierCurveTo() {},
      quadraticCurveTo(cx, cy, x, y) { quads.push({ cx, cy, x, y }); },
      arc(x, y, r) { arcs.push({ x, y, r }); },
      fill() {}, stroke() {},
      createLinearGradient(x0, y0, x1, y1) {
        const stops = [];
        const g = { x0, y0, x1, y1, stops, addColorStop(t, c) { stops.push([t, c]); } };
        grads.push(g);
        return g;
      },
    };
    capturedApi.drawCurtain(ctx, 300, 240, st);
    return { quads, arcs, grads };
  };

  // Mid-pull closing: renders cylindrical velvet gradients, curved pleats/scallops, brass rings & rounded paw
  const closing = runCapture({ edge: 72, rodA: 1, hand: true, rustle: 0, spark: 0, el: 325, adx: -10, ady: -2, open: false });
  assert.ok(closing.grads.length >= 8, "expected cylindrical pleat + valance + rod gradients");
  assert.ok(closing.quads.length >= 30, "expected smooth quadratic curves for pleats, scallops, swags, and arm");
  assert.ok(closing.arcs.length >= 10, "expected circular arcs for brass rings, finials, tassel, and rounded paw");

  // Holding closed: renders 4-point star sparkles (each star = 4 concave quadratic curves)
  const holding = runCapture({ edge: 20, rodA: 1, hand: false, rustle: 1.2, spark: 1, el: 610, adx: 0, ady: 0, open: false });
  assert.ok(holding.quads.length > closing.quads.length - 4, "expected curved pleats + 4-point star sparkles while holding");

  h.window.__atom.destroy();
});

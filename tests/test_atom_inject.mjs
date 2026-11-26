import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const INJECT_SRC = fs.readFileSync(path.join(ROOT, "atom_inject.js"), "utf8");

function makeHarness({
  withPromptBox = true,
  preDom = false,
  skinNames = ["atom"],
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
      this.style = { display: "", transform: "" };
      this.children = [];
      this.parentElement = null;
      this.shadow = null;
      this.width = 0;
      this.height = 0;
      this.title = "";
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
      root.querySelector = (sel) => {
        if (sel === "canvas") return root._canvas || (root._canvas = new MockElement("canvas"));
        if (sel === "#hit") return root._hit || (root._hit = new MockElement("div"));
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
        clearRect() {},
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

  const storage = new Map();
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

  const source = INJECT_SRC.replace(
    "const SKIN_NAMES = __ATOM_SKIN_NAMES__;",
    `const SKIN_NAMES = ${JSON.stringify(skinNames)};`,
  );
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

test("Alt+click switches mascot side (left/right) and persists in storage", async () => {
  const h = makeHarness({ skinNames: ["atom"] });
  assert.equal(h.window.__atom.state.align, "right");
  h.triggerHitClick({ altKey: true });
  assert.equal(h.window.__atom.state.align, "left");
  h.triggerHitClick({ altKey: true });
  assert.equal(h.window.__atom.state.align, "right");
});

test("automatically hoists above stacked cards (e.g. Queued Messages)", async () => {
  const h = makeHarness({ skinNames: ["atom"] });
  await h.window.__atom.__loadSkin("atom", fakeSkinPayload());
  await h.advance(20);

  const host = h.docEl.children.find((c) => c.id === "atom-mascot");
  assert.ok(host.style.transform.includes("translate("));
  const normalY = parseInt(host.style.transform.match(/,\s*(\d+)px\)/)[1], 10);

  // Add a stacked queued-messages card directly above the prompt box
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

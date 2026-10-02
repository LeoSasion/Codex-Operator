"use strict";

// Find production scripts through the canonical plugin marker, not test depth.
const operatorTestFs = require("node:fs");
const operatorTestPath = require("node:path");
const operatorTestRoot = (() => {
  let current = __dirname;
  while (!operatorTestFs.existsSync(operatorTestPath.join(current, ".codex-plugin/plugin.json")) ||
      !operatorTestFs.existsSync(operatorTestPath.join(current, "scripts/source_route_contract.py"))) {
    const parent = operatorTestPath.dirname(current);
    if (parent === current) throw new Error("canonical_plugin_root_not_found");
    current = parent;
  }
  return current;
})();
const operatorTestScript = name => operatorTestPath.join(operatorTestRoot, "scripts", name);


const test = require("node:test");
const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { BrowserSurface, surfaceBounds, validateAssistancePacket, assistanceReady,
  recoverableBeforeDispatch, navigationAllowed, isPublicLoginUrl,
  isEmptyTemporaryChatUrl } = require(operatorTestScript("web_browser_surface.cjs"));

class Contents extends EventEmitter {
  constructor() {
    super(); this.url = "about:blank"; this.destroyed = false; this.calls = [];
    this.session = { flushStorageData() {}, cookies: { flushStore: async () => {} } };
    this.navigationHistory = { clear: () => this.calls.push(["clearHistory"]) };
  }
  setBackgroundThrottling(value) { this.calls.push(["throttle", value]); }
  setWindowOpenHandler(handler) { this.popup = handler; }
  enableDeviceEmulation(value) { this.calls.push(["enable", value]); }
  disableDeviceEmulation() { this.calls.push(["disable"]); }
  isDestroyed() { return this.destroyed; }
  getURL() { return this.url; }
  isFocused() { return this.focused === true; }
  focus() { this.focused = true; this.calls.push(["focus"]); }
  async loadURL(url) {
    this.emit("did-start-navigation", {}, url, false, true);
    this.url = url; this.calls.push(["load", url]); this.emit("dom-ready");
  }
  close(options) { this.destroyed = true; this.calls.push(["close", options]); }
}
class Window extends EventEmitter {
  constructor(options) {
    super(); this.options = options; this.size = [1080, 850]; this.visible = false;
    this.focused = false; this.minimized = false; this.destroyed = false;
    this.webContents = new Contents(); this.calls = [];
    this.contentView = { addChildView: view => { this.child = view; } };
  }
  getContentSize() { return this.size; }
  isVisible() { return this.visible; }
  isFocused() { return this.focused; }
  isMinimized() { return this.minimized; }
  isDestroyed() { return this.destroyed; }
  setFocusable(value) { this.calls.push(["focusable", value]); }
  setTitle(value) { this.title = value; }
  setSkipTaskbar(value) { this.calls.push(["taskbar", value]); }
  show() { this.visible = true; this.calls.push(["show"]); this.emit("show"); }
  hide() { this.visible = false; this.focused = false; this.child.webContents.focused = false; this.calls.push(["hide"]); this.emit("hide"); }
  focus() { this.focused = true; this.calls.push(["focus"]); this.emit("focus"); }
}
class View {
  constructor(options) { this.options = options; this.webContents = new Contents(); this.calls = []; }
  setBounds(value) { this.bounds = value; this.calls.push(["bounds", value]); }
  setVisible(value) { this.visible = value; this.calls.push(["visible", value]); }
}
function makeSurface(extra = {}) {
  return new BrowserSurface({ BrowserWindow: Window, WebContentsView: View,
    browserSession: { identity: "fixture-partition" }, ...extra });
}
const ready = { pageKind: "chatgpt", composer: true, modelButtonCount: 1,
  loginVisible: false, userCount: 0, assistantCount: 0, modernRowCount: 0 };

test("hidden shell owns a distinct persistent-session view without showing or focusing", () => {
  const surface = makeSurface();
  assert.equal(surface.window.options.show, false);
  assert.equal(surface.window.options.focusable, false);
  assert.notEqual(surface.webContents, surface.window.webContents);
  assert.equal(surface.view.options.webPreferences.session.identity, "fixture-partition");
  assert.equal(surface.view.options.webPreferences.backgroundThrottling, false);
  assert.equal(surface.view.options.webPreferences.sandbox, true);
  assert.equal(surface.view.options.webPreferences.nodeIntegration, false);
  assert.equal(surface.view.visible, true);
  assert.ok(surface.view.bounds.x > surface.window.size[0]);
  assert.equal(surface.window.calls.some(([kind]) => ["show", "focus"].includes(kind)), false);
  assert.equal(surface.webContents.calls.some(([kind]) => kind === "focus"), false);
});

test("zero-sized hidden shell retains at least an 800 by 600 renderer viewport", async () => {
  const surface = makeSurface(); surface.window.size = [0, 0];
  await surface.loadURL("https://chatgpt.com/?temporary-chat=true");
  assert.deepEqual(surface.view.bounds, { x: 801, y: 601, width: 800, height: 600 });
  const emulation = surface.webContents.calls.filter(([kind]) => kind === "enable").at(-1)[1];
  assert.deepEqual(emulation.viewSize, { width: 800, height: 600 });
  assert.equal(emulation.screenPosition, "desktop");
  assert.equal(surface.window.visible, false);
});

test("stalled navigation fails within its deadline without marking the renderer ready", async () => {
  const surface = makeSurface();
  surface.webContents.loadURL = () => new Promise(() => {});
  await assert.rejects(surface.loadURL("https://chatgpt.com/?temporary-chat=true", 20),
    /web_navigation_timeout_no_retry/);
  assert.equal(surface.rendererReady, false);
  assert.equal(surface.window.visible, false);
});

test("new renderer navigation reapplies emulation even when bounds have not changed", async () => {
  const surface = makeSurface();
  await surface.loadURL("https://chatgpt.com/?temporary-chat=true");
  const count = () => surface.webContents.calls.filter(([kind]) => kind === "enable").length;
  const before = count();
  surface.webContents.emit("did-start-navigation", {}, "https://chatgpt.com/", false, true);
  assert.equal(surface.rendererReady, false);
  surface.webContents.emit("dom-ready");
  assert.equal(count(), before + 1);
  surface.sync(); assert.equal(count(), before + 1);
});

test("explicit assistance reveals the exact view and hiding restores its offscreen viewport", async () => {
  const surface = makeSurface();
  await surface.loadURL("https://chatgpt.com/?temporary-chat=true");
  const owned = surface.webContents;
  surface.show();
  assert.equal(surface.window.isVisible(), true);
  assert.equal(surface.window.isFocused(), true);
  assert.equal(owned.isFocused(), true);
  assert.equal(surface.view.bounds.x, 0);
  assert.equal(surface.webContents.calls.at(-2)[0], "disable");
  surface.hide();
  assert.equal(surface.webContents, owned);
  assert.equal(surface.window.isVisible(), false);
  assert.equal(surface.window.isFocused(), false);
  assert.ok(surface.view.bounds.x > surface.window.size[0]);
  assert.equal(surface.view.visible, true);
});

test("minimize keeps a drawable viewport without showing or refocusing the window", async () => {
  const surface = makeSurface(); await surface.loadURL("https://chatgpt.com/"); surface.show();
  const calls = surface.window.calls.length;
  surface.window.minimized = true; surface.window.emit("minimize");
  assert.ok(surface.view.bounds.x > 0);
  assert.equal(surface.window.calls.length, calls);
  surface.window.minimized = false; surface.window.emit("restore");
  assert.equal(surface.view.bounds.x, 0);
  assert.equal(surface.window.calls.length, calls);
});

test("snapshot preview escapes public text while the account view remains hidden and unchanged", async () => {
  const surface = makeSurface(); await surface.loadURL("https://chatgpt.com/c/fixture");
  const originalCalls = surface.webContents.calls.length;
  await surface.prepareSnapshot({parts:['exact 中文\r\n<script>secret()</script>', '', ' second part\n'], notices:['<a href="https://example.com">do not navigate</a>']});
  assert.equal(surface.window.isVisible(), false);
  assert.equal(surface.window.options.webPreferences.partition.startsWith("persist:"), false);
  assert.equal(surface.window.options.webPreferences.javascript, false);
  assert.equal(surface.window.options.webPreferences.devTools, false);
  const html = Buffer.from(surface.window.webContents.getURL().split(",")[1], "base64").toString();
  assert.match(html, /default-src 'none'/);
  assert.match(html, /&lt;script&gt;secret\(\)&lt;\/script&gt;/);
  assert.match(html, /exact 中文\r\n/);
  assert.match(html, /&lt;\/script&gt;<\/pre><pre><\/pre><pre> second part\n<\/pre>/);
  assert.doesNotMatch(html, /<script|<form|<a /);
  surface.showSnapshot();
  assert.equal(surface.window.isVisible(), true);
  assert.equal(surface.revealed, false);
  assert.ok(surface.view.bounds.x > surface.window.size[0]);
  assert.equal(surface.webContents.isFocused(), false);
  assert.equal(surface.webContents.getURL(), "https://chatgpt.com/c/fixture");
  surface.hide(); await surface.clearSnapshot();
  assert.equal(surface.window.webContents.getURL(), "about:blank");
  assert.equal(surface.window.webContents.calls.at(-1)[0], "clearHistory");
  assert.deepEqual(surface.webContents.calls.slice(originalCalls), []);
});

test("blank rendered notices have an explicit empty state without altering their text", async () => {
  for (const notices of [[], ['', ' \r\n']]) {
    const surface = makeSurface();
    await surface.prepareSnapshot({parts:['complete'],notices});
    const html = Buffer.from(surface.window.webContents.getURL().split(',')[1], 'base64').toString();
    assert.match(html, /当前未发现可读的已显示提示。/);
    for (const notice of notices) assert.ok(html.includes('<pre>' + notice + '</pre>'));
  }
});

test("malformed or oversized snapshot rejects before showing without truncation", async () => {
  for (const snapshot of [null, {parts:['a'],notices:[],extra:true}, {parts:['a'],notices:[null]},
    {parts:['a'],notices:Array(17).fill('')}, {parts:['中'.repeat(22000)],notices:[]},
    {parts:[],notices:[]}, {parts:[null],notices:[]}, {parts:Array(1025).fill(''),notices:[]},
    {parts:['a'],notices:['a'.repeat(4097)]}, {text:'obsolete DOM reply',notices:[]},
  ]) {
    const surface = makeSurface();
    await assert.rejects(surface.prepareSnapshot(snapshot), /web_inspection_snapshot_/);
    assert.equal(surface.window.isVisible(), false);
    assert.equal(surface.window.webContents.getURL(), "about:blank");
  }
});

test("closing the shell closes its owned browser renderer without beforeunload", () => {
  const surface = makeSurface(); surface.window.destroyed = true; surface.window.emit("closed");
  assert.equal(surface.webContents.isDestroyed(), true);
  assert.deepEqual(surface.webContents.calls.at(-1), ["close", { waitForBeforeUnload: false }]);
  assert.throws(() => surface.show(), /web_host_closed/);
});

test("emulation failures surface to the owner rather than revealing or restarting", () => {
  const errors = []; const surface = makeSurface({ onFailure: error => errors.push(error) });
  surface.webContents.enableDeviceEmulation = () => { throw new Error("viewport rejected"); };
  surface.webContents.emit("dom-ready");
  assert.equal(errors.length, 1);
  assert.equal(surface.window.calls.some(([kind]) => kind === "show"), false);
});

test("assistance accepts a fresh exact id packet and rejects payloads or replays", () => {
  const id = "a".repeat(32), seen = new Set();
  assert.equal(validateAssistancePacket({ id }, seen), id);
  assert.equal(validateAssistancePacket({ id, inspect_completed: true }, seen), id);
  for (const value of [null, [], { id, text: "do work" }, { id: "b" }, { id: "A".repeat(32) },
    {id, inspect_completed: false}, {id, inspect_completed: "true"}, {id, inspect_completed: true, replace: true}])
    assert.throws(() => validateAssistancePacket(value, seen), /web_worker_assistance_identity_invalid/);
  seen.add(id); assert.throws(() => validateAssistancePacket({ id }, seen));
});

test("assistance readiness never accepts a login, challenge, prior turn or ambiguous composer", () => {
  assert.equal(assistanceReady(ready), true);
  for (const changes of [{ pageKind: "challenge" }, { composer: false }, { loginVisible: true },
    { modelButtonCount: 2 }, { userCount: 1 }, { assistantCount: 1 },
    { modernRowCount: 1 }, { modernRowCount: undefined }, { loginVisible: undefined }])
    assert.equal(assistanceReady({ ...ready, ...changes }), false);
  for (const value of ["https://chatgpt.com/", "https://chatgpt.com/c/abc?temporary-chat=true",
    "https://auth.openai.com/?temporary-chat=true", "https://chatgpt.com/?temporary-chat=true#x",
    "https://chatgpt.com/?temporary-chat=true&x=1", "https://user@chatgpt.com/?temporary-chat=true"])
    assert.equal(isEmptyTemporaryChatUrl(value), false);
  assert.equal(isEmptyTemporaryChatUrl("https://chatgpt.com/?temporary-chat=true"), true);
});

test("only explicit assistance admits the visible sign-in providers, never an arbitrary IdP", () => {
  assert.equal(navigationAllowed("https://chatgpt.com/", false), true);
  for (const value of ["https://auth.openai.com/login", "https://accounts.google.com/o/oauth2/v2/auth",
    "https://appleid.apple.com/auth/authorize"]) {
    assert.equal(navigationAllowed(value, false), false);
    assert.equal(navigationAllowed(value, true), true);
    assert.equal(isPublicLoginUrl(value), true);
  }
  assert.equal(isPublicLoginUrl("https://chatgpt.com/auth/login?next=%2F%3Ftemporary-chat%3Dtrue"), true);
  assert.equal(isPublicLoginUrl("https://chatgpt.com/auth/unknown"), false);
  assert.equal(navigationAllowed("https://login.microsoftonline.com/common/oauth2/authorize", true), false);
  assert.equal(navigationAllowed("https://login.microsoftonline.com/common/oauth2/authorize", true, true), true);
  assert.equal(navigationAllowed("https://login.microsoftonline.com/common/oauth2/authorize", false, true), false);
  for (const value of ["https://login.microsoftonline.com/", "https://auth.openai.com.evil/",
    "http://auth.openai.com/", "https://user@auth.openai.com/", "file:///C:/private"])
    assert.equal(navigationAllowed(value, true), false);
  for (const value of ["http://login.microsoftonline.com/", "https://user@login.microsoftonline.com/",
    "file:///C:/private", "javascript:alert(1)"])
    assert.equal(navigationAllowed(value, true, true), false);
});

test("only pre-dispatch login and challenge failures can preserve the worker for assistance", () => {
  for (const error of ["web_browser_login_required_before_dispatch", "web_browser_challenge_required_before_dispatch"]) {
    assert.equal(recoverableBeforeDispatch(error, false), true);
    assert.equal(recoverableBeforeDispatch(error, true), false);
    assert.equal(recoverableBeforeDispatch(error, undefined), false);
  }
  for (const error of [null, "web_host_deadline_no_retry", "web_cancelled_no_retry",
    "web_model_http_rejected_no_retry", "web_browser_storage_failed"])
    assert.equal(recoverableBeforeDispatch(error, false), false);
});

// Run the actual host in a VM with an in-memory file mailbox and Electron fakes.
// No browser, remote URL, child process, profile or real file is opened.
function hostHarness(configOverride = {}) {
  const outputs = [], files = new Map(), timeouts = new Set(), intervals = new Set();
  let elapsedMs = 0;
  class FixtureDate extends Date { static now() { return Date.now() + elapsedMs; } }
  const fixture = { state: { ...ready }, draft: "", operations: [], publicFinal: null,
    redirectOnce: null, landingUrl: null }, signals = new Map();
  const root = path.resolve(process.env.TEMP || ".", "surface-host-fixture");
  const configPath = path.join(root, "config.json");
  const config = { version: 1, mode: "worker", profileDirectory: path.join(root, "profile"),
    sessionPartition: "persist:operator-test", model: "gpt-5.6-sol", visible: false,
    timeoutMs: 10000, backgroundInput: "dom_v1", workerDirectory: root, parentPid: 99999,
    ...configOverride };
  files.set(configPath, Buffer.from(JSON.stringify(config)));
  const memoryFs = {
    readFileSync: file => files.get(file),
    lstatSync: file => {
      if (file === root) return { isDirectory: () => true, isSymbolicLink: () => false };
      if (!files.has(file)) throw Object.assign(new Error("missing"), { code: "ENOENT" });
      return { isFile: () => true, isSymbolicLink: () => false, size: files.get(file).length };
    },
    openSync: file => file, closeSync() {},
    readSync: (file, buffer) => { const data = files.get(file); data.copy(buffer); return data.length; },
    existsSync: file => files.has(file),
    renameSync: (from, to) => { files.set(to, files.get(from)); files.delete(from); },
    unlinkSync: file => files.delete(file),
  };
  let context;
  const browserSession = { setPermissionRequestHandler() {}, webRequest: {
    onSendHeaders() {}, onResponseStarted() {}, onCompleted() {}, onErrorOccurred() {} } };
  const app = { setName() {}, setAppUserModelId() {}, setPath() {}, requestSingleInstanceLock: () => true,
    whenReady: () => Promise.resolve(), exit: code => { outputs.push({ exitCode: code }); context.__host?.stop(); } };
  class HostContents extends Contents {
    async loadURL(url) {
      if (fixture.redirectOnce) {
        const destination = fixture.redirectOnce;
        fixture.redirectOnce = null;
        this.calls.push(["loadAttempt", url]);
        let prevented = false;
        this.emit("will-redirect", { preventDefault() { prevented = true; } }, destination, false, true);
        if (prevented) throw new Error("fixture navigation rejected");
      }
      const result = await super.loadURL(url);
      if (fixture.landingUrl) this.url = fixture.landingUrl;
      return result;
    }
    async executeJavaScript(source) {
      if (source.includes("function cancelGeneration(")) {
        fixture.operations.push("cancelGeneration");
        if (fixture.cancelPageContext) return vm.runInNewContext(source, fixture.cancelPageContext);
        if (fixture.stopAvailable === false) return { ok: true, value: false };
        fixture.stopPresent = fixture.keepGenerating === true;
        return { ok: true, value: true };
      }
      if (source.includes("function controls(")) return { ok: true, value: { ...fixture.state } };
      if (source.includes("function startupControlStructure(")) return { ok: true, value: fixture.structure };
      if (source.includes("function composerPrefix(")) return { ok: true, value: fixture.draft };
      if (source.includes("function capturePublicDispatchBinding(")) {
        const args = JSON.parse(source.match(/\)\(\.\.\.(\[[^\n]*\])\) \}; \}/)[1]);
        const exact = fixture.bindingExact !== false
          && (fixture.expectedPrompt === undefined || args[0] === fixture.expectedPrompt);
        return {ok:true,value:{prompt:args[0],userId:exact ? fixture.userId ?? 'fixture-user' : null,
          shape:{exact},modern:false,requestBinding:null}};
      }
      if (source.includes("function publicUserBindingShape(")) {
        const args = JSON.parse(source.match(/\)\(\.\.\.(\[[^\n]*\])\) \}; \}/)[1]);
        const exact = fixture.bindingExact !== false
          && (fixture.expectedPrompt === undefined || args[0] === fixture.expectedPrompt);
        return { ok: true, value: args[2] === true
          ? (exact ? fixture.userId ?? 'fixture-user' : null) : {exact} };
      }
      if (source.includes("function publicInterruptionState("))
        return { ok: true, value: { sessionExpired: false, approvalCards: fixture.approval ? 1 : 0,
          connectorDialogs: 0, subscriptionUnavailable: false, responseError: false } };
      if (source.includes("function publicGenerationState("))
        return { ok: true, value: { stopPresent: fixture.stopPresent === true, userRows: 1 } };
      if (source.includes("function pluginMaintenanceReady(")) return { ok: true, value: fixture.maintenanceReady === true };
      if (source.includes("function publicFinal(")) {
        fixture.operations.push("publicFinal"); return { ok: true, value: fixture.publicFinal };
      }
      if (source.includes("function inspectionSnapshot(")) {
        fixture.operations.push("inspectionSnapshot");
        return {ok:true,value:{text:'G',notices:['visible fixture alert']}};
      }
      if (source.includes("function startFreshChat(")) {
        fixture.operations.push("startFreshChat");
        fixture.state = { ...ready }; this.url = "https://chatgpt.com/";
        return { ok: true };
      }
      if (source.includes("function emptyFreshChat("))
        return { ok: true, value: fixture.state.composer === true
          && fixture.state.userCount === 0 && fixture.state.assistantCount === 0 };
      if (source.includes("function enableTemporaryChat(")) {
        fixture.operations.push("enableTemporaryChat"); this.url = "https://chatgpt.com/?temporary-chat=true";
        return { ok: true };
      }
      throw new Error("fixture rejected unexpected page operation");
    }
  }
  class HostView extends View { constructor(options) { super(options); this.webContents = new HostContents(); } }
  context = vm.createContext({ console, Buffer, TextDecoder, URL, Promise, Date: FixtureDate,
    setTimeout: (fn, ms) => { const id = setTimeout(() => { timeouts.delete(id); fn(); }, ms); timeouts.add(id); return id; },
    clearTimeout: id => { clearTimeout(id); timeouts.delete(id); },
    setInterval: (fn, ms) => { const id = setInterval(fn, ms); intervals.add(id); return id; },
    clearInterval: id => { clearInterval(id); intervals.delete(id); },
    process: { argv: ["electron", "host", configPath], stdout: { write: line => outputs.push(JSON.parse(line)) },
      kill() {}, on: (name, handler) => signals.set(name, handler) },
    require: name => name === "electron" ? { app, BrowserWindow: Window, WebContentsView: HostView,
      session: { fromPartition: () => browserSession } } : name === "node:fs" ? memoryFs
      : name === "node:path" ? path : require(operatorTestScript(name)),
  });
  const source = fs.readFileSync(operatorTestScript("web_browser_host.cjs"), "utf8");
  vm.runInContext(source + '\n globalThis.__host = { get surface() { return surface; }, setCompleted(value) { completedPage = value; }, stop() { workerClosing = true; } };', context);
  return { outputs, context, fixture, signal: name => signals.get(name)(),
    advanceTime: milliseconds => { elapsedMs += milliseconds; },
    invoke: expression => vm.runInContext(expression, context),
    put: (name, value) => files.set(path.join(root, name), Buffer.from(JSON.stringify(
      name === 'next.json' ? {model:'gpt-5.6-sol',effort:'high',...value} : value))),
    cleanup() { context.__host.stop(); for (const id of timeouts) clearTimeout(id); for (const id of intervals) clearInterval(id); } };
}
async function observed(harness, predicate) {
  const end = Date.now() + 2000;
  while (!predicate()) {
    if (Date.now() >= end) throw new Error("host fixture observation timed out: " + JSON.stringify(harness.outputs));
    await new Promise(resolve => setTimeout(resolve, 10));
  }
}

test("saved worker prepares one hidden empty page before any model request", async () => {
  const h = hostHarness({ startupPrepare: true });
  try {
    await observed(h, () => h.outputs.some(x => x.kind === 'worker_prepared'));
    assert.equal(h.outputs.filter(x => x.kind === 'worker_ready').length, 1);
    assert.equal(h.outputs.find(x => x.kind === 'worker_prepared').hidden, true);
    assert.equal(h.outputs.find(x => x.kind === 'worker_prepared').empty, true);
    assert.equal(h.invoke('preparedPage'), true);
    assert.deepEqual(h.context.__host.surface.webContents.calls.filter(([kind]) => kind === 'load'),
      [['load', 'https://chatgpt.com/?temporary-chat=true']]);
    assert.equal(h.context.__host.surface.window.isVisible(), false);
    assert.equal(h.outputs.some(x => x.requestId || x.kind === 'dispatch_started'), false);
  } finally { h.cleanup(); }
});

test("a prepared page is rechecked at consumption and cannot hide a later draft", async () => {
  const h = hostHarness({ startupPrepare: true });
  try {
    await observed(h, () => h.outputs.some(x => x.kind === 'worker_prepared'));
    h.fixture.state.userCount = 1;
    await assert.rejects(h.invoke('loadFreshPage()'), /web_prepared_page_changed/);
    assert.equal(h.outputs.some(x => x.kind === 'dispatch_started'), false);
    assert.equal(h.context.__host.surface.webContents.calls.filter(([kind]) => kind === 'load').length, 1);
  } finally { h.cleanup(); }
});

test("a prepared temporary URL cannot admit retained modern conversation rows", async () => {
  const h = hostHarness({ startupPrepare: true });
  try {
    await observed(h, () => h.outputs.some(x => x.kind === 'worker_prepared'));
    h.fixture.state.modernRowCount = 2;
    h.fixture.state.pageKind = 'other'; // A conversation title is not page identity.
    await assert.rejects(h.invoke('loadFreshPage()'), /web_prepared_page_changed/);
    assert.equal(h.outputs.some(x => x.kind === 'dispatch_started'), false);
    assert.equal(h.context.__host.surface.webContents.calls.filter(([kind]) => kind === 'load').length, 1);
  } finally { h.cleanup(); }
});

test("an idle challenge may clear during hidden preparation without a popup", async () => {
  const h = hostHarness({ startupPrepare: true });
  h.fixture.state = { ...ready, pageKind: 'challenge', composer: false };
  try {
    await observed(h, () => h.outputs.some(x => x.kind === 'worker_ready'));
    setTimeout(() => { h.fixture.state = { ...ready }; }, 80);
    await observed(h, () => h.outputs.some(x => x.kind === 'worker_prepared'));
    assert.equal(h.outputs.some(x => x.kind === 'worker_attention_required'), false);
    assert.equal(h.context.__host.surface.window.isVisible(), false);
    assert.equal(h.outputs.some(x => x.kind === 'dispatch_started'), false);
  } finally { h.cleanup(); }
});

test("persistent challenge and login redirect request assistance without consuming a turn", async () => {
  for (const variant of ['challenge', 'login']) {
    const h = hostHarness({ startupPrepare: true });
    if (variant === 'challenge') h.fixture.state = { ...ready, pageKind: 'challenge', composer: false };
    else h.fixture.redirectOnce = 'https://auth.openai.com/login';
    try {
      await observed(h, () => h.outputs.some(x => x.kind === 'worker_ready'));
      h.advanceTime(65001);
      await observed(h, () => h.outputs.some(x => x.kind === 'worker_attention_required'));
      const attention = h.outputs.find(x => x.kind === 'worker_attention_required');
      assert.equal(attention.reason, variant === 'challenge'
        ? 'web_browser_challenge_required_before_dispatch'
        : 'web_browser_login_required_before_dispatch');
      assert.equal(h.invoke('assistanceRequired'), true);
      assert.equal(h.context.__host.surface.window.isVisible(), false);
      assert.equal(h.outputs.some(x => x.requestId || x.kind === 'dispatch_started'), false);
    } finally { h.cleanup(); }
  }
});

test("an observed ChatGPT login route requests assistance even without a login-labelled button", async () => {
  const h = hostHarness({ startupPrepare: true });
  h.fixture.state = { ...ready, pageKind: "other", composer: false, loginVisible: false };
  h.fixture.landingUrl = "https://chatgpt.com/auth/login?next=%2F%3Ftemporary-chat%3Dtrue";
  try {
    await observed(h, () => h.outputs.some(x => x.kind === "worker_ready"));
    h.advanceTime(65001);
    await observed(h, () => h.outputs.some(x => x.kind === "worker_attention_required"));
    assert.equal(h.outputs.find(x => x.kind === "worker_attention_required").reason,
      "web_browser_login_required_before_dispatch");
    assert.equal(h.outputs.some(x => x.kind === "failed" || x.kind === "dispatch_started"), false);
  } finally { h.cleanup(); }
});

test("visible assistance permits an HTTPS identity provider and displays its host", async () => {
  const h = hostHarness({ startupPrepare: true });
  h.fixture.state = { ...ready, pageKind: "challenge", composer: false };
  try {
    await observed(h, () => h.outputs.some(x => x.kind === "worker_ready"));
    h.advanceTime(65001);
    await observed(h, () => h.outputs.some(x => x.kind === "worker_attention_required"));
    h.put("assist.json", { id: "e".repeat(32) });
    await observed(h, () => h.outputs.some(x => x.kind === "assistance_opened"));
    assert.equal(h.context.__host.surface.window.isVisible(), true);
    h.fixture.redirectOnce = "https://login.example.com/authorize";
    await h.context.__host.surface.webContents.loadURL("https://chatgpt.com/?temporary-chat=true");
    h.context.__host.surface.webContents.url = "https://login.example.com/authorize";
    h.context.__host.surface.webContents.emit("did-navigate");
    assert.equal(h.context.__host.surface.window.title, "Operator 登录辅助窗口 · login.example.com");
    assert.equal(h.outputs.some(x => x.kind === "assistance_failed" || x.kind === "dispatch_started"), false);
  } finally { h.cleanup(); }
});

test("a rejected startup login redirect does not require assistance after the saved page becomes ready", async () => {
  const h = hostHarness({ startupPrepare: true });
  h.fixture.redirectOnce = 'https://auth.openai.com/login';
  try {
    await observed(h, () => h.outputs.some(x => x.kind === 'worker_ready'));
    setTimeout(() => {
      h.context.__host.surface.webContents.url = 'https://chatgpt.com/?temporary-chat=true';
    }, 80);
    await observed(h, () => h.outputs.some(x => x.kind === 'worker_prepared'));
    assert.equal(h.outputs.some(x => x.kind === 'startup_login_redirect_cleared'), true);
    assert.equal(h.outputs.some(x => x.kind === 'worker_attention_required'), false);
    assert.equal(h.context.__host.surface.window.isVisible(), false);
    assert.equal(h.outputs.some(x => x.requestId || x.kind === 'dispatch_started'), false);
  } finally { h.cleanup(); }
});

test("hidden preparation timeout reports only fixed readiness gates before failing", async () => {
  const h = hostHarness({ startupPrepare: true });
  h.fixture.state = { ...ready, modelButtonCount: 0, modelButtonLabels: ["PRIVATE PAGE TEXT"] };
  h.fixture.structure = { readyState: "complete", legacyEditorCount: "one",
    legacyEditorEditable: "no", legacyEditorRect: "yes", testIdEditorVisible: "one",
    roleTextboxEditableVisible: "one", editableVisible: "one", textareaVisible: "zero",
    globalModelTotal: "one", globalModelVisible: "one", editorFormExists: "yes",
    accessibleModelCount: "one", accessibleModelSource: "aria_label",
    accessibleModelTag: "button", accessibleModelInEditorForm: "no",
    accessibleModelHaspopup: "menu", accessibleModelDisabled: "no" };
  try {
    await observed(h, () => h.outputs.some(x => x.kind === "worker_ready"));
    h.advanceTime(65001);
    await observed(h, () => h.outputs.some(x => x.kind === "failed"));
    const check = h.outputs.find(x => x.kind === "startup_prepare_state");
    assert.ok(check);
    assert.equal(check.stage, "startup_prepare");
    assert.equal(check.sent, false);
    assert.equal(check.route, "temporary");
    assert.equal(check.pageKind, "chatgpt");
    assert.equal(check.composer, "yes");
    assert.equal(check.modelControl, "zero");
    const structure = h.outputs.find(x => x.kind === "startup_control_structure");
    assert.ok(structure);
    assert.equal(structure.legacyEditorEditable, "no");
    assert.equal(structure.roleTextboxEditableVisible, "one");
    assert.equal(structure.globalModelVisible, "one");
    assert.equal(structure.accessibleModelCount, "one");
    assert.equal(structure.accessibleModelInEditorForm, "no");
    assert.equal(h.outputs.find(x => x.kind === "failed").error,
      "web_startup_prepare_unavailable");
    assert.equal(h.outputs.some(x => x.kind === "worker_prepared" || x.kind === "dispatch_started"
      || x.requestId), false);
    assert.equal(JSON.stringify(h.outputs).includes("PRIVATE PAGE TEXT"), false);
  } finally { h.cleanup(); }
});

test("model network errors seal only tracked generation and preserve cancellation", async () => {
  for (const variant of ['reset', 'offline', 'dns', 'proxy', 'aborted', 'unknown', 'cancel', 'foreign', 'untracked']) {
    const h = hostHarness();
    try {
      await observed(h, () => h.outputs.some(x => x.kind === 'worker_ready'));
      h.context.__host.surface.webContents.id = 42;
      h.invoke(`sent = true; stage = 'wait_public_final'; workerRequestId = 'a'.repeat(32);
        finish = (code, value) => { record(code ? 'failed' : 'completed', value); ended = true; };`);
      const detail = { id: 7, webContentsId: variant === 'foreign' ? 43 : 42, method: 'POST',
        url: 'https://chatgpt.com/backend-api/conversation' };
      if (variant !== 'untracked') h.invoke(`observeModelNetwork('sent', ${JSON.stringify(detail)})`);
      if (variant === 'cancel') h.invoke('cancelling = true');
      const error = {reset: 'net::ERR_CONNECTION_RESET', offline: 'net::ERR_INTERNET_DISCONNECTED',
        dns: 'net::ERR_NAME_NOT_RESOLVED', proxy: 'net::ERR_PROXY_CONNECTION_FAILED',
        aborted: 'net::ERR_ABORTED', unknown: 'PRIVATE arbitrary error'}[variant] || 'net::ERR_CONNECTION_RESET';
      h.invoke(`observeModelNetwork('error', ${JSON.stringify({...detail, error})})`);
      const failures = h.outputs.filter(x => x.kind === 'failed');
      if (['reset', 'offline', 'dns', 'proxy'].includes(variant)) {
        assert.equal(failures.length, 1);
        assert.equal(failures[0].error, 'web_model_network_interrupted_no_retry');
        assert.equal(failures[0].networkError, error);
        assert.equal(failures[0].sent, true);
      } else assert.equal(failures.length, 0);
      assert.equal(JSON.stringify(h.outputs).includes('PRIVATE'), false);
      assert.equal(JSON.stringify(h.outputs).includes('/backend-api/'), false);
      assert.equal(h.outputs.some(x => x.kind === 'assistance_opened'), false);
    } finally { h.cleanup(); }
  }
});

test("bound cancellation retains one hidden worker only after stop and stable page idle", async () => {
  const h = hostHarness();
  try {
    await observed(h, () => h.outputs.some(x => x.kind === 'worker_ready'));
    h.fixture.state.userCount = 1;
    h.fixture.stopPresent = true;
    h.context.__host.surface.webContents.url = 'https://chatgpt.com/?temporary-chat=true';
    h.invoke(`runCurrentPage = async function () {
      stage = 'wait_public_final'; sent = true; dispatchedPublicPrompt = config.text;
      dispatchedUserId = 'fixture-user'; record('dispatch_started');
      if (config.text === 'next independent input') return finish(0, {model: config.model,
        effortIndex: 2, publicMessage: {content: {parts: ['next answer']}}});
      await waitFor(() => false, 5000);
    }`);
    h.put('next.json', {id: 'a'.repeat(32), text: 'cancel only this input'});
    await observed(h, () => h.outputs.some(x => x.kind === 'dispatch_started'));
    h.put('cancel.json', {id: 'a'.repeat(32), reuse_when_idle: true});
    await observed(h, () => h.outputs.some(x => x.kind === 'worker_idle' && x.requestId));
    const idle = h.outputs.find(x => x.kind === 'worker_idle' && x.requestId);
    assert.equal(idle.resultCode, 1);
    assert.equal(idle.cancelledIdleVerified, true);
    assert.equal(h.outputs.some(x => Object.hasOwn(x, 'exitCode')), false);
    assert.equal(h.outputs.filter(x => x.kind === 'failed').length, 1);
    assert.equal(h.outputs.find(x => x.kind === 'failed').error, 'web_cancelled_no_retry');
    assert.deepEqual(h.fixture.operations.filter(x => x === 'cancelGeneration'), ['cancelGeneration']);
    assert.equal(h.context.__host.surface.window.isVisible(), false);
    h.put('next.json', {id: 'b'.repeat(32), text: 'next independent input'});
    await observed(h, () => h.outputs.some(x => x.kind === 'completed' && x.requestId === 'b'.repeat(32)));
    assert.equal(h.outputs.filter(x => x.kind === 'dispatch_started').length, 2);
    assert.equal(h.outputs.some(x => x.kind === 'assistance_opened'), false);
  } finally { h.cleanup(); }
});

test("legacy one-shot native input retains its bound best-effort Stop without worker reuse", async () => {
  const h = hostHarness();
  try {
    await observed(h, () => h.outputs.some(x => x.kind === 'worker_ready'));
    h.fixture.state.userCount = 1;
    h.context.__host.surface.webContents.url = 'https://chatgpt.com/?temporary-chat=true';
    h.context.__host.surface.window.visible = true;
    await h.invoke(`config.backgroundInput = false; workerMode = false;
      sent = true; dispatchedPublicPrompt = 'legacy explicit input'; dispatchedUserId = 'fixture-user';
      cancelOwnedGeneration(false);`);
    assert.deepEqual(h.fixture.operations.filter(x => x === 'cancelGeneration'), ['cancelGeneration']);
    assert.equal(h.outputs.some(x => x.cancelledIdleVerified === true), false);
    assert.equal(h.outputs.find(x => x.kind === 'failed').error, 'web_cancelled_no_retry');
  } finally { h.cleanup(); }
});

test('host Stop rechecks the actual page after its earlier identity observation without retrying', async () => {
  const {stopControlSelector} = require(operatorTestScript('web_browser_page.cjs'));
  for (const change of ['none', 'identity', 'source', 'route']) {
    const h = hostHarness();
    try {
      await observed(h, () => h.outputs.some(x => x.kind === 'worker_ready'));
      h.fixture.state.userCount = 1;
      h.fixture.stopPresent = true;
      h.context.__host.surface.webContents.url = 'https://chatgpt.com/?temporary-chat=true';
      let clicks = 0;
      const root = {tag: 3, return: null, stateNode: {}};
      root.stateNode.current = root;
      const id = change === 'identity' ? 'different-user' : 'fixture-user';
      const source = change === 'source' ? 'different request' : 'exact cancellation input';
      const fiber = {memoizedProps: {message: {id, author: {role: 'user'},
        content: {content_type: 'text', parts: [source]}}}, return: root};
      root.child = fiber;
      const user = {getAttribute: () => id, __reactFiber$fixture: fiber};
      const composer = {textContent: '', getClientRects: () => [{}], getAttribute: () => 'true'};
      const stop = {getClientRects: () => [{}], getAttribute: () => null, closest: () => null,
        disabled: false, click: () => clicks++};
      h.fixture.cancelPageContext = {URL, location: {href: change === 'route'
        ? 'https://chatgpt.com/plugins' : 'https://chatgpt.com/?temporary-chat=true'},
        document: {title: 'ChatGPT', querySelectorAll: selector => selector === '#prompt-textarea' ? [composer]
          : selector === '[data-message-author-role="user"]' ? [user]
          : selector === stopControlSelector() ? [stop] : []}};
      h.invoke(`runCurrentPage = async function () {
        stage = 'wait_public_final'; sent = true; dispatchedPublicPrompt = config.text;
        dispatchedUserId = 'fixture-user'; record('dispatch_started');
        await waitFor(() => false, 5000);
      }`);
      h.put('next.json', {id: 'f'.repeat(32), text: 'exact cancellation input'});
      await observed(h, () => h.outputs.some(x => x.kind === 'dispatch_started'));
      h.put('cancel.json', {id: 'f'.repeat(32)});
      await observed(h, () => h.outputs.some(x => Object.hasOwn(x, 'exitCode')));
      assert.equal(clicks, change === 'none' ? 1 : 0, change);
      assert.deepEqual(h.fixture.operations.filter(x => x === 'cancelGeneration'), ['cancelGeneration']);
      assert.equal(h.outputs.filter(x => x.kind === 'dispatch_started').length, 1);
      assert.equal(h.outputs.find(x => x.kind === 'failed').error, 'web_cancelled_no_retry');
      if (change !== 'none') assert.equal(h.outputs.find(x => x.kind === 'cancel_click_unavailable').error,
        change === 'route' ? 'web_cancel_page_binding_required' : 'web_cancel_user_binding_required');
      assert.equal(h.outputs.some(x => x.cancelledIdleVerified === true), false);
    } finally {h.cleanup();}
  }
});

test("cancellation cannot reuse mismatched, busy, draft, permission or unconfirmed pages", async () => {
  for (const change of [
    {bindingExact: false}, {userId: 'different-user'}, {stopAvailable: false}, {keepGenerating: true}, {draft: 'private draft'},
    {approval: true}, {visible: true}, {wrongCancel: true}, {noReuse: true},
  ]) {
    const h = hostHarness();
    try {
      await observed(h, () => h.outputs.some(x => x.kind === 'worker_ready'));
      Object.assign(h.fixture, change); h.fixture.state.userCount = 1;
      h.context.__host.surface.webContents.url = 'https://chatgpt.com/?temporary-chat=true';
      h.context.__host.surface.window.visible = change.visible === true;
      h.invoke(`runCurrentPage = async function () {
        stage = 'wait_public_final'; sent = true; dispatchedPublicPrompt = config.text;
        dispatchedUserId = 'fixture-user'; record('dispatch_started');
        await waitFor(() => false, 5000);
      }`);
      h.put('next.json', {id: 'a'.repeat(32), text: 'one input'});
      await observed(h, () => h.outputs.some(x => x.kind === 'dispatch_started'));
      h.put('cancel.json', {id: (change.wrongCancel ? 'c' : 'a').repeat(32),
        ...(change.noReuse ? {} : {reuse_when_idle: true})});
      await observed(h, () => h.outputs.some(x => x.kind === 'cancel_requested' || x.kind === 'failed'));
      h.advanceTime(3000);
      await observed(h, () => h.outputs.some(x => Object.hasOwn(x, 'exitCode')));
      assert.equal(h.outputs.some(x => x.cancelledIdleVerified === true), false);
      if (change.bindingExact === false || change.userId)
        assert.equal(h.outputs.find(x => x.kind === 'cancel_click_unavailable')?.error,
          'web_cancel_user_binding_required');
      assert.equal(h.outputs.filter(x => x.kind === 'dispatch_started').length, 1);
      assert.ok(h.fixture.operations.filter(x => x === 'cancelGeneration').length <= 1);
      assert.equal(h.outputs.some(x => x.kind === 'assistance_opened'), false);
    } finally { h.cleanup(); }
  }
});

test("current app-pill cancellation binds its dispatched public prompt and modern idle page", async () => {
  const mention = { name: 'Operator', id: 'plugin:asdk_app_' + 'a'.repeat(32) };
  const h = hostHarness();
  try {
    await observed(h, () => h.outputs.some(x => x.kind === 'worker_ready'));
    h.fixture.state.userCount = h.fixture.state.assistantCount = 0;
    h.fixture.state.modernRowCount = 2;
    h.fixture.stopPresent = true;
    h.fixture.expectedPrompt = '[$operator](app://asdk_app_' + 'a'.repeat(32) + ')\u00a0new cancellation input';
    h.context.__host.surface.webContents.url = 'https://chatgpt.com/?temporary-chat=true';
    h.invoke(`runCurrentPage = async function () {
      dispatchedPublicPrompt = ${JSON.stringify(h.fixture.expectedPrompt)};
      dispatchedUserId = 'fixture-user';
      stage = 'wait_public_final'; sent = true; record('dispatch_started');
      await waitFor(() => false, 5000);
    }`);
    h.put('next.json', { id: 'd'.repeat(32), text: 'new cancellation input',
      connectorMention: mention, autoSelectConnector: true });
    await observed(h, () => h.outputs.some(x => x.kind === 'dispatch_started'));
    h.put('cancel.json', { id: 'd'.repeat(32), reuse_when_idle: true });
    await observed(h, () => h.outputs.some(x => x.kind === 'worker_idle' && x.requestId));
    assert.equal(h.outputs.find(x => x.kind === 'worker_idle' && x.requestId).cancelledIdleVerified, true);
    assert.deepEqual(h.fixture.operations.filter(x => x === 'cancelGeneration'), ['cancelGeneration']);
    assert.equal(h.outputs.some(x => Object.hasOwn(x, 'exitCode')), false);
    assert.equal(h.outputs.filter(x => x.kind === 'failed').length, 1);
  } finally { h.cleanup(); }
});

test("a virtualized user cancellation carries its private binding and cannot reuse an unrelated turn", async () => {
  for (const matches of [true, false]) {
    const h = hostHarness();
    try {
      await observed(h, () => h.outputs.some(x => x.kind === 'worker_ready'));
      Object.assign(h.fixture.state, {userCount: 0, assistantCount: 0, modernRowCount: 1});
      h.fixture.bindingExact = false;
      h.fixture.stopPresent = true;
      h.context.__host.surface.webContents.url = 'https://chatgpt.com/?temporary-chat=true';
      h.invoke(`const existingPageRead = inPage;
        let privateBindingReads = 0;
        inPage = async (fn,...args) => {
          if (fn === page.publicBoundUserIdentity) {
            requireValue(args[0] === config.text && args[1] === dispatchedUserId
              && args[2] === dispatchedRequestBinding,'web_binding_changed');
            privateBindingReads++;
            return ${matches} ? dispatchedUserId : null;
          }
          if (fn === page.cancelGeneration) requireValue(args[0] === config.text && args[1] === dispatchedUserId
            && args[2] === dispatchedRequestBinding && args[3] === null, 'web_binding_changed');
          return existingPageRead(fn,...args);
        };
        runCurrentPage = async function () {
          dispatchedPublicPrompt = config.text;
          dispatchedUserId = '11111111-1111-4111-8111-111111111111';
          dispatchedRequestBinding = {kind:'modern_fresh_document_v1',userId:dispatchedUserId,prompt:config.text,
            conversationId:'22222222-2222-4222-8222-222222222222',nonce:workerRequestId};
          stage = 'wait_public_final'; sent = true; record('dispatch_started');
          await waitFor(() => false,5000);
        };`);
      h.put('next.json', {id: 'b'.repeat(32), text: 'new exact virtualized cancellation'});
      await observed(h, () => h.outputs.some(x => x.kind === 'dispatch_started'));
      h.put('cancel.json', {id: 'b'.repeat(32), reuse_when_idle: true});
      await observed(h, () => h.outputs.some(x => x.kind === 'worker_idle' && x.requestId));
      assert.equal(h.outputs.find(x => x.kind === 'worker_idle' && x.requestId).cancelledIdleVerified, matches);
      assert.equal(h.fixture.operations.filter(x => x === 'cancelGeneration').length, matches ? 1 : 0);
      assert.equal(h.invoke('privateBindingReads > 0'), true);
      assert.equal(h.outputs.some(x => JSON.stringify(x).includes('11111111-1111-4111-8111-111111111111')), false);
    } finally {h.cleanup();}
  }
});

test("cancel idle timeout records its fixed failed gate without exposing page data", async () => {
  for (const [state, code] of [
    [{pageKind: 'challenge'}, 'web_cancel_idle_page_kind'],
    [{userCount: 0}, 'web_cancel_idle_user_shape_changed'],
    [{loginVisible: true}, 'web_cancel_idle_login_visible'],
    [{composer: false}, 'web_cancel_idle_composer_missing'],
  ]) {
    const h = hostHarness();
    try {
      await observed(h, () => h.outputs.some(x => x.kind === 'worker_ready'));
      Object.assign(h.fixture.state, {userCount: 1}, state);
      h.context.__host.surface.webContents.url = 'https://chatgpt.com/?temporary-chat=true';
      h.invoke(`runCurrentPage = async function () {
        stage = 'wait_public_final'; sent = true; dispatchedPublicPrompt = config.text;
        dispatchedUserId = 'fixture-user';
        record('dispatch_started'); await waitFor(() => false, 5000);
      }`);
      h.put('next.json', {id: 'e'.repeat(32), text: 'new diagnostic input'});
      await observed(h, () => h.outputs.some(x => x.kind === 'dispatch_started'));
      h.put('cancel.json', {id: 'e'.repeat(32), reuse_when_idle: true});
      await observed(h, () => h.outputs.some(x => x.kind === 'cancel_click_attempted'));
      h.advanceTime(2100);
      await observed(h, () => h.outputs.some(x => x.kind === 'cancel_idle_unverified'));
      assert.equal(h.outputs.find(x => x.kind === 'cancel_idle_unverified').error, code);
      assert.equal(h.outputs.some(x => x.cancelledIdleVerified === true), false);
      assert.deepEqual(h.fixture.operations.filter(x => x === 'cancelGeneration'), ['cancelGeneration']);
    } finally { h.cleanup(); }
  }
});

test("a ChatGPT title cannot make login or plugin pages reusable after cancellation", async () => {
  for (const url of ['https://chatgpt.com/auth/login', 'https://chatgpt.com/plugins']) {
    const h = hostHarness();
    try {
      await observed(h, () => h.outputs.some(x => x.kind === 'worker_ready'));
      h.fixture.state.userCount = 1;
      h.context.__host.surface.webContents.url = url;
      h.invoke(`runCurrentPage = async function () {
        stage = 'wait_public_final'; sent = true; dispatchedPublicPrompt = config.text;
        dispatchedUserId = 'fixture-user';
        record('dispatch_started'); await waitFor(() => false, 5000);
      }`);
      h.put('next.json', {id: 'f'.repeat(32), text: 'new route fixture'});
      await observed(h, () => h.outputs.some(x => x.kind === 'dispatch_started'));
      h.put('cancel.json', {id: 'f'.repeat(32), reuse_when_idle: true});
      await observed(h, () => h.outputs.some(x => x.kind === 'cancel_click_unavailable'));
      assert.equal(h.outputs.find(x => x.kind === 'cancel_click_unavailable').error,
        'web_cancel_page_binding_required');
      assert.deepEqual(h.fixture.operations.filter(x => x === 'cancelGeneration'), []);
      assert.equal(h.outputs.some(x => x.cancelledIdleVerified === true), false);
    } finally { h.cleanup(); }
  }
});

test("dispatch binds one exact app separator projection without reinserting or resending the body", async () => {
  for (const variant of ['nbsp', 'space', 'changed', 'false-classification']) {
    const h = hostHarness();
    try {
      await observed(h, () => h.outputs.some(x => x.kind === 'worker_ready'));
      h.invoke(`globalThis.fixtureSends = 0; globalThis.fixtureText = [];
        globalThis.fixtureFinalPrompt = null;
        loadFreshPage = async function () {};
        selectModel = async function () { verifiedSelection = { model: config.model, effortIndex: 2 }; };
        insertText = async function (text) { fixtureText.push(text); };
        inPage = async function (fn, ...args) {
          const head = '[$operator](app://asdk_app_' + 'a'.repeat(32) + ')';
          if (fn.name === 'controls') return {composer:true, modelButtonCount:1,
            userCount:0, assistantCount:0, modernRowCount:0, sendReady:true};
          if (fn.name === 'connectorAccessState') return 'enabled';
          if (fn.name === 'selectedConnector') return {id:config.connectorMention.id, publicPrefix:head+'\\u00a0'};
          if (fn.name === 'composerPrefix') return 'Operator ';
          if (fn.name === 'sendOnce') { fixtureSends++; return; }
          if (fn.name === 'capturePublicDispatchBinding') {
            const expected = head + (${JSON.stringify(variant)} === 'nbsp' ? '\\u00a0' : ' ') + config.text;
            return {prompt:expected,userId:'fixture-user',modern:false,requestBinding:null,
              shape:{exact: !['changed','false-classification'].includes(${JSON.stringify(variant)})}};
          }
          return true;
        };
        waitForPublicFinal = async function (prompt) {
          fixtureFinalPrompt=prompt; return { id:'fixture', content:{parts:['answer']} };
        };`);
      h.put('next.json', { id: 'e'.repeat(32), text: ' exact\nbody ',
        connectorMention: {name:'Operator',id:'plugin:asdk_app_'+'a'.repeat(32)}, autoSelectConnector:true });
      await observed(h, () => h.outputs.some(x => x.kind === 'worker_idle' && x.requestId));
      assert.equal(h.invoke('fixtureSends'), 1);
      assert.deepEqual([...h.invoke('fixtureText')].slice(-1), ['  exact\nbody ']);
      const passed = ['nbsp', 'space'].includes(variant);
      assert.equal(h.outputs.some(x => x.kind === 'completed' && x.requestId), passed);
      assert.equal(h.invoke('fixtureFinalPrompt !== null'), passed);
      if (passed) {
        assert.equal(h.invoke('dispatchedPublicPrompt'), h.invoke('fixtureFinalPrompt'));
        assert.equal(h.invoke('dispatchedUserId'), 'fixture-user');
      }
      else assert.equal(h.outputs.find(x => x.kind === 'failed').error, 'web_user_turn_mismatch');
    } finally { h.cleanup(); }
  }
});

test('a fast virtualized dispatch cannot bypass its managed binding or make a late controls read',async()=>{
  for(const retainBinding of [true,false]) {
    const h=hostHarness();
    try {
      await observed(h,()=>h.outputs.some(x=>x.kind==='worker_ready'));
      h.invoke(`globalThis.fixtureSends=0; globalThis.fixtureFinalRead=false;
        loadFreshPage=async function(){};
        selectModel=async function(){verifiedSelection={model:config.model,effortIndex:2};};
        insertText=async function(){};
        inPage=async function(fn,...args){
          if(fn.name==='controls') {
            if(fixtureSends) throw Error('late control read lost original source');
            return {composer:true,modelButtonCount:1,userCount:0,assistantCount:0,modernRowCount:0,sendReady:true};
          }
          if(fn.name==='sendOnce'){fixtureSends++;return;}
          if(fn.name==='capturePublicDispatchBinding') {
            requireValue(args[0]===config.text && args[1]===workerRequestId,'web_binding_changed');
            const userId='11111111-1111-4111-8111-111111111111';
            return {prompt:args[0],userId,shape:{exact:true},modern:true,
              requestBinding:${retainBinding} ? {kind:'modern_fresh_document_v1',userId,prompt:args[0],
                conversationId:'temporary opaque key',nonce:args[1]} : null};
          }
          return true;
        };
        waitForPublicFinal=async function(prompt){
          fixtureFinalRead=true;
          requireValue(dispatchedRequestBinding?.prompt===prompt && dispatchedRequestBinding.nonce===workerRequestId,
            'web_binding_changed');
          return {id:'fixture',content:{parts:['answer']}};
        };`);
      h.put('next.json',{id:'c'.repeat(32),text:'different exact rapid reply source'});
      await observed(h,()=>h.outputs.some(x=>x.kind==='worker_idle' && x.requestId));
      assert.equal(h.invoke('fixtureSends'),1);
      assert.equal(h.invoke('fixtureFinalRead'),retainBinding);
      assert.equal(h.outputs.some(x=>x.kind==='completed' && x.requestId),retainBinding);
      if(!retainBinding) assert.equal(h.outputs.find(x=>x.kind==='failed').error,'web_user_identity_unavailable');
      const diagnostics=JSON.stringify(h.outputs);
      assert.equal(diagnostics.includes('temporary opaque key'),false);
      assert.equal(diagnostics.includes('different exact rapid reply source'),false);
    } finally {h.cleanup();}
  }
});

test("a changed user identity after Stop cannot retain the cancelled worker", async () => {
  const h = hostHarness();
  try {
    await observed(h, () => h.outputs.some(x => x.kind === 'worker_ready'));
    h.fixture.state.userCount = 1;
    h.context.__host.surface.webContents.url = 'https://chatgpt.com/?temporary-chat=true';
    h.invoke(`const originalPage = inPage;
      inPage = async function (fn, ...args) {
        if (fn.name === 'publicUserBindingShape' && globalThis.fixtureStopped)
          return 'different-user';
        const result = await originalPage(fn, ...args);
        if (fn.name === 'cancelGeneration') globalThis.fixtureStopped = true;
        return result;
      };
      runCurrentPage = async function () {
        sent = true; dispatchedPublicPrompt = config.text; dispatchedUserId = 'fixture-user';
        stage = 'wait_public_final'; record('dispatch_started'); await waitFor(() => false, 5000);
      };`);
    h.put('next.json', {id: 'c'.repeat(32), text: 'same text must not conceal another user identity'});
    await observed(h, () => h.outputs.some(x => x.kind === 'dispatch_started'));
    h.put('cancel.json', {id: 'c'.repeat(32), reuse_when_idle: true});
    await observed(h, () => h.outputs.some(x => x.kind === 'cancel_idle_unverified'));
    assert.equal(h.outputs.find(x => x.kind === 'cancel_idle_unverified').error,
      'web_cancel_user_binding_required');
    assert.deepEqual(h.fixture.operations.filter(x => x === 'cancelGeneration'), ['cancelGeneration']);
    assert.equal(h.outputs.some(x => x.cancelledIdleVerified === true), false);
  } finally { h.cleanup(); }
});

test("the exact dispatched user identity survives presentation URL and title changes", async () => {
  const h = hostHarness();
  try {
    await observed(h, () => h.outputs.some(x => x.kind === 'worker_ready'));
    h.fixture.state.userCount = 1;
    h.fixture.state.pageKind = 'other';
    h.invoke(`const originalPage = inPage;
      inPage = async function (fn, ...args) {
        const result = await originalPage(fn, ...args);
        if (fn.name === 'cancelGeneration') surface.webContents.url = 'https://chatgpt.com/c/private-fixture#changed';
        return result;
      };
      runCurrentPage = async function () {
        sent = true; dispatchedPublicPrompt = config.text; dispatchedUserId = 'fixture-user';
        surface.webContents.url = 'https://chatgpt.com/c/private-fixture';
        stage = 'wait_public_final'; record('dispatch_started'); await waitFor(() => false, 5000);
      };`);
    h.put('next.json', {id: 'c'.repeat(32), text: 'private matching prompt'});
    await observed(h, () => h.outputs.some(x => x.kind === 'dispatch_started'));
    h.put('cancel.json', {id: 'c'.repeat(32), reuse_when_idle: true});
    await observed(h, () => h.outputs.some(x => x.kind === 'worker_idle' && x.requestId));
    assert.equal(h.outputs.find(x => x.kind === 'worker_idle' && x.requestId).cancelledIdleVerified, true);
    assert.deepEqual(h.fixture.operations.filter(x => x === 'cancelGeneration'), ['cancelGeneration']);
    assert.equal(/fixture-user|private-fixture|private matching prompt/.test(JSON.stringify(h.outputs)), false);
  } finally { h.cleanup(); }
});

test("plugin navigation after the one Stop click cannot retain the cancelled worker", async () => {
  const h = hostHarness();
  try {
    await observed(h, () => h.outputs.some(x => x.kind === 'worker_ready'));
    h.fixture.state.userCount = 1;
    h.context.__host.surface.webContents.url = 'https://chatgpt.com/?temporary-chat=true';
    h.invoke(`const originalPage = inPage;
      inPage = async function (fn, ...args) {
        const result = await originalPage(fn, ...args);
        if (fn.name === 'cancelGeneration') surface.webContents.url = 'https://chatgpt.com/plugins';
        return result;
      };
      runCurrentPage = async function () {
        sent = true; dispatchedPublicPrompt = config.text;
        dispatchedUserId = 'fixture-user';
        stage = 'wait_public_final'; record('dispatch_started'); await waitFor(() => false, 5000);
      };`);
    h.put('next.json', {id: 'c'.repeat(32), text: 'new stop navigation fixture'});
    await observed(h, () => h.outputs.some(x => x.kind === 'dispatch_started'));
    h.put('cancel.json', {id: 'c'.repeat(32), reuse_when_idle: true});
    await observed(h, () => h.outputs.some(x => x.kind === 'cancel_idle_unverified'));
    assert.equal(h.outputs.find(x => x.kind === 'cancel_idle_unverified').error,
      'web_cancel_page_binding_required');
    assert.deepEqual(h.fixture.operations.filter(x => x === 'cancelGeneration'), ['cancelGeneration']);
    assert.equal(h.outputs.some(x => x.cancelledIdleVerified === true), false);
  } finally { h.cleanup(); }
});

test("a racing answer cannot complete a turn already owned by cancellation", async () => {
  const h = hostHarness();
  try {
    await observed(h, () => h.outputs.some(x => x.kind === 'worker_ready'));
    h.fixture.state.userCount = 1;
    h.context.__host.surface.webContents.url = 'https://chatgpt.com/?temporary-chat=true';
    h.invoke(`runCurrentPage = async function () {
      stage = 'wait_public_final'; sent = true; dispatchedPublicPrompt = config.text;
      dispatchedUserId = 'fixture-user'; record('dispatch_started');
      await waitFor(() => cancelling, 5000);
      completedPage = {prompt: config.text, message: {text: 'racing answer'}};
      finish(0, {model: config.model, effortIndex: 2, publicMessage: {text: 'racing answer'}});
    }`);
    h.put('next.json', {id: 'a'.repeat(32), text: 'cancel race'});
    await observed(h, () => h.outputs.some(x => x.kind === 'dispatch_started'));
    h.put('cancel.json', {id: 'a'.repeat(32), reuse_when_idle: true});
    await observed(h, () => h.outputs.some(x => x.kind === 'worker_idle' && x.requestId));
    assert.equal(h.outputs.some(x => x.kind === 'completed'), false);
    assert.equal(h.outputs.filter(x => x.kind === 'failed').length, 1);
    assert.equal(h.outputs.find(x => x.kind === 'worker_idle').cancelledIdleVerified, true);
    assert.equal(h.invoke('completedPage'), null);
  } finally { h.cleanup(); }
});

test("completed inspection keeps the exact page, sends nothing, and resumes hidden on close", async () => {
  const h = hostHarness();
  try {
    await observed(h, () => h.outputs.some(e => e.kind === "worker_ready"));
    const owned = h.context.__host.surface.webContents;
    owned.url = "https://chatgpt.com/c/fixture";
    const message = { id: 'completed', content: {content_type:'text', parts:['G1 complete public reply 中文\r\n', '', ' second part']} };
    h.fixture.publicFinal = message;
    h.context.__host.setCompleted({ prompt: "bound prompt", message });
    h.put("assist.json", { id: "3".repeat(32), inspect_completed: true });
    await observed(h, () => h.outputs.some(e => e.kind === "assistance_opened"));
    assert.equal(h.outputs.find(e => e.kind === "assistance_opened").inspectCompleted, true);
    assert.equal(h.context.__host.surface.revealed, false);
    assert.equal(owned.isFocused(), false);
    const html = Buffer.from(h.context.__host.surface.window.webContents.getURL().split(',')[1], 'base64').toString();
    assert.ok(html.includes('<pre>G1 complete public reply 中文\r\n</pre><pre></pre><pre> second part</pre>'));
    assert.ok(!html.includes('<pre>G</pre>'));
    h.context.__host.surface.window.emit("close", { preventDefault() {} });
    await observed(h, () => h.outputs.some(e => e.kind === "assistance_hidden"));
    assert.equal(h.outputs.find(e => e.kind === "assistance_hidden").pagePreserved, true);
    assert.equal(owned.getURL(), "https://chatgpt.com/c/fixture");
    assert.equal(JSON.stringify(h.invoke("completedPage.message")), JSON.stringify(message));
    assert.equal(h.invoke("preparedPage"), false);
    assert.ok(h.fixture.operations.every(op => ["publicFinal", "inspectionSnapshot"].includes(op)));
    assert.equal(h.outputs.some(e => e.requestId || e.kind === "dispatch_started"), false);
    assert.equal(h.context.__host.surface.window.isVisible(), false);
    // The next normal request still owns the one checked New chat navigation.
    await h.invoke("loadFreshPage()");
    assert.equal(h.fixture.operations.filter(op => op === "startFreshChat").length, 1);
  } finally { h.cleanup(); }
});

test("missing or changed completed page cannot open a snapshot or navigate", async () => {
  for (const changed of [false, true]) {
    const h = hostHarness();
    try {
      await observed(h, () => h.outputs.some(e => e.kind === "worker_ready"));
      if (changed) {
        h.context.__host.surface.webContents.url = "https://chatgpt.com/c/fixture";
        h.context.__host.setCompleted({ prompt: "bound", message: { text: "original" } });
        h.fixture.publicFinal = { text: "changed" };
      }
      h.put("assist.json", { id: "4".repeat(32), inspect_completed: true });
      await observed(h, () => h.outputs.some(e => e.kind === "assistance_failed"));
      assert.equal(h.outputs.some(e => e.kind === "assistance_opened"), false);
      assert.equal(h.context.__host.surface.window.isVisible(), false);
      assert.equal(h.fixture.operations.some(op => op !== "publicFinal"), false);
    } finally { h.cleanup(); }
  }
});

test("inspection close rejects a changed page and never declares it preserved", async () => {
  const h = hostHarness();
  try {
    await observed(h, () => h.outputs.some(e => e.kind === "worker_ready"));
    h.context.__host.surface.webContents.url = "https://chatgpt.com/c/fixture";
    const message = { id: 'completed', content: { content_type:'text', parts:['original'] } };
    h.context.__host.setCompleted({ prompt: "bound", message }); h.fixture.publicFinal = message;
    h.put("assist.json", { id: "5".repeat(32), inspect_completed: true });
    await observed(h, () => h.outputs.some(e => e.kind === "assistance_opened"));
    h.fixture.publicFinal = { text: "changed" };
    h.context.__host.surface.window.emit("close", { preventDefault() {} });
    await observed(h, () => h.outputs.some(e => e.kind === "assistance_failed"));
    assert.equal(h.outputs.some(e => e.kind === "assistance_hidden"), false);
    assert.equal(h.fixture.operations.some(op => !["publicFinal", "inspectionSnapshot"].includes(op)), false);
  } finally { h.cleanup(); }
});

test("idle worker accepts a new request after 72 hours without forgetting completed requests", async () => {
  const h = hostHarness();
  try {
    await observed(h, () => h.outputs.some(e => e.kind === "worker_ready"));
    const owned = h.context.__host.surface.webContents;
    // The real mailbox, lifecycle, completion and replay checks run unchanged.
    // Only model generation is synthetic; no browser/account is contacted.
    h.invoke(`let fixtureRuns = [];
      runCurrentPage = async () => {
        fixtureRuns.push(workerRequestId); sent = true;
        record("dispatch_started"); finish(0, { syntheticGeneration: true });
      };`);
    const first = "1".repeat(32), next = "2".repeat(32);
    h.put("next.json", { id: first, text: "first synthetic request" });
    await observed(h, () => h.outputs.some(e => e.kind === "worker_idle" && e.requestId === first));
    h.advanceTime(72 * 60 * 60 * 1000);
    h.put("next.json", { id: next, text: "new request after a long idle" });
    await observed(h, () => h.outputs.some(e => e.kind === "worker_idle" && e.requestId === next));
    assert.equal(h.context.__host.surface.webContents, owned);
    assert.equal(h.outputs.filter(e => e.kind === "worker_ready").length, 1);
    assert.equal(h.outputs.some(e => e.kind === "worker_limit_reached" || e.exitCode !== undefined), false);
    const windows = h.outputs.filter(e => e.kind === "window_state");
    assert.equal(windows.length, 2);
    assert.ok(windows.every(e => !e.visible && !e.focused && e.shown === 0 && e.focusedEvents === 0));
    h.put("next.json", { id: first, text: "must remain rejected after long idle" });
    await observed(h, () => h.outputs.some(e => e.kind === "failed" && e.error === "web_worker_request_identity_invalid"));
    assert.equal(h.invoke('JSON.stringify(fixtureRuns)'), JSON.stringify([first, next]));
  } finally { h.cleanup(); }
});

test("idle assistance uses its id, hides only on verified close, and never admits a turn", async () => {
  const h = hostHarness();
  try {
    await observed(h, () => h.outputs.some(e => e.kind === "worker_ready"));
    assert.equal(h.context.__host.surface.window.isVisible(), false);
    h.put("assist.json", { id: "b".repeat(32) });
    await observed(h, () => h.outputs.some(e => e.kind === "assistance_opened"));
    const owned = h.context.__host.surface.webContents;
    let prevented = false;
    h.context.__host.surface.window.emit("close", { preventDefault: () => { prevented = true; } });
    await observed(h, () => h.outputs.some(e => e.kind === "assistance_hidden"));
    assert.equal(prevented, true);
    const event = h.outputs.find(e => e.kind === "assistance_hidden");
    assert.equal(event.assistanceId, "b".repeat(32));
    assert.equal(event.visible, false); assert.equal(event.focused, false); assert.equal(event.userClosed, true);
    assert.equal(h.context.__host.surface.webContents, owned);
    assert.equal(h.outputs.some(e => e.requestId || e.kind === "send_started"), false);
  } finally { h.cleanup(); }
});

test("ready-looking assistance failure reports only fixed bounded close gates", async () => {
  const h = hostHarness();
  try {
    await observed(h, () => h.outputs.some(e => e.kind === "worker_ready"));
    h.put("assist.json", { id: "a".repeat(32) });
    await observed(h, () => h.outputs.some(e => e.kind === "assistance_opened"));
    h.fixture.state = { ...ready, modelButtonCount: 0,
      modelButtonLabels: ["PRIVATE PAGE TEXT"], composerShape: [{ text: "PRIVATE DRAFT" }] };
    h.context.__host.surface.window.emit("close", { preventDefault() {} });
    await observed(h, () => h.outputs.some(e => e.kind === "assistance_failed"));
    const check = h.outputs.find(e => e.kind === "assistance_close_state");
    assert.ok(check);
    assert.equal(check.assistanceId, "a".repeat(32));
    assert.equal(check.phase, "before");
    assert.equal(check.route, "temporary");
    assert.equal(check.pageKind, "chatgpt");
    assert.equal(check.modelControl, "zero");
    assert.equal(check.composer, "yes");
    assert.equal(check.composerEmpty, "unchecked");
    assert.equal(h.outputs.find(e => e.kind === "assistance_failed").error,
      "web_assistance_closed_before_ready");
    assert.equal(h.outputs.some(e => e.kind === "assistance_hidden" || e.sent || e.requestId), false);
    assert.equal(JSON.stringify(h.outputs).includes("PRIVATE PAGE TEXT"), false);
    assert.equal(JSON.stringify(h.outputs).includes("PRIVATE DRAFT"), false);
  } finally { h.cleanup(); }
});

test("a queued next during assistance fails closed without running or replaying it", async () => {
  const h = hostHarness();
  try {
    await observed(h, () => h.outputs.some(e => e.kind === "worker_ready"));
    h.put("assist.json", { id: "c".repeat(32) });
    await observed(h, () => h.outputs.some(e => e.kind === "assistance_opened"));
    h.put("next.json", { id: "d".repeat(32), text: "must never execute" });
    await observed(h, () => h.outputs.some(e => e.kind === "assistance_failed"));
    const failed = h.outputs.find(e => e.kind === "assistance_failed");
    assert.equal(failed.assistanceId, "c".repeat(32));
    assert.equal(failed.error, "web_worker_request_during_assistance");
    assert.equal(h.outputs.some(e => e.requestId), false);
  } finally { h.cleanup(); }
});

test("shutdown during assistance exits promptly without requiring window close", async () => {
  const h = hostHarness();
  try {
    await observed(h, () => h.outputs.some(e => e.kind === "worker_ready"));
    h.put("assist.json", { id: "e".repeat(32) });
    await observed(h, () => h.outputs.some(e => e.kind === "assistance_opened"));
    h.put("shutdown.json", { stop: true });
    await observed(h, () => h.outputs.some(e => e.exitCode === 0));
    assert.equal(h.outputs.some(e => e.kind === "assistance_hidden"), false);
  } finally { h.cleanup(); }
});

test("assistance does not interpret closing a draft or a prior conversation as success", async () => {
  for (const mutation of [h => { h.fixture.draft = "owner draft"; },
    h => { h.fixture.state.userCount = 1; }]) {
    const h = hostHarness();
    try {
      await observed(h, () => h.outputs.some(e => e.kind === "worker_ready"));
      h.put("assist.json", { id: "a".repeat(32) });
      await observed(h, () => h.outputs.some(e => e.kind === "assistance_opened"));
      mutation(h);
      h.context.__host.surface.window.emit("close", { preventDefault() {} });
      await observed(h, () => h.outputs.some(e => e.kind === "assistance_failed"));
      assert.equal(h.outputs.some(e => e.kind === "assistance_hidden"), false);
      assert.equal(h.outputs.find(e => e.kind === "assistance_failed").assistanceId, "a".repeat(32));
    } finally { h.cleanup(); }
  }
});

test("closing on the login origin fails without executing ChatGPT page helpers there", async () => {
  const h = hostHarness();
  try {
    await observed(h, () => h.outputs.some(e => e.kind === "worker_ready"));
    h.put("assist.json", { id: "a".repeat(32) });
    await observed(h, () => h.outputs.some(e => e.kind === "assistance_opened"));
    const contents = h.context.__host.surface.webContents;
    contents.url = "https://auth.openai.com/login";
    let helpers = 0;
    contents.executeJavaScript = async () => { helpers++; throw Error("must not run"); };
    h.context.__host.surface.window.emit("close", { preventDefault() {} });
    await observed(h, () => h.outputs.some(e => e.kind === "assistance_failed"));
    assert.equal(helpers, 0);
    assert.equal(h.outputs.some(e => e.kind === "assistance_hidden"), false);
  } finally { h.cleanup(); }
});

test("assistance packet replay cannot show the page twice", async () => {
  const h = hostHarness();
  try {
    await observed(h, () => h.outputs.some(e => e.kind === "worker_ready"));
    h.put("assist.json", { id: "a".repeat(32) });
    await observed(h, () => h.outputs.some(e => e.kind === "assistance_opened"));
    h.context.__host.surface.window.emit("close", { preventDefault() {} });
    await observed(h, () => h.outputs.some(e => e.kind === "assistance_hidden"));
    h.put("assist.json", { id: "a".repeat(32) });
    await observed(h, () => h.outputs.some(e => e.kind === "failed"));
    assert.equal(h.outputs.filter(e => e.kind === "assistance_opened").length, 1);
    assert.equal(h.outputs.find(e => e.kind === "failed").error, "web_worker_assistance_identity_invalid");
  } finally { h.cleanup(); }
});

test("an already queued request conflicts with assistance and is never admitted", async () => {
  const h = hostHarness();
  try {
    await observed(h, () => h.outputs.some(e => e.kind === "worker_ready"));
    h.put("assist.json", { id: "a".repeat(32) });
    h.put("next.json", { id: "b".repeat(32), text: "old queued text" });
    await observed(h, () => h.outputs.some(e => e.kind === "failed"));
    assert.equal(h.outputs.some(e => e.requestId || e.kind === "assistance_opened"), false);
    assert.equal(h.context.__host.surface.window.isVisible(), false);
  } finally { h.cleanup(); }
});

test("cancellation during assistance terminates without waiting for human close", async () => {
  const h = hostHarness();
  try {
    await observed(h, () => h.outputs.some(e => e.kind === "worker_ready"));
    h.put("assist.json", { id: "a".repeat(32) });
    await observed(h, () => h.outputs.some(e => e.kind === "assistance_opened"));
    h.signal("SIGTERM");
    await observed(h, () => h.outputs.some(e => e.exitCode === 1));
    const failure = h.outputs.find(e => e.kind === "assistance_failed");
    assert.equal(failure.assistanceId, "a".repeat(32));
    assert.equal(failure.error, "web_cancelled_no_retry");
    assert.equal(h.outputs.some(e => e.kind === "assistance_hidden"), false);
  } finally { h.cleanup(); }
});

test("explicit assistance prepares a verified completed page with New chat and never resends", async () => {
  const h = hostHarness();
  try {
    await observed(h, () => h.outputs.some(e => e.kind === "worker_ready"));
    h.context.__host.surface.webContents.url = "https://chatgpt.com/c/prior";
    h.fixture.publicFinal = { id: "prior-public", content: { parts: ["prior answer"] } };
    h.fixture.state = { ...ready, userCount: 1, assistantCount: 1 };
    h.context.__host.setCompleted({ prompt: "prior prompt", message: h.fixture.publicFinal });
    h.put("assist.json", { id: "a".repeat(32) });
    await observed(h, () => h.outputs.some(e => e.kind === "assistance_opened"));
    assert.deepEqual(h.fixture.operations, ["publicFinal", "startFreshChat", "enableTemporaryChat"]);
    assert.equal(h.context.__host.surface.webContents.url, "https://chatgpt.com/?temporary-chat=true");
    h.context.__host.surface.window.emit("close", { preventDefault() {} });
    await observed(h, () => h.outputs.some(e => e.kind === "worker_idle"));
    const idle = h.outputs.find(e => e.kind === "worker_idle");
    assert.equal(idle.assistanceRequired, false);
    assert.equal(idle.requestId, undefined);
    assert.equal(h.outputs.some(e => e.sent || e.requestId), false);
  } finally { h.cleanup(); }
});

test("assistance refuses a changed completed page before any navigation or display", async () => {
  const h = hostHarness();
  try {
    await observed(h, () => h.outputs.some(e => e.kind === "worker_ready"));
    h.context.__host.surface.webContents.url = "https://chatgpt.com/c/prior";
    h.context.__host.setCompleted({ prompt: "prior prompt", message: { id: "known" } });
    h.fixture.publicFinal = { id: "changed" };
    h.put("assist.json", { id: "a".repeat(32) });
    await observed(h, () => h.outputs.some(e => e.kind === "assistance_failed"));
    assert.deepEqual(h.fixture.operations, ["publicFinal"]);
    assert.equal(h.context.__host.surface.window.isVisible(), false);
    assert.equal(h.outputs.some(e => e.kind === "assistance_opened"), false);
    assert.equal(h.outputs.find(e => e.kind === "assistance_failed").error, "web_new_chat_previous_page_changed");
  } finally { h.cleanup(); }
});

test("a synchronous storage flush failure settles the admitted turn and cannot preserve its worker", async () => {
  const h = hostHarness();
  try {
    await observed(h, () => h.outputs.some(e => e.kind === "worker_ready"));
    h.context.__host.surface.webContents.session.flushStorageData = () => { throw Error("storage unavailable"); };
    h.put("next.json", { id: "b".repeat(32), text: "synthetic fixture" });
    await observed(h, () => h.outputs.some(e => e.kind === "worker_idle"));
    assert.equal(h.outputs.find(e => e.kind === "failed").error, "web_browser_storage_failed");
    assert.equal(h.outputs.find(e => e.kind === "worker_idle").assistanceRequired, false);
    assert.equal(h.outputs.some(e => e.sent), false);
  } finally { h.cleanup(); }
});

test("closing assistance after login on empty home restores temporary mode once and hides", async () => {
  const h = hostHarness();
  try {
    await observed(h, () => h.outputs.some(e => e.kind === "worker_ready"));
    h.put("assist.json", { id: "a".repeat(32) });
    await observed(h, () => h.outputs.some(e => e.kind === "assistance_opened"));
    h.context.__host.surface.webContents.url = "https://chatgpt.com/";
    h.context.__host.surface.window.emit("close", { preventDefault() {} });
    await observed(h, () => h.outputs.some(e => e.kind === "assistance_hidden"));
    assert.deepEqual(h.fixture.operations, ["enableTemporaryChat"]);
    assert.equal(h.context.__host.surface.webContents.url, "https://chatgpt.com/?temporary-chat=true");
    assert.equal(h.outputs.some(e => e.sent || e.requestId), false);
    assert.equal(h.outputs.find(e => e.kind === "assistance_hidden").assistanceId, "a".repeat(32));
  } finally { h.cleanup(); }
});

test("closing a checked read-only plugin page returns once to blank chat without a model send", async () => {
  const h = hostHarness();
  try {
    await observed(h, () => h.outputs.some(e => e.kind === 'worker_ready'));
    h.put('assist.json', {id:'a'.repeat(32)});
    await observed(h, () => h.outputs.some(e => e.kind === 'assistance_opened'));
    const contents = h.context.__host.surface.webContents;
    contents.calls.length = 0;
    contents.url = 'https://chatgpt.com/plugins/plugin_asdk_app_' + 'a'.repeat(32)
      + '#settings/Plugins/plugin_asdk_app_' + 'a'.repeat(32);
    h.fixture.maintenanceReady = true;
    h.context.__host.surface.window.emit('close', {preventDefault() {}});
    await observed(h, () => h.outputs.some(e => e.kind === 'assistance_hidden'));
    assert.deepEqual(contents.calls.filter(([name]) => name === 'load'), [['load','https://chatgpt.com/?temporary-chat=true']]);
    assert.deepEqual(h.fixture.operations, []);
    assert.equal(h.outputs.some(e => e.requestId || e.sent), false);
    assert.equal(h.context.__host.surface.window.isVisible(), false);
  } finally {h.cleanup();}
});

test("plugin return rejects edits, other routes and changed landing pages without retry", async () => {
  for (const [url, ready, draft] of [
    ['https://chatgpt.com/plugins',false,''],
    ['https://chatgpt.com/plugins?x=1',true,''],
    ['https://chatgpt.com/plugins/new',true,''],
    ['https://chatgpt.com/plugins#settings/Security',true,''],
    ['https://chatgpt.com/plugins',true,'new draft'],
  ]) {
    const h=hostHarness();
    try {
      await observed(h,()=>h.outputs.some(e=>e.kind==='worker_ready'));
      h.put('assist.json',{id:'a'.repeat(32)});
      await observed(h,()=>h.outputs.some(e=>e.kind==='assistance_opened'));
      const contents=h.context.__host.surface.webContents;contents.calls.length=0;contents.url=url;
      h.fixture.maintenanceReady=ready;h.fixture.draft=draft;
      h.context.__host.surface.window.emit('close',{preventDefault(){}});
      await observed(h,()=>h.outputs.some(e=>e.kind==='assistance_failed'));
      assert.equal(contents.calls.filter(([name])=>name==='load').length,draft?1:0);
      assert.equal(h.outputs.some(e=>e.kind==='assistance_hidden'||e.sent),false);
    } finally {h.cleanup();}
  }
});

test("home-page assistance never activates temporary mode over a draft or conversation", async () => {
  for (const mutation of [h => { h.fixture.draft = "owner draft"; },
    h => { h.fixture.state.userCount = 1; }, h => { h.fixture.state.assistantCount = 1; },
    h => { h.fixture.state.modernRowCount = 1; },
    h => { h.fixture.state.loginVisible = true; }]) {
    const h = hostHarness();
    try {
      await observed(h, () => h.outputs.some(e => e.kind === "worker_ready"));
      h.put("assist.json", { id: "a".repeat(32) });
      await observed(h, () => h.outputs.some(e => e.kind === "assistance_opened"));
      h.context.__host.surface.webContents.url = "https://chatgpt.com/";
      mutation(h);
      h.context.__host.surface.window.emit("close", { preventDefault() {} });
      await observed(h, () => h.outputs.some(e => e.kind === "assistance_failed"));
      assert.deepEqual(h.fixture.operations, []);
      assert.equal(h.outputs.some(e => e.kind === "assistance_hidden"), false);
    } finally { h.cleanup(); }
  }
});

test("assistance rejects conversation URLs and unknown home queries before page operations", async () => {
  for (const url of ["https://chatgpt.com/c/other", "https://chatgpt.com/?model=other",
    "https://chatgpt.com/?temporary-chat=true&x=1"]) {
    const h = hostHarness();
    try {
      await observed(h, () => h.outputs.some(e => e.kind === "worker_ready"));
      h.put("assist.json", { id: "a".repeat(32) });
      await observed(h, () => h.outputs.some(e => e.kind === "assistance_opened"));
      h.context.__host.surface.webContents.url = url;
      h.context.__host.surface.window.emit("close", { preventDefault() {} });
      await observed(h, () => h.outputs.some(e => e.kind === "assistance_failed"));
      assert.deepEqual(h.fixture.operations, []);
      assert.equal(h.outputs.some(e => e.kind === "assistance_hidden"), false);
    } finally { h.cleanup(); }
  }
});

test("a rejected pre-dispatch public login redirect can load only the constant page on explicit assistance", async () => {
  const h = hostHarness();
  try {
    await observed(h, () => h.outputs.some(e => e.kind === "worker_ready"));
    h.fixture.redirectOnce = "https://auth.openai.com/login?fixture=DO_NOT_RETAIN";
    h.put("next.json", { id: "b".repeat(32), text: "old request must stay failed" });
    await observed(h, () => h.outputs.some(e => e.kind === "worker_idle"));
    const failed = h.outputs.find(e => e.kind === "failed");
    assert.equal(failed.error, "web_browser_login_required_before_dispatch");
    assert.equal(failed.stage, "load_fresh_page");
    assert.equal(failed.sent, false);
    assert.equal(h.outputs.find(e => e.kind === "worker_idle").assistanceRequired, true);
    assert.equal(h.outputs.some(e => e.exitCode !== undefined), false);
    h.put("assist.json", { id: "a".repeat(32) });
    await observed(h, () => h.outputs.some(e => e.kind === "assistance_opened"));
    assert.equal(h.outputs.find(e => e.kind === "assistance_opened").requestId, undefined);
    assert.deepEqual(h.context.__host.surface.webContents.calls.filter(([name]) => name === "load"),
      [["load", "https://chatgpt.com/?temporary-chat=true"]]);
    assert.equal(JSON.stringify(h.outputs).includes("DO_NOT_RETAIN"), false);
    assert.equal(h.outputs.some(e => e.sent), false);
    h.context.__host.surface.window.emit("close", { preventDefault() {} });
    await observed(h, () => h.outputs.some(e => e.kind === "assistance_hidden"));
  } finally { h.cleanup(); }
});

test("nonpublic login redirects remain terminal and cannot request assistance recovery", async () => {
  for (const url of ["https://auth.openai.com.evil/login", "https://user@auth.openai.com/login",
    "https://login.microsoftonline.com/", "http://auth.openai.com/login"]) {
    const h = hostHarness();
    try {
      await observed(h, () => h.outputs.some(e => e.kind === "worker_ready"));
      h.fixture.redirectOnce = url;
      h.put("next.json", { id: "b".repeat(32), text: "synthetic fixture" });
      await observed(h, () => h.outputs.some(e => e.kind === "worker_idle"));
      assert.equal(h.outputs.find(e => e.kind === "failed").error, "web_navigation_not_allowed_no_retry");
      assert.equal(h.outputs.find(e => e.kind === "worker_idle").assistanceRequired, false);
      assert.equal(h.outputs.some(e => e.sent), false);
    } finally { h.cleanup(); }
  }
});

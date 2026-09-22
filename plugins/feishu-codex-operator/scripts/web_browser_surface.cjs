"use strict";

/*
 * Hidden viewport placement and device-emulation lifecycle adapted from:
 * https://github.com/miuuyy/codex-chatgpt-web/blob/e85e3693fdb4e3e033348c08df0298c20fcdb612/launcher/electron/browser-host.cjs
 * (hiddenTurnBounds, enableHiddenTurnViewport, presentTurnView).
 * The Operator host uses Electron directly; it does not open a CDP endpoint.
 *
 * MIT License
 * Copyright (c) 2026 codex-chatgpt-web contributors
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */

const MIN_VIEWPORT = Object.freeze({ width: 800, height: 600 });

function surfaceBounds(window, visible) {
  const [contentWidth, contentHeight] = window.getContentSize();
  const width = Math.max(MIN_VIEWPORT.width, Math.round(contentWidth || 0));
  const height = Math.max(MIN_VIEWPORT.height, Math.round(contentHeight || 0));
  return { x: visible ? 0 : width + 1, y: visible ? 0 : height + 1, width, height };
}

class BrowserSurface {
  constructor({ BrowserWindow, WebContentsView, browserSession, onFailure = () => {} }) {
    this.onFailure = onFailure;
    this.rendererReady = false;
    this.emulationDirty = true;
    this.emulationViewport = null;
    this.revealed = false;
    this.closed = false;
    this.snapshotReady = false;
    this.window = new BrowserWindow({ width: 1080, height: 850, show: false,
      title: "Operator 网页模型辅助窗口", autoHideMenuBar: true,
      focusable: false, skipTaskbar: true,
      webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true,
        backgroundThrottling: false, partition: "operator-web-preview",
        javascript: false, devTools: false } });
    this.view = new WebContentsView({ webPreferences: { session: browserSession,
      nodeIntegration: false, contextIsolation: true, sandbox: true,
      backgroundThrottling: false } });
    this.webContents = this.view.webContents;
    this.window.contentView.addChildView(this.view);
    this.webContents.setBackgroundThrottling(false);
    this.window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    this.window.webContents.on("will-navigate", event => event.preventDefault());
    this.window.webContents.on("render-process-gone", () => this.onFailure(new Error("web_shell_renderer_lost_no_retry")));
    this.visibilityChanged = () => this.syncSafely();
    for (const event of ["show", "hide", "minimize", "restore", "resize"])
      this.window.on(event, this.visibilityChanged);
    // Reapply the viewport after every main-frame navigation. Chromium may clear
    // effective emulation while Electron still remembers the previous dimensions.
    this.webContents.on("did-start-navigation", (_event, _url, isInPlace, isMainFrame) => {
      if (isMainFrame !== true || isInPlace) return;
      this.rendererReady = false;
      this.emulationDirty = true;
    });
    this.webContents.on("dom-ready", () => {
      this.rendererReady = true;
      this.emulationDirty = true;
      this.syncSafely();
    });
    this.window.on("closed", () => {
      this.closed = true;
      if (!this.webContents.isDestroyed()) this.webContents.close({ waitForBeforeUnload: false });
    });
    this.sync();
  }

  syncSafely() {
    try { this.sync(); } catch (error) { this.onFailure(error); }
  }

  sync() {
    if (this.closed || this.window.isDestroyed() || this.webContents.isDestroyed()) return;
    const visible = this.revealed && this.window.isVisible() && !this.window.isMinimized();
    const bounds = surfaceBounds(this.window, visible);
    if (visible) {
      // Establish on-screen bounds before clearing the explicit hidden viewport.
      this.view.setBounds(bounds);
      if (this.rendererReady && this.emulationViewport) {
        this.webContents.disableDeviceEmulation();
        this.emulationViewport = null;
      }
      if (this.rendererReady) this.emulationDirty = false;
    } else {
      if (this.rendererReady && (this.emulationDirty
          || this.emulationViewport?.width !== bounds.width
          || this.emulationViewport?.height !== bounds.height)) {
        this.webContents.enableDeviceEmulation({ screenPosition: "desktop",
          screenSize: { width: bounds.width, height: bounds.height },
          viewPosition: { x: 0, y: 0 }, deviceScaleFactor: 0,
          viewSize: { width: bounds.width, height: bounds.height }, scale: 1 });
        this.emulationViewport = { width: bounds.width, height: bounds.height };
        this.emulationDirty = false;
      }
      this.view.setBounds(bounds);
    }
    // Hiding WebContentsView itself can collapse its renderer to a 0x0 viewport.
    // Keep it drawable and place it outside the hidden shell's content rectangle.
    this.view.setVisible(true);
  }

  async loadURL(url) {
    await this.webContents.loadURL(url);
    this.rendererReady = true;
    this.emulationDirty = true;
    this.sync();
  }

  show() {
    if (this.closed || this.window.isDestroyed()) throw new Error("web_host_closed");
    if (this.snapshotReady) throw new Error("web_inspection_already_open");
    this.revealed = true;
    this.window.setFocusable(true);
    this.window.setSkipTaskbar(false);
    this.window.show();
    this.sync();
    this.window.focus();
    this.webContents.focus();
  }

  hide() {
    if (this.closed || this.window.isDestroyed()) throw new Error("web_host_closed");
    this.revealed = false;
    this.window.hide();
    this.window.setSkipTaskbar(true);
    this.window.setFocusable(false);
    this.sync();
  }

  async prepareSnapshot(snapshot) {
    if (this.closed || this.revealed || this.snapshotReady || this.window.isVisible()
        || this.window.isFocused()) throw new Error("web_inspection_requires_hidden_page");
    // Only the explicitly selected public turn and rendered notices are shown.
    // No DOM/HTML, account page, input, cookie or private reasoning is copied.
    if (!snapshot || !Array.isArray(snapshot.parts) || !snapshot.parts.length || snapshot.parts.length > 1024
        || snapshot.parts.some(text => typeof text !== "string") || !Array.isArray(snapshot.notices)
        || snapshot.notices.length > 16 || snapshot.notices.some(text => typeof text !== "string" || text.length > 4096)
        || Object.keys(snapshot).length !== 2)
      throw new Error("web_inspection_snapshot_invalid");
    if (Buffer.byteLength(JSON.stringify(snapshot), "utf8") > 65536)
      throw new Error("web_inspection_snapshot_bound");
    const escape = text => text.replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
    const html = '<!doctype html><meta charset="utf-8">'
      + '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
      + '<title>Operator 现场预览（只读）</title><style>body{margin:0;background:#eee;color:#222;font:15px system-ui}'
      + 'p,h2,pre{padding:16px;margin:0}h2{font-size:16px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;background:white}</style>'
      + '<p>当前回复与已显示提示的只读文字快照 · 关闭后保留原对话</p>'
      + '<h2>页面提示</h2>' + (snapshot.notices.some(text => /\S/u.test(text)) ? '' : '<p>当前未发现可读的已显示提示。</p>')
      + snapshot.notices.map(text => '<pre>' + escape(text) + '</pre>').join('')
      + '<h2>完整回复</h2>' + snapshot.parts.map(text => '<pre>' + escape(text) + '</pre>').join('')
      + '<p>回复内容与页面提示分别展示；模型自述的拒绝原因不等于实际拒绝证据。</p>';
    await this.window.webContents.loadURL('data:text/html;charset=utf-8;base64,' + Buffer.from(html).toString('base64'));
    this.snapshotReady = true;
  }

  showSnapshot() {
    if (this.closed || this.window.isDestroyed() || !this.snapshotReady || this.revealed)
      throw new Error("web_inspection_snapshot_invalid");
    this.window.setTitle("Operator 现场预览（只读）");
    this.window.setFocusable(true);
    this.window.setSkipTaskbar(false);
    this.window.show();
    this.sync(); // revealed remains false: never present/focus the account view.
    this.window.focus();
  }

  async clearSnapshot() {
    if (this.window.isVisible() || this.window.isFocused()) throw new Error("web_inspection_requires_hidden_page");
    await this.window.webContents.loadURL("about:blank");
    this.window.webContents.navigationHistory.clear();
    this.snapshotReady = false;
    this.window.setTitle("Operator 网页模型辅助窗口");
  }
}

function validateAssistancePacket(value, seen) {
  if (!value || typeof value !== "object" || Array.isArray(value)
      || Object.keys(value).some(key => !["id", "inspect_completed"].includes(key))
      || (Object.hasOwn(value, "inspect_completed") && value.inspect_completed !== true)
      || typeof value.id !== "string"
      || !/^[a-f0-9]{32}$/.test(value.id) || seen.has(value.id) || seen.size >= 128)
    throw new Error("web_worker_assistance_identity_invalid");
  return value.id;
}

function assistanceReady(state) {
  return state?.pageKind === "chatgpt" && state.composer === true
    && state.modelButtonCount === 1 && state.loginVisible === false
    && state.userCount === 0 && state.assistantCount === 0;
}

function recoverableBeforeDispatch(error, sent) {
  return sent === false && ["web_browser_login_required_before_dispatch",
    "web_browser_challenge_required_before_dispatch"].includes(error);
}

function navigationAllowed(value, assisting) {
  try {
    const url = new URL(value);
    return !url.username && !url.password && (url.origin === "https://chatgpt.com"
      || assisting === true && url.origin === "https://auth.openai.com");
  } catch { return false; }
}

function isPublicLoginUrl(value) {
  try {
    const url = new URL(value);
    return url.origin === "https://auth.openai.com" && !url.username && !url.password;
  } catch { return false; }
}

function isEmptyTemporaryChatUrl(value) {
  try {
    const url = new URL(value);
    return url.origin === "https://chatgpt.com" && !url.username && !url.password
      && url.pathname === "/" && url.search === "?temporary-chat=true" && url.hash === "";
  } catch { return false; }
}

function isEmptyChatHomeUrl(value) {
  try {
    const url = new URL(value);
    return url.origin === "https://chatgpt.com" && !url.username && !url.password
      && url.pathname === "/" && url.search === "" && url.hash === "";
  } catch { return false; }
}

function isPluginMaintenanceUrl(value) {
  try {
    const url = new URL(value);
    if (url.origin !== "https://chatgpt.com" || url.username || url.password || url.search) return false;
    const detail = /^\/plugins\/(plugin_asdk_app_[a-f0-9]{32})$/.exec(url.pathname);
    return url.pathname === "/plugins" && ["", "#settings/Plugins"].includes(url.hash)
      || !!detail && ["", "#settings/Plugins/" + detail[1]].includes(url.hash);
  } catch { return false; }
}

module.exports = { BrowserSurface, surfaceBounds, MIN_VIEWPORT,
  validateAssistancePacket, assistanceReady, recoverableBeforeDispatch,
  navigationAllowed, isEmptyTemporaryChatUrl, isEmptyChatHomeUrl, isPublicLoginUrl,
  isPluginMaintenanceUrl };

"use strict";

// Operator-owned, opt-in single-request browser host. This is not an installer
// or MCP executor. It uses Electron directly; the attributed hidden-surface
// implementation lives in web_browser_surface.cjs, with no upstream runtime import.
// Dated ChatGPT DOM/message contract and source ideas: references/chatgpt-web-integration.md.
const { app, BrowserWindow, WebContentsView, session } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const page = require("./web_browser_page.cjs");
const modelCatalog = require("./operator_core/web_model_catalog.json");
const { BrowserSurface, validateAssistancePacket, assistanceReady,
  recoverableBeforeDispatch, navigationAllowed, isEmptyTemporaryChatUrl,
  isEmptyChatHomeUrl, isPublicLoginUrl, isPluginMaintenanceUrl } = require("./web_browser_surface.cjs");

const configPath = process.argv[2];
let config, win, surface, timer, cancelWatch, deadlineAt, stage = "configuration", sent = false, ended = false, cancelling = false;
let ownedConnectorQuery = null;
let windowShown = 0, windowFocused = 0;
let workerMode = false, workerRequestId = null, workerClosing = false, finishTurn = null;
let cancelledIdleVerified = false;
let assisting = false, assistanceClosing = false, finishAssistance = null;
let assistanceId = null, assistanceFailed = false, assistanceRequired = false, lastFailure = null;
let needsAssistanceNavigation = false;
let preparedPage = false;
let completedPage = null;
let inspectionPage = null;
let verifiedSelection = null;

function modelSelection(value) {
  requireValue(Object.hasOwn(modelCatalog.models, value.model), "web_explicit_model_required");
  const definition = modelCatalog.models[value.model];
  requireValue(definition.reasoning_efforts.includes(value.effort), "web_explicit_effort_required");
  return { ...definition, effort: modelCatalog.efforts[value.effort] };
}
function effortDiagnostic(state) {
  const knownLabels = ["即时", "中", "高", "极高", "Instant", "Medium", "High", "Extra high", "Pro"];
  const rawHeader = state?.generationLabel;
  return {
    value: Number.isInteger(state?.value) && state.value >= 0 && state.value <= 4 ? state.value : null,
    label: knownLabels.includes(state?.label) ? state.label : "unrecognized",
    announcedGeneration: ["5.6", "6"].includes(state?.announcedGeneration)
      ? state.announcedGeneration : null,
    // Model-menu text is public UI, but never retain arbitrary page text.
    header: typeof rawHeader === "string" && /^[A-Za-z0-9. -]{1,32}$/.test(rawHeader)
      ? rawHeader : "unrecognized",
  };
}
function boundedEffortRange(state, shape, generation) {
  const count = value => ['zero', 'one', 'multiple', 'unknown'].includes(value) ? value : 'unknown';
  const number = value => Number.isInteger(value) && value >= 0 && value <= 9
    ? value : ['absent', 'other', 'unknown'].includes(value) ? value : 'unknown';
  const flag = value => ['yes', 'no', 'unknown'].includes(value) ? value : 'unknown';
  return {containerCount: count(shape?.containerCount),
    newContainerTotal: count(shape?.newContainerTotal),
    newContainerVisible: count(shape?.newContainerVisible),
    sliderCount: count(shape?.sliderCount),
    statePresent: state && typeof state === 'object' ? 'yes' : 'no',
    min: number(shape?.min), max: number(shape?.max), now: number(shape?.now),
    locked: flag(shape?.locked),
    globalSliderTotal: count(shape?.globalSliderTotal),
    globalSliderVisible: count(shape?.globalSliderVisible),
    globalMin: number(shape?.globalMin), globalMax: number(shape?.globalMax),
    globalNow: number(shape?.globalNow),
    globalSliderRect: flag(shape?.globalSliderRect),
    globalSliderHidden: flag(shape?.globalSliderHidden),
    globalSliderInert: flag(shape?.globalSliderInert),
    globalSliderAriaHidden: flag(shape?.globalSliderAriaHidden),
    globalSliderClosedMenu: flag(shape?.globalSliderClosedMenu),
    globalSliderInNewContainer: flag(shape?.globalSliderInNewContainer),
    ownerMenuitem: flag(shape?.ownerMenuitem), ownerMenu: flag(shape?.ownerMenu),
    sameMenuAsChooser: flag(shape?.sameMenuAsChooser),
    generationMatches: !state ? 'unknown' : state.announcedGeneration === null ? 'unannounced'
      : state.announcedGeneration === generation ? 'yes' : 'no',
    proLabel: !state || state.label === null ? 'unknown' : state.label === 'Pro' ? 'yes' : 'no',
    proHeader: !state || typeof state.generationLabel !== 'string' ? 'unknown'
      : /Pro\s*$/.test(state.generationLabel) ? 'yes' : 'no'};
}
const networkRequests = new Map();
let networkEventCount = 0;
function record(kind, value = {}) {
  process.stdout.write(JSON.stringify({ operator_web: 1, kind, stage, sent,
    ...(workerRequestId ? { requestId: workerRequestId } : {}), ...value }) + "\n");
}
function exitBrowser(code) {
  record("exit_requested", { exitCode: code });
  app.exit(code);
}
function finish(code, value) {
  if (ended) return;
  // The bound cancellation owns its terminal and bounded idle check. A racing
  // public answer must not seal a successful turn or skip that check.
  if (cancelling && code === 0) return;
  lastFailure = code ? value?.error : null;
  if (assisting && code && !assistanceFailed) {
    assistanceFailed = true;
    record("assistance_failed", { ...(assistanceId ? { assistanceId } : {}), error: lastFailure });
  }
  ended = true;
  clearTimeout(timer);
  if (!workerMode || !workerRequestId) clearInterval(cancelWatch);
  if (win && !win.isDestroyed()) record("window_state", {
    visible: win.isVisible(), focused: win.isFocused(), shown: windowShown, focusedEvents: windowFocused,
    backgroundInput: config.backgroundInput === "dom_v1", inputMode: config.backgroundInput || "native_v1" });
  if (workerMode && workerRequestId) {
    let settled = false;
    const done = failed => {
      if (settled) return;
      settled = true;
      clearTimeout(closing);
      if (failed) { code = 1; value = { error: "web_browser_storage_failed" }; }
      lastFailure = code ? value?.error : null;
      record(code ? "failed" : "completed", value);
      finishTurn(code);
    };
    const closing = setTimeout(() => done(true), 5000);
    if (!win || win.isDestroyed() || !surface || surface.webContents.isDestroyed()) { done(true); return; }
    try {
      surface.webContents.session.flushStorageData();
      surface.webContents.session.cookies.flushStore().then(() => done(false), () => done(true));
    } catch { done(true); }
    return;
  }
  record(code ? "failed" : "completed", value);
  if (!win || win.isDestroyed()) return exitBrowser(code);
  if (!surface || surface.webContents.isDestroyed()) return exitBrowser(code || 1);
  const closing = setTimeout(() => exitBrowser(code || 1), 5000);
  try {
    surface.webContents.session.flushStorageData();
    surface.webContents.session.cookies.flushStore().then(() => {
      clearTimeout(closing);
      exitBrowser(code);
    }, () => { clearTimeout(closing); exitBrowser(1); });
  } catch { clearTimeout(closing); exitBrowser(1); }
}
function requireValue(ok, code) { if (!ok) throw new Error(code); }
function observeModelNetwork(phase, details) {
  // Passive Electron notifications only. Never inspect/alter headers, bodies,
  // cookies, responses, or authentication; status is not a model completion.
  if (!sent || ended || !win || win.isDestroyed() || details.webContentsId !== surface.webContents.id
      || !Number.isSafeInteger(details.id) || networkEventCount >= 64) return;
  if (phase === 'sent') {
    if (networkRequests.size >= 16 || details.method !== 'POST') return;
    let url;
    try { url = new URL(details.url); } catch { return; }
    if (url.origin !== 'https://chatgpt.com' || url.search || url.hash
        || !['/backend-api/conversation', '/backend-api/f/conversation'].includes(url.pathname)) return;
    networkRequests.set(details.id, { requestId: workerRequestId });
  }
  const tracked = networkRequests.get(details.id);
  if (!tracked || tracked.requestId !== workerRequestId) return;
  const errors = new Set(['net::ERR_TIMED_OUT', 'net::ERR_CONNECTION_RESET',
    'net::ERR_HTTP2_PROTOCOL_ERROR', 'net::ERR_NETWORK_CHANGED', 'net::ERR_NAME_NOT_RESOLVED',
    'net::ERR_INTERNET_DISCONNECTED', 'net::ERR_CONNECTION_CLOSED', 'net::ERR_CONNECTION_REFUSED',
    'net::ERR_PROXY_CONNECTION_FAILED', 'net::ERR_TUNNEL_CONNECTION_FAILED']);
  record('model_network_state', { phase,
    status: Number.isInteger(details.statusCode) && details.statusCode >= 100 && details.statusCode <= 599 ? details.statusCode : null,
    error: phase === 'error' ? errors.has(details.error) || details.error === 'net::ERR_ABORTED'
      ? details.error : 'other' : null });
  networkEventCount++;
  if (phase === 'completed' || phase === 'error') networkRequests.delete(details.id);
  if (phase === 'error' && !cancelling && errors.has(details.error)) {
    // Abort/cancellation and unknown errors cannot establish a network failure.
    // Seal this dispatched turn; never retry it or infer expired authentication.
    finish(1, { error: 'web_model_network_interrupted_no_retry', networkError: details.error });
  }
  if (phase === 'response_started' && Number.isInteger(details.statusCode)
      && details.statusCode >= 400 && details.statusCode <= 599) {
    // The current generation request was rejected. Do not wait for a success
    // message, retry, or reinterpret this as an unsubmitted/login-only request.
    finish(1, { error: 'web_model_http_rejected_no_retry', upstreamStatus: details.statusCode });
  }
}
function safeError(error) {
  const value = error?.message;
  return typeof value === "string" && /^web_[a-z_]+$/.test(value) ? value : "web_browser_operation_failed";
}
function boundedControlState(state) {
  const flag = value => value === true ? "yes" : value === false ? "no" : "unknown";
  const rows = value => Number.isSafeInteger(value) && value >= 0
    ? value === 0 ? "zero" : "nonzero" : "unknown";
  const modelControl = Number.isSafeInteger(state?.modelButtonCount) && state.modelButtonCount >= 0
    ? state.modelButtonCount === 0 ? "zero" : state.modelButtonCount === 1 ? "one" : "multiple" : "unknown";
  return { pageKind: ["chatgpt", "challenge", "other"].includes(state?.pageKind)
      ? state.pageKind : "unknown", composer: flag(state?.composer), modelControl,
    loginVisible: flag(state?.loginVisible), userRows: rows(state?.userCount),
    assistantRows: rows(state?.assistantCount) };
}
function assistanceCloseState(destination, state, composerEmpty, phase) {
  return { phase, route: isEmptyTemporaryChatUrl(destination) ? "temporary"
    : isEmptyChatHomeUrl(destination) ? "home" : "other",
    ...boundedControlState(state), composerEmpty: composerEmpty === null ? "unchecked"
      : composerEmpty ? "yes" : "no" };
}
try {
  requireValue(typeof configPath === "string" && path.isAbsolute(configPath), "web_absolute_config_required");
  const bytes = fs.readFileSync(configPath);
  requireValue(bytes.length <= 1024 * 1024, "web_config_too_large");
  config = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  requireValue(config && typeof config === "object" && !Array.isArray(config), "web_config_required");
  const allowed = new Set(["version", "mode", "profileDirectory", "sessionPartition", "proxyRules", "model", "effort", "text", "visible", "timeoutMs", "awaitSendRelease", "sendReleaseFile", "prepareReleaseFile", "connectorMention", "connectorSelectionName", "autoSelectConnector", "parentPid", "cancelFile", "softwareRendering", "inspectCitations", "includeCitations", "backgroundInput", "workerDirectory", "startupAssistance", "startupPrepare", "mcpContinuation"]);
  requireValue(Object.keys(config).every(k => allowed.has(k)) && config.version === 1, "web_config_fields_invalid");
  requireValue(["assist", "inspect", "prepare", "generate", "worker"].includes(config.mode), "web_mode_invalid");
  workerMode = config.mode === "worker";
  requireValue(config.startupAssistance === undefined || workerMode && config.startupAssistance === true,
    "web_startup_assistance_invalid");
  requireValue(config.startupPrepare === undefined || workerMode && config.startupPrepare === true
    && config.startupAssistance !== true, "web_startup_prepare_invalid");
  assisting = config.startupAssistance === true;
  requireValue(workerMode ? config.backgroundInput === "dom_v1" && typeof config.workerDirectory === "string"
    && path.resolve(config.workerDirectory) === path.dirname(path.resolve(configPath))
    && fs.lstatSync(config.workerDirectory).isDirectory() && !fs.lstatSync(config.workerDirectory).isSymbolicLink()
    && Number.isSafeInteger(config.parentPid) && config.parentPid > 0
    && ["text", "cancelFile", "connectorMention", "autoSelectConnector", "awaitSendRelease", "prepareReleaseFile", "sendReleaseFile", "connectorSelectionName", "inspectCitations"].every(k => config[k] === undefined)
    : config.workerDirectory === undefined, "web_worker_configuration_invalid");
  requireValue(config.inspectCitations === undefined || config.mode === "generate"
    && typeof config.inspectCitations === "boolean", "web_citation_inspection_invalid");
  requireValue(config.includeCitations === undefined || ["generate", "worker"].includes(config.mode)
    && typeof config.includeCitations === "boolean", "web_citation_selection_invalid");
  requireValue(typeof config.profileDirectory === "string" && path.isAbsolute(config.profileDirectory), "web_profile_required");
  requireValue(typeof config.sessionPartition === "string" && /^persist:[a-z0-9-]{1,96}$/.test(config.sessionPartition), "web_partition_required");
  // Only old single-model packets may omit effort; keep their exact high default.
  if (config.effort === undefined && config.model === "gpt-5.6-sol") config.effort = "high";
  modelSelection(config);
  requireValue(typeof config.visible === "boolean", "web_visibility_required");
  requireValue(config.backgroundInput === undefined || config.backgroundInput === false
    || config.backgroundInput === "dom_v1" && (config.visible === false && config.mode !== "assist"
      && config.connectorSelectionName === undefined && config.prepareReleaseFile === undefined),
    "web_background_input_invalid");
  requireValue(config.softwareRendering === undefined || typeof config.softwareRendering === "boolean",
    "web_rendering_mode_invalid");
  if (config.softwareRendering === true) app.disableHardwareAcceleration();
  if (config.parentPid !== undefined) {
    requireValue(Number.isSafeInteger(config.parentPid) && config.parentPid > 0, "web_parent_pid_invalid");
  }
  if (config.cancelFile !== undefined) {
    requireValue(config.mode === "generate" && typeof config.cancelFile === "string"
      && path.isAbsolute(config.cancelFile)
      && path.dirname(path.resolve(config.cancelFile)) === path.dirname(path.resolve(configPath))
      && path.basename(config.cancelFile) === "cancel.txt", "web_cancel_file_invalid");
  }
  requireValue(config.awaitSendRelease === undefined || typeof config.awaitSendRelease === "boolean", "web_send_release_invalid");
  if (config.connectorMention !== undefined) {
    // Mirror Python's bounded ASCII/CJK fullmatch; JS $ alone admits final newlines.
    const mention = config.connectorMention;
    requireValue((config.mode === "generate" || config.mode === "prepare" && config.autoSelectConnector === true)
      && mention && typeof mention === "object"
      && !Array.isArray(mention) && Object.keys(mention).length === 2
      && typeof mention.id === "string" && /^plugin:asdk_app_[a-f0-9]{32}$/.test(mention.id)
      && typeof mention.name === "string" && /^[A-Za-z0-9\u3400-\u4dbf\u4e00-\u9fff][A-Za-z0-9\u3400-\u4dbf\u4e00-\u9fff -]{0,63}(?![\s\S])/.test(mention.name),
      "web_connector_mention_invalid");
  }
  if (config.connectorSelectionName !== undefined) {
    requireValue(config.mode === "generate" && config.connectorMention === undefined
      && config.awaitSendRelease === true && typeof config.connectorSelectionName === "string"
      && /^[A-Za-z0-9\u3400-\u4dbf\u4e00-\u9fff][A-Za-z0-9\u3400-\u4dbf\u4e00-\u9fff -]{0,63}(?![\s\S])/.test(config.connectorSelectionName),
      "web_connector_selection_invalid");
  }
  if (config.autoSelectConnector !== undefined) {
    requireValue(typeof config.autoSelectConnector === "boolean"
      && (!config.autoSelectConnector || config.connectorMention !== undefined),
      "web_connector_auto_selection_invalid");
  }
  if (config.sendReleaseFile !== undefined) {
    requireValue(config.mode === "generate" && config.awaitSendRelease === true
      && typeof config.sendReleaseFile === "string" && path.isAbsolute(config.sendReleaseFile)
      && path.dirname(path.resolve(config.sendReleaseFile)) === path.dirname(path.resolve(configPath))
      && path.basename(config.sendReleaseFile) === "send-release.txt", "web_send_release_file_invalid");
  }
  if (config.prepareReleaseFile !== undefined) {
    requireValue(config.mode === "generate" && typeof config.prepareReleaseFile === "string"
      && path.isAbsolute(config.prepareReleaseFile)
      && path.dirname(path.resolve(config.prepareReleaseFile)) === path.dirname(path.resolve(configPath))
      && path.basename(config.prepareReleaseFile) === "prepare-release.txt", "web_prepare_release_file_invalid");
  }
  requireValue(config.mcpContinuation === undefined || config.mcpContinuation === true
    && ["generate", "worker"].includes(config.mode), "web_mcp_continuation_invalid");
  requireValue(Number.isInteger(config.timeoutMs) && config.timeoutMs >= 10000
    && config.timeoutMs <= (config.mode === "assist" ? 900000 : config.prepareReleaseFile
      || config.mcpContinuation === true ? 600000 : 180000), "web_timeout_invalid");
  requireValue(config.mode !== "generate" ? config.text === undefined :
    typeof config.text === "string" && config.text.length > 0 && Buffer.byteLength(config.text, "utf8") <= 64 * 1024
      && [...config.text].every(c => c.codePointAt(0) < 0xd800 || c.codePointAt(0) > 0xdfff),
    "web_text_invalid");
  if (config.proxyRules !== undefined) {
    requireValue(/^socks5:\/\/127\.0\.0\.1:[1-9][0-9]{0,4}$/.test(config.proxyRules), "web_proxy_invalid");
    requireValue(Number(config.proxyRules.split(":").pop()) <= 65535, "web_proxy_invalid");
  }
  app.setName("Operator Web Model Host");
  app.setAppUserModelId("feishu.codex.operator.web-model-host");
  app.setPath("userData", config.profileDirectory);
  requireValue(app.requestSingleInstanceLock(), "web_profile_already_owned");
} catch (error) {
  record("failed", { error: safeError(error) });
  app.exit(1);
}

async function cancelOwnedGeneration(reuseWhenIdle = false) {
  if (ended || cancelling) return;
  cancelling = true;
  clearTimeout(timer);
  timer = setTimeout(() => finish(1, { error: "web_cancelled_no_retry" }), 3000);
  record("cancel_requested");
  // Best effort on this fresh, owned page only. A click does not attest to
  // provider receipt, stopped inference or billing. Never send another prompt.
  if (sent && win && !win.isDestroyed() && !config.connectorSelectionName) {
    let clicked = false;
    try {
      const expected = config.connectorMention
        ? "@" + config.connectorMention.name + " " + config.text : config.text;
      const binding = await inPage(page.publicUserBindingShape, expected, true);
      requireValue(binding?.exact === true, "web_cancel_user_binding_required");
      clicked = await inPage(page.cancelGeneration);
      record(clicked ? "cancel_click_attempted" : "cancel_click_unavailable");
      if (clicked && reuseWhenIdle && workerMode && !workerClosing) {
        let idleSince = null;
        await waitFor(async () => {
          requireBackgroundWindow();
          const binding = await inPage(page.publicUserBindingShape, expected, true);
          requireValue(binding?.exact === true, "web_cancel_user_binding_required");
          const interruption = await inPage(page.publicInterruptionState, config.connectorMention?.name ?? null);
          requireValue(interruptionCode(interruption) === null, "web_cancel_page_interrupted");
          const progress = await inPage(page.publicGenerationState, true);
          const controls = await inPage(page.controls);
          const idle = progress.stopPresent === false && progress.userRows === 1
            && controls.pageKind === "chatgpt" && controls.loginVisible === false
            && controls.composer === true && controls.userCount === 1
            && await inPage(page.composerPrefix, null) === "";
          if (!idle) { idleSince = null; return false; }
          if (idleSince === null) idleSince = Date.now();
          return Date.now() - idleSince >= 150;
        }, 2000);
        cancelledIdleVerified = !ended && !workerClosing;
      }
    } catch { record(clicked ? "cancel_idle_unverified" : "cancel_click_unavailable"); }
  }
  finish(1, { error: "web_cancelled_no_retry" });
}

if (config?.parentPid !== undefined || config?.cancelFile !== undefined) {
  cancelWatch = setInterval(() => {
    if (ended || cancelling) return;
    if (config.parentPid !== undefined) {
      try { process.kill(config.parentPid, 0); }
      catch (error) { if (error?.code === "ESRCH") { workerClosing = true; void cancelOwnedGeneration(); return; } }
    }
    if (workerMode && workerRequestId) {
      try {
        const cancel = readWorkerPacket("cancel.json", 256);
        if (cancel !== null) {
          requireValue(cancel.id === workerRequestId
            && (Object.keys(cancel).length === 1 || Object.keys(cancel).length === 2
              && cancel.reuse_when_idle === true), "web_worker_cancel_identity_changed");
          void cancelOwnedGeneration(cancel.reuse_when_idle === true);
        }
      } catch { finish(1, { error: "web_worker_cancel_identity_changed" }); }
    }
    if (workerMode && assisting) {
      try {
        requireValue(readWorkerPacket("next.json", 1024 * 1024) === null,
          "web_worker_request_during_assistance");
        const stop = readWorkerPacket("shutdown.json", 256);
        if (stop !== null) {
          requireValue(Object.keys(stop).length === 1 && stop.stop === true, "web_worker_shutdown_invalid");
          finish(0, { workerStopped: true });
        }
      } catch (error) { finish(1, { error: safeError(error) }); }
    }
    if (config.cancelFile !== undefined && fs.existsSync(config.cancelFile)) {
      try {
        const info = fs.lstatSync(config.cancelFile);
        requireValue(info.isFile() && !info.isSymbolicLink() && info.size === 7,
          "web_cancel_file_invalid");
        requireValue(fs.readFileSync(config.cancelFile).equals(Buffer.from("cancel\n")),
          "web_cancel_file_invalid");
        void cancelOwnedGeneration();
      } catch { finish(1, { error: "web_cancel_file_invalid" }); }
    }
  }, 250);
}

async function inPage(fn, ...args) {
  requireValue(!ended && win && !win.isDestroyed(), "web_host_closed");
  const current = new URL(surface.webContents.getURL());
  requireValue(current.origin === "https://chatgpt.com", "web_expected_origin_required");
  const result = await surface.webContents.executeJavaScript(`(() => {
    const currentPublicFiber = (${page.currentPublicFiber.toString()});
    const uniqueComposer = (${page.uniqueComposer.toString()});
    const eligibleModelButtons = (${page.eligibleModelButtons.toString()});
    const eligibleEffortContainer = (${page.eligibleEffortContainer.toString()});
    try { return { ok: true, value: (${fn.toString()})(...${JSON.stringify(args)}) }; }
    catch (error) { return { ok: false, code: /^web_[a-z_]+$/.test(error?.message)
      ? error.message : "web_page_operation_failed" }; }
  })()`, true);
  requireValue(result?.ok === true, result?.code || "web_page_result_invalid");
  return result.value;
}
async function waitFor(fn, milliseconds = 10000) {
  const deadline = Date.now() + milliseconds;
  do {
    const value = await fn();
    if (value) return value;
    requireValue(Date.now() < deadline, "web_page_state_timeout");
    await new Promise(resolve => setTimeout(resolve, 150));
  } while (!ended);
  throw new Error("web_host_closed");
}
function interruptionCode(state) {
  if (state.sessionExpired) return "web_session_expired_during_generation_no_retry";
  if (state.approvalCards > 0 || state.connectorDialogs > 0) return "web_tool_confirmation_required_no_retry";
  if (state.subscriptionUnavailable) return "web_subscription_unavailable_during_generation_no_retry";
  if (state.responseError) return "web_response_error_no_retry";
  return null;
}
async function waitForPublicFinal(publicPrompt, connectorName) {
  let lastObservation = 0, priorState = null, interruptedAt = 0, previousCode = null;
  return waitFor(async () => {
    const state = await inPage(page.publicInterruptionState, connectorName);
    const encoded = JSON.stringify(state), code = interruptionCode(state);
    if (encoded !== priorState) {
      record("public_interruption_state", { state });
      priorState = encoded;
    }
    if (code !== previousCode) { previousCode = code; interruptedAt = Date.now(); }
    if (code) {
      // A card may disappear after the platform applies a saved permission.
      // Observe briefly, then stop once. Do not click it, show a window or send
      // again. Even a simultaneous public answer cannot hide unresolved UI.
      if (Date.now() - interruptedAt >= 2000) throw new Error(code);
      return false;
    }
    const result = await inPage(page.publicFinal, publicPrompt, config.includeCitations === true, true);
    if (result || Date.now() - lastObservation >= 15000) {
      lastObservation = Date.now();
      record("generation_state", { progress: await inPage(page.publicGenerationState, true) });
    }
    return result;
  }, Math.max(1, deadlineAt - Date.now() - 2000));
}
async function key(keyCode) {
  if (config.backgroundInput) {
    requireBackgroundWindow();
    if (keyCode === "Backspace") {
      requireValue(await inPage(page.composerFocused), "web_background_composer_focus_required");
      surface.webContents.delete();
    } else await inPage(page.backgroundMenuKey, keyCode);
    return;
  }
  surface.webContents.sendInputEvent({ type: "keyDown", keyCode });
  surface.webContents.sendInputEvent({ type: "keyUp", keyCode });
}
function requireBackgroundWindow() {
  requireValue(config.backgroundInput === "dom_v1" && win && !win.isDestroyed()
    && !win.isVisible() && !win.isFocused() && windowShown === 0 && windowFocused === 0,
    "web_background_window_became_visible");
  requireValue(new URL(surface.webContents.getURL()).origin === "https://chatgpt.com", "web_background_input_unavailable");
}
async function insertText(text) {
  if (config.backgroundInput) {
    requireBackgroundWindow();
    requireValue(await inPage(page.composerFocused), "web_background_composer_focus_required");
  }
  await surface.webContents.insertText(text);
}
async function selectAll() {
  if (config.backgroundInput) {
    requireBackgroundWindow();
    requireValue(await inPage(page.composerFocused), "web_background_composer_focus_required");
  }
  surface.webContents.selectAll();
}
async function waitRelease(file, command) {
  await waitFor(async () => {
    let stat;
    try { stat = fs.lstatSync(file); }
    catch (error) { if (error.code === "ENOENT") return false; throw error; }
    const expected = Buffer.from(command);
    requireValue(stat.isFile() && !stat.isSymbolicLink() && stat.size === expected.length, "web_send_release_invalid");
    const fd = fs.openSync(file, "r");
    try {
      const bytes = Buffer.alloc(expected.length + 1);
      requireValue(fs.readSync(fd, bytes, 0, bytes.length, 0) === expected.length
        && bytes.subarray(0, expected.length).equals(expected), "web_send_release_invalid");
    } finally { fs.closeSync(fd); }
    return true;
  }, Math.max(1, deadlineAt - Date.now() - 2000));
}
async function menu() {
  if (!config.backgroundInput) {
    win.focus();
    surface.webContents.focus();
    await waitFor(async () => win.isFocused() && surface.webContents.isFocused()
      && (await inPage(page.controls)).documentFocused, 5000);
  }
  if (await inPage(page.focusModelMenu)) {
    // The first hydrated composer can still replace its initial model control.
    // Wait for one stable visible target before our single activation.
    let prior = null, stableSince = 0;
    const ready = await waitFor(async () => {
      const state = await inPage(page.controls);
      if (!state.modelControlInteractive || !state.modelControlFocused || !state.modelControlPoint) return false;
      const signature = JSON.stringify([state.modelControlPoint, state.modelButtonLabels]);
      if (signature !== prior) { prior = signature; stableSince = Date.now(); }
      return Date.now() - stableSince >= 750 && state;
    });
    const { x, y } = ready.modelControlPoint;
    const [width, height] = win.getContentSize();
    requireValue(Number.isInteger(x) && Number.isInteger(y) && x >= 0 && y >= 0
      && x < width && y < height, "web_model_point_invalid");
    if (config.backgroundInput) {
      requireBackgroundWindow();
      await inPage(page.backgroundModelInput, { x, y });
    } else {
      surface.webContents.sendInputEvent({ type: "mouseMove", x, y });
      await new Promise(resolve => setTimeout(resolve, 80));
      surface.webContents.sendInputEvent({ type: "mouseDown", x, y, button: "left", clickCount: 1 });
      await new Promise(resolve => setTimeout(resolve, 80));
      surface.webContents.sendInputEvent({ type: "mouseUp", x, y, button: "left", clickCount: 1 });
    }
  }
  record("model_menu_input", { controls: boundedControlState(await inPage(page.controls)) });
  await waitFor(async () => (await inPage(page.controls)).chooser);
}
async function selectModel() {
  verifiedSelection = null;
  const requested = modelSelection(config);
  const controls = () => inPage(page.controls, requested.picker_labels);
  stage = "open_model_menu";
  await menu();
  stage = "open_versions";
  await inPage(page.clickModelChooser);
  await waitFor(async () => (await controls()).modelOption);
  stage = "choose_model";
  await inPage(page.chooseModel, requested.picker_labels);
  await waitFor(async () => (await inPage(page.controls)).chooser);
  stage = "verify_selection";
  await inPage(page.clickModelChooser);
  const selected = await waitFor(async () => {
    const state = await controls();
    return state.modelOption && state;
  });
  requireValue(selected.modelChecked === "true", "web_selected_model_not_retained");
  record("model_selection_checked", { model: config.model, checked: selected.modelChecked });
  stage = "close_versions";
  await key("Escape");
  await waitFor(async () => !(await controls()).modelOption);
  stage = "open_effort_menu";
  await menu();
  stage = "select_effort";
  let slider;
  try { slider = await inPage(page.effortState); }
  catch (error) {
    if (error?.message === 'web_effort_shape_invalid') {
      let shape = null;
      try { shape = await inPage(page.effortRangeShape); } catch { /* Keep the original failure. */ }
      record('effort_range_unavailable', boundedEffortRange(null, shape, requested.generation));
    }
    throw error;
  }
  if (!slider || slider.min !== 0 || slider.max !== 4 || slider.locked) {
    let shape = null;
    try { shape = await inPage(page.effortRangeShape); } catch { /* Keep the original failure. */ }
    record('effort_range_unavailable', boundedEffortRange(slider, shape, requested.generation));
    throw new Error('web_effort_range_invalid');
  }
  record("effort_initial_state", effortDiagnostic(slider));
  const move = async target => { for (let steps = 0; slider.value !== target; steps++) {
    requireValue(steps < 4, "web_effort_step_mismatch");
    const direction = slider.value < target ? 1 : -1;
    await inPage(page.focusEffort);
    await key(direction > 0 ? "Right" : "Left");
    const previous = slider.value;
    let lastStepState = slider;
    try {
      slider = await waitFor(async () => {
        const next = await inPage(page.effortState);
        lastStepState = next;
        return next && next.value !== previous && next;
      });
    } catch (error) {
      record("effort_step_unavailable", { previous, target, ...effortDiagnostic(lastStepState) });
      throw error;
    }
    record("effort_step_verified", { previous, target, ...effortDiagnostic(slider) });
    requireValue(slider.min === 0 && slider.max === 4 && !slider.locked
      && slider.value === previous + direction, "web_effort_step_mismatch");
  }};
  // Latest is a moving alias. Its public Pro header currently names the
  // generation even when ordinary effort labels omit it. Never infer 6 from
  // the word Latest alone or silently adopt a future generation.
  await move(4);
  // The slider value and its model header are committed by separate UI updates.
  // Wait for the Pro header before comparing generations; a different named
  // generation still fails below, without submitting the request.
  let lastProState = slider;
  try {
    slider = await waitFor(async () => {
      const next = await inPage(page.effortState);
      lastProState = next;
      return next && next.value === 4 && next.label === "Pro"
        && /Pro$/.test((next.generationLabel || "").replace(/\s+/g, "")) && next;
    }, 5000);
  } catch (error) {
    record("effort_pro_unavailable", effortDiagnostic(lastProState));
    throw error;
  }
  const observedHeader = (slider.generationLabel || "").replace(/\s+/g, "");
  const allowedHeaders = [requested.generation + "Pro", "GPT-" + requested.generation + "Pro"];
  // This account's managed Electron page renders the selected 5.6 Pro header
  // as "5.6 Sol Pro"; the in-app browser renders "5.6 Pro". Both name the
  // same explicit generation, and the 5.6 radio option was checked above.
  if (requested.generation === "5.6") allowedHeaders.push("5.6SolPro", "GPT-5.6SolPro");
  // The managed Latest page can render just "Pro" in its heading while the
  // same visible slider announces "6 Pro". Accept that observed combination
  // only after the Latest radio option was checked and the slider names 6.
  const announcedLatestPro = requested.generation === "6" && observedHeader === "Pro"
    && slider.announcedGeneration === "6";
  requireValue(slider.label === "Pro" && (allowedHeaders.includes(observedHeader) || announcedLatestPro)
    && (slider.announcedGeneration === null || slider.announcedGeneration === requested.generation),
    "web_model_generation_mismatch");
  record("effort_pro_verified", effortDiagnostic(slider));
  await move(requested.effort.index);
  requireValue(requested.effort.labels.includes(slider.label), "web_effort_label_mismatch");
  requireValue(slider.announcedGeneration === null || slider.announcedGeneration === requested.generation,
    "web_model_generation_mismatch");
  record("effort_target_verified", effortDiagnostic(slider));
  verifiedSelection = { model: config.model, effortIndex: slider.value };
  record("model_verified", { ...verifiedSelection, generation: requested.generation, effort: config.effort });
  await key("Escape");
  await waitFor(async () => !(await inPage(page.controls)).chooser);
}

app.whenReady().then(async () => {
  if (!workerMode) {
    deadlineAt = Date.now() + config.timeoutMs;
    timer = setTimeout(() => finish(1, { error: "web_host_deadline_no_retry" }), config.timeoutMs);
  }
  const browserSession = session.fromPartition(config.sessionPartition);
  if (config.proxyRules) await browserSession.setProxy({ proxyRules: config.proxyRules });
  browserSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  surface = new BrowserSurface({ BrowserWindow, WebContentsView, browserSession,
    onFailure: error => finish(1, { error: safeError(error) }) });
  win = surface.window;
  windowShown = win.isVisible() ? 1 : 0;
  windowFocused = win.isFocused() ? 1 : 0;
  win.on("show", () => { windowShown++; if (config.backgroundInput && !assisting) finish(1, { error: "web_background_window_became_visible" }); });
  win.on("focus", () => { windowFocused++; if (config.backgroundInput && !assisting) finish(1, { error: "web_background_window_became_visible" }); });
  win.on("page-title-updated", event => event.preventDefault());
  surface.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  const guardNavigation = (event, url) => {
    if (navigationAllowed(url, assisting || config.mode === "assist")) return;
    event.preventDefault();
    if (workerMode && config.backgroundInput === "dom_v1" && !assisting && !sent
        && (stage === "load_fresh_page" || stage === "startup_prepare") && isPublicLoginUrl(url)) {
      // This rejected public login redirect is not a dispatched model request.
      // Keep only a boolean, never the authorization URL or its query values.
      needsAssistanceNavigation = true;
      if (stage !== "startup_prepare") finish(1, { error: "web_browser_login_required_before_dispatch" });
      return;
    }
    finish(1, { error: assisting || config.mode === "assist"
      ? "web_assistance_navigation_not_allowed" : "web_navigation_not_allowed_no_retry" });
  };
  surface.webContents.on("will-navigate", guardNavigation);
  surface.webContents.on("will-redirect", (event, url, _inPlace, isMainFrame) => {
    if (isMainFrame !== false) guardNavigation(event, url);
  });
  surface.webContents.on("render-process-gone", () => finish(1, { error: "web_renderer_lost_no_retry" }));
  const modelFilter = { urls: ['https://chatgpt.com/backend-api/*'] };
  browserSession.webRequest.onSendHeaders(modelFilter, details => observeModelNetwork('sent', details));
  browserSession.webRequest.onResponseStarted(modelFilter, details => observeModelNetwork('response_started', details));
  browserSession.webRequest.onCompleted(modelFilter, details => observeModelNetwork('completed', details));
  browserSession.webRequest.onErrorOccurred(modelFilter, details => observeModelNetwork('error', details));
  win.on("close", event => {
    if (assisting && !ended) {
      event.preventDefault();
      if (!assistanceClosing) {
        assistanceClosing = true;
        void completeAssistance().catch(handleFailure);
      }
    }
  });
  if (assisting || config.visible) surface.show();
  win.on("closed", () => {
    if (!ended) {
      if (config.mode === "assist") finish(0, { assistanceWindowClosed: true });
      else finish(1, { error: "web_window_closed_no_retry" });
    }
  });
  if (assisting) {
    stage = "startup_assistance";
    timer = setTimeout(() => finish(1, { error: "web_startup_assistance_timeout" }), 600000);
    const hidden = new Promise(resolve => { finishAssistance = resolve; });
    await surface.loadURL("https://chatgpt.com/?temporary-chat=true");
    record("assistance_opened");
    await hidden;
    clearTimeout(timer);
  }
  if (workerMode) await workerLoop();
  else await runCurrentPage();
}).catch(handleFailure);

async function completeAssistance() {
  requireValue(assisting && !workerRequestId && !sent, "web_startup_assistance_invalid");
  requireValue(readWorkerPacket("next.json", 1024 * 1024) === null,
    "web_worker_request_during_assistance");
  if (inspectionPage) {
    await checkInspectionPage();
    surface.hide();
    await waitFor(async () => !win.isVisible() && !win.isFocused(), 3000);
    await surface.clearSnapshot();
    await checkInspectionPage();
    requireValue(readWorkerPacket("next.json", 1024 * 1024) === null,
      "web_worker_request_during_assistance");
    const claimed = readWorkerPacket("assisting.json", 256);
    requireValue(claimed?.id === assistanceId && claimed.inspect_completed === true
      && Object.keys(claimed).length === 2, "web_worker_assistance_identity_invalid");
    fs.unlinkSync(path.join(config.workerDirectory, "assisting.json"));
    record("assistance_hidden", { assistanceId, inspectCompleted: true,
      visible: false, focused: false, userClosed: true, pagePreserved: true });
    windowShown = windowFocused = 0;
    assisting = false;
    inspectionPage = null;
    finishAssistance();
    return;
  }
  let destination = surface.webContents.getURL();
  if (isPluginMaintenanceUrl(destination)) {
    requireValue(await inPage(page.pluginMaintenanceReady) === true
      && surface.webContents.getURL() === destination, "web_assistance_closed_before_ready");
    // One explicit close of a checked read-only maintenance page. No prompt,
    // permission change, plugin refresh, prior request or retry is performed.
    await surface.loadURL("https://chatgpt.com/?temporary-chat=true");
    await waitFor(async () => assistanceReady(await inPage(page.controls)), 15000);
    destination = surface.webContents.getURL();
  }
  const routeReady = isEmptyTemporaryChatUrl(destination) || isEmptyChatHomeUrl(destination);
  const state = routeReady ? await inPage(page.controls) : null;
  let composerEmpty = null;
  let composerError = null;
  if (routeReady && assistanceReady(state)) {
    try { composerEmpty = await inPage(page.composerPrefix, null) === ""; }
    catch (error) { composerEmpty = false; composerError = error; }
  }
  if (assistanceId) record("assistance_close_state", { assistanceId,
    ...assistanceCloseState(destination, state, composerEmpty, "before") });
  requireValue(routeReady && assistanceReady(state), "web_assistance_closed_before_ready");
  if (composerError) throw composerError;
  requireValue(composerEmpty === true, "web_assistance_closed_before_ready");
  if (isEmptyChatHomeUrl(destination)) {
    // Login can return to the ordinary empty home page. The same public control
    // already used by fresh-chat navigation may restore temporary mode once;
    // no draft, prior conversation, unknown query or account action is changed.
    requireValue(surface.webContents.getURL() === destination, "web_assistance_closed_before_ready");
    await inPage(page.enableTemporaryChat);
    await waitFor(async () => isEmptyTemporaryChatUrl(surface.webContents.getURL()), 5000);
  }
  const finalDestination = surface.webContents.getURL();
  const finalRouteReady = isEmptyTemporaryChatUrl(finalDestination);
  const finalState = finalRouteReady ? await inPage(page.controls) : null;
  let finalComposerEmpty = null;
  let finalComposerError = null;
  if (finalRouteReady && assistanceReady(finalState)) {
    try { finalComposerEmpty = await inPage(page.composerPrefix, null) === ""; }
    catch (error) { finalComposerEmpty = false; finalComposerError = error; }
  }
  if (assistanceId) record("assistance_close_state", { assistanceId,
    ...assistanceCloseState(finalDestination, finalState, finalComposerEmpty, "after_restore") });
  requireValue(finalRouteReady && assistanceReady(finalState), "web_assistance_closed_before_ready");
  if (finalComposerError) throw finalComposerError;
  requireValue(finalComposerEmpty === true, "web_assistance_closed_before_ready");
  surface.hide();
  await waitFor(async () => !win.isVisible() && !win.isFocused(), 3000);
  requireValue(readWorkerPacket("next.json", 1024 * 1024) === null,
    "web_worker_request_during_assistance");
  if (assistanceId) {
    const claimed = readWorkerPacket("assisting.json", 256);
    requireValue(claimed?.id === assistanceId && Object.keys(claimed).length === 1,
      "web_worker_assistance_identity_invalid");
    fs.unlinkSync(path.join(config.workerDirectory, "assisting.json"));
  }
  // The initial owner-operated assistance is recorded separately. Model turns
  // begin only after hiding, with their own strict zero-show/focus baseline.
  record("assistance_hidden", { ...(assistanceId ? { assistanceId } : {}),
    visible: false, focused: false, userClosed: true });
  windowShown = windowFocused = 0;
  assisting = false;
  preparedPage = true;
  completedPage = null;
  assistanceRequired = false;
  finishAssistance();
}

async function checkInspectionPage() {
  requireValue(inspectionPage && completedPage === inspectionPage.page
    && surface.webContents.getURL() === inspectionPage.url, "web_inspection_page_changed");
  const current = await inPage(page.publicFinal, completedPage.prompt, config.includeCitations === true, true);
  requireValue(current && JSON.stringify(current) === JSON.stringify(completedPage.message),
    "web_inspection_page_changed");
}

async function openWorkerAssistance(id, inspectCompleted = false) {
  requireValue(workerMode && !workerRequestId && !sent && !assisting,
    "web_worker_assistance_not_idle");
  assisting = true;
  assistanceClosing = assistanceFailed = false;
  assistanceId = id;
  stage = "worker_assistance";
  timer = setTimeout(() => finish(1, { error: "web_assistance_timeout" }), 600000);
  const hidden = new Promise(resolve => { finishAssistance = resolve; });
  // A completed, unchanged public turn can use the existing checked New chat
  // path. Failed pre-dispatch login/challenge pages remain exactly in place for
  // the owner to repair. Neither branch prepares or sends model input.
  if (inspectCompleted) {
    requireValue(completedPage && !preparedPage && !assistanceRequired && !needsAssistanceNavigation,
      "web_inspection_completed_page_required");
    requireBackgroundWindow();
    inspectionPage = { page: completedPage, url: surface.webContents.getURL() };
    await checkInspectionPage();
    const snapshot = await inPage(page.inspectionSnapshot, completedPage.message.id);
    // Use the exact public final already validated above, not a partly painted
    // assistant row. Preserve every part and boundary in the read-only shell.
    await surface.prepareSnapshot({ parts: completedPage.message.content.parts.slice(), notices: snapshot.notices });
    await checkInspectionPage();
    requireBackgroundWindow();
    surface.showSnapshot();
  } else if (needsAssistanceNavigation) {
    needsAssistanceNavigation = false; // One owner-requested page load, no retry.
    await surface.loadURL("https://chatgpt.com/?temporary-chat=true");
  } else if (completedPage) {
    await loadFreshPage();
    preparedPage = true;
    stage = "worker_assistance";
  } else if (surface.webContents.getURL() === "" || surface.webContents.getURL() === "about:blank") {
    await surface.loadURL("https://chatgpt.com/?temporary-chat=true");
  }
  if (!inspectCompleted) surface.show();
  record("assistance_opened", { assistanceId, ...(inspectCompleted ? { inspectCompleted: true } : {}) });
  await hidden;
  clearTimeout(timer);
  finishAssistance = null;
  assistanceId = null;
  assistanceClosing = false;
  stage = "worker_idle";
}

async function loadFreshPage() {
  stage = "load_fresh_page";
  if (preparedPage) {
    // Preparation is a cached page, not a promise that the public page stayed
    // empty while idle. Recheck it at consumption without another navigation.
    requireBackgroundWindow();
    requireValue(isEmptyTemporaryChatUrl(surface.webContents.getURL())
      && assistanceReady(await inPage(page.controls)), "web_prepared_page_changed");
    preparedPage = false;
    return;
  }
  if (!completedPage) { await surface.loadURL("https://chatgpt.com/?temporary-chat=true"); return; }
  requireValue(workerMode && !sent, "web_new_chat_worker_required");
  requireBackgroundWindow();
  const previous = completedPage;
  completedPage = null; // One navigation attempt only; any failure ends the worker.
  const current = await inPage(page.publicFinal, previous.prompt, config.includeCitations === true, true);
  requireValue(current && JSON.stringify(current) === JSON.stringify(previous.message), "web_new_chat_previous_page_changed");
  await inPage(page.startFreshChat);
  await waitFor(async () => {
    const state = await inPage(page.controls);
    return state.composer && state.userCount === 0 && state.assistantCount === 0;
  }, 10000);
  let destination = new URL(surface.webContents.getURL());
  requireValue(destination.origin === "https://chatgpt.com" && destination.pathname === "/" && !destination.hash,
    "web_new_chat_destination_invalid");
  if (destination.search === "") {
    // The ordinary New chat action exits temporary mode. Restore it through
    // the observed public button on the empty page, before attaching any text.
    await inPage(page.enableTemporaryChat);
    await waitFor(async () => new URL(surface.webContents.getURL()).searchParams.get("temporary-chat") === "true", 5000);
    destination = new URL(surface.webContents.getURL());
  }
  requireValue(destination.origin === "https://chatgpt.com" && destination.pathname === "/"
    && destination.search === "?temporary-chat=true" && !destination.hash, "web_new_chat_temporary_mode_required");
  record("fresh_chat_navigation", { mode: "ui_new_chat_v1", temporary: true, userRows: 0, assistantRows: 0 });
}
async function runCurrentPage() {
  await loadFreshPage();
  record("document_loaded", { controls: boundedControlState(await inPage(page.controls)) });
  try {
    let attentionReason = null, attentionSince = 0;
    await waitFor(async () => {
      const state = await inPage(page.controls);
      const reason = !config.backgroundInput ? null : state.pageKind === "challenge"
        ? "web_browser_challenge_required_before_dispatch"
        : state.loginVisible ? "web_browser_login_required_before_dispatch" : null;
      if (reason !== attentionReason) { attentionReason = reason; attentionSince = Date.now(); }
      // A first-load verification/login placeholder can resolve on its own.
      // Observe it briefly; never click a challenge or change its protections.
      if (reason && Date.now() - attentionSince >= 8000) throw new Error(reason);
      if (reason) return false;
      return state.composer;
    },
      config.mode === "assist" ? config.timeoutMs - 30000 : config.visible ? 65000 : 20000);
    await waitFor(async () => (await inPage(page.controls)).modelButtonCount === 1, 25000);
  } catch (error) {
    record("page_unavailable", { controls: boundedControlState(await inPage(page.controls)) });
    throw error;
  }
  const fresh = await inPage(page.controls);
  requireValue(fresh.userCount === 0 && fresh.assistantCount === 0, "web_fresh_page_required");
  record("page_ready", { controls: boundedControlState(fresh) });
  if (config.mode === "assist") {
    // Initial page readiness is bounded; a ready human-assistance window stays
    // open until the user closes it. It never automatically submits a prompt.
    clearTimeout(timer);
    record("assistance_ready");
    return;
  }
  if (config.mode === "inspect") return finish(0, { inspected: true, navigation: await inPage(page.freshChatControls) });
  if (config.prepareReleaseFile) {
    stage = "await_prepare_release";
    record("awaiting_prepare_release");
    await waitRelease(config.prepareReleaseFile, "ready\n");
  }
  await selectModel();
  let mention = config.connectorMention ?? null;
  if (config.autoSelectConnector) {
    stage = "select_registered_connector";
    record("connector_access_state", { access: await inPage(page.connectorAccessState) });
    await waitFor(async () => await inPage(page.connectorAccessState) === "enabled", 25000);
    const query = "@" + mention.name.split(" ")[0];
    await inPage(page.focusComposer, "");
    for (const character of query) await insertText(character);
    ownedConnectorQuery = query;
    await waitFor(() => inPage(page.connectorMenuChoice, mention.name, query, false, mention.id));
    await inPage(page.connectorMenuChoice, mention.name, query, true, mention.id);
    const selected = await waitFor(() => inPage(page.selectedConnector, mention.name));
    ownedConnectorQuery = null;
    requireValue(selected.id === mention.id, "web_connector_registered_identity_changed");
    await inPage(page.composerPrefix, mention);
    record("connector_selected", { mention, automatic: true });
  }
  if (config.mode === "prepare") {
    if (config.autoSelectConnector) {
      // Clear only this freshly created, exactly verified draft before closing.
      // This avoids persisting a half-hydrated pill into a later fresh turn.
      stage = "clear_prepared_connector";
      await inPage(page.focusComposer, await inPage(page.composerPrefix, mention));
      await selectAll();
      await key("Backspace");
      await inPage(page.composerPrefix, null);
    }
    return finish(0, { prepared: true, connectorVerified: mention });
  }
  if (config.connectorSelectionName !== undefined) {
    stage = "await_connector_selection";
    record("awaiting_connector_selection", { name: config.connectorSelectionName });
    mention = await waitFor(() => inPage(page.selectedConnector, config.connectorSelectionName),
      Math.max(1, deadlineAt - Date.now() - 2000));
    // Bind the one observed user-selected pill; never choose an app by name,
    // inspect an account store, grant permissions or fabricate a connector id.
    record("connector_selected", { mention });
  }
  if (config.awaitSendRelease) {
    // Optional private parent handshake for selecting a registered connector.
    // The pipe accepts one fixed command, no script, prompt or arbitrary action.
    stage = "await_send_release";
    record("awaiting_send_release");
    if (config.sendReleaseFile) {
      // Windows GUI processes may receive a closed stdin. An explicitly selected
      // private sibling file carries the same one-shot literal command instead.
      // This is preparation signalling only, never an executable payload.
      await waitRelease(config.sendReleaseFile, "send\n");
    } else await new Promise((resolve, reject) => {
      let input = "";
      process.stdin.setEncoding("utf8");
      const receive = chunk => {
        input += chunk;
        if (input.length > 16 || !"send\n".startsWith(input)) reject(new Error("web_send_release_invalid"));
        else if (input === "send\n") { process.stdin.removeListener("data", receive); process.stdin.pause(); resolve(); }
      };
      process.stdin.on("data", receive);
      process.stdin.once("end", () => reject(new Error("web_send_release_closed")));
      process.stdin.resume();
    });
  }
  stage = "attach_prompt";
  const prefix = await inPage(page.composerPrefix, mention);
  await inPage(page.focusComposer, prefix);
  await insertText(config.text);
  // A model switch can settle the editor after the send control becomes ready.
  // Observe the already inserted text briefly; never insert it a second time.
  let exactPrompt = false;
  try {
    exactPrompt = await waitFor(async () => (await inPage(page.controls)).sendReady
      && await inPage(page.composerMatches, config.text, prefix, mention), 2000);
  } catch (error) {
    if (error.message !== "web_page_state_timeout") throw error;
  }
  requireValue(exactPrompt, "web_prompt_text_mismatch");
  stage = "send_once";
  sent = true; // An uncertain input is terminal. Never submit a second time.
  record("dispatch_started");
  await inPage(page.sendOnce);
  const bindingShape = await waitFor(async () => inPage(page.publicUserBindingShape, config.text, true));
  record("public_user_binding", { shape: bindingShape });
  stage = "wait_public_final";
  // The dated inline plugin pill serializes as a literal @name prefix. This
  // exact projection is explicit; never trim or infer arbitrary message text.
  const publicPrompt = mention
    ? "@" + mention.name + " " + config.text : config.text;
  const message = await waitForPublicFinal(publicPrompt, mention?.name ?? null);
  if (config.inspectCitations === true)
    record("public_citation_shape", { shape: await inPage(page.publicCitationShape, true) });
  if (workerMode) completedPage = { prompt: publicPrompt, message };
  requireValue(verifiedSelection?.model === config.model
    && verifiedSelection.effortIndex === modelSelection(config).effort.index, "web_model_selection_unverified");
  finish(0, { ...verifiedSelection, publicMessage: message });
}
async function handleFailure(error) {
  if (win && !win.isDestroyed() && !ended) {
    if (!sent && ownedConnectorQuery !== null) {
      try {
        await inPage(page.focusComposer, ownedConnectorQuery);
        await selectAll();
        await key("Backspace");
        await inPage(page.composerPrefix, null);
        record("owned_preparation_draft_cleared");
      } catch { record("owned_preparation_draft_preserved"); }
    }
    try { record("failure_controls", { controls: boundedControlState(await inPage(page.controls)) }); } catch {}
    if (sent) {
      try { record("failure_public_shape", { shape: await inPage(page.publicMessageShape) }); } catch {}
    }
  }
  finish(1, { error: safeError(error) });
}

async function prepareWorkerPage() {
  // A saved service checks its own empty public page before accepting a turn.
  // This navigation has no prompt, model request, connector selection or retry.
  stage = "startup_prepare";
  requireValue(readWorkerPacket("next.json", 1024 * 1024) === null,
    "web_worker_request_during_preparation");
  try { await surface.loadURL("https://chatgpt.com/?temporary-chat=true"); }
  catch (error) { if (!needsAssistanceNavigation) throw error; }
  if (needsAssistanceNavigation) {
    assistanceRequired = true;
    record("worker_attention_required", { reason: "web_browser_login_required_before_dispatch" });
    return;
  }
  let ready = false;
  try {
    ready = await waitFor(async () => {
      if (workerClosing || readWorkerPacket("shutdown.json", 256) !== null)
        throw new Error("web_host_closed");
      const controls = await inPage(page.controls);
      return isEmptyTemporaryChatUrl(surface.webContents.getURL()) && assistanceReady(controls);
    }, 65000);
  } catch (error) {
    if (error.message !== "web_page_state_timeout") throw error;
  }
  if (ready) {
    requireBackgroundWindow();
    requireValue(readWorkerPacket("next.json", 1024 * 1024) === null,
      "web_worker_request_during_preparation");
    preparedPage = true;
    record("worker_prepared", { hidden: true, empty: true });
    return;
  }
  const controls = await inPage(page.controls);
  const reason = controls.pageKind === "challenge"
    ? "web_browser_challenge_required_before_dispatch"
    : controls.loginVisible === true ? "web_browser_login_required_before_dispatch" : null;
  if (reason === null) {
    record("startup_prepare_state", {
      route: isEmptyTemporaryChatUrl(surface.webContents.getURL()) ? "temporary"
        : isEmptyChatHomeUrl(surface.webContents.getURL()) ? "home" : "other",
      ...boundedControlState(controls) });
    try { record("startup_control_structure", await inPage(page.startupControlStructure)); }
    catch { /* Keep the original preparation failure and the existing fail-closed admission. */ }
  }
  requireValue(reason !== null, "web_startup_prepare_unavailable");
  assistanceRequired = true;
  record("worker_attention_required", { reason });
}

function readWorkerPacket(name, maximum) {
  const file = path.join(config.workerDirectory, name);
  let info;
  try { info = fs.lstatSync(file); }
  catch (error) { if (error.code === "ENOENT") return null; throw error; }
  requireValue(info.isFile() && !info.isSymbolicLink() && info.size <= maximum, "web_worker_packet_invalid");
  const fd = fs.openSync(file, "r"), buffer = Buffer.alloc(maximum + 1);
  let length;
  try { length = fs.readSync(fd, buffer, 0, buffer.length, 0); }
  finally { fs.closeSync(fd); }
  requireValue(length <= maximum, "web_worker_packet_invalid");
  const value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(buffer.subarray(0, length)));
  requireValue(value && typeof value === "object" && !Array.isArray(value), "web_worker_packet_invalid");
  return value;
}
function validateWorkerRequest(request, seen) {
  requireValue(Object.keys(request).every(k => ["id", "text", "model", "effort", "connectorMention", "autoSelectConnector"].includes(k))
    && typeof request.id === "string" && /^[a-f0-9]{32}$/.test(request.id)
    && !seen.has(request.id) && seen.size < 128, "web_worker_request_identity_invalid");
  modelSelection(request);
  requireValue(typeof request.text === "string" && request.text.length > 0
    && Buffer.byteLength(request.text, "utf8") <= 65536
    && [...request.text].every(c => c.codePointAt(0) < 0xd800 || c.codePointAt(0) > 0xdfff), "web_text_invalid");
  const mention = request.connectorMention;
  requireValue(mention === undefined ? request.autoSelectConnector === undefined
    : mention && typeof mention === "object" && !Array.isArray(mention)
      && Object.keys(mention).length === 2 && typeof mention.id === "string"
      && /^plugin:asdk_app_[a-f0-9]{32}$/.test(mention.id) && typeof mention.name === "string"
      && /^[A-Za-z0-9\u3400-\u4dbf\u4e00-\u9fff][A-Za-z0-9\u3400-\u4dbf\u4e00-\u9fff -]{0,63}(?![\s\S])/.test(mention.name) && request.autoSelectConnector === true,
    "web_connector_mention_invalid");
}
async function workerLoop() {
  // The Python owner controls service lifetime. Idle time must not silently
  // retire this hidden worker; retain request deadlines and the no-replay cap.
  const base = { ...config }, seen = new Set(), assistanceSeen = new Set();
  record("worker_ready");
  if (config.startupPrepare === true) await prepareWorkerPage();
  while (!workerClosing && seen.size < 128) {
    const stop = readWorkerPacket("shutdown.json", 256);
    if (stop !== null) {
      requireValue(Object.keys(stop).length === 1 && stop.stop === true, "web_worker_shutdown_invalid");
      break;
    }
    const assistance = readWorkerPacket("assist.json", 256);
    if (assistance !== null) {
      const id = validateAssistancePacket(assistance, assistanceSeen);
      requireValue(!seen.has(id) && readWorkerPacket("next.json", 1024 * 1024) === null
        && !fs.existsSync(path.join(base.workerDirectory, "active.json"))
        && !fs.existsSync(path.join(base.workerDirectory, "assisting.json")),
        "web_worker_assistance_not_idle");
      fs.renameSync(path.join(base.workerDirectory, "assist.json"), path.join(base.workerDirectory, "assisting.json"));
      const claimed = readWorkerPacket("assisting.json", 256);
      requireValue(JSON.stringify(claimed) === JSON.stringify(assistance),
        "web_worker_assistance_identity_invalid");
      assistanceSeen.add(id);
      await openWorkerAssistance(id, assistance.inspect_completed === true);
      record("worker_idle", { resultCode: 0, assistanceRequired: false });
      continue;
    }
    const request = readWorkerPacket("next.json", 1024 * 1024);
    if (request === null) { await new Promise(resolve => setTimeout(resolve, 150)); continue; }
    requireValue(!assistanceRequired, "web_worker_assistance_required");
    validateWorkerRequest(request, seen);
    requireValue(!assistanceSeen.has(request.id), "web_worker_request_identity_invalid");
    requireValue(!fs.existsSync(path.join(base.workerDirectory, "active.json")), "web_worker_already_active");
    fs.renameSync(path.join(base.workerDirectory, "next.json"), path.join(base.workerDirectory, "active.json"));
    seen.add(request.id);  // No replay after admission, including process loss.
    workerRequestId = request.id;
    config = { ...base, ...request, mode: "generate" };
    delete config.id;
    ended = sent = cancelling = false;
    cancelledIdleVerified = false;
    lastFailure = null;
    networkRequests.clear(); networkEventCount = 0;
    ownedConnectorQuery = null;
    deadlineAt = Date.now() + config.timeoutMs;
    const completed = new Promise(resolve => { finishTurn = resolve; });
    timer = setTimeout(() => finish(1, { error: "web_host_deadline_no_retry" }), config.timeoutMs);
    try { await runCurrentPage(); }
    catch (error) { await handleFailure(error); }
    const code = await completed;
    for (const name of ["active.json", "cancel.json"]) {
      const file = path.join(base.workerDirectory, name);
      if (fs.existsSync(file)) {
        const info = fs.lstatSync(file);
        requireValue(info.isFile() && !info.isSymbolicLink(), "web_worker_packet_invalid");
        fs.unlinkSync(file);
      }
    }
    const recoverable = code !== 0 && recoverableBeforeDispatch(lastFailure, sent);
    const cancelledIdle = code === 1 && lastFailure === "web_cancelled_no_retry"
      && cancelledIdleVerified && !workerClosing;
    if (cancelledIdle) completedPage = null;
    assistanceRequired = recoverable;
    record("worker_idle", { resultCode: code, assistanceRequired: recoverable,
      cancelledIdleVerified: cancelledIdle });
    workerRequestId = null; finishTurn = null; config = base;
    ended = sent = cancelling = false;
    // A login/challenge observed before dispatch terminates that request while
    // preserving only its page for explicit owner assistance. A caller-cancelled
    // turn may retain this process after the exact stop click and idle checks.
    // This is local page readiness, never proof of upstream inference/billing
    // cessation. All other failures end the worker; no input is ever replayed.
    if (code && !recoverable && !cancelledIdle) { workerClosing = true; break; }
  }
  if (!workerClosing && seen.size >= 128)
    record("worker_limit_reached", { reason: "request_limit" });
  finish(0, { workerStopped: true });
}
process.on("SIGINT", () => { workerClosing = true; void cancelOwnedGeneration(); });
process.on("SIGTERM", () => { workerClosing = true; void cancelOwnedGeneration(); });
process.on("uncaughtException", error => finish(1, { error: safeError(error) }));
process.on("unhandledRejection", error => finish(1, { error: safeError(error) }));

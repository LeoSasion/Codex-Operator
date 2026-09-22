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


// Synthetic DOM/Fiber boundaries, not a browser/model integration test.
const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const { publicFinal, clickModelChooser, focusModelMenu, connectorMenuChoice, selectedConnector, composerPrefix, composerMatches } = require(operatorTestScript("web_browser_page.cjs"));
const prompt = "Synthetic fixture 中文";

test('plugin close readiness excludes drafts, forms, permissions, auth and pending refresh', () => {
  const {pluginMaintenanceReady}=require(operatorTestScript("web_browser_page.cjs"));
  const element=(attrs={})=>({tagName:'INPUT',value:'',textContent:'',disabled:false,
    getClientRects:()=>[{}],closest:()=>null,getAttribute:k=>attrs[k]??null,...attrs});
  let fields=[element({placeholder:'搜索设置'})], dialogs=[element({role:'dialog','aria-label':'设置'})], buttons=[], busy=[];
  const document={readyState:'complete',title:'ChatGPT - Operator fixture',getElementById:()=>null,
    querySelectorAll:s=>s.startsWith('input,')?fields:s.startsWith('[role="dialog"')?dialogs:s==='button,a'?buttons:busy};
  const read=()=>vm.runInNewContext('('+pluginMaintenanceReady.toString()+')()',{document});
  assert.equal(read(),true);
  for(const field of [element({value:'draft',placeholder:'搜索设置'}),element({type:'password'}),
    element({tagName:'TEXTAREA',value:'draft'}),element({tagName:'BUTTON',role:'switch'}),
    element({tagName:'DIV',contenteditable:'true'})]) {fields=[field];assert.equal(read(),false);}
  fields=[];
  for(const button of [element({textContent:'刷新',disabled:true}),element({textContent:'Log in'})]) {
    buttons=[button];assert.equal(read(),false);
  }
  buttons=[];dialogs=[element({role:'alertdialog','aria-label':'Settings'})];assert.equal(read(),false);
  dialogs=[element({role:'dialog','aria-label':'Permissions'})];assert.equal(read(),false);
  dialogs=[];busy=[element()];assert.equal(read(),false);busy=[];
  document.title='Just a moment';assert.equal(read(),false);
});
test('inspection binds the exact public row without reading its partial text and reads only rendered notices', () => {
  const { inspectionSnapshot } = require(operatorTestScript("web_browser_page.cjs"));
  const element = (text, id, hidden=false) => ({innerText:text, getClientRects:()=>[{}],
    closest:()=>hidden?{}:null, getAttribute:()=>id});
  const row = element('G', 'selected');
  Object.defineProperty(row, 'innerText', {get() {throw new Error('partial DOM reply must not be read');}});
  const alert = element('visible refusal card');
  let rows = [element('unrelated private row','other'), row];
  let cards = [alert, element('hidden text',null,true)];
  const document = {querySelectorAll:selector => selector.startsWith('[data-message-author-role') ? rows : cards};
  const read = () => vm.runInNewContext('('+inspectionSnapshot.toString()+')("selected")', {document});
  assert.equal(JSON.stringify(read()), JSON.stringify({notices:[alert.innerText]}));
  rows.push(row); assert.throws(read, /web_inspection_message_ambiguous/); rows.pop();
  cards = Array(17).fill(alert); assert.throws(read, /web_inspection_snapshot_bound/);
  cards = [element('a'.repeat(4097))]; assert.throws(read, /web_inspection_snapshot_bound/);
  rows = []; assert.throws(read, /web_inspection_message_ambiguous/);
});
function hiddenHostFixture(overrides = {}) {
  // Evaluate the actual host with an unstarted app and a synthetic WebContents.
  // No Electron window, browser profile, page request or model is opened.
  const path = require('node:path');
  const surfaceHelpers = require(operatorTestScript("web_browser_surface.cjs"));
  const source = require('node:fs').readFileSync(operatorTestScript("web_browser_host.cjs"), 'utf8');
  const commands = [], exits = [], events = [];
  const config = { version: 1, mode: 'prepare', profileDirectory: path.resolve(__dirname),
    sessionPartition: 'persist:host-fixture', model: 'gpt-5.6-sol', visible: false,
    backgroundInput: 'dom_v1', timeoutMs: 10000, ...overrides };
  const state = { visible: false, focused: false, origin: 'https://chatgpt.com/' };
  const noNativeInput = () => { throw Error('native window/input must not be used'); };
  const fixtureWindow = { isDestroyed: () => false, isVisible: () => state.visible,
    isFocused: () => state.focused, focus: noNativeInput, getContentSize: () => [1080, 850],
    hide: () => { commands.push({ method: 'hide' }); state.visible = state.focused = false; },
    setSkipTaskbar: value => commands.push({ method: 'skipTaskbar', value }),
    setFocusable: value => commands.push({ method: 'focusable', value }),
    webContents: { getURL: () => state.origin, focus: noNativeInput, sendInputEvent: noNativeInput,
      insertText: async text => commands.push({ method: 'insertText', text }),
      selectAll: () => commands.push({ method: 'selectAll' }), delete: () => commands.push({ method: 'delete' }),
      executeJavaScript: async code => vm.runInNewContext(code, {
        document: { activeElement: { dispatchEvent: event => commands.push({ method: 'key', type: event.type, key: event.key }) } },
        KeyboardEvent: class { constructor(type, options) { this.type = type; Object.assign(this, options); } } }),
      debugger: { attach: noNativeInput, sendCommand: noNativeInput } } };
  const fixtureSurface = { window: fixtureWindow, webContents: fixtureWindow.webContents,
    closed: false, revealed: false, sync() {}, loadURL: noNativeInput,
    hide: surfaceHelpers.BrowserSurface.prototype.hide };
  const app = { setName() {}, setAppUserModelId() {}, setPath() {}, requestSingleInstanceLock: () => true,
    exit: code => exits.push(code), whenReady: () => new Promise(() => {}) };
  const page = { backgroundModelInput: function () { return true; }, composerFocused: function () { return true; },
    composerPrefix: function () { return ''; },
    publicFinal: function () {}, startFreshChat: function () {}, enableTemporaryChat: function () {},
    currentPublicFiber: require(operatorTestScript("web_browser_page.cjs")).currentPublicFiber,
    backgroundMenuKey: require(operatorTestScript("web_browser_page.cjs")).backgroundMenuKey,
    focusModelMenu: function () { return true; }, controls: function () {
    return { pageKind: 'chatgpt', composer: true, modelButtonCount: 1, loginVisible: false,
      userCount: 0, assistantCount: 0, documentFocused: false, modelControlInteractive: true, modelControlFocused: true,
      modelControlPoint: { x: 80, y: 90 }, modelButtonLabels: ['fixture'], chooser: true };
  } };
  const context = vm.createContext({ fixtureWindow, fixtureSurface, Buffer, TextDecoder, URL, setTimeout, clearTimeout,
    setInterval: () => null, clearInterval, process: { argv: ['', '', path.resolve(__dirname, 'synthetic.json')],
      stdout: { write: value => events.push(JSON.parse(value)) }, on() {} }, require: name => {
        if (name === 'electron') return { app };
        if (name === 'node:fs') return { readFileSync: () => Buffer.from(JSON.stringify(config)),
          lstatSync: file => {
            if (path.dirname(file) === config.workerDirectory && path.basename(file) === 'next.json')
              throw Object.assign(new Error('fixture mailbox is empty'), { code: 'ENOENT' });
            return { isDirectory: () => true, isSymbolicLink: () => false };
          } };
        if (name === 'node:path') return path;
        if (name === './web_browser_page.cjs') return page;
        if (name === './web_browser_surface.cjs') return surfaceHelpers;
        throw Error('unexpected dependency');
      } });
  vm.runInContext(source, context);
  vm.runInContext('win = fixtureWindow; surface = fixtureSurface', context);
  return { state, commands, exits, events, invoke: expression => vm.runInContext(expression, context) };
}
test('long generation waits require explicit MCP continuation and stay bounded', () => {
  for (const [selection, accepted] of [
    [{timeoutMs: 180000}, true], [{timeoutMs: 600000}, false],
    [{timeoutMs: 600000, mcpContinuation: true}, true],
    [{timeoutMs: 600001, mcpContinuation: true}, false],
    [{timeoutMs: 180000, mcpContinuation: 'true'}, false],
    [{timeoutMs: 180000, mcpContinuation: false}, false]
  ]) {
    const host = hiddenHostFixture({mode: 'generate', text: 'fixture', ...selection});
    assert.deepEqual(host.exits, accepted ? [] : [1]);
    assert.equal(host.events.some(e => e.kind === 'dispatch_started'), false);
  }
});
test('passive model diagnostics retain fixed status only and reject unrelated or stale requests', () => {
  const host = hiddenHostFixture();
  host.invoke(`sent = true; surface.webContents.id = 17;
    let details = { id: 1, webContentsId: 17, method: 'POST', url: 'https://chatgpt.com/backend-api/f/conversation' };
    for (const field of ['requestHeaders', 'responseHeaders', 'uploadData'])
      Object.defineProperty(details, field, { get() { throw Error('private material accessed'); } });
    observeModelNetwork('sent', details);
    details.statusCode = 200; observeModelNetwork('response_started', details);
    observeModelNetwork('completed', details);
    observeModelNetwork('error', { ...details, error: 'private unknown' });
    observeModelNetwork('sent', { ...details, id: 2, webContentsId: 99 });
    observeModelNetwork('sent', { ...details, id: 2, url: 'https://chatgpt.com/backend-api/me' });
    observeModelNetwork('sent', { ...details, id: 2 });
    observeModelNetwork('error', { ...details, id: 2, error: 'private unknown' });
    ended = true; observeModelNetwork('sent', { ...details, id: 3 });`);
  assert.deepEqual(host.events.map(e => e.phase), ['sent', 'response_started', 'completed', 'sent', 'error']);
  assert.deepEqual(host.events.map(e => e.status), [null, 200, 200, 200, 200]);
  assert.equal(host.events.at(-1).error, 'other');
  assert.equal(JSON.stringify(host.events).includes('https://'), false);
  assert.equal(JSON.stringify(host.events).includes('private'), false);
});
test('a tracked generation HTTP rejection ends waiting once without resending or accepting a final', () => {
  for (const status of [401, 403, 429, 500]) {
    const host = hiddenHostFixture();
    host.invoke(`sent = true; surface.webContents.id = 17; let failures = [];
      finish = (code, value) => { failures.push({code,value}); ended = true; };
      let request = { id: 1, webContentsId: 17, method: 'POST', url: 'https://chatgpt.com/backend-api/f/conversation' };
      observeModelNetwork('sent', request);
      observeModelNetwork('response_started', { ...request, id: 99, statusCode: ${status} });
      observeModelNetwork('response_started', { ...request, statusCode: ${status} });
      observeModelNetwork('completed', { ...request, statusCode: ${status} });`);
    assert.deepEqual(plain(host.invoke('failures')), [{ code: 1, value: {
      error: 'web_model_http_rejected_no_retry', upstreamStatus: status } }]);
    assert.equal(host.invoke('ended && sent'), true);
    assert.deepEqual(host.commands, []);
    assert.deepEqual(host.events.map(e => e.phase), ['sent', 'response_started']);
  }
});
test('hidden host uses renderer input without native focus, showing or foreground input', async () => {
  const host = hiddenHostFixture();
  assert.deepEqual(host.exits, []);
  await host.invoke('menu()');
  await host.invoke('key("Left")');
  await host.invoke('key("Escape")');
  await host.invoke('insertText("中文😀 a_b\\r\\n")');
  await host.invoke('selectAll()');
  assert.deepEqual(host.commands.filter(c => c.method === 'key').map(c => c.key), ['ArrowLeft', 'ArrowLeft', 'Escape', 'Escape']);
  assert.equal(host.commands.find(c => c.method === 'insertText').text, '中文😀 a_b\r\n');
  assert.equal(host.commands.filter(c => c.method === 'selectAll').length, 1);
  assert.deepEqual(host.exits, []);
  for (const change of [{ visible: true }, { focused: true }, { origin: 'https://example.com/' }]) {
    Object.assign(host.state, { visible: false, focused: false, origin: 'https://chatgpt.com/' }, change);
    const count = host.commands.length;
    await assert.rejects(host.invoke('key("Escape")'), /web_background_(window_became_visible|input_unavailable)/);
    assert.equal(host.commands.length, count);
  }
});
test('hidden input cannot be selected for human assistance or arbitrary commands', async () => {
  for (const config of [{ visible: true }, { mode: 'assist' }, { backgroundInput: true },
      { connectorSelectionName: 'Operator fixture' }, { startupAssistance: true }]) {
    assert.deepEqual(hiddenHostFixture(config).exits, [1]);
  }
  const host = hiddenHostFixture();
  await assert.rejects(host.invoke('key("Enter")'), /web_background_key_invalid/);
  assert.equal(host.commands.length, 0);
});

test('explicit initial assistance closes to the same hidden window before any model request', async () => {
  const host = hiddenHostFixture({ mode: 'worker', workerDirectory: require('node:path').resolve(__dirname),
    parentPid: 1, startupAssistance: true });
  assert.deepEqual(host.exits, []);
  host.state.visible = host.state.focused = true;
  host.state.origin = 'https://chatgpt.com/?temporary-chat=true';
  host.invoke('windowShown = 1; windowFocused = 1; let assistanceFinished = 0; finishAssistance = () => assistanceFinished++');
  await host.invoke('completeAssistance()');
  assert.equal(host.state.visible, false);
  assert.equal(host.state.focused, false);
  assert.deepEqual(host.commands, [{ method: 'hide' }, { method: 'skipTaskbar', value: true },
    { method: 'focusable', value: false }]);
  assert.equal(host.invoke('assistanceFinished === 1 && !assisting && !sent && windowShown === 0 && windowFocused === 0'), true);
  assert.deepEqual(host.exits, []);
});
test('fresh chat clicks only equivalent public home links on the idle owned page', () => {
  const { startFreshChat } = require(operatorTestScript("web_browser_page.cjs"));
  const actions = [];
  const composer = { textContent: '' };
  const link = (text = '新聊天', href = '/') => ({ textContent: text,
    getClientRects: () => [{}], getAttribute: key => key === 'href' ? href : null,
    click: () => actions.push(href) });
  let choices = [link(), link('新聊天CtrlShiftO')], users = [{}], assistants = [{}], stops = [];
  const invoke = () => vm.runInNewContext(`(${startFreshChat.toString()})()`, { document: {
    querySelector: () => composer, querySelectorAll: selector => selector.includes('author-role="user"') ? users
      : selector.includes('author-role="assistant"') ? assistants : selector.includes('stop-button') ? stops : choices } });
  invoke();
  assert.deepEqual(actions, ['/']);
  for (const bad of [[], [link('Unknown')], [link('新聊天', '/c/unrelated')], [link(), link(), link()]]) {
    choices = bad;
    assert.throws(invoke, /web_new_chat_control_ambiguous/);
  }
  choices = [link()];
  composer.textContent = 'unsubmitted draft';
  assert.throws(invoke, /web_new_chat_idle_page_required/);
  composer.textContent = '';
  stops = [{ getClientRects: () => [{}] }];
  assert.throws(invoke, /web_new_chat_idle_page_required/);
  stops = []; users = [{}, {}];
  assert.throws(invoke, /web_new_chat_idle_page_required/);
  assert.equal(actions.length, 1);
});
test('worker enters a fresh temporary chat without reload and rejects changed previous output or lost temporary mode', async () => {
  const setup = () => {
    const host = hiddenHostFixture({ mode: 'worker', workerDirectory: require('node:path').resolve(__dirname), parentPid: 1 });
    host.state.origin = 'https://chatgpt.com/?temporary-chat=true';
    host.invoke(`let navigationCalls = 0, temporaryCalls = 0;
      surface.loadURL = async () => { throw Error('unexpected full reload'); };
      completedPage = { prompt: 'exact previous', message: { id: 'previous' } };
      inPage = async (fn, ...args) => {
        if (fn === page.publicFinal) { requireValue(args[0] === 'exact previous', 'web_binding_changed'); return { id: 'previous' }; }
        if (fn === page.startFreshChat) { navigationCalls++; return; }
        if (fn === page.enableTemporaryChat) { temporaryCalls++; surface.webContents.getURL = () => 'https://chatgpt.com/?temporary-chat=true'; return; }
        return { composer: true, userCount: 0, assistantCount: 0 };
      };`);
    return host;
  };
  const good = setup();
  await good.invoke('loadFreshPage()');
  assert.equal(good.invoke('navigationCalls === 1 && completedPage === null && !sent'), true);
  const changed = setup();
  changed.invoke("completedPage.message.id = 'changed'");
  await assert.rejects(changed.invoke('loadFreshPage()'), /web_new_chat_previous_page_changed/);
  assert.equal(changed.invoke('navigationCalls'), 0);
  const home = setup();
  home.state.origin = 'https://chatgpt.com/';
  await home.invoke('loadFreshPage()');
  assert.equal(home.invoke('navigationCalls === 1 && temporaryCalls === 1'), true);
  const unknown = setup();
  unknown.state.origin = 'https://chatgpt.com/?unknown=true';
  await assert.rejects(unknown.invoke('loadFreshPage()'), /web_new_chat_temporary_mode_required/);
  assert.equal(unknown.invoke('navigationCalls === 1 && temporaryCalls === 0'), true);
});
test('temporary chat requires one enabled public control and an empty page', () => {
  const { enableTemporaryChat } = require(operatorTestScript("web_browser_page.cjs"));
  let clicks = 0, rows = [], draft = '';
  const button = { getClientRects: () => [{}], disabled: false,
    getAttribute: key => key === 'aria-label' ? '临时聊天' : null, click: () => clicks++ };
  let buttons = [button];
  const invoke = () => vm.runInNewContext(`(${enableTemporaryChat.toString()})()`, { document: {
    querySelector: () => ({ textContent: draft }), querySelectorAll: selector => selector === 'button' ? buttons : rows } });
  invoke();
  buttons = [button, button];
  assert.throws(invoke, /web_temporary_chat_control_ambiguous/);
  buttons = [button]; button.disabled = true;
  assert.throws(invoke, /web_temporary_chat_control_ambiguous/);
  button.disabled = false; rows = [{}];
  assert.throws(invoke, /web_empty_composer_required/);
  rows = []; draft = 'unfinished';
  assert.throws(invoke, /web_empty_composer_required/);
  assert.equal(clicks, 1);
});
test('background model pointer input binds the focused enabled public control and its current position', () => {
  const { backgroundModelInput } = require(operatorTestScript("web_browser_page.cjs"));
  const events = [];
  const button = { disabled: false, getAttribute: () => null, getClientRects: () => [{}],
    getBoundingClientRect: () => ({ x: 10, y: 20, width: 20, height: 40 }),
    dispatchEvent: event => events.push(plain(event)) };
  const doc = { activeElement: button, querySelector: () => ({ closest: () => ({ querySelectorAll: () => [button] }) }) };
  const invoke = point => vm.runInNewContext(`(${backgroundModelInput.toString()})(point)`, {
    document: doc, point, PointerEvent: class { constructor(type, options) { this.type = type; Object.assign(this, options); this.isTrusted = false; } } });
  invoke({ x: 20, y: 40 });
  assert.deepEqual(events.map(e => e.type), ['pointerdown', 'pointerup']);
  assert.equal(events.every(e => !e.isTrusted && e.button === 0 && e.pointerType === 'mouse'), true);
  assert.throws(() => invoke({ x: 21, y: 40 }), /web_model_point_invalid/);
  button.disabled = true;
  assert.throws(() => invoke({ x: 20, y: 40 }), /web_model_point_invalid/);
  assert.equal(events.length, 2);
});
test('persistent worker admits only bounded text and registered connector data, without replay or runtime overrides', () => {
  const host = hiddenHostFixture();
  const valid = { id: 'a'.repeat(32), text: '中文😀 a_b\r\n' };
  host.invoke(`validateWorkerRequest(${JSON.stringify(valid)}, new Set())`);
  host.invoke(`validateWorkerRequest(${JSON.stringify({ ...valid,
    connectorMention: { id: 'plugin:asdk_app_' + 'b'.repeat(32), name: 'Operator fixture' },
    autoSelectConnector: true })}, new Set())`);
  for (const value of [{ ...valid, profileDirectory: '/other' }, { ...valid, visible: true },
      { ...valid, mode: 'assist' }, { ...valid, id: 'not-an-id' }, { ...valid, text: 'x'.repeat(65537) },
      { ...valid, text: '\ud800' }, { ...valid, autoSelectConnector: true },
      { ...valid, connectorMention: { id: 'unknown', name: 'fixture' } }]) {
    assert.throws(() => host.invoke(`validateWorkerRequest(${JSON.stringify(value)}, new Set())`), /web_/);
  }
  assert.throws(() => host.invoke(`validateWorkerRequest(${JSON.stringify(valid)}, new Set(["${valid.id}"]))`), /web_worker_request_identity_invalid/);
  assert.equal(host.commands.length, 0);
});

test('connector labels preserve Chinese names across startup, worker and public selection', () => {
  const host = hiddenHostFixture();
  const id = 'plugin:asdk_app_' + 'b'.repeat(32);
  for (const name of ['Operator fixture', 'Operator 固定连接', '固定连接', '连'.repeat(64)]) {
    const mention = { id, name };
    for (const mode of ['prepare', 'generate']) {
      assert.deepEqual(hiddenHostFixture({ mode, text: mode === 'generate' ? 'fixture' : undefined,
        connectorMention: mention, autoSelectConnector: true }).exits, []);
    }
    assert.deepEqual(hiddenHostFixture({ mode: 'generate', text: 'fixture', visible: true, backgroundInput: undefined,
      awaitSendRelease: true, connectorSelectionName: name }).exits, []);
    host.invoke(`validateWorkerRequest(${JSON.stringify({ id: 'c'.repeat(32), text: 'fixture',
      connectorMention: mention, autoSelectConnector: true })}, new Set())`);
    const f = connectorFixture({ name });
    assert.deepEqual(plain(vm.runInNewContext(`(${selectedConnector.toString()})(name)`,
      { document: f.document, name })), { id: f.id, name });
    let clicks = 0;
    const query = '@' + name.split(' ')[0], composer = { textContent: query };
    const row = { textContent: name, getClientRects: () => [{}], getAttribute: () => null,
      closest: selector => selector === '[data-composer-plugin-impression-id]' ? { getAttribute: () => id.slice(7) } : null,
      click: () => clicks++ };
    const picked = vm.runInNewContext(`(${connectorMenuChoice.toString()})(name, query, true, id)`,
      { name, query, id, document: { activeElement: composer, querySelector: () => composer,
        querySelectorAll: () => [row] } });
    assert.equal(picked.name, name);
    assert.equal(clicks, 1);
  }
  for (const name of ['连'.repeat(65), '固定\n', '固定\r', '固定\u2028', '固定\u2029',
      '固定\u200b连接', ' 固定', '固定<script>', '\ud800']) {
    const mention = { id, name };
    assert.deepEqual(hiddenHostFixture({ connectorMention: mention, autoSelectConnector: true }).exits, [1]);
    assert.throws(() => host.invoke(`validateWorkerRequest(${JSON.stringify({ id: 'c'.repeat(32),
      text: 'fixture', connectorMention: mention, autoSelectConnector: true })}, new Set())`), /web_connector_mention_invalid/);
    assert.throws(() => vm.runInNewContext(`(${selectedConnector.toString()})(name)`, { name }), /web_connector_name_invalid/);
    assert.throws(() => vm.runInNewContext(`(${connectorMenuChoice.toString()})(name, query, true)`,
      { name, query: '@' + name.split(' ')[0] }), /web_connector_query_invalid/);
  }
  assert.equal(host.commands.length, 0);
});
test('generation diagnostics distinguish hidden stop controls and finished public rows without reading content', () => {
  const { publicGenerationState } = require(operatorTestScript("web_browser_page.cjs"));
  const invoke = message => {
    Object.defineProperty(message, 'content', { get() { throw Error('message content accessed'); } });
    const row = { getAttribute: () => 'message-1', querySelectorAll: () => [],
      __reactFiber$fixture: { memoizedProps: { message }, return: null } };
    const document = {
      querySelector: () => ({ getClientRects: () => [] }),
      querySelectorAll: selector => selector === '[role="alert"]'
        ? [{ getClientRects: () => [{}], textContent: '未能加载订阅：Something went wrong. PRIVATE' }]
        : selector.includes('assistant') ? [row] : [{}] };
    return plain(vm.runInNewContext(`(${publicGenerationState.toString()})()`, { document }));
  };
  const state = invoke(authored([]));
  assert.deepEqual(state, { userRows: 1, assistantRows: 1, finalRows: 1, finishedFinalRows: 1,
    currentFinalRows: 1, currentFinishedFinalRows: 1, renderedTextLength: 0,
    stopPresent: true, stopVisible: false, subscriptionWarning: true, errorAlert: true });
  for (const change of [{ channel: 'analysis' }, { recipient: 'tool' }, { id: 'other' },
      { metadata: { is_visually_hidden: true } }]) {
    const hidden = invoke(authored([], change));
    assert.equal(hidden.finalRows, 0);
    assert.equal(hidden.finishedFinalRows, 0);
  }
  assert.equal(invoke(authored([], { status: 'in_progress', end_turn: false })).finishedFinalRows, 0);
  assert.equal(Object.values(state).every(value => ['boolean', 'number'].includes(typeof value)), true);
});

test('public interruptions require rendered UI and exact connector heading, never assistant wording', () => {
  const { publicInterruptionState } = require(operatorTestScript("web_browser_page.cjs"));
  const clear = { approvalCards: 0, connectorDialogs: 0, sessionExpired: false,
    subscriptionUnavailable: false, responseError: false };
  const element = (text, options = {}) => ({ innerText: text,
    getClientRects: () => options.unrendered ? [] : [{}], closest: () => options.hidden ? {} : null,
    querySelectorAll: () => options.headings || [], click() { throw Error('approval must not be clicked'); } });
  const read = (entries, name = 'Operator 固定连接') => plain(vm.runInNewContext(
    `(${publicInterruptionState.toString()})(name)`, { name, document: { querySelectorAll: selector => {
      assert.ok(['[role="alert"]', '[role="dialog"]', '[data-testid="tool-approval-card"]',
        '[data-testid="regenerate-thread-error-button"]'].includes(selector));
      return entries[selector] || [];
    } } }));
  assert.deepEqual(read({}), clear);
  assert.deepEqual(read({ '[role="alert"]': [element('Your session has expired. PRIVATE', { hidden: true })],
    '[data-testid="tool-approval-card"]': [element('PRIVATE', { unrendered: true }), element('PRIVATE', { hidden: true })] }), clear);
  const exact = element('PRIVATE call arguments', { headings: [element('Allow ChatGPT to use Operator 固定连接?')] });
  assert.equal(read({ '[role="dialog"]': [exact] }).connectorDialogs, 1);
  assert.deepEqual(read({ '[role="dialog"]': [exact] }, 'Operator'), clear);
  assert.deepEqual(read({ '[role="dialog"]': [exact] }, null), clear);
  assert.equal(read({ '[data-testid="tool-approval-card"]': [element('PRIVATE')] }).approvalCards, 1);
  for (const [text, flag] of [['Your session has expired. PRIVATE', 'sessionExpired'],
    ['您的会话已过期', 'sessionExpired'], ['Failed to load subscription. PRIVATE', 'subscriptionUnavailable'],
    ['Unable to load subscription', 'subscriptionUnavailable'], ['Something went wrong. PRIVATE', 'responseError']]) {
    assert.deepEqual(read({ '[role="alert"]': [element(text)] }), { ...clear, [flag]: true });
  }
  assert.deepEqual(read({ '[data-testid="regenerate-thread-error-button"]': [element('')] }),
    { ...clear, responseError: true });
  assert.deepEqual(read({ '[role="alert"]': [element('x'.repeat(4096) + 'Your session has expired')] }), clear);
  // Ordinary final text is never queried, even if it quotes every error phrase.
  const prose = element('Something went wrong. OpenAI safety blocked run_tests. Your session has expired.');
  assert.deepEqual(read({ '[data-message-author-role="assistant"]': [prose] }), clear);
});

test('persistent public interruption stops without approval clicks or accepting a simultaneous final', async () => {
  for (const [state, code] of [
    [{ approvalCards: 1 }, 'web_tool_confirmation_required_no_retry'],
    [{ connectorDialogs: 1 }, 'web_tool_confirmation_required_no_retry'],
    [{ sessionExpired: true }, 'web_session_expired_during_generation_no_retry'],
    [{ subscriptionUnavailable: true }, 'web_subscription_unavailable_during_generation_no_retry'],
    [{ responseError: true }, 'web_response_error_no_retry']]) {
    const host = hiddenHostFixture();
    host.invoke(`let fixtureClock = 1000, finalReads = 0;
      Date.now = () => fixtureClock;
      page.publicInterruptionState = function () {};
      inPage = async fn => {
        if (fn === page.publicInterruptionState) return { approvalCards: 0, connectorDialogs: 0,
          sessionExpired: false, subscriptionUnavailable: false, responseError: false, ...${JSON.stringify(state)} };
        if (fn === page.publicFinal) { finalReads++; return { id: 'unaccepted' }; }
        throw Error('unexpected action');
      };
      waitFor = async fn => { for (let i = 0; i < 4; i++, fixtureClock += 1000) {
        const result = await fn(); if (result) return result;
      } throw Error('fixture did not settle'); };`);
    await assert.rejects(host.invoke("waitForPublicFinal('exact prompt', 'Operator 固定连接')"), new RegExp(code));
    assert.equal(host.invoke('finalReads'), 0);
    assert.equal(host.events.filter(e => e.kind === 'public_interruption_state').length, 1);
    assert.equal(host.commands.length, 0);
  }
});

test('transient UI clears before final acceptance and prose never becomes interruption evidence', async () => {
  const host = hiddenHostFixture();
  host.invoke(`let fixtureClock = 1000, stateReads = 0;
    Date.now = () => fixtureClock;
    page.publicInterruptionState = function () {}; page.publicGenerationState = function () {};
    inPage = async fn => {
      if (fn === page.publicInterruptionState) return { approvalCards: stateReads++ === 0 ? 1 : 0,
        connectorDialogs: 0, sessionExpired: false, subscriptionUnavailable: false, responseError: false };
      if (fn === page.publicGenerationState) return {};
      if (fn === page.publicFinal) return { content: { parts: ['OpenAI safety blocked run_tests.'] } };
      throw Error('unexpected action');
    };
    waitFor = async fn => { for (let i = 0; i < 4; i++, fixtureClock += 1000) {
      const result = await fn(); if (result) return result;
    } throw Error('fixture did not settle'); };`);
  assert.deepEqual(plain(await host.invoke("waitForPublicFinal('exact prompt', 'Operator 固定连接')")),
    { content: { parts: ['OpenAI safety blocked run_tests.'] } });
  assert.deepEqual(host.events.filter(e => e.kind === 'public_interruption_state').map(e => e.state.approvalCards), [1, 0]);
  assert.equal(host.commands.length, 0);
});

function currentTree(previous, latest) {
  const rootState = {};
  const rootA = { tag: 3, return: null, stateNode: rootState };
  const rootB = { tag: 3, return: null, stateNode: rootState };
  const parentA = { return: rootA, memoizedProps: {} }, parentB = { return: rootB, memoizedProps: {} };
  const a = { return: parentA, memoizedProps: { message: previous } };
  const b = { return: parentB, memoizedProps: { message: latest } };
  for (const [one, two] of [[rootA, rootB], [parentA, parentB], [a, b]]) {
    one.alternate = two; two.alternate = one;
  }
  rootA.child = parentA; rootB.child = parentB;
  parentA.child = a; parentB.child = b; rootState.current = rootB;
  return { a, b, parentA, parentB, rootState, rootA, rootB };
}

test('public branch resolution proves current membership, including shared return and bailout links', () => {
  const { currentPublicFiber } = require(operatorTestScript("web_browser_page.cjs"));
  const tree = currentTree({}, {});
  Object.defineProperty(tree.a, 'memoizedProps', { get() { throw Error('props read during graph lookup'); } });
  assert.equal(currentPublicFiber(tree.a), tree.b);
  tree.b.return = tree.parentA;
  assert.equal(currentPublicFiber(tree.a), tree.b);
  tree.parentB.child = tree.a;
  assert.equal(currentPublicFiber(tree.b), tree.a);
  tree.rootState.current = {};
  assert.throws(() => currentPublicFiber(tree.a), /web_public_current_branch_unavailable/);
  const disconnected = { return: { child: null } };
  assert.throws(() => currentPublicFiber(disconnected), /web_public_current_branch_unavailable/);
  const other = {}; other.sibling = other; disconnected.return.child = other;
  assert.throws(() => currentPublicFiber(disconnected), /web_public_tree_cycle/);
});

test('committed public output never releases a stale successful copy or reads its content', () => {
  const { currentPublicFiber, publicGenerationState } = require(operatorTestScript("web_browser_page.cjs"));
  const tree = currentTree(authored(['STALE']), authored(['exact 中文😀\r\n_a_']));
  Object.defineProperty(tree.a.memoizedProps.message, 'content', { get() { throw Error('stale content read'); } });
  const row = { getAttribute: () => 'message-1', querySelectorAll: () => [], __reactFiber$fixture: tree.a };
  const document = { querySelector: () => null, querySelectorAll: selector => selector === '[role="alert"]' ? []
    : selector.includes('user') ? [{ textContent: prompt }] : [row] };
  const invoke = expression => vm.runInNewContext(`const currentPublicFiber = (${currentPublicFiber.toString()}); ${expression}`,
    { document, prompt, TextEncoder });
  const result = invoke(`(${publicFinal.toString()})(prompt, false, true)`);
  assert.deepEqual(plain(result.content.parts), ['exact 中文😀\r\n_a_']);
  tree.b.memoizedProps.message.status = 'in_progress';
  tree.b.memoizedProps.message.end_turn = false;
  assert.equal(invoke(`(${publicFinal.toString()})(prompt, false, true)`), null);
  let progress = invoke(`(${publicGenerationState.toString()})(true)`);
  assert.equal(progress.finishedFinalRows, 1);
  assert.equal(progress.currentFinishedFinalRows, 0);
  tree.a.memoizedProps.message.status = 'in_progress';
  tree.a.memoizedProps.message.end_turn = false;
  tree.b.memoizedProps.message.status = 'finished_successfully';
  tree.b.memoizedProps.message.end_turn = true;
  progress = invoke(`(${publicGenerationState.toString()})(true)`);
  assert.equal(progress.finishedFinalRows, 0);
  assert.equal(progress.currentFinishedFinalRows, 1);
  tree.rootState.current = null;
  assert.throws(() => invoke(`(${publicFinal.toString()})(prompt, false, true)`), /web_public_current_branch_unavailable/);
});

test('current public membership handles deep paired ancestors within the same bounded read budget', () => {
  const { currentPublicFiber } = require(operatorTestScript("web_browser_page.cjs"));
  const tree = currentTree({}, {});
  let left = tree.parentA, right = tree.parentB;
  for (let index = 0; index < 300; index++) {
    const parent = { child: left }, other = { child: right };
    parent.alternate = other; other.alternate = parent;
    left.return = parent; right.return = other;
    left = parent; right = other;
  }
  left.return = tree.rootA; right.return = tree.rootB;
  tree.rootA.child = left; tree.rootB.child = right;
  assert.equal(currentPublicFiber(tree.a), tree.b);
  tree.rootState.current = tree.rootA;
  assert.equal(currentPublicFiber(tree.b), tree.a);
  const unpaired = { return: tree.a };
  tree.a.child = unpaired;
  assert.equal(currentPublicFiber(unpaired), unpaired);
  tree.rootState.current = tree.rootB;
  assert.throws(() => currentPublicFiber(unpaired), /web_public_current_branch_unavailable/);
});

test("citation inspection reads only bounded public final metadata shapes", () => {
  const { publicCitationShape } = require(operatorTestScript("web_browser_page.cjs"));
  const invoke = message => {
    const row = { getAttribute: () => 'message-1', __reactFiber$fixture: {
      memoizedProps: { message }, return: null } };
    return plain(vm.runInNewContext(`(${publicCitationShape.toString()})()`,
      { document: { querySelectorAll: () => [row] } }));
  };
  const publicMessage = authored(['answer'], { metadata: { content_references: [
    { url: 'https://example.com', title: 'DO_NOT_EXPORT', start_idx: 0, secret: { value: 'private' } }],
    unrelated: 'DO_NOT_EXPORT' } });
  const result = invoke(publicMessage);
  assert.equal(result.observations[0].content_references.length, 1);
  assert.equal(result.observations[0].content_references.items[0].fields.url.kind, 'string');
  assert.equal(JSON.stringify(result).includes('DO_NOT_EXPORT'), false);
  for (const changes of [{ channel: 'analysis' }, { recipient: 'tool' }, { end_turn: false }, { id: 'other' }]) {
    const message = authored([], changes);
    Object.defineProperty(message, 'metadata', { get() { throw Error('private metadata accessed'); } });
    assert.deepEqual(invoke(message), { observations: [] });
  }
  publicMessage.metadata.is_visually_hidden = true;
  assert.deepEqual(invoke(publicMessage), { observations: [] });
});
test("public user diagnostics retain bounded counts without source text", () => {
  const { publicUserBindingShape } = require(operatorTestScript("web_browser_page.cjs"));
  const call = (text, expected) => {
    const row = { getAttribute: () => 'user-1', __reactFiber$fixture: {
      memoizedProps: { message: { id: 'user-1', author: { role: 'user' },
        content: { content_type: 'text', parts: [text] } } }, return: null } };
    return plain(vm.runInNewContext(`(${publicUserBindingShape.toString()})(expected)`,
      { document: { querySelectorAll: () => [row] }, expected }));
  };
  const exact = call('secret  中文\n', 'secret  中文\n');
  assert.equal(exact.exact, true);
  assert.equal(exact.firstDifference, -1);
  const changed = call('secret \u00a0中文\n', 'secret  中文\n');
  assert.equal(changed.exact, false);
  assert.equal(changed.firstDifference, 7);
  assert.equal(changed.sharedSuffix, 3);
  assert.equal(changed.sourceNbsp, 1);
  assert.equal(changed.promptNbsp, 0);
  assert.equal(changed.sourceLineFeeds, 1);
  assert.equal(changed.promptOffset, -1);
  assert.equal(changed.backslashInsertionsOnly, false);
  const escaped = call('snake\\_case \\[x\\]', 'snake_case [x]');
  assert.equal(escaped.backslashInsertionsOnly, true);
  assert.equal(escaped.sourceBackslashes, 3);
  assert.equal(Object.values(changed).some(value => typeof value === 'string'), false);
  assert.deepEqual(call('x'.repeat(1024 * 1024 + 1), 'x'), { supportedTextShape: false });
});
test("cancel clicks only one visible enabled stop control", () => {
  const { cancelGeneration } = require(operatorTestScript("web_browser_page.cjs"));
  let clicks = 0;
  const button = (visible = true, disabled = false) => ({ disabled,
    getClientRects: () => visible ? [{}] : [], getAttribute: () => null, click: () => { clicks++; } });
  const call = rows => vm.runInNewContext(`(${cancelGeneration.toString()})()`,
    { document: { querySelectorAll: () => rows } });
  assert.equal(call([]), false);
  assert.equal(call([button(false), button(true, true)]), false);
  assert.equal(call([button()]), true);
  assert.equal(clicks, 1);
  assert.throws(() => call([button(), button()]), /web_stop_control_ambiguous/);
  assert.equal(clicks, 1);
});
function authored(parts = ["answer"], extra = {}) {
  return { id: "message-1", author: { role: "assistant" }, recipient: "all", channel: "final",
    end_turn: true, status: "finished_successfully", content: { content_type: "text", parts }, ...extra };
}
function project(messages, options = {}) {
  const rows = messages.map(message => ({
    getAttribute: () => options.rowId || message.id,
    querySelectorAll: () => [],
    __reactFiber$fixture: { memoizedProps: { message }, return: null },
  }));
  const document = {
    querySelector: () => options.running ? {} : null,
    querySelectorAll: selector => selector === '[data-message-author-role="user"]'
      ? [{ textContent: options.prompt ?? prompt, getAttribute: () => options.userId ?? "user-1",
          __reactFiber$fixture: { memoizedProps: { message: options.userMessage }, return: null } }] : rows,
  };
  // Match Electron's function-source serialization, with no module closure.
  return vm.runInNewContext(`(${publicFinal.toString()})(prompt, includeCitations)`,
    { document, prompt, TextEncoder, includeCitations: options.includeCitations === true });
}
function plain(value) { return value === null ? null : JSON.parse(JSON.stringify(value)); }

test("explicit public references retain only the bound public citation fields", () => {
  const reference = { type: 'grouped_webpages', start_idx: 2, end_idx: 10,
    matched_text: 'citation', items: [{ title: 'Public title', url: 'https://example.com',
      snippet: 'DO_NOT_EXPORT' }], prompt_text: 'DO_NOT_EXPORT' };
  const message = authored(['🪐citation'], { metadata: { content_references: [reference] } });
  assert.equal(project([message]).public_references, undefined);
  const result = plain(project([message], { includeCitations: true }));
  assert.deepEqual(result.public_references, [{ type: 'grouped_webpages', start_idx: 2, end_idx: 10,
    matched_text: 'citation', items: [{ title: 'Public title', url: 'https://example.com' }] }]);
  assert.equal(JSON.stringify(result).includes('DO_NOT_EXPORT'), false);
  reference.start_idx = -1;
  assert.throws(() => project([message], { includeCitations: true }), /web_public_citation_position_invalid/);
  reference.start_idx = 2;
  reference.items = Array(65).fill({});
  assert.throws(() => project([message], { includeCitations: true }), /web_public_citation_sources_invalid/);
});

test("labelled public URLs project their own item without snippets or inferred URLs", () => {
  const marker = '\ue200url\ue202Public label\ue202turn0search1\ue201';
  const reference = { type: 'url', title: 'Public label', start_idx: 0, end_idx: marker.length,
    matched_text: marker, item: { title: 'Source title', url: 'https://example.test/source', snippet: 'DO_NOT_EXPORT' },
    safe_urls: ['https://example.test/unused'], prompt_text: 'DO_NOT_EXPORT' };
  const message = authored([marker], { metadata: { content_references: [reference] } });
  const value = plain(project([message], { includeCitations: true })).public_references[0];
  assert.deepEqual(value, { type: 'url', title: 'Public label', start_idx: 0, end_idx: marker.length,
    matched_text: marker, item: { title: 'Source title', url: 'https://example.test/source' } });
  assert.equal(JSON.stringify(value).includes('DO_NOT_EXPORT'), false);
  delete reference.item;
  assert.throws(() => project([message], { includeCitations: true }), /web_public_citation_field_invalid/);
});

test("automatic selection binds the exact public plugin identity before activating its row", () => {
  let clicked = 0;
  const name = "Operator gpttest Pro", query = "@Operator", id = 'plugin:asdk_app_' + 'a'.repeat(32);
  const composer = { textContent: query };
  const row = (label, visible = true, rowId = id, hidden = false) => ({ textContent: label + " description",
    getClientRects: () => visible ? [{}] : [], getAttribute: () => null,
    closest: selector => selector === '[data-composer-plugin-impression-id]' ? { getAttribute: () => rowId.slice(7) } : hidden ? {} : null,
    querySelectorAll: () => [{ textContent: label }], click: () => { clicked++; } });
  const invoke = (rows, activate = false) => vm.runInNewContext(
    `(${connectorMenuChoice.toString()})(name, query, activate, id)`,
    { name, query, activate, id, document: { activeElement: composer,
      querySelector: () => composer, querySelectorAll: selector => {
        assert.equal(selector, '[data-composer-plugin-impression-id] .__menu-item[tabindex="0"]');
        return rows;
      } } });
  const rows = [row("Other app"), row(name, false), row(name)];
  assert.equal(invoke(rows).activated, false);
  assert.equal(clicked, 0);
  assert.equal(invoke(rows, true).activated, true);
  assert.equal(clicked, 1);
  assert.equal(invoke([row(name, true, 'plugin:asdk_app_' + 'b'.repeat(32))], true), null);
  assert.equal(invoke([row(name, true, id, true)], true), null);
  assert.equal(invoke([row(name, true, 'plugin:asdk_app_' + 'b'.repeat(32)), row(name)]).id, id);
  assert.equal(invoke([row("Other app")], true), null);
  assert.equal(invoke([...Array.from({ length: 100 }, (_, i) => row("Other " + i)), row(name)]).name, name);
  assert.throws(() => invoke(Array.from({ length: 513 }, () => row("Other"))), /web_connector_menu_too_large/);
  assert.throws(() => invoke([row(name), row(name)], true), /web_connector_menu_ambiguous/);
  composer.textContent = "user supplied text";
  assert.throws(() => invoke(rows, true), /web_connector_query_changed/);
  assert.equal(clicked, 1);
});

test("connector access observation reads the visible public setting without changing it", () => {
  const { connectorAccessState } = require(operatorTestScript("web_browser_page.cjs"));
  const button = (label, hidden = false) => ({ getClientRects: () => [{}],
    closest: () => hidden ? {} : null, getAttribute: () => label,
    click: () => { throw Error('must not change account settings'); } });
  const state = rows => vm.runInNewContext(`(${connectorAccessState.toString()})()`, {
    document: { querySelectorAll: () => rows } });
  assert.equal(state([]), 'unknown');
  assert.equal(state([button('不个性化')]), 'disabled');
  assert.equal(state([button('个性化')]), 'enabled');
  assert.equal(state([button('个性化', true), button('不个性化')]), 'disabled');
  assert.equal(state([button('个性化'), button('不个性化')]), 'unknown');
});

function connectorFixture(options = {}) {
  const name = options.name ?? "Operator gpttest Pro", id = "plugin:asdk_app_" + "a".repeat(32);
  const attrs = { 'data-id': id, 'data-system-hint-type': id, 'data-symbol': 'ecosystemMention',
    'data-keyword': name, contenteditable: 'false', ...options.attrs };
  const pill = { textContent: options.label ?? name, getAttribute: key => attrs[key] };
  const cursor = { textContent: options.cursorText ?? '\uFEFF', getAttribute: () => 'false' };
  const composer = { textContent: options.text ?? '\uFEFF' + name + ' ',
    innerText: options.text ?? '\uFEFF' + name + ' ', getClientRects: () => [{}],
    querySelectorAll: selector => selector === '[data-inline-selection-pill]'
      ? Array(options.pills ?? 1).fill(pill) : Array(options.cursors ?? 1).fill(cursor) };
  const document = { querySelectorAll: () => [composer], querySelector: () => composer, activeElement: composer };
  Object.defineProperty(composer, 'childNodes', { configurable: true,
    get: () => [{ nodeType: 1, tagName: 'P', textContent: composer.textContent, querySelectorAll: () => [] }] });
  return { name, id, document, composer, attrs };
}

test("selected app identity comes from one exact visible pill and stays bound before send", () => {
  const f = connectorFixture();
  const invoke = (fn, args) => vm.runInNewContext(`(${fn.toString()})(...args)`, { document: f.document, args });
  const mention = plain(invoke(selectedConnector, [f.name]));
  assert.deepEqual(mention, { name: f.name, id: f.id });
  const prefix = invoke(composerPrefix, [mention]);
  f.composer.textContent += "authorized fixture";
  f.composer.innerText += "authorized fixture";
  assert.equal(invoke(composerMatches, ["authorized fixture", prefix, mention]), true);
  f.attrs['data-id'] = "plugin:asdk_app_" + "b".repeat(32);
  assert.equal(invoke(composerMatches, ["authorized fixture", prefix, mention]), false);
  assert.throws(() => invoke(composerPrefix, [mention]), /web_connector_mention_mismatch/);
});

test("connector prompt comparison retains paragraph breaks and rejects collapsed or changed text", () => {
  const f = connectorFixture();
  const mention = { id: f.id, name: f.name };
  const prefix = '\uFEFF' + f.name + ' ';
  const text = '  first line\n\n中文😀 last line  ';
  // Paragraph textContent drops line boundaries; innerText may add UI layout
  // breaks. Neither scalar value is a faithful labelled multiline editor.
  f.composer.textContent = prefix + text.replaceAll('\n', '');
  f.composer.innerText = prefix + '\n' + text;
  const paragraph = value => ({ nodeType: 1, tagName: 'P', textContent: value,
    querySelectorAll: () => value === '' ? [{}] : [] });
  Object.defineProperty(f.composer, 'childNodes', { writable: true,
    value: (prefix + text).split('\n').map(paragraph) });
  const invoke = () => vm.runInNewContext(`(${composerMatches.toString()})(text, prefix, mention)`,
    { document: f.document, text, prefix, mention });
  assert.equal(invoke(), true);
  const original = f.composer.childNodes;
  f.composer.childNodes = [paragraph(f.composer.textContent)];
  assert.equal(invoke(), false);
  f.composer.childNodes = [...original, paragraph('')];
  assert.equal(invoke(), false);
  f.composer.childNodes = [...original];
  f.composer.childNodes[1] = { nodeType: 3, textContent: '' };
  assert.equal(invoke(), false);
  f.composer.childNodes = original;
  f.composer.childNodes[0] = { ...original[0], querySelectorAll: () => [{}] };
  assert.equal(invoke(), false);
  f.composer.childNodes = (prefix + text).split('\n').map(paragraph);
  f.attrs['data-system-hint-type'] = 'another-app';
  assert.equal(invoke(), false);
});

test("selection waits only for an absent pill and rejects ambiguity or altered app metadata", () => {
  const invoke = options => {
    const f = connectorFixture(options);
    return vm.runInNewContext(`(${selectedConnector.toString()})(name)`, { document: f.document, name: f.name });
  };
  assert.equal(invoke({ pills: 0 }), null);
  for (const options of [{ pills: 2 }, { cursors: 0 }, { label: "Other app" },
    { attrs: { 'data-id': 'bad' } }, { attrs: { 'data-system-hint-type': 'other' } },
    { attrs: { 'data-keyword': 'Other app' } }, { attrs: { 'data-symbol': 'other' } },
    { attrs: { contenteditable: 'true' } }, { cursorText: '' }, { text: 'typed prompt' }]) {
    assert.throws(() => invoke(options), /web_connector_mention_(mismatch|ambiguous)/);
  }
});

test("public text retains all parts and exposes only the public projection", () => {
  const parts = ["  中文😀 a_b\r\n", "", "```python\nx = 1\n```\n"];
  const source = authored(parts, { metadata: { irrelevant_account_data: "not exported" } });
  const result = plain(project([source]));
  assert.deepEqual(result.content.parts, parts);
  assert.deepEqual(result.metadata, {});
  result.content.parts[0] = "different";
  assert.equal(source.content.parts[0], parts[0]);
});

test("private and tool messages never read content", () => {
  for (const changes of [{ channel: "analysis" }, { recipient: "some_tool" }, { end_turn: false }, { status: "in_progress" }]) {
    const message = authored([], changes);
    Object.defineProperty(message, "content", { get() { throw new Error("private content accessed"); } });
    assert.equal(project([message]), null);
  }
});

test("row identity and exact current prompt bind the projected message", () => {
  assert.equal(project([authored()], { rowId: "different-row" }), null);
  assert.throws(() => project([authored()], { prompt: prompt + " " }), /web_user_source_unavailable/);
  assert.equal(project([authored()], { running: true }), null);
});

test("long user display requires an exact structured source with matching row identity", () => {
  const userMessage = { id: "user-1", author: { role: "user" },
    content: { content_type: "text", parts: [prompt] } };
  const options = { prompt: prompt + " Show more", userMessage };
  assert.equal(project([authored()], options).id, "message-1");
  assert.throws(() => project([authored()], { ...options, userId: "other" }), /web_user_source_unavailable/);
  assert.throws(() => project([authored()], { ...options,
    userMessage: { ...userMessage, author: { role: "assistant" } } }), /web_user_source_unavailable/);
  for (const parts of [[prompt + " "], [prompt, ""], [prompt, { image: "x" }]]) {
    assert.throws(() => project([authored()], { ...options,
      userMessage: { ...userMessage, content: { content_type: "text", parts } } }), /web_user_turn_mismatch/);
  }
});

test("mixed or hidden content rejects the entire output", () => {
  for (const invalid of [authored(["text", { image: "x" }]),
    authored(["text"], { metadata: { is_visually_hidden: true } }),
    authored(["text"], { metadata: { is_visually_hidden: "true" } }),
    authored([], { content: { content_type: "text", text: "no parts fallback" } })]) {
    assert.throws(() => project([authored(), { ...invalid, id: "message-2" }]), /web_(text_parts_invalid|hidden_message_rejected)/);
  }
});

test("duplicate observations converge but contradictions and multiple finals fail", () => {
  assert.equal(plain(project([authored(), authored()])).id, "message-1");
  assert.throws(() => project([authored(), authored(["different"])]), /web_public_message_contradiction/);
  assert.throws(() => project([authored(), authored(["other"], { id: "message-2" })]), /web_final_message_ambiguous/);
});

test("public UTF-8 payload bounds reject without truncation", () => {
  assert.throws(() => project([authored(["中文".repeat(200000)])]), /web_public_message_too_large/);
});

test("tool-shaped prose remains public text", () => {
  const text = '{"type":"function_call","name":"exec","arguments":"untrusted"}';
  assert.deepEqual(plain(project([authored([text])])).content.parts, [text]);
});

test("the version chooser follows its accessible label rather than the effort text", () => {
  let clicked = 0;
  const item = (label, text) => ({ textContent: text, getClientRects: () => [{}],
    getAttribute: name => name === "aria-label" ? label : null, closest: () => null, click: () => { clicked++; } });
  const invoke = rows => vm.runInNewContext(`(${clickModelChooser.toString()})()`,
    { document: { querySelectorAll: () => rows } });
  invoke([item("选择模型", "极高"), item("能力", "")]);
  assert.equal(clicked, 1);
  assert.throws(() => invoke([item(null, "选择模型")]), /web_model_chooser_ambiguous/);
  assert.throws(() => invoke([item("选择模型", "极高"), item("选择模型", "高")]), /web_model_chooser_ambiguous/);
  assert.equal(clicked, 1);
});

test('model selection ignores retained inert panels and closing menu animations', () => {
  const page = require(operatorTestScript("web_browser_page.cjs"));
  let hiddenAncestor = null, clicks = 0;
  const blocked = selector => hiddenAncestor && selector.includes(hiddenAncestor) ? {} : null;
  const element = attributes => ({ textContent: attributes.text || '', getClientRects: () => [{}],
    closest: blocked, getAttribute: key => attributes[key] ?? null, click: () => clicks++ });
  const chooser = element({ 'aria-label': '选择模型', text: '5.6高' });
  const option = element({ text: 'GPT-5.6 Sol', 'aria-checked': 'true' });
  const focusControl = { focus: () => { document.activeElement = focusControl; } };
  const slider = element({ 'aria-valuemin': '0', 'aria-valuemax': '4', 'aria-valuenow': '2' });
  slider.closest = () => focusControl;
  const panel = { ...element({}), querySelectorAll: () => [slider], querySelector: () => slider };
  const document = { title: 'ChatGPT', readyState: 'complete', activeElement: null,
    hasFocus: () => false, querySelector: () => null, querySelectorAll: selector => {
      if (selector === '[role="menuitem"]') return [chooser];
      if (selector === '[role="menuitemradio"]') return [option];
      if (selector === '[role="menuitem"],[role="menuitemradio"]') return [chooser, option];
      if (selector === '[data-model-reasoning-effort-slider]') return [panel];
      return [];
    } };
  const invoke = name => vm.runInNewContext(`(${page[name].toString()})()`, { document });
  for (const attribute of ['[inert]', '[aria-hidden="true"]', '[hidden]', '[role="menu"][data-state="closed"]']) {
    hiddenAncestor = attribute;
    const state = invoke('controls');
    assert.equal(state.chooser, false);
    assert.equal(state.modelOption, false);
    assert.equal(state.modelChecked, null);
    assert.deepEqual(plain(state.modelMenuLabels), []);
    assert.equal(invoke('effortState'), null);
    assert.throws(() => invoke('clickModelChooser'), /web_model_chooser_ambiguous/);
    assert.throws(() => invoke('chooseSol'), /web_model_option_ambiguous/);
    assert.throws(() => invoke('focusEffort'), /web_effort_control_ambiguous/);
    assert.equal(clicks, 0);
    assert.equal(document.activeElement, null);
  }
  hiddenAncestor = null;
  assert.equal(invoke('controls').modelChecked, 'true');
  assert.deepEqual(plain(invoke('effortState')), { min: 0, max: 4, value: 2 });
  invoke('clickModelChooser'); invoke('chooseSol'); invoke('focusEffort');
  assert.equal(clicks, 2);
  assert.equal(document.activeElement, focusControl);
});

test("menu input requires the unique enabled model control to own focus", () => {
  let rows, focused = 0;
  const document = { activeElement: null,
    querySelector: () => ({ closest: () => ({ querySelectorAll: () => rows }) }) };
  const button = { getClientRects: () => [{}], getAttribute: () => "false",
    focus: () => { focused++; document.activeElement = button; } };
  const invoke = () => vm.runInNewContext(`(${focusModelMenu.toString()})()`, { document });
  rows = [button];
  assert.equal(invoke(), true);
  assert.equal(focused, 1);
  rows = [button, button];
  assert.throws(invoke, /web_model_control_ambiguous/);
  rows = [{ ...button, disabled: true }];
  assert.throws(invoke, /web_model_control_disabled/);
  document.activeElement = null;
  rows = [{ ...button, focus: () => {} }];
  assert.throws(invoke, /web_model_focus_failed/);
  rows = [{ ...button, getAttribute: name => name === "aria-expanded" ? "true" : "false" }];
  assert.equal(invoke(), false);
  assert.equal(focused, 1);
});

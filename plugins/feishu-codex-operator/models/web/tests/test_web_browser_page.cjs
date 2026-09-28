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
const { publicFinal, clickModelChooser, focusModelMenu, connectorMenuChoice, connectorPillState, selectedConnector, composerPrefix, focusComposer, composerMatches,
  uniqueComposer, eligibleModelButtons, eligibleEffortContainer } = require(operatorTestScript("web_browser_page.cjs"));
const prompt = "Synthetic fixture 中文";

test('startup control structure exposes only bounded selector counts and flags', () => {
  const { startupControlStructure } = require(operatorTestScript('web_browser_page.cjs'));
  const form = {contains: element => element === model};
  const element = (editable, rects, attributes = {}) => ({tagName: attributes.tagName || 'DIV',
    disabled: attributes.disabled, textContent: attributes.text || 'PRIVATE PAGE TEXT',
    getClientRects: () => Array(rects).fill({}),
    getAttribute: name => name === 'contenteditable' ? editable : attributes[name] || null,
    closest: selector => selector === 'form' ? attributes.form || null : null});
  const editor = element('false', 1), alternative = element('true', 1, {form});
  const hidden = element('true', 0), model = element(null, 1,
    {tagName: 'BUTTON', disabled: false, 'aria-label': '选择 ChatGPT 模型',
      'aria-haspopup': 'menu', form});
  const otherButton = element(null, 1);
  const selectors = new Map([
    ['#prompt-textarea', [editor]],
    ['[data-testid="prompt-textarea"]', [alternative]],
    ['[role="textbox"][contenteditable="true"]', [alternative]],
    ['[contenteditable="true"]', [alternative, hidden]],
    ['textarea', []],
    ['button[aria-haspopup="menu"][data-tone="neutral"],button[data-testid="model-switcher-dropdown-button"]', [model, hidden]],
    ['button,[role="button"]', [model, otherButton]],
  ]);
  const document = {readyState: 'complete', querySelectorAll: selector => selectors.get(selector) || []};
  const result = vm.runInNewContext('(' + startupControlStructure.toString() + ')()', {document});
  assert.equal(JSON.stringify(result), JSON.stringify({readyState: 'complete',
    legacyEditorCount: 'one', legacyEditorEditable: 'no', legacyEditorRect: 'yes',
    testIdEditorVisible: 'one', roleTextboxEditableVisible: 'one',
    editableVisible: 'one', textareaVisible: 'zero',
    globalModelTotal: 'multiple', globalModelVisible: 'one',
    editorFormExists: 'yes', accessibleModelCount: 'one',
    accessibleModelSource: 'aria_label', accessibleModelTag: 'button',
    accessibleModelInEditorForm: 'yes', accessibleModelHaspopup: 'menu',
    accessibleModelDisabled: 'no'}));
  assert.equal(JSON.stringify(result).includes('PRIVATE PAGE TEXT'), false);
  selectors.set('button,[role="button"]', [model,
    element(null, 1, {tagName: 'BUTTON', text: 'Choose ChatGPT model'})]);
  const duplicate = vm.runInNewContext('(' + startupControlStructure.toString() + ')()', {document});
  assert.equal(duplicate.accessibleModelCount, 'multiple');
  assert.equal(duplicate.accessibleModelSource, 'unknown');
});

test('composer and model compatibility uses only one observed control per page and fails closed on conflicts', () => {
  const {focusModelMenu, composerFocused, sendOnce} = require(operatorTestScript('web_browser_page.cjs'));
  let oldEditors = [], roleEditors = [], editables = [], oldButtons = [], namedButtons = [];
  let sendClicks = 0;
  const document = {activeElement: null, querySelectorAll: selector => ({
    '#prompt-textarea': oldEditors,
    '[role="textbox"][contenteditable="true"]': roleEditors,
    '[contenteditable="true"]': editables,
    'button[aria-haspopup="menu"][data-tone="neutral"],button[data-testid="model-switcher-dropdown-button"]': oldButtons,
    'button[aria-label="选择 ChatGPT 模型"],button[aria-label="Choose ChatGPT model"]': namedButtons,
  })[selector] || []};
  const sendButton = {disabled: false, getAttribute: () => null, getClientRects: () => [{}], closest: () => null,
    click: () => sendClicks++};
  let retainedRows = [];
  const originalQuery = document.querySelectorAll;
  document.querySelectorAll = selector => selector === '[data-message-author-role],[data-chatgpt-search-unit-key]'
    ? retainedRows : originalQuery(selector);
  let oldSendButtons = [sendButton], currentSendButtons = [];
  const form = {contains: element => element === namedButton || element === oldButton,
    querySelectorAll: selector => selector === '[data-testid="send-button"]' ? oldSendButtons
      : selector === 'button[type="submit"]' ? currentSendButtons : []};
  const editor = {textContent: '', getAttribute: name => name === 'contenteditable' ? 'true' : null,
    getClientRects: () => [{}], closest: selector => selector === 'form' ? form : null};
  const oldButton = {disabled: false, getClientRects: () => [{}],
    getAttribute: name => name === 'aria-expanded' ? 'false' : null,
    focus: () => {document.activeElement = oldButton;}};
  const namedButton = {disabled: false, getClientRects: () => [{}],
    getAttribute: name => name === 'aria-haspopup' ? 'menu'
      : name === 'aria-label' ? '选择 ChatGPT 模型' : null,
    closest: () => null,
    focus: () => {document.activeElement = namedButton;}};
  const run = source => vm.runInNewContext(`(() => {
    const uniqueComposer = (${uniqueComposer.toString()});
    const eligibleModelButtons = (${eligibleModelButtons.toString()});
    return ${source};
  })()`, {document});
  const read = () => run('({editor: uniqueComposer(), buttons: eligibleModelButtons(uniqueComposer())})');
  roleEditors = editables = [editor]; namedButtons = [namedButton];
  assert.equal(read().editor, editor);
  assert.equal(read().buttons[0], namedButton);
  const hiddenEditor = {...editor, closest: selector => selector === 'form' ? form
    : selector.includes('aria-hidden') ? {} : null};
  roleEditors = editables = [hiddenEditor];
  assert.equal(read().editor, null); // Layout rect alone is insufficient.
  roleEditors = editables = [editor];
  namedButtons = [{...namedButton, closest: selector => selector.includes('aria-hidden') ? {} : null}];
  assert.equal(read().buttons.length, 0);
  namedButtons = [namedButton];
  assert.equal(run(`(${focusModelMenu.toString()})()`), true);
  assert.equal(run(`(${composerFocused.toString()})()`), false);
  run(`(${sendOnce.toString()})()`);
  assert.equal(sendClicks, 1);
  retainedRows = [{}];
  assert.throws(() => run(`(${sendOnce.toString()})()`), /web_fresh_page_required/);
  assert.equal(sendClicks, 1);
  retainedRows = [];
  oldSendButtons = [];
  currentSendButtons = [{...sendButton, getAttribute: name => name === 'aria-label' ? '发送' : null}];
  run(`(${sendOnce.toString()})()`);
  assert.equal(sendClicks, 2);
  currentSendButtons.push({...currentSendButtons[0]});
  assert.throws(() => run(`(${sendOnce.toString()})()`), /web_send_control_ambiguous/);
  currentSendButtons = [];
  oldEditors = [editor]; oldButtons = [oldButton];
  assert.equal(read().buttons[0], oldButton);
  assert.equal(run(`(${focusModelMenu.toString()})()`), true);
  oldEditors = [{...editor, getClientRects: () => []}];
  assert.equal(read().editor, null); // Present but unusable old editor cannot fall back.
  oldEditors = []; oldButtons = [{...oldButton, getClientRects: () => []}];
  assert.equal(read().buttons.length, 0); // Hidden old button cannot activate new fallback.
  oldButtons = []; editables = [editor, {...editor}];
  assert.equal(read().editor, null);
  editables = [editor]; namedButtons = [namedButton, {...namedButton}];
  assert.equal(read().buttons.length, 0);
  namedButtons = [{...namedButton, getAttribute: name => name === 'aria-haspopup' ? 'dialog' : '选择 ChatGPT 模型'}];
  assert.equal(read().buttons.length, 0);
  namedButtons = [{...namedButton, getAttribute: name => name === 'aria-disabled' ? 'true'
    : name === 'aria-haspopup' ? 'menu' : '选择 ChatGPT 模型'}];
  assert.equal(read().buttons.length, 0);
  namedButtons = [namedButton];
  form.contains = () => false;
  assert.equal(read().buttons.length, 0);
});

test('control snapshot counts retained modern rows before a new task is admitted', () => {
  const { controls } = require(operatorTestScript('web_browser_page.cjs'));
  let modernRows = [];
  const document = { title: 'ChatGPT', readyState: 'complete',
    hasFocus: () => false, activeElement: null,
    querySelectorAll: selector => selector === '[data-chatgpt-search-unit-key]' ? modernRows : [] };
  const read = () => vm.runInNewContext(`(${controls.toString()})()`, {
    document, uniqueComposer: () => null, eligibleModelButtons: () => [] });
  assert.equal(read().modernRowCount, 0);
  modernRows = [{}, {}];
  assert.equal(read().modernRowCount, 2);
});

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
  const document = {querySelectorAll:selector => selector.startsWith('[data-message-author-role') ? rows
    : selector === '[data-chatgpt-search-unit-key]' ? [] : cards};
  const read = () => vm.runInNewContext('('+inspectionSnapshot.toString()+')("selected")', {document});
  assert.equal(JSON.stringify(read()), JSON.stringify({notices:[alert.innerText]}));
  rows.push(row); assert.throws(read, /web_inspection_message_ambiguous/); rows.pop();
  cards = Array(17).fill(alert); assert.throws(read, /web_inspection_snapshot_bound/);
  cards = [element('a'.repeat(4097))]; assert.throws(read, /web_inspection_snapshot_bound/);
  rows = []; assert.throws(read, /web_inspection_message_ambiguous/);
});

test('inspection accepts the exact mounted modern result without reading reply text', () => {
  const { inspectionSnapshot, modernPublicItem } = require(operatorTestScript('web_browser_page.cjs'));
  const id = '22222222-2222-4222-8222-222222222222';
  const item = { messageId: id, type: 'assistant-message' };
  Object.defineProperty(item, 'content', { get() { throw Error('reply text must not be read'); } });
  const row = { getClientRects: () => [{}], closest: () => null,
    getAttribute: key => key === 'data-chatgpt-search-unit-key' ? 'fixture:1:assistant'
      : key === 'data-chatgpt-search-message-ids' ? id : null,
    querySelectorAll: () => [{ getAttribute: () => id }],
    __reactFiber$fixture: { memoizedProps: { item, entry: { turn: {} } }, return: null } };
  const alert = { innerText: 'visible notice', getClientRects: () => [{}], closest: () => null };
  let rows = [row];
  const document = { querySelectorAll: selector => selector === '[data-chatgpt-search-unit-key]'
    ? rows : selector === '[role="alert"],[data-testid="tool-approval-card"]' ? [alert] : [] };
  const read = expected => vm.runInNewContext(`(() => {
    const currentPublicFiber = fiber => fiber;
    const modernPublicItem = (${modernPublicItem.toString()});
    return (${inspectionSnapshot.toString()})(expected);
  })()`, { document, expected });
  assert.deepEqual(plain(read(id)), { notices: ['visible notice'] });
  assert.throws(() => read('another-message'), /web_inspection_message_ambiguous/);
  rows = [row, row]; assert.throws(() => read(id), /web_public_message_ambiguous/);
  rows = []; assert.throws(() => read(id), /web_inspection_message_ambiguous/);
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
    setTitle: value => { state.title = value; },
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
    composerPrefix: function () { return ''; }, connectorPillState,
    promptMismatchShape: function () { return null; },
    modernPublicItem: function () {}, modernPublicFinal: function () {},
    projectPublicReferences: require(operatorTestScript('web_browser_page.cjs')).projectPublicReferences,
    uniqueComposer, eligibleModelButtons, eligibleEffortContainer,
    publicFinal: function () {}, startFreshChat: function () {}, freshChatControlStructure: function () {},
    enableTemporaryChat: function () {},
    currentPublicFiber: require(operatorTestScript("web_browser_page.cjs")).currentPublicFiber,
    backgroundMenuKey: require(operatorTestScript("web_browser_page.cjs")).backgroundMenuKey,
    focusModelMenu: function () { return true; }, controls: function () {
    return { pageKind: 'chatgpt', composer: true, modelButtonCount: 1, loginVisible: false,
      userCount: 0, assistantCount: 0, modernRowCount: 0,
      documentFocused: false, modelControlInteractive: true, modelControlFocused: true,
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
        if (name === './operator_core/web_model_catalog.json') return require(operatorTestScript('operator_core/web_model_catalog.json'));
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
  assert.equal(host.state.title, 'Operator 网页模型辅助窗口');
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
  const invoke = () => vm.runInNewContext(`(${startFreshChat.toString()})()`, { uniqueComposer: () => composer, document: {
    querySelector: () => composer, querySelectorAll: selector => selector.includes('author-role="user"') ? users
      : selector.includes('author-role="assistant"') ? assistants : selector.includes('stop-button') ? stops
      : selector === '[data-chatgpt-search-unit-key]' || selector.startsWith('nav[') ? [] : choices } });
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
test('fresh chat accepts only the exact completed modern turn and unique sidebar button', () => {
  const { startFreshChat } = require(operatorTestScript('web_browser_page.cjs'));
  const actions = [], composer = { textContent: '' };
  const button = { textContent: '新聊天', disabled: false, getClientRects: () => [{}],
    getAttribute: key => key === 'type' ? 'button' : null, closest: () => null,
    click: () => actions.push('new-chat') };
  let rows = [{}, {}], buttons = [button], links = [], finalId = 'bound-id';
  const document = { querySelectorAll: selector => selector === '[data-chatgpt-search-unit-key]' ? rows
    : selector.startsWith('nav[') ? buttons
    : selector === 'a[data-testid="create-new-chat-button"]' ? links : [] };
  const invoke = (prompt = 'exact prompt', id = 'bound-id') => vm.runInNewContext(
    `(${startFreshChat.toString()})(prompt,id)`, { prompt, id, uniqueComposer: () => composer,
      modernPublicFinal: value => value === 'exact prompt' ? { id: finalId } : null, document });
  invoke();
  assert.deepEqual(actions, ['new-chat']);
  finalId = 'different-id';
  assert.throws(() => invoke(), /web_new_chat_idle_page_required/);
  assert.throws(() => invoke('wrong prompt'), /web_new_chat_idle_page_required/);
  finalId = 'bound-id'; buttons = [button, button];
  assert.throws(() => invoke(), /web_new_chat_control_ambiguous/);
  buttons = [button]; links = [{getClientRects: () => [{}]}];
  assert.throws(() => invoke(), /web_new_chat_control_ambiguous/);
  links = []; rows = [];
  assert.throws(() => invoke(), /web_new_chat_idle_page_required/);
  assert.deepEqual(actions, ['new-chat']);
});
test('fresh chat recognizes the visible text button in chat-history navigation', () => {
  const { startFreshChat } = require(operatorTestScript('web_browser_page.cjs'));
  const actions = [], composer = { textContent: '' };
  const button = (text, aria = null) => ({ textContent: text, disabled: false,
    getClientRects: () => [{}], getAttribute: key => key === 'type' ? 'button'
      : key === 'aria-label' ? aria : null, closest: () => null,
    click: () => actions.push(text || 'icon') });
  const textButton = button('新聊天'), iconButton = button('', '新聊天');
  const document = { querySelectorAll: selector => selector === '[data-chatgpt-search-unit-key]'
    ? [{}, {}] : selector.includes('nav[aria-label="聊天记录"]')
      ? [textButton, iconButton] : [] };
  vm.runInNewContext(`(${startFreshChat.toString()})('new prompt','bound-id')`, {
    uniqueComposer: () => composer,
    modernPublicFinal: () => ({ id: 'bound-id' }), document });
  assert.deepEqual(actions, ['新聊天']);
});
test('failed fresh chat diagnostic contains only fixed selector categories', () => {
  const { freshChatControlStructure } = require(operatorTestScript('web_browser_page.cjs'));
  const element = (text, attributes = {}) => ({textContent: text, disabled: false,
    getClientRects: () => [{}], getAttribute: key => attributes[key] ?? null,
    closest: () => null});
  const link = element('PRIVATE LINK', {href: '/c/private-conversation'});
  const button = element('New chat', {type: 'submit', href: '/c/private-target'});
  const privateButton = element('PRIVATE BUTTON');
  const document = {querySelectorAll: selector => selector.startsWith('a[') ? [link]
    : [button, privateButton]};
  const result = vm.runInNewContext(`(${freshChatControlStructure.toString()})()`, {document});
  assert.equal(JSON.stringify(result), JSON.stringify({legacyLinks: 'one', legacyRootHref: 'no',
    legacyLabel: 'no', legacyEnabled: 'yes', navButtons: 'multiple', namedButtons: 'one',
    buttonType: 'other', buttonDisabled: 'no', buttonAriaDisabled: 'no',
    buttonHref: 'present', buttonTarget: 'absent', buttonHiddenAncestor: 'no'}));
  assert.equal(JSON.stringify(result).includes('PRIVATE'), false);
  assert.equal(JSON.stringify(result).includes('/c/'), false);
});
test('empty fresh chat rejects retained modern messages and drafts', () => {
  const { emptyFreshChat } = require(operatorTestScript('web_browser_page.cjs'));
  let text = '', rows = [], stops = [];
  const invoke = () => vm.runInNewContext(`(${emptyFreshChat.toString()})()`, {
    uniqueComposer: () => ({ textContent: text }), document: { querySelectorAll: selector =>
      selector.includes('stop-button') ? stops : rows } });
  assert.equal(invoke(), true);
  rows = [{}]; assert.equal(invoke(), false);
  rows = []; text = 'draft'; assert.equal(invoke(), false);
  text = ''; stops = [{ getClientRects: () => [{}] }]; assert.equal(invoke(), false);
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
        if (fn === page.startFreshChat) {
          requireValue(args[0] === 'exact previous' && args[1] === 'previous',
            'web_binding_changed'); navigationCalls++; return;
        }
        if (fn === page.emptyFreshChat) return true;
        if (fn === page.enableTemporaryChat) { temporaryCalls++; surface.webContents.getURL = () => 'https://chatgpt.com/?temporary-chat=true'; return; }
        return { composer: true, userCount: 0, assistantCount: 0 };
      };`);
    return host;
  };
  const good = setup();
  await good.invoke('loadFreshPage()');
  assert.equal(good.invoke('navigationCalls === 1 && completedPage === null && !sent'), true);
  const settling = setup();
  settling.invoke(`let priorReads = 0, priorInPage = inPage;
    inPage = async (fn, ...args) => fn === page.publicFinal && priorReads++ === 0
      ? null : priorInPage(fn, ...args);`);
  await settling.invoke('loadFreshPage()');
  assert.equal(settling.invoke('priorReads === 2 && navigationCalls === 1'), true);
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
  unknown.invoke(`waitFor = async fn => {
    const value = await fn();
    if (!value) throw Error('web_page_state_timeout');
    return value;
  };`);
  await assert.rejects(unknown.invoke('loadFreshPage()'), /web_page_state_timeout/);
  assert.equal(unknown.invoke('navigationCalls === 1 && temporaryCalls === 0'), true);
});
test('worker waits for the new chat URL before trusting an empty modern row count', async () => {
  const host = hiddenHostFixture({ mode: 'worker', workerDirectory: require('node:path').resolve(__dirname), parentPid: 1 });
  host.state.origin = 'https://chatgpt.com/c/synthetic?temporary-chat=true';
  host.invoke(`let navigationCalls = 0, emptyReads = 0, urlChecks = 0, waitCalls = 0;
    completedPage = { prompt: 'bound prompt', message: { id: 'bound-id' } };
    inPage = async (fn, ...args) => {
      if (fn === page.publicFinal) return { id: 'bound-id' };
      if (fn === page.startFreshChat) {
        requireValue(args[0] === 'bound prompt' && args[1] === 'bound-id', 'web_binding_changed');
        navigationCalls++; return;
      }
      if (fn === page.emptyFreshChat) { emptyReads++; return true; }
      throw Error('unexpected page read');
    };
    waitFor = async fn => {
      if (waitCalls++ === 0) return await fn();
      urlChecks++;
      requireValue(await fn() === false, 'web_navigation_prematurely_accepted');
      surface.webContents.getURL = () => 'https://chatgpt.com/?temporary-chat=true';
      urlChecks++;
      const result = await fn();
      requireValue(result === true, 'web_navigation_not_accepted');
      return result;
    };`);
  await host.invoke('loadFreshPage()');
  assert.equal(host.invoke('navigationCalls === 1 && emptyReads === 1 && urlChecks === 2'), true);
});
test('ambiguous New chat control emits one bounded read before the worker stops', async () => {
  const host = hiddenHostFixture({mode: 'worker', workerDirectory: require('node:path').resolve(__dirname),
    parentPid: 1});
  host.invoke(`completedPage = { prompt: 'prior prompt', message: { id: 'prior-id' } };
    let readCount = 0, clickCount = 0;
    inPage = async fn => {
      if (fn === page.publicFinal) return { id: 'prior-id' };
      if (fn === page.startFreshChat) { clickCount++; throw Error('web_new_chat_control_ambiguous'); }
      if (fn === page.freshChatControlStructure) { readCount++; return {
        legacyLinks: 'zero', legacyRootHref: 'unknown', legacyLabel: 'unknown',
        legacyEnabled: 'unknown', navButtons: 'multiple', namedButtons: 'zero',
        buttonType: 'unknown', buttonDisabled: 'unknown', buttonAriaDisabled: 'unknown',
        buttonHref: 'unknown', buttonTarget: 'unknown', buttonHiddenAncestor: 'unknown' }; }
      throw Error('unexpected page operation');
    };`);
  await assert.rejects(host.invoke('loadFreshPage()'), /web_new_chat_control_ambiguous/);
  assert.equal(host.invoke('readCount === 1 && clickCount === 1 && !sent'), true);
  assert.equal(host.events.filter(e => e.kind === 'fresh_chat_control_structure').length, 1);
  assert.equal(host.events.some(e => e.kind === 'dispatch_started'), false);
});
test('temporary chat requires one enabled public control and an empty page', () => {
  const { enableTemporaryChat } = require(operatorTestScript("web_browser_page.cjs"));
  let clicks = 0, rows = [], draft = '';
  const button = { getClientRects: () => [{}], disabled: false,
    getAttribute: key => key === 'aria-label' ? '临时聊天' : null, click: () => clicks++ };
  let buttons = [button];
  const invoke = () => vm.runInNewContext(`(${enableTemporaryChat.toString()})()`, { uniqueComposer: () => ({textContent: draft}), document: {
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
    document: doc, point, uniqueComposer: () => ({}), eligibleModelButtons: () => [button],
    PointerEvent: class { constructor(type, options) { this.type = type; Object.assign(this, options); this.isTrusted = false; } } });
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
  const valid = { id: 'a'.repeat(32), text: '中文😀 a_b\r\n', model:'gpt-5.6-sol', effort:'high' };
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
    host.invoke(`validateWorkerRequest(${JSON.stringify({ id: 'c'.repeat(32), text: 'fixture', model:'gpt-5.6-sol', effort:'high',
      connectorMention: mention, autoSelectConnector: true })}, new Set())`);
    const f = connectorFixture({ name });
    assert.deepEqual(plain(vm.runInNewContext(`(() => {
      const connectorPillState = (${connectorPillState.toString()});
      return (${selectedConnector.toString()})(name);
    })()`, { document: f.document, name, uniqueComposer: () => f.composer })),
    { id: f.id, name, publicPrefix: '@' + name + ' ' });
    let clicks = 0;
    const query = '@' + name.split(' ')[0], composer = { textContent: query };
    const row = { textContent: name, getClientRects: () => [{}], getAttribute: () => null,
      closest: selector => selector === '[data-composer-plugin-impression-id]' ? { getAttribute: () => id.slice(7) } : null,
      click: () => clicks++ };
    const picked = vm.runInNewContext(`(${connectorMenuChoice.toString()})(name, query, true, id)`,
      { name, query, id, uniqueComposer: () => composer, document: { activeElement: composer, querySelector: () => composer,
        querySelectorAll: () => [row] } });
    assert.equal(picked.name, name);
    assert.equal(clicks, 1);
  }
  for (const name of ['连'.repeat(65), '固定\n', '固定\r', '固定\u2028', '固定\u2029',
      '固定\u200b连接', ' 固定', '固定<script>', '\ud800']) {
    const mention = { id, name };
    assert.deepEqual(hiddenHostFixture({ connectorMention: mention, autoSelectConnector: true }).exits, [1]);
    assert.throws(() => host.invoke(`validateWorkerRequest(${JSON.stringify({ id: 'c'.repeat(32),
      text: 'fixture', model:'gpt-5.6-sol', effort:'high', connectorMention: mention, autoSelectConnector: true })}, new Set())`), /web_connector_mention_invalid/);
    assert.throws(() => vm.runInNewContext(`(() => {
      const connectorPillState = (${connectorPillState.toString()});
      return (${selectedConnector.toString()})(name);
    })()`, { name }), /web_connector_name_invalid/);
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
    `(${publicInterruptionState.toString()})(name)`, { name, getComputedStyle: () => ({}), document: { querySelectorAll: selector => {
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

test('public interruptions exclude accessibility-only and CSS-hidden surfaces and ancestors', () => {
  const { publicInterruptionState } = require(operatorTestScript('web_browser_page.cjs'));
  const clear = { approvalCards: 0, connectorDialogs: 0, sessionExpired: false,
    subscriptionUnavailable: false, responseError: false };
  const element = (options = {}) => ({ innerText: 'Something went wrong. Your session has expired.',
    parentElement: options.parent || null, style: options.style || {}, hiddenSelector: options.hiddenSelector,
    // A tiny rectangle alone does not establish hiddenness.
    getClientRects: () => [{ width: 1, height: 1 }],
    closest(selector) {
      for (let node = this; node; node = node.parentElement)
        if (node.hiddenSelector && selector.split(',').includes(node.hiddenSelector)) return node;
      return null;
    },
    querySelectorAll: () => [] });
  const read = node => plain(vm.runInNewContext(`(${publicInterruptionState.toString()})()`, {
    getComputedStyle: element => {
      let visibility = 'visible';
      for (let node = element; node; node = node.parentElement) {
        if (node.style.visibility !== undefined) { visibility = node.style.visibility; break; }
      }
      return { ...element.style, visibility };
    },
    document: { querySelectorAll: () => [node] }
  }));
  for (const hiddenSelector of ['.sr-only', '.visually-hidden', '[data-testid="visually-hidden"]']) {
    assert.deepEqual(read(element({ hiddenSelector })), clear, hiddenSelector);
    assert.deepEqual(read(element({ parent: element({ hiddenSelector }) })), clear, hiddenSelector + ' ancestor');
  }
  for (const style of [{ display: 'none' }, { visibility: 'hidden' },
      { visibility: 'collapse' }, { contentVisibility: 'hidden' }]) {
    assert.deepEqual(read(element({ style })), clear, JSON.stringify(style));
    assert.deepEqual(read(element({ parent: element({ style }) })), clear, JSON.stringify(style) + ' ancestor');
  }
  const shown = { ...clear, approvalCards: 1, sessionExpired: true, responseError: true };
  assert.deepEqual(read(element()), shown);
  assert.deepEqual(read(element({ style: { visibility: 'visible' },
    parent: element({ style: { visibility: 'hidden' } }) })), shown);
  for (const style of [{ display: 'none' }, { contentVisibility: 'hidden' }]) {
    assert.deepEqual(read(element({ style: { display: 'block', visibility: 'visible', contentVisibility: 'visible' },
      parent: element({ style }) })), clear, 'visible child cannot override ' + JSON.stringify(style));
  }
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

test('current public branch follows the sole mounted child only after proving its parent is current', () => {
  const { currentPublicFiber } = require(operatorTestScript('web_browser_page.cjs'));
  const tree = currentTree({}, {});
  tree.parentA.child = null;
  tree.rootState.current = tree.rootB;
  assert.equal(currentPublicFiber(tree.a), tree.b);
  tree.rootState.current = tree.rootA;
  assert.throws(() => currentPublicFiber(tree.a), /web_public_current_branch_unavailable/);
  tree.parentA.child = tree.a;
  tree.parentB.child = null;
  assert.equal(currentPublicFiber(tree.b), tree.a);
  tree.rootState.current = tree.rootB;
  assert.throws(() => currentPublicFiber(tree.b), /web_public_current_branch_unavailable/);
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
  const { projectPublicReferences } = require(operatorTestScript('web_browser_page.cjs'));
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
  return vm.runInNewContext(`const projectPublicReferences = (${projectPublicReferences.toString()});
    (${publicFinal.toString()})(prompt, includeCitations)`,
    { document, prompt, TextEncoder, includeCitations: options.includeCitations === true });
}
function plain(value) { return value === null ? null : JSON.parse(JSON.stringify(value)); }

test('current message units bind exact source, terminal status and one public output string', () => {
  const page = require(operatorTestScript('web_browser_page.cjs'));
  const userId = '11111111-1111-4111-8111-111111111111';
  const answerId = '22222222-2222-4222-8222-222222222222';
  const request = '[$operator](app://asdk_app_' + 'a'.repeat(32) + ') synthetic probe';
  const user = { type: 'user-message', messageId: userId, message: request };
  const answer = { type: 'assistant-message', messageId: answerId,
    latestMessageId: answerId, sourceMessageIds: [answerId],
    completed: true, phase: 'final_answer', content: '  exact reply\n', contentReferences: [] };
  const turn = { status: 'complete', workCompletedAtMs: 12 };
  Object.defineProperty(turn, 'messageIds', { get() { throw Error('turn-wide messages must not be read'); } });
  const makeRow = (role, id, item) => ({ getClientRects: () => [{}], closest: () => null,
    getAttribute: key => key === 'data-chatgpt-search-unit-key' ? 'fallback-turn-0:'
      + (role === 'user' ? '0:user' : '2:assistant')
      : key === 'data-chatgpt-search-message-ids' ? role === 'user' ? id : id + ' ' + id : null,
    querySelectorAll: selector => role === 'user'
      ? selector === '[data-user-message-bubble="true"]' ? [{}] : []
      : selector === '[data-chatgpt-selection-message-id]'
        ? selectionReady ? [{ getAttribute: () => id }] : [] : [],
    __reactFiber$fixture: { memoizedProps: {}, return: { memoizedProps: { item },
      return: { memoizedProps: { entry: { turn } }, return: null } } } });
  const userRow = makeRow('user', userId, user), answerRow = makeRow('assistant', answerId, answer);
  let rows = [userRow, answerRow], stop = false, unstableAssistant = null,
    selectionReady = true;
  const document = { querySelector: selector => selector === '[data-testid="stop-button"]'
    ? stop ? {} : null : selector === '[data-chatgpt-search-unit-key]' ? rows[0] : null,
    querySelectorAll: selector => selector === '[data-chatgpt-search-unit-key]' ? rows
      : selector === '[data-message-author-role="user"]' ? [] : [] };
  const run = (citations = false) => vm.runInNewContext(`(() => {
    const currentPublicFiber = fiber => {
      if (unstableAssistant && fiber === answerRow.__reactFiber$fixture)
        throw Error(unstableAssistant);
      return fiber;
    };
    const modernPublicItem = (${page.modernPublicItem.toString()});
    const projectPublicReferences = (${page.projectPublicReferences.toString()});
    const modernPublicFinal = (${page.modernPublicFinal.toString()});
    return (${publicFinal.toString()})(request, citations, true);
  })()`, { document, request, citations, TextEncoder, answerRow, unstableAssistant });
  assert.deepEqual(plain(run()), { id: answerId, author: { role: 'assistant' },
    recipient: null, channel: 'final', end_turn: true, status: 'finished_successfully',
    metadata: { operator_web_renderer: 'modern_content_references_v1' },
    content: { content_type: 'text', parts: ['  exact reply\n'] } });
  assert.deepEqual(plain(run(true)).public_references, []);
  const answerEntry = answerRow.__reactFiber$fixture.return.return.memoizedProps.entry;
  answerEntry.turn = {...turn};
  turn.status = 'in_progress';
  assert.equal(run(), null); // A completed reply from another turn cannot finish this request.
  turn.status = 'complete';
  assert.equal(run(), null); // Matching terminal flags do not establish turn identity.
  answerEntry.turn = turn;
  selectionReady = false; assert.equal(run(), null); selectionReady = true;
  unstableAssistant = 'web_public_current_branch_unavailable';
  assert.equal(run(), null);
  unstableAssistant = 'web_public_tree_cycle';
  assert.throws(run, /web_public_tree_cycle/);
  unstableAssistant = null;
  stop = true; assert.equal(run(), null); stop = false;
  answer.completed = false; assert.equal(run(), null); answer.completed = true;
  turn.status = 'in_progress'; assert.equal(run(), null); turn.status = 'complete';
  answer.sourceMessageIds = [userId]; assert.equal(run(), null); answer.sourceMessageIds = [answerId];
  user.message += ' changed'; assert.throws(run, /web_user_turn_mismatch/);
  user.message = request;
  rows = [userRow, answerRow, answerRow];
  assert.throws(run, /web_public_message_ambiguous/);
  rows = [userRow, answerRow]; answer.contentReferences = [{ snippet: 'DO_NOT_EXPORT' }];
  assert.throws(() => run(true), /web_public_citation_field_invalid/);
  answer.contentReferences = [{ type: 'grouped_webpages', start_idx: 0, end_idx: 4,
    matched_text: 'text', items: [{ title: 'Source', url: 'https://example.test',
      snippet: 'DO_NOT_EXPORT' }], prompt_text: 'DO_NOT_EXPORT' },
  { type: 'sources_footnote', start_idx: answer.content.length,
    end_idx: answer.content.length + 1, matched_text: ' ',
    sources: [{ title: 'Another', url: 'https://example.test/other' }],
    prompt_text: 'DO_NOT_EXPORT' }];
  assert.deepEqual(plain(run(true)).public_references, [
    { type: 'grouped_webpages', start_idx: 0, end_idx: 4, matched_text: 'text',
      items: [{ title: 'Source', url: 'https://example.test' }] },
    { type: 'sources_footnote', start_idx: answer.content.length,
      end_idx: answer.content.length + 1, matched_text: ' ',
      sources: [{ title: 'Another', url: 'https://example.test/other' }] }]);
  assert.equal(JSON.stringify(run(true)).includes('DO_NOT_EXPORT'), false);
});

test('public app separator classification preserves the exact app link and complete body', () => {
  const { publicUserBindingShape } = require(operatorTestScript('web_browser_page.cjs'));
  const head = '[$operator](app://asdk_app_' + 'a'.repeat(32) + ')';
  const body = ' exact body\n\u00a0keep both spaces';
  const prompt = head + '\u00a0' + body;
  const read = source => plain(vm.runInNewContext(`(${publicUserBindingShape.toString()})(prompt, true)`, {
    document: { querySelectorAll: () => [], querySelector: () => ({}) }, prompt,
    modernPublicItem: () => ({ item: { message: source } }),
  }));
  assert.equal(read(prompt).exact, true);
  assert.equal(read(prompt).appSeparatorOnly, false);
  assert.equal(read(head + ' ' + body).appSeparatorOnly, true);
  for (const value of [head + '\t' + body, head + ' ' + body.trim(),
      head + ' ' + body.replace('\u00a0', ' '), head.replace('operator', 'other') + ' ' + body,
      head + '  ' + body, ' ' + head + ' ' + body]) {
    assert.equal(read(value).exact, false);
    assert.equal(read(value).appSeparatorOnly, false);
  }
});

test('current assistant identity diagnostic exposes only bounded public structure', () => {
  const { modernIdentityShape } = require(operatorTestScript('web_browser_page.cjs'));
  const first = '11111111-1111-4111-8111-111111111111';
  const last = '22222222-2222-4222-8222-222222222222';
  const row = { getAttribute: key => key === 'data-chatgpt-search-unit-key'
    ? 'fallback-turn-0:2:assistant' : key === 'data-chatgpt-search-message-ids'
      ? first + ' ' + last : null,
    getClientRects: () => [{}], closest: () => null,
    querySelectorAll: () => [{ getAttribute: () => last }] };
  const shape = plain(vm.runInNewContext(`(${modernIdentityShape.toString()})()`,
    { document: { querySelectorAll: () => [row] } }));
  assert.deepEqual(shape, { assistantRows: 1, rows: [{ keyPattern: true,
    visible: true, hidden: false, idsBounded: true, idsCount: 2,
    allIdsUuid: true, allIdsEqual: false, selectedCount: 1,
    selectedUuid: true, selectedFirst: false, selectedLast: true,
    selectedAny: true }] });
  assert.equal(JSON.stringify(shape).includes(first), false);
  assert.equal(JSON.stringify(shape).includes(last), false);
});

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
    { name, query, activate, id, uniqueComposer: () => composer, document: { activeElement: composer,
      querySelector: () => composer, querySelectorAll: selector => selector
        === '[data-composer-plugin-impression-id] .__menu-item[tabindex="0"]' ? rows : [] } });
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
  const button = (label, hidden = false, text = '', popup = null) => ({ getClientRects: () => [{}],
    closest: () => hidden ? {} : null, textContent: text,
    getAttribute: name => name === 'aria-label' ? label : name === 'aria-haspopup' ? popup : null,
    click: () => { throw Error('must not change account settings'); } });
  const state = rows => vm.runInNewContext(`(${connectorAccessState.toString()})()`, {
    document: { querySelectorAll: () => rows } });
  assert.equal(state([]), 'unknown');
  assert.equal(state([button('不个性化')]), 'disabled');
  assert.equal(state([button('个性化')]), 'enabled');
  assert.equal(state([button('个性化', true), button('不个性化')]), 'disabled');
  assert.equal(state([button('个性化'), button('不个性化')]), 'unknown');
  assert.equal(state([button(null, false, '个性化', 'menu')]), 'enabled');
  assert.equal(state([button(null, false, '不个性化', 'menu')]), 'disabled');
  assert.equal(state([button(null, false, '个性化', null)]), 'unknown');
  assert.equal(state([button(null, false, '个性化 设置', 'menu')]), 'unknown');
  assert.equal(state([button(null, true, '个性化', 'menu')]), 'unknown');
});

test('current app menu only provisionally selects a unique label and validates its pill before send', () => {
  const name = 'Operator 固定连接', id = 'plugin:asdk_app_' + 'a'.repeat(32);
  const composer = { textContent: '@Operator' };
  let clicks = 0, rows = [];
  const row = label => ({ getClientRects: () => [{}], getAttribute: () => null,
    closest: () => null, querySelectorAll: () => [{ textContent: label }],
    click: () => { clicks++; } });
  const document = { activeElement: composer, querySelectorAll: selector => selector
    === '[data-mention-list-scroll-area] button[data-list-navigation-item="true"]' ? rows : [] };
  const choose = activate => vm.runInNewContext(
    `(${connectorMenuChoice.toString()})(name, '@Operator', activate, id)`,
    { document, name, activate, id, uniqueComposer: () => composer });
  rows = [row(name)];
  assert.deepEqual(plain(choose(false)), { name, id: null, activated: false, identityPending: true });
  assert.equal(clicks, 0);
  assert.equal(choose(true).identityPending, true);
  assert.equal(clicks, 1);
  rows = [row(name), row(name)];
  assert.throws(() => choose(true), /web_connector_menu_ambiguous/);
  assert.equal(clicks, 1);

  const path = 'app://' + id.slice(7), label = '$operator';
  const attrs = { 'app-mention-path': path, 'data-prompt-link-href': path,
    'data-prompt-link-label': label, 'app-mention-name': 'operator',
    'app-mention-display-name': name, contenteditable: 'false' };
  const pill = { textContent: name, getAttribute: key => attrs[key] ?? null };
  const tail = { nodeType: 3, textContent: ' ' };
  const editor = { querySelectorAll: selector => selector === 'span[app-mention-path]' ? [pill]
    : selector === '[data-prompt-literal-paste]' ? paragraph.childNodes.filter(
      node => node.getAttribute?.('data-prompt-literal-paste') === '') : [],
    querySelector: selector => selector === '[data-prompt-literal-paste]'
      ? paragraph.childNodes.find(node => node.getAttribute?.('data-prompt-literal-paste') === '') || null : null,
    get textContent() { return paragraph.textContent; },
    get innerText() { return paragraph.textContent; },
    get childNodes() { return [paragraph]; } };
  const paragraph = { nodeType: 1, tagName: 'P', parentElement: editor, childNodes: [pill, tail],
    get textContent() { return this.childNodes.map(node => node.textContent).join(''); }, querySelectorAll: () => [] };
  pill.parentElement = paragraph;
  const invoke = (fn, args) => vm.runInNewContext(`(() => {
    const connectorPillState = (${connectorPillState.toString()});
    return (${fn.toString()})(...args);
  })()`, { args, document: { activeElement: editor }, uniqueComposer: () => editor });
  const picked = plain(invoke(selectedConnector, [name]));
  assert.deepEqual(picked, { id, name, publicPrefix: '[' + label + '](' + path + ')\u00a0' });
  assert.equal(invoke(composerPrefix, [picked]), name + ' ');
  const caret = [];
  const focusDocument = { activeElement: null, createRange: () => ({
    setStart: (node, offset) => caret.push(['start', node, offset]),
    setEnd: (node, offset) => caret.push(['end', node, offset]),
    selectNodeContents: () => caret.push(['container']),
    collapse: atStart => caret.push(['collapse', atStart]) }) };
  editor.focus = () => { focusDocument.activeElement = editor; };
  vm.runInNewContext(`(() => {
    const connectorPillState = (${connectorPillState.toString()});
    return (${focusComposer.toString()})(prefix);
  })()`, { prefix: name + ' ', document: focusDocument,
    window: { getSelection: () => ({ removeAllRanges() {}, addRange() {} }) },
    uniqueComposer: () => editor });
  assert.deepEqual(caret, [['start', tail, 1], ['collapse', true]]);
  caret.length = 0;
  vm.runInNewContext(`(() => {
    const connectorPillState = (${connectorPillState.toString()});
    return (${focusComposer.toString()})(prefix, true);
  })()`, { prefix: name + ' ', document: focusDocument,
    window: { getSelection: () => ({ removeAllRanges() {}, addRange() {} }) },
    uniqueComposer: () => editor });
  assert.deepEqual(caret, [['start', tail, 0], ['end', tail, 1]]);
  tail.textContent += 'synthetic probe';
  assert.equal(invoke(composerMatches, ['synthetic probe', name + ' ', picked]), true);
  tail.textContent = '\u00a0synthetic probe';
  assert.equal(invoke(composerMatches, ['synthetic probe', name + ' ', picked]), true);
  tail.textContent = '\u00a0\u00a0synthetic probe';
  assert.equal(invoke(composerMatches, ['synthetic probe', name + ' ', picked]), false);
  tail.textContent = ' ';
  const literal = { nodeType: 1, tagName: 'SPAN', attributes: [{}],
    getAttribute: key => key === 'data-prompt-literal-paste' ? '' : null,
    childNodes: [{nodeType: 3, textContent: 'first'},
      {nodeType: 1, tagName: 'BR', attributes: [], childNodes: []},
      {nodeType: 3, textContent: 'second'}], get textContent() { return 'firstsecond'; } };
  paragraph.childNodes.push(literal);
  assert.equal(invoke(composerMatches, ['first\nsecond', name + ' ', picked]), true);
  assert.equal(invoke(composerMatches, ['firstsecond', name + ' ', picked]), false);
  literal.childNodes.push({nodeType: 1, tagName: 'IMG', attributes: [], childNodes: []});
  assert.equal(invoke(composerMatches, ['first\nsecond', name + ' ', picked]), false);
  paragraph.childNodes.pop();
  tail.textContent += 'synthetic probe';
  attrs['app-mention-path'] = 'app://asdk_app_' + 'b'.repeat(32);
  attrs['data-prompt-link-href'] = attrs['app-mention-path'];
  assert.equal(invoke(composerMatches, ['synthetic probe', name + ' ', picked]), false);
  tail.textContent = ' '; attrs['app-mention-display-name'] = 'Another app';
  assert.throws(() => invoke(selectedConnector, [name]), /web_connector_mention_mismatch/);
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
      ? Array(options.pills ?? 1).fill(pill)
      : selector === '[data-inline-selection-pill-cursor-target]'
        ? Array(options.cursors ?? 1).fill(cursor) : [] };
  const document = { querySelectorAll: () => [composer], querySelector: () => composer, activeElement: composer };
  Object.defineProperty(composer, 'childNodes', { configurable: true,
    get: () => [{ nodeType: 1, tagName: 'P', textContent: composer.textContent, querySelectorAll: () => [] }] });
  return { name, id, document, composer, attrs };
}

test("selected app identity comes from one exact visible pill and stays bound before send", () => {
  const f = connectorFixture();
  const invoke = (fn, args) => vm.runInNewContext(`(() => {
    const connectorPillState = (${connectorPillState.toString()});
    return (${fn.toString()})(...args);
  })()`,
    { document: f.document, args, uniqueComposer: () => f.composer });
  const mention = plain(invoke(selectedConnector, [f.name]));
  assert.deepEqual(mention, { name: f.name, id: f.id, publicPrefix: '@' + f.name + ' ' });
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
  const invoke = () => vm.runInNewContext(`(() => {
    const connectorPillState = (${connectorPillState.toString()});
    return (${composerMatches.toString()})(text, prefix, mention);
  })()`,
    { document: f.document, text, prefix, mention, uniqueComposer: () => f.composer });
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

test("plain multiline prompt accepts exact editor paragraphs without normalizing input", () => {
  const text = '  first line\n\n中文😀 last line  ';
  const paragraph = value => ({ nodeType: 1, tagName: 'P', textContent: value,
    querySelectorAll: () => value === '' ? [{}] : [] });
  const composer = { innerText: '  first line\n\n\n中文😀 last line  ',
    childNodes: text.split('\n').map(paragraph),
    querySelectorAll: () => [] };
  const document = { querySelector: () => composer, activeElement: composer };
  const invoke = () => vm.runInNewContext(`(${composerMatches.toString()})(text)`,
    { document, text, uniqueComposer: () => composer });
  assert.equal(invoke(), true);
  composer.childNodes[1] = paragraph('unexpected');
  assert.equal(invoke(), false);
  composer.childNodes = text.split('\n').map(paragraph);
  composer.childNodes.push(paragraph(''));
  assert.equal(invoke(), false);
  composer.childNodes = text.split('\n').map(paragraph);
  composer.querySelectorAll = selector => selector === '[data-inline-selection-pill]' ? [{}] : [];
  assert.equal(invoke(), false);
});

test("selection waits only for an absent pill and rejects ambiguity or altered app metadata", () => {
  const invoke = options => {
    const f = connectorFixture(options);
    return vm.runInNewContext(`(() => {
      const connectorPillState = (${connectorPillState.toString()});
      return (${selectedConnector.toString()})(name);
    })()`,
      { document: f.document, name: f.name, uniqueComposer: () => f.composer });
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
  const focusControl = { focus: () => { document.activeElement = focusControl; }, getAttribute: () => 'effort-label' };
  const slider = element({ 'aria-valuemin': '0', 'aria-valuemax': '4', 'aria-valuenow': '2' });
  slider.closest = () => focusControl;
  const panel = { ...element({}), querySelectorAll: () => [slider], querySelector: selector => selector === '[role="slider"]' ? slider : null };
  const document = { title: 'ChatGPT', readyState: 'complete', activeElement: null,
    getElementById: () => ({textContent:'高，第 3 项，共 5 项。'}),
    hasFocus: () => false, querySelector: () => null, querySelectorAll: selector => {
      if (selector === '[role="menuitem"]') return [chooser];
      if (selector === '[role="menuitemradio"]') return [option];
      if (selector === '[role="menuitem"],[role="menuitemradio"]') return [chooser, option];
      if (selector === '[data-model-reasoning-effort-slider]') return [panel];
      return [];
    } };
  const invoke = name => vm.runInNewContext(`(${page[name].toString()})(["GPT-5.6 Sol"])`,
    { document, uniqueComposer: () => null, eligibleModelButtons: () => [],
      eligibleEffortContainer: () => hiddenAncestor ? null : panel });
  for (const attribute of ['[inert]', '[aria-hidden="true"]', '[hidden]', '[role="menu"][data-state="closed"]']) {
    hiddenAncestor = attribute;
    const state = invoke('controls');
    assert.equal(state.chooser, false);
    assert.equal(state.modelOption, false);
    assert.equal(state.modelChecked, null);
    assert.deepEqual(plain(state.modelMenuLabels), []);
    assert.equal(invoke('effortState'), null);
    assert.throws(() => invoke('clickModelChooser'), /web_model_chooser_ambiguous/);
    assert.throws(() => invoke('chooseModel'), /web_model_option_ambiguous/);
    assert.throws(() => invoke('focusEffort'), /web_effort_control_ambiguous/);
    assert.equal(clicks, 0);
    assert.equal(document.activeElement, null);
  }
  hiddenAncestor = null;
  assert.equal(invoke('controls').modelChecked, 'true');
  assert.deepEqual(plain(invoke('effortState')), { min: 0, max: 4, value: 2, label: '高', announcedGeneration: null,
    generationLabel: '5.6高', locked: false });
  invoke('clickModelChooser'); invoke('chooseModel'); invoke('focusEffort');
  assert.equal(clicks, 2);
  assert.equal(document.activeElement, focusControl);
});

test('effort control reads generation-prefixed public slider announcements', () => {
  const { effortState } = require(operatorTestScript('web_browser_page.cjs'));
  let described = '5.6 极高，第 4 项，共 5 项。', value = '3';
  const control = { getAttribute: name => name === 'aria-describedby' ? 'effort-help' : null };
  const slider = { getAttribute: name => ({ 'aria-valuemin':'0', 'aria-valuemax':'4', 'aria-valuenow':value })[name],
    closest: () => control };
  const panel = { getClientRects: () => [{}], closest: () => null,
    querySelectorAll: () => [slider], querySelector: () => null };
  const chooser = { getClientRects: () => [{}], closest: () => null,
    getAttribute: name => name === 'aria-label' ? '选择模型' : null,
    textContent: '5.6 SolPro' };
  const document = { getElementById: () => ({ textContent: described }),
    querySelectorAll: selector => selector === '[data-model-reasoning-effort-slider]' ? [panel]
      : selector === '[role="menuitem"]' ? [chooser] : [] };
  const read = () => plain(vm.runInNewContext(`(${effortState.toString()})()`,
    { document, eligibleEffortContainer: () => panel }));
  assert.deepEqual(read(), { min:0, max:4, value:3, label:'极高', announcedGeneration:'5.6',
    generationLabel:'5.6 SolPro', locked:false });
  described = '5.6 Pro，第 5 项，共 5 项。'; value = '4';
  assert.deepEqual(read(), { min:0, max:4, value:4, label:'Pro', announcedGeneration:'5.6',
    generationLabel:'5.6 SolPro', locked:false });
  described = '6 Pro，第 5 项，共 5 项。';
  assert.equal(read().announcedGeneration, '6');
  described = 'unexpected page text';
  assert.equal(read().label, null);
});

test('new effort container fallback stays inside the unique active model menu', () => {
  const page = require(operatorTestScript('web_browser_page.cjs'));
  const menu = {}, otherMenu = {};
  const document = {activeElement: null, getElementById: () => ({textContent: '中，第 2 项，共 5 项。'}),
    querySelectorAll: selector => selector === '[data-model-reasoning-effort-slider]' ? oldContainers
      : selector === '[data-model-picker-power-slider]' ? newContainers
        : selector === '[role="menuitem"]' ? choosers : []};
  let parentHidden = false, menuitemHidden = false;
  const menuitem = {getClientRects: () => [{}],
    closest: selector => menuitemHidden && selector.includes('[aria-hidden="true"]') ? menuitem : null,
    getAttribute: name => name === 'aria-describedby' ? 'effort-help' : null,
    focus: () => {document.activeElement = menuitem;}};
  const slider = {getClientRects: () => [{}],
    parentElement: {closest: selector => parentHidden && selector === '[aria-hidden="true"]' ? {} : null},
    getAttribute: name => ({'aria-valuemin': '0', 'aria-valuemax': '4', 'aria-valuenow': '1'})[name] ?? null,
    closest: selector => selector === '[role="menuitem"]' ? menuitem
      : selector === '[role="menu"]' ? menu
        : selector.includes('[aria-hidden="true"]') ? slider : null};
  const chooser = {textContent: '最新', getClientRects: () => [{}],
    getAttribute: name => name === 'aria-label' ? '选择模型' : null,
    closest: selector => selector === '[role="menu"]' ? menu : null};
  let sliders = [slider], oldContainers = [], newContainers = [], choosers = [chooser];
  const panel = {getClientRects: () => [{}], closest: () => null,
    querySelectorAll: () => sliders, querySelector: selector => selector === '[role="slider"]' ? slider : null};
  newContainers = [panel];
  const run = source => vm.runInNewContext(`(() => {
    const eligibleEffortContainer = (${page.eligibleEffortContainer.toString()});
    return ${source};
  })()`, {document});
  assert.equal(run('eligibleEffortContainer()'), panel);
  // The observed slider span is aria-hidden itself; its visible menuitem is the
  // keyboard target. A hidden ancestor or menuitem must still be rejected.
  parentHidden = true;
  assert.equal(run('eligibleEffortContainer()'), null);
  parentHidden = false; menuitemHidden = true;
  assert.equal(run('eligibleEffortContainer()'), null);
  menuitemHidden = false;
  assert.deepEqual(plain(run(`(${page.effortState.toString()})()`)),
    {min: 0, max: 4, value: 1, label: '中', announcedGeneration: null,
      generationLabel: '最新', locked: false});
  run(`(${page.focusEffort.toString()})()`);
  assert.equal(document.activeElement, menuitem);
  oldContainers = [panel]; newContainers = [panel, panel];
  assert.equal(run('eligibleEffortContainer()'), panel); // Preserve the legacy path.
  oldContainers = [{...panel, getClientRects: () => []}]; newContainers = [panel];
  assert.equal(run('eligibleEffortContainer()'), null); // No fallback from an unusable old path.
  oldContainers = []; newContainers = [panel, panel];
  assert.equal(run('eligibleEffortContainer()'), null);
  newContainers = [panel]; sliders = [slider, slider];
  assert.equal(run('eligibleEffortContainer()'), null);
  sliders = [slider]; choosers = [{...chooser, closest: selector => selector === '[role="menu"]' ? otherMenu : null}];
  assert.equal(run('eligibleEffortContainer()'), null);
  choosers = [chooser, chooser];
  assert.equal(run('eligibleEffortContainer()'), null);
});

test('failed effort range probe exposes only bounded slider shape', () => {
  const {effortRangeShape} = require(operatorTestScript('web_browser_page.cjs'));
  const attrs = {'aria-valuemin': '0', 'aria-valuemax': '4', 'aria-valuenow': '4'};
  const menu = {}, menuitem = {};
  let sliderHidden = false;
  const slider = {getClientRects: () => [{}], getAttribute: name => attrs[name] ?? null,
    closest: selector => selector === '[role="menuitem"]' ? menuitem
      : selector === '[role="menu"]' ? menu
        : selector === '[data-model-picker-power-slider]' ? panel
          : sliderHidden && selector.includes('[aria-hidden="true"]') ? {} : null};
  const chooser = {getClientRects: () => [{}], getAttribute: name => name === 'aria-label' ? '选择模型' : null,
    closest: selector => selector === '[role="menu"]' ? menu : null};
  let sliders = [slider], containers = [], newContainers = [], globalSliders = [];
  const panel = {getClientRects: () => [{}], closest: () => null,
    querySelectorAll: () => sliders, querySelector: () => null};
  const document = {querySelectorAll: selector => selector === '[data-model-reasoning-effort-slider]'
    ? containers : selector === '[data-model-picker-power-slider]' ? newContainers
      : selector === '[role="slider"]' ? globalSliders
        : selector === '[role="menuitem"]' ? [chooser] : []};
  const read = () => plain(vm.runInNewContext(`(${effortRangeShape.toString()})()`, {document}));
  assert.deepEqual(read(), {containerCount: 'zero', newContainerTotal: 'zero',
    newContainerVisible: 'zero', sliderCount: 'unknown', min: 'unknown', max: 'unknown',
    now: 'unknown', locked: 'unknown', globalSliderTotal: 'zero', globalSliderVisible: 'zero',
    globalMin: 'unknown', globalMax: 'unknown', globalNow: 'unknown',
    globalSliderRect: 'unknown', globalSliderHidden: 'unknown', globalSliderInert: 'unknown',
    globalSliderAriaHidden: 'unknown', globalSliderClosedMenu: 'unknown',
    globalSliderInNewContainer: 'unknown',
    ownerMenuitem: 'unknown', ownerMenu: 'unknown', sameMenuAsChooser: 'unknown'});
  newContainers = [panel]; globalSliders = [slider];
  assert.equal(read().newContainerVisible, 'one');
  assert.equal(read().globalSliderVisible, 'one');
  assert.equal(read().globalMax, 4);
  assert.equal(read().globalSliderInNewContainer, 'yes');
  assert.equal(read().sameMenuAsChooser, 'yes');
  sliderHidden = true;
  assert.equal(read().globalSliderVisible, 'zero');
  assert.equal(read().globalSliderRect, 'yes');
  assert.equal(read().globalSliderAriaHidden, 'yes');
  assert.equal(read().globalSliderInNewContainer, 'yes');
  sliderHidden = false;
  containers = [panel];
  assert.equal(read().sliderCount, 'one');
  assert.equal(read().max, 4);
  attrs['aria-valuemax'] = '5';
  panel.querySelector = () => ({});
  assert.equal(read().max, 5);
  assert.equal(read().globalMax, 5);
  assert.equal(read().locked, 'yes');
  attrs['aria-valuemax'] = 'PRIVATE PAGE TEXT';
  assert.equal(read().max, 'other');
  assert.equal(read().globalMax, 'other');
  sliders = [slider, slider];
  assert.equal(read().sliderCount, 'multiple');
  assert.equal(read().max, 'unknown');
  containers = [panel, panel];
  assert.equal(read().containerCount, 'multiple');
  globalSliders = [slider, slider];
  assert.equal(read().globalSliderVisible, 'multiple');
  assert.equal(read().sameMenuAsChooser, 'unknown');
  assert.equal(JSON.stringify(read()).includes('PRIVATE PAGE TEXT'), false);
});

test('failed effort range host classification never retains generation header text', () => {
  const host = hiddenHostFixture();
  const diagnostic = host.invoke(`boundedEffortRange({label: 'Pro', announcedGeneration: '6',
    generationLabel: 'PRIVATE PAGE TEXT 6 Pro'}, {containerCount: 'one', sliderCount: 'one',
    newContainerTotal: 'one', newContainerVisible: 'one',
    min: 0, max: 5, now: 4, locked: 'yes', globalSliderTotal: 'one',
    globalSliderVisible: 'one', globalMin: 0, globalMax: 5, globalNow: 4,
    globalSliderRect: 'yes', globalSliderHidden: 'no', globalSliderInert: 'no',
    globalSliderAriaHidden: 'no', globalSliderClosedMenu: 'no',
    globalSliderInNewContainer: 'yes',
    ownerMenuitem: 'yes', ownerMenu: 'yes', sameMenuAsChooser: 'yes'}, '6')`);
  assert.equal(diagnostic.generationMatches, 'yes');
  assert.equal(diagnostic.proLabel, 'yes');
  assert.equal(diagnostic.proHeader, 'yes');
  assert.equal(diagnostic.max, 5);
  assert.equal(diagnostic.globalMax, 5);
  assert.equal(diagnostic.globalSliderInNewContainer, 'yes');
  assert.equal(diagnostic.sameMenuAsChooser, 'yes');
  assert.equal(JSON.stringify(diagnostic).includes('PRIVATE PAGE TEXT'), false);
});

test('effort range failure records fixed shape before dispatch without changing rejection', async () => {
  const host = hiddenHostFixture({model: 'gpt-6-pro', effort: 'max'});
  host.invoke(`let menuClosed = false;
    menu = async () => {};
    key = async () => { menuClosed = true; };
    waitFor = async fn => { const value = await fn(); if (!value) throw Error('unexpected wait'); return value; };
    page.effortState = function effortState() {};
    page.effortRangeShape = function effortRangeShape() {};
    inPage = async fn => fn === page.controls
      ? {modelOption: !menuClosed, chooser: true, modelChecked: 'true'}
      : fn === page.effortState
        ? {min: 0, max: 5, value: 4, locked: true, label: 'Pro',
          announcedGeneration: '6', generationLabel: 'PRIVATE PAGE TEXT 6 Pro'}
        : fn === page.effortRangeShape
          ? {containerCount: 'one', newContainerTotal: 'one', newContainerVisible: 'one',
            sliderCount: 'one', min: 0, max: 5, now: 4, locked: 'yes',
            globalSliderTotal: 'one', globalSliderVisible: 'one',
            globalMin: 0, globalMax: 5, globalNow: 4,
            globalSliderRect: 'yes', globalSliderHidden: 'no', globalSliderInert: 'no',
            globalSliderAriaHidden: 'no', globalSliderClosedMenu: 'no',
            globalSliderInNewContainer: 'yes',
            ownerMenuitem: 'yes', ownerMenu: 'yes', sameMenuAsChooser: 'yes'}
          : null;`);
  await assert.rejects(host.invoke('selectModel()'), /web_effort_range_invalid/);
  const result = host.events.find(event => event.kind === 'effort_range_unavailable');
  assert.equal(result.stage, 'select_effort');
  assert.equal(result.max, 5);
  assert.equal(result.proLabel, 'yes');
  assert.equal(JSON.stringify(result).includes('PRIVATE PAGE TEXT'), false);
  assert.equal(host.events.some(event => event.kind === 'dispatch_started'), false);
});

test('effort shape exception retains its original rejection and bounded geometry', async () => {
  const host = hiddenHostFixture({model: 'gpt-6-pro', effort: 'max'});
  host.invoke(`let menuClosed = false;
    menu = async () => {};
    key = async () => { menuClosed = true; };
    waitFor = async fn => { const value = await fn(); if (!value) throw Error('unexpected wait'); return value; };
    page.effortState = function effortState() {};
    page.effortRangeShape = function effortRangeShape() {};
    inPage = async fn => fn === page.controls
      ? {modelOption: !menuClosed, chooser: true, modelChecked: 'true'}
      : fn === page.effortState ? (() => { throw Error('web_effort_shape_invalid'); })()
        : fn === page.effortRangeShape
          ? {containerCount: 'zero', newContainerTotal: 'one', newContainerVisible: 'one',
            sliderCount: 'unknown', min: 'unknown', max: 'unknown', now: 'unknown',
            locked: 'unknown', globalSliderTotal: 'one', globalSliderVisible: 'one',
            globalMin: 0, globalMax: 5, globalNow: 4,
            globalSliderRect: 'yes', globalSliderHidden: 'no', globalSliderInert: 'no',
            globalSliderAriaHidden: 'no', globalSliderClosedMenu: 'no',
            globalSliderInNewContainer: 'yes',
            ownerMenuitem: 'yes', ownerMenu: 'yes', sameMenuAsChooser: 'yes'}
          : null;`);
  await assert.rejects(host.invoke('selectModel()'), /web_effort_shape_invalid/);
  const record = host.events.find(event => event.kind === 'effort_range_unavailable');
  assert.equal(record.globalMax, 5);
  assert.equal(record.statePresent, 'no');
  assert.equal(host.events.some(event => event.kind === 'dispatch_started'), false);
});

test("menu input requires the unique enabled model control to own focus", () => {
  let rows, focused = 0;
  const document = { activeElement: null,
    querySelector: () => ({ closest: () => ({ querySelectorAll: () => rows }) }) };
  const button = { getClientRects: () => [{}], getAttribute: () => "false",
    focus: () => { focused++; document.activeElement = button; } };
  const invoke = () => vm.runInNewContext(`(${focusModelMenu.toString()})()`,
    { document, uniqueComposer: () => ({}), eligibleModelButtons: () => rows });
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

function pickerFixture(model, effort, generation) {
  const fixture = hiddenHostFixture({model, effort});
  fixture.invoke(`
    const picker = { panel: 'none', value: 1, generation: ${JSON.stringify(generation)}, announcedGeneration: ${JSON.stringify(generation)}, badLabel: false,
      staleProHeaderReads: 0, proHeader: null };
    page.chooseModel = function chooseModel() {};
    page.clickModelChooser = function clickModelChooser() {};
    page.effortState = function effortState() {};
    page.focusEffort = function focusEffort() {};
    menu = async () => { picker.panel = 'effort'; };
    key = async direction => {
      if (direction === 'Escape') picker.panel = 'none';
      else picker.value += direction === 'Right' ? 1 : -1;
    };
    waitFor = async check => { const found = await check(); if (!found) throw Error('fixture missing state'); return found; };
    inPage = async fn => {
      if (fn === page.controls) return {chooser: picker.panel === 'effort',
        modelOption: picker.panel === 'versions', modelChecked: 'true'};
      if (fn === page.clickModelChooser) { picker.panel = 'versions'; return; }
      if (fn === page.chooseModel) { picker.panel = 'effort'; return; }
      if (fn === page.focusEffort) return;
      if (fn === page.effortState) {
        const generationLabel = picker.value===4 && picker.staleProHeaderReads-- > 0
          ? picker.generation+'极高' : picker.proHeader || picker.generation+'Pro';
        return {min:0,max:4,value:picker.value,locked:false,
           generationLabel, announcedGeneration: picker.announcedGeneration,
          label:picker.badLabel && picker.value===2 ? 'Medium' : ['即时','中','高','极高','Pro'][picker.value]};
      }
      throw Error('unexpected fixture operation');
    };
  `);
  return fixture;
}

test('public picker verifies every generation and effort before returning selection', async () => {
  const catalog = require(operatorTestScript('operator_core/web_model_catalog.json'));
  let count = 0;
  for (const [model, definition] of Object.entries(catalog.models)) {
    for (const effort of definition.reasoning_efforts) {
      const fixture = pickerFixture(model, effort, definition.generation);
      await fixture.invoke('selectModel()');
      const verified = fixture.events.find(event => event.kind === 'model_verified');
      assert.equal(verified.model, model);
      assert.equal(verified.effortIndex, catalog.efforts[effort].index);
      assert.equal(verified.generation, definition.generation);
      assert.equal(fixture.events.some(event => event.kind === 'dispatch_started'), false);
      count++;
    }
  }
  assert.equal(count, 6);
});

test('public picker waits for the Pro header after the slider moves', async () => {
  const fixture = pickerFixture('gpt-5.6-sol', 'high', '5.6');
  fixture.invoke('picker.staleProHeaderReads = 1');
  await fixture.invoke('selectModel()');
  assert.equal(fixture.events.find(event => event.kind === 'model_verified')?.generation, '5.6');
  assert.equal(fixture.events.some(event => event.kind === 'dispatch_started'), false);
});

test('public picker accepts the observed 5.6 Sol Pro header but not another generation', async () => {
  const selected = pickerFixture('gpt-5.6-sol', 'high', '5.6');
  selected.invoke("picker.proHeader = '5.6 Sol Pro'");
  await selected.invoke('selectModel()');
  assert.equal(selected.events.find(event => event.kind === 'model_verified')?.generation, '5.6');
  const changed = pickerFixture('gpt-5.6-sol', 'high', '5.6');
  changed.invoke("picker.proHeader = '6 Sol Pro'");
  await assert.rejects(changed.invoke('selectModel()'), /web_model_generation_mismatch/);
  assert.equal(changed.invoke('verifiedSelection'), null);
  const inconsistent = pickerFixture('gpt-5.6-sol', 'high', '5.6');
  inconsistent.invoke("picker.announcedGeneration = '6'");
  await assert.rejects(inconsistent.invoke('selectModel()'), /web_model_generation_mismatch/);
  assert.equal(inconsistent.invoke('verifiedSelection'), null);
});

test('Latest accepts a bare Pro heading only when the visible slider announces 6', async () => {
  const selected = pickerFixture('gpt-6-pro', 'max', '6');
  selected.invoke("picker.proHeader = 'Pro'");
  await selected.invoke('selectModel()');
  assert.equal(selected.events.find(event => event.kind === 'model_verified')?.generation, '6');
  const missing = pickerFixture('gpt-6-pro', 'max', '6');
  missing.invoke("picker.proHeader = 'Pro'; picker.announcedGeneration = null");
  await assert.rejects(missing.invoke('selectModel()'), /web_model_generation_mismatch/);
  assert.equal(missing.invoke('verifiedSelection'), null);
  const changed = pickerFixture('gpt-6-pro', 'max', '6');
  changed.invoke("picker.proHeader = 'Pro'; picker.announcedGeneration = '5.6'");
  await assert.rejects(changed.invoke('selectModel()'), /web_model_generation_mismatch/);
  assert.equal(changed.invoke('verifiedSelection'), null);
});

test('Latest generation drift and a mismatched visible effort label stop before sending', async () => {
  const drift = pickerFixture('gpt-6-pro', 'max', '7');
  await assert.rejects(drift.invoke('selectModel()'), /web_model_generation_mismatch/);
  assert.equal(drift.invoke('verifiedSelection'), null);
  const wrong = pickerFixture('gpt-5.6-sol', 'high', '5.6');
  wrong.invoke('picker.badLabel = true');
  await assert.rejects(wrong.invoke('selectModel()'), /web_effort_label_mismatch/);
  assert.equal(wrong.invoke('verifiedSelection'), null);
});

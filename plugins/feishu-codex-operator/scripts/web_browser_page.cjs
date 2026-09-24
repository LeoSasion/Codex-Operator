"use strict";

// These fixed page operations accept data only. No caller-supplied JavaScript,
// authentication material, private reasoning or general DOM dump crosses out.
function controls(modelLabels = ["GPT-5.6 Sol"]) {
  const visible = e => !!e && e.getClientRects().length > 0;
  // The picker retains both panels and closing animations with layout boxes.
  // Inert/hidden panels are not usable controls, even when their bounds remain.
  const menuVisible = e => visible(e)
    && !e.closest('[hidden],[inert],[aria-hidden="true"],[role="menu"][data-state="closed"]');
  const composer = document.querySelector('#prompt-textarea[contenteditable="true"]');
  const form = composer?.closest("form");
  const modelButtons = [...(form?.querySelectorAll('button[aria-haspopup="menu"][data-tone="neutral"],button[data-testid="model-switcher-dropdown-button"]') || [])].filter(visible);
  const chooser = [...document.querySelectorAll('[role="menuitem"]')].filter(e => menuVisible(e) && ["选择模型", "Choose model"].includes(e.getAttribute("aria-label")));
  const options = [...document.querySelectorAll('[role="menuitemradio"]')].filter(e => menuVisible(e) && modelLabels.includes(e.textContent.trim()));
  const send = form?.querySelector('[data-testid="send-button"]');
  const modelControl = modelButtons.length === 1 ? modelButtons[0] : null;
  const modelPropsKey = modelControl && Object.keys(modelControl).find(k => k.startsWith("__reactProps$"));
  const modelProps = modelPropsKey ? modelControl[modelPropsKey] : null;
  const modelRect = modelControl?.getBoundingClientRect();
  return { composer: visible(composer), modelButtonCount: modelButtons.length,
    composerShape: composer ? [composer, ...composer.querySelectorAll('*')].slice(0, 16).map(e => ({
      tag: e.tagName, editable: e.getAttribute('contenteditable'), textLength: (e.textContent || '').length,
      data: [...e.attributes].filter(a => a.name.startsWith('data-') && a.name !== 'data-placeholder')
        .slice(0, 8).map(a => [a.name, a.value.slice(0, 160)]),
      chipText: e.getAttribute('contenteditable') === 'false' ? (e.textContent || '').slice(0, 64) : null })) : [],
    composerCandidates: [...document.querySelectorAll('#prompt-textarea,[data-testid="prompt-textarea"]')].slice(0, 4)
      .map(e => ({ tag: e.tagName, editable: e.getAttribute("contenteditable"), visible: visible(e) })),
    readyState: document.readyState, documentFocused: document.hasFocus(),
    modelControlFocused: modelButtons.length === 1 && document.activeElement === modelButtons[0],
    modelControlInteractive: !!modelProps && ["onClick", "onPointerDown", "onKeyDown"].some(k => typeof modelProps[k] === "function"),
    modelControlHandlers: modelProps ? ["onClick", "onPointerDown", "onKeyDown"].filter(k => typeof modelProps[k] === "function") : [],
    modelControlPoint: modelRect && modelRect.width > 0 && modelRect.height > 0
      ? { x: Math.round(modelRect.x + modelRect.width / 2), y: Math.round(modelRect.y + modelRect.height / 2) } : null,
    pageKind: document.title === "ChatGPT" ? "chatgpt" : /just a moment|请稍候/i.test(document.title) ? "challenge" : "other",
    loginVisible: [...document.querySelectorAll('button,a')].some(e => visible(e) && /^(登录|Log in|Sign in)$/.test(e.textContent.trim())),
    formControls: [...(form?.querySelectorAll("button") || [])].filter(visible).slice(0, 20)
      .map(e => ({ text: e.textContent.trim().slice(0, 100), testId: e.getAttribute("data-testid"),
        menu: e.getAttribute("aria-haspopup"), tone: e.getAttribute("data-tone") })),
    modelMenuLabels: [...document.querySelectorAll('[role="menuitem"],[role="menuitemradio"]')].filter(menuVisible).slice(0, 20)
      .map(e => ({ label: e.getAttribute("aria-label"), text: e.textContent.trim().slice(0, 100) })),
    modelButtonLabels: modelButtons.map(e => (e.textContent || "").slice(0, 100)),
    chooser: chooser.length === 1, modelOption: options.length === 1,
    modelChecked: options.length === 1 ? options[0].getAttribute("aria-checked") : null,
    userCount: document.querySelectorAll('[data-message-author-role="user"]').length,
    assistantCount: document.querySelectorAll('[data-message-author-role="assistant"]').length,
    sendReady: visible(send) && !send.disabled && send.getAttribute("aria-disabled") !== "true" };
}
function freshChatControls() {
  const visible = e => !!e && e.getClientRects().length > 0;
  // Only the fixed public home controls, never sidebar conversation links.
  const links = [...document.querySelectorAll('a[href="/"],a[href="/?temporary-chat=true"]')]
    .filter(visible).slice(0, 8).map(e => ({ href: e.getAttribute('href'),
      label: (e.getAttribute('aria-label') || '').slice(0, 80),
      text: (e.textContent || '').slice(0, 80), testId: e.getAttribute('data-testid') }));
  const temporary = [...document.querySelectorAll('button')].filter(e => visible(e)
    && /临时聊天|临时对话|Temporary chat/i.test(e.getAttribute('aria-label') || e.textContent?.trim() || ''))
    .slice(0, 4).map(e => ({ label: e.getAttribute('aria-label'), testId: e.getAttribute('data-testid'),
      pressed: e.getAttribute('aria-pressed'), state: e.getAttribute('data-state') }));
  return { links, temporary };
}
function pluginMaintenanceReady() {
  // Closing a read-only plugin page may return to a fresh empty chat. Never
  // navigate away from an edit, permission dialog, login, or pending refresh.
  const visible = e => !!e && e.getClientRects().length > 0
    && !e.closest('[hidden],[inert],[aria-hidden="true"]');
  if (document.readyState !== 'complete' || !/^ChatGPT(?: - .+)?$/.test(document.title)) return false;
  if ([...document.querySelectorAll('[data-message-author-role],[data-testid="stop-button"],[aria-busy="true"]')].some(visible)) return false;
  if ([...document.querySelectorAll('button,a')].some(e => visible(e)
    && (/^(登录|Log in|Sign in)$/.test(e.textContent.trim())
      || /^(刷新|Refresh)$/.test(e.textContent.trim()) && (e.disabled || e.getAttribute('aria-disabled') === 'true')))) return false;
  if ([...document.querySelectorAll('input,textarea,[contenteditable="true"],[role="checkbox"],[role="radio"],[role="switch"]')]
    .some(e => visible(e) && !(e.tagName === 'INPUT' && e.value === ''
      && /^(搜索设置|搜索插件|Search settings|Search plugins)$/.test(e.getAttribute('placeholder') || '')))) return false;
  const dialogs = [...document.querySelectorAll('[role="dialog"],[role="alertdialog"]')].filter(visible);
  if (dialogs.length > 1 || dialogs.some(e => e.getAttribute('role') !== 'dialog'
    || !/^(设置|Settings)$/.test(e.getAttribute('aria-label')
      || document.getElementById(e.getAttribute('aria-labelledby'))?.textContent?.trim() || ''))) return false;
  return true;
}
function startFreshChat() {
  const composer = document.querySelector('#prompt-textarea[contenteditable="true"]');
  if (!composer || composer.textContent !== ''
      || document.querySelectorAll('[data-message-author-role="user"]').length !== 1
      || document.querySelectorAll('[data-message-author-role="assistant"]').length !== 1
      || [...document.querySelectorAll('[data-testid="stop-button"]')].some(e => e.getClientRects().length))
    throw new Error('web_new_chat_idle_page_required');
  const choices = [...document.querySelectorAll('a[data-testid="create-new-chat-button"]')]
    .filter(e => e.getClientRects().length);
  // The observed toolbar and sidebar expose two equivalent home links.
  // Both must keep the same fixed destination and dated public label.
  if (choices.length < 1 || choices.length > 2 || choices.some(e => e.getAttribute('href') !== '/'
      || e.getAttribute('aria-disabled') === 'true' || e.getAttribute('target')
      || !/^(新聊天|New chat)(CtrlShiftO)?$/.test((e.textContent || '').trim())))
    throw new Error('web_new_chat_control_ambiguous');
  choices[0].click();
}
function enableTemporaryChat() {
  const composer = document.querySelector('#prompt-textarea[contenteditable="true"]');
  if (!composer || composer.textContent !== ''
      || document.querySelectorAll('[data-message-author-role="user"],[data-message-author-role="assistant"]').length !== 0)
    throw new Error('web_empty_composer_required');
  const choices = [...document.querySelectorAll('button')].filter(e => e.getClientRects().length
    && /^(临时聊天|Temporary chat)$/.test(e.getAttribute('aria-label') || ''));
  if (choices.length !== 1 || choices[0].disabled || choices[0].getAttribute('aria-disabled') === 'true')
    throw new Error('web_temporary_chat_control_ambiguous');
  choices[0].click();
}
function focusModelMenu() {
  const form = document.querySelector('#prompt-textarea[contenteditable="true"]')?.closest("form");
  const found = [...(form?.querySelectorAll('button[aria-haspopup="menu"][data-tone="neutral"],button[data-testid="model-switcher-dropdown-button"]') || [])].filter(e => e.getClientRects().length);
  if (found.length !== 1) throw new Error("web_model_control_ambiguous");
  const button = found[0];
  if (button.getAttribute("aria-expanded") === "true") return false;
  if (button.disabled || button.getAttribute("aria-disabled") === "true")
    throw new Error("web_model_control_disabled");
  button.focus();
  if (document.activeElement !== button) throw new Error("web_model_focus_failed");
  return true;
}
function backgroundModelInput(point) {
  const form = document.querySelector('#prompt-textarea[contenteditable="true"]')?.closest("form");
  const found = [...(form?.querySelectorAll('button[aria-haspopup="menu"][data-tone="neutral"],button[data-testid="model-switcher-dropdown-button"]') || [])].filter(e => e.getClientRects().length);
  if (found.length !== 1 || document.activeElement !== found[0]) throw new Error("web_model_control_ambiguous");
  const button = found[0], rect = button.getBoundingClientRect();
  if (button.disabled || button.getAttribute("aria-disabled") === "true"
      || !point || point.x !== Math.round(rect.x + rect.width / 2)
      || point.y !== Math.round(rect.y + rect.height / 2)) throw new Error("web_model_point_invalid");
  // The public menu handles pointerdown, rather than click alone. These are
  // ordinary DOM events; no React handler invocation or trusted-event spoofing.
  const options = { bubbles: true, cancelable: true, button: 0, pointerId: 1,
    pointerType: "mouse", isPrimary: true, clientX: point.x, clientY: point.y };
  button.dispatchEvent(new PointerEvent("pointerdown", { ...options, buttons: 1 }));
  button.dispatchEvent(new PointerEvent("pointerup", { ...options, buttons: 0 }));
}
function backgroundMenuKey(key) {
  const keys = { Escape: "Escape", Left: "ArrowLeft", Right: "ArrowRight" };
  if (!Object.hasOwn(keys, key)) throw new Error("web_background_key_invalid");
  const target = document.activeElement;
  if (!target || typeof target.dispatchEvent !== "function") throw new Error("web_background_input_unavailable");
  const options = { key: keys[key], code: keys[key], bubbles: true, cancelable: true };
  target.dispatchEvent(new KeyboardEvent("keydown", options));
  target.dispatchEvent(new KeyboardEvent("keyup", options));
}
function composerFocused() {
  const composer = document.querySelector('#prompt-textarea[contenteditable="true"]');
  return !!composer && document.activeElement === composer;
}
function clickModelChooser() {
  const found = [...document.querySelectorAll('[role="menuitem"]')].filter(e => e.getClientRects().length
    && !e.closest('[hidden],[inert],[aria-hidden="true"],[role="menu"][data-state="closed"]')
    && ["选择模型", "Choose model"].includes(e.getAttribute("aria-label")));
  if (found.length !== 1) throw new Error("web_model_chooser_ambiguous");
  found[0].click();
}
function chooseModel(modelLabels) {
  const found = [...document.querySelectorAll('[role="menuitemradio"]')].filter(e => e.getClientRects().length
    && !e.closest('[hidden],[inert],[aria-hidden="true"],[role="menu"][data-state="closed"]')
    && modelLabels.includes(e.textContent.trim()));
  if (found.length !== 1) throw new Error("web_model_option_ambiguous");
  found[0].click();
}
function effortState() {
  const containers = [...document.querySelectorAll('[data-model-reasoning-effort-slider]')].filter(e => e.getClientRects().length
    && !e.closest('[hidden],[inert],[aria-hidden="true"],[role="menu"][data-state="closed"]'));
  if (containers.length !== 1) return null;
  const sliders = containers[0].querySelectorAll('[role="slider"]');
  if (sliders.length !== 1) return null;
  const values = ["aria-valuemin", "aria-valuemax", "aria-valuenow"].map(k => sliders[0].getAttribute(k));
  if (values.some(v => !/^[0-4]$/.test(v || ""))) throw new Error("web_effort_shape_invalid");
  const control = sliders[0].closest('[role="menuitem"]');
  const descriptions = (control?.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean)
    .slice(0, 4).map(id => document.getElementById(id)?.textContent || '');
  const chooser = [...document.querySelectorAll('[role="menuitem"]')].filter(e => e.getClientRects().length
    && !e.closest('[hidden],[inert],[aria-hidden="true"],[role="menu"][data-state="closed"]')
    && ["选择模型", "Choose model"].includes(e.getAttribute('aria-label')));
  // The current public slider announcement prefixes the effort with its
  // generation (for example "5.6 极高" and "5.6 Pro"). Retain that prefix as
  // separate evidence instead of treating the entire label as unknown.
  const labels = descriptions.map(text => text.match(/^(?:(?:GPT-)?(5\.6|6)(?:\s*Sol)?\s*)?(即时|中|高|极高|Instant|Medium|High|Extra high|Pro)[，,]/)).filter(Boolean);
  return { min: Number(values[0]), max: Number(values[1]), value: Number(values[2]),
    label: labels.length === 1 ? labels[0][2] : null,
    announcedGeneration: labels.length === 1 ? labels[0][1] || null : null,
    generationLabel: chooser.length === 1 ? chooser[0].textContent.trim().slice(0, 64) : null,
    locked: !!containers[0].querySelector('[data-locked="true"],[aria-disabled="true"]') };
}
function focusEffort() {
  const container = [...document.querySelectorAll('[data-model-reasoning-effort-slider]')].filter(e => e.getClientRects().length
    && !e.closest('[hidden],[inert],[aria-hidden="true"],[role="menu"][data-state="closed"]'));
  if (container.length !== 1) throw new Error("web_effort_control_ambiguous");
  const control = container[0].querySelector('[role="slider"]')?.closest('[role="menuitem"]');
  if (!control) throw new Error("web_effort_control_missing");
  control.focus();
  if (document.activeElement !== control) throw new Error("web_effort_focus_failed");
}
function connectorAccessState() {
  // The initial temporary page can render before account plugin access loads.
  // Read only the public setting; never change personalization or permissions.
  const controls = [...document.querySelectorAll('button[aria-label="个性化"],button[aria-label="不个性化"]')]
    .filter(e => e.getClientRects().length && !e.closest('[hidden],[inert],[aria-hidden="true"]'));
  if (controls.length !== 1) return 'unknown';
  return controls[0].getAttribute('aria-label') === '个性化' ? 'enabled' : 'disabled';
}
function connectorMenuChoice(name, query, activate = false, expectedId) {
  // Match the complete ASCII/CJK label, including a true end-of-input check.
  if (typeof name !== 'string' || !/^[A-Za-z0-9\u3400-\u4dbf\u4e00-\u9fff][A-Za-z0-9\u3400-\u4dbf\u4e00-\u9fff -]{0,63}(?![\s\S])/.test(name)
      || query !== '@' + name.split(' ')[0] || typeof activate !== 'boolean'
      || typeof expectedId !== 'string' || !/^plugin:asdk_app_[a-f0-9]{32}$/.test(expectedId))
    throw new Error("web_connector_query_invalid");
  const composer = document.querySelector('#prompt-textarea[contenteditable="true"]');
  if (!composer || document.activeElement !== composer || composer.textContent !== query)
    throw new Error("web_connector_query_changed");
  const rows = [...document.querySelectorAll('[data-composer-plugin-impression-id] .__menu-item[tabindex="0"]')]
    .filter(e => e.getClientRects().length && e.getAttribute('aria-disabled') !== 'true'
      && !e.closest('[hidden],[inert],[aria-hidden="true"]'));
  if (rows.length > 512) throw new Error("web_connector_menu_too_large");
  const matches = rows.filter(e => e.closest('[data-composer-plugin-impression-id]')
    ?.getAttribute('data-composer-plugin-impression-id') === expectedId.slice('plugin:'.length)
    && (e.textContent === name || [...e.querySelectorAll('span')].some(label => label.textContent === name)));
  if (matches.length > 1) throw new Error("web_connector_menu_ambiguous");
  if (!matches.length) return null;
  if (activate) matches[0].click();
  return { name, id: expectedId, activated: activate };
}
function selectedConnector(expectedName) {
  if (typeof expectedName !== 'string' || !/^[A-Za-z0-9\u3400-\u4dbf\u4e00-\u9fff][A-Za-z0-9\u3400-\u4dbf\u4e00-\u9fff -]{0,63}(?![\s\S])/.test(expectedName))
    throw new Error("web_connector_name_invalid");
  const composers = [...document.querySelectorAll('#prompt-textarea[contenteditable="true"]')]
    .filter(e => e.getClientRects().length);
  if (composers.length !== 1) throw new Error("web_composer_missing");
  const composer = composers[0];
  const pills = composer.querySelectorAll('[data-inline-selection-pill]');
  if (pills.length === 0) return null;
  const cursors = composer.querySelectorAll('[data-inline-selection-pill-cursor-target]');
  if (pills.length !== 1 || cursors.length !== 1) throw new Error("web_connector_mention_ambiguous");
  const pill = pills[0], cursor = cursors[0], id = pill.getAttribute('data-id');
  if (!/^plugin:asdk_app_[a-f0-9]{32}$/.test(id || '')
      || pill.getAttribute('contenteditable') !== 'false'
      || pill.getAttribute('data-system-hint-type') !== id
      || pill.getAttribute('data-symbol') !== 'ecosystemMention'
      || pill.getAttribute('data-keyword') !== expectedName || pill.textContent !== expectedName
      || cursor.getAttribute('contenteditable') !== 'false' || cursor.textContent !== '\uFEFF'
      || composer.textContent !== '\uFEFF' + expectedName + ' ')
    throw new Error("web_connector_mention_mismatch");
  return { id, name: expectedName };
}
function composerPrefix(mention) {
  const composer = document.querySelector('#prompt-textarea[contenteditable="true"]');
  if (!composer) throw new Error("web_composer_missing");
  if (mention == null) {
    if (composer.textContent !== "") throw new Error("web_empty_composer_required");
    return "";
  }
  const pills = composer.querySelectorAll('[data-inline-selection-pill]');
  const cursors = composer.querySelectorAll('[data-inline-selection-pill-cursor-target]');
  if (pills.length !== 1 || cursors.length !== 1) throw new Error("web_connector_mention_ambiguous");
  const pill = pills[0], cursor = cursors[0];
  if (pill.getAttribute('contenteditable') !== 'false'
      || pill.getAttribute('data-id') !== mention.id
      || pill.getAttribute('data-system-hint-type') !== mention.id
      || pill.getAttribute('data-symbol') !== 'ecosystemMention'
      || pill.getAttribute('data-keyword') !== mention.name
      || pill.textContent !== mention.name
      || cursor.getAttribute('contenteditable') !== 'false'
      || cursor.textContent !== '\uFEFF') throw new Error("web_connector_mention_mismatch");
  const prefix = '\uFEFF' + mention.name + ' ';
  if (composer.textContent !== prefix) throw new Error("web_connector_composer_not_empty");
  return prefix;
}
function focusComposer(prefix = "") {
  const inputs = [...document.querySelectorAll('#prompt-textarea[contenteditable="true"]')].filter(e => e.getClientRects().length);
  if (inputs.length !== 1 || inputs[0].textContent !== prefix) throw new Error("web_empty_composer_required");
  inputs[0].focus();
  if (document.activeElement !== inputs[0]) throw new Error("web_composer_focus_failed");
  const range = document.createRange();
  range.selectNodeContents(inputs[0]);
  range.collapse(false);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
}
function composerMatches(text, prefix = "", mention = null) {
  const composer = document.querySelector('#prompt-textarea[contenteditable="true"]');
  if (!composer || document.activeElement !== composer) return false;
  const pills = composer.querySelectorAll('[data-inline-selection-pill]');
  const cursors = composer.querySelectorAll('[data-inline-selection-pill-cursor-target]');
  // The observed editor represents each inserted LF line as a direct P child,
  // including empty lines. textContent drops these boundaries; innerText adds
  // layout-dependent breaks around the application pill. Validate each node
  // against its exact original line instead of rewriting the submitted text.
  const paragraphs = [...composer.childNodes], lines = (prefix + text).split('\n');
  const exactParagraphs = paragraphs.length > 0 && paragraphs.length <= 1024
    && paragraphs.length === lines.length && paragraphs.every((p, index) => {
      if (p.nodeType !== 1 || p.tagName !== 'P' || p.textContent !== lines[index]) return false;
      const breaks = p.querySelectorAll('br');
      return breaks.length === 0 || (breaks.length === 1 && p.textContent === '');
    });
  // A plain multiline paste also becomes one P per source line. innerText can
  // add layout breaks, so accept only the exact ordered paragraph structure.
  if (mention == null) return prefix === '' && pills.length === 0 && cursors.length === 0
    && (composer.innerText === text || exactParagraphs);
  return prefix === '\uFEFF' + mention.name + ' '
    && pills.length === 1 && cursors.length === 1
    && cursors[0].getAttribute('contenteditable') === 'false' && cursors[0].textContent === '\uFEFF'
    && pills[0].getAttribute('contenteditable') === 'false'
    && pills[0].getAttribute('data-id') === mention.id
    && pills[0].getAttribute('data-system-hint-type') === mention.id
    && pills[0].getAttribute('data-symbol') === 'ecosystemMention'
    && pills[0].getAttribute('data-keyword') === mention.name
    && pills[0].textContent === mention.name && exactParagraphs;
}
function sendOnce() {
  const form = document.querySelector('#prompt-textarea[contenteditable="true"]')?.closest("form");
  const buttons = [...(form?.querySelectorAll('[data-testid="send-button"]') || [])].filter(e => e.getClientRects().length && !e.disabled && e.getAttribute("aria-disabled") !== "true");
  if (buttons.length !== 1) throw new Error("web_send_control_ambiguous");
  buttons[0].click();
}
function cancelGeneration() {
  const buttons = [...document.querySelectorAll('[data-testid="stop-button"]')]
    .filter(e => e.getClientRects().length && !e.disabled && e.getAttribute("aria-disabled") !== "true");
  if (buttons.length > 1) throw new Error("web_stop_control_ambiguous");
  if (!buttons.length) return false;
  buttons[0].click();
  return true;
}
function currentPublicFiber(fiber) {
  // Determine mounted membership from graph identities, not from whichever
  // message copy looks finished. Only read tree links and HostRoot.current;
  // never traverse props, turn histories or application stores here.
  let budget = 8192;
  const spend = () => { if (--budget < 0) throw new Error("web_public_tree_bound"); };
  const invalid = () => { throw new Error("web_public_current_branch_unavailable"); };
  const cache = new Map();
  const childOf = (owner, first, second = null) => {
    let found = null;
    const seen = new Set();
    for (let child = owner?.child; child; child = child.sibling) {
      spend();
      if (seen.has(child)) throw new Error("web_public_tree_cycle");
      seen.add(child);
      if (child === first || child === second) {
        if (found) invalid();
        found = child;
      }
    }
    return found;
  };
  const resolve = (seed, level = 0) => {
    spend();
    if (!seed) invalid();
    if (level > 512) throw new Error("web_public_tree_bound");
    if (cache.has(seed)) return cache.get(seed);
    if (!seed.alternate) {
      const path = [], seen = new Set();
      for (let node = seed; node; node = node.return) {
        spend();
        if (seen.has(node)) throw new Error("web_public_tree_cycle");
        seen.add(node); path.push(node);
        if (node.tag === 3) {
          if (node.return != null || node.stateNode?.current !== node) invalid();
          for (const member of path) cache.set(member, member);
          return seed;
        }
        const parent = node.return;
        const owner = parent?.alternate ? resolve(parent, level + 1) : parent;
        if (childOf(owner, node) !== node) invalid();
        if (parent?.alternate) {
          for (const member of path) cache.set(member, member);
          return seed;
        }
      }
      invalid();
    }
    // Walk the two ancestor chains together. A breadth-first search of both
    // branches at every level needlessly revisits the inactive ancestor tree.
    const path = [], seen = new Set();
    const finish = useFirst => {
      for (const pair of path) {
        cache.set(pair[0], pair[useFirst ? 0 : 1]);
        cache.set(pair[1], pair[useFirst ? 0 : 1]);
      }
      return useFirst ? seed : seed.alternate;
    };
    let first = seed, second = seed.alternate;
    while (first && second) {
      spend();
      if (first.alternate !== second || second.alternate !== first) invalid();
      if (seen.has(first) || seen.has(second)) throw new Error("web_public_tree_cycle");
      seen.add(first); seen.add(second); path.push([first, second]);
      if (first.tag === 3 || second.tag === 3) {
        if (first.tag !== 3 || second.tag !== 3 || first.return != null || second.return != null
            || first.stateNode !== second.stateNode) invalid();
        const current = first.stateNode?.current;
        if (current !== first && current !== second) invalid();
        return finish(current === first);
      }
      const parent = first.return, other = parent?.alternate;
      if (!parent || second.return !== parent && second.return !== other) invalid();
      if (!other || parent.child === other.child) {
        const owner = resolve(parent, level + 1);
        const child = childOf(owner, first, second);
        if (!child) invalid();
        return finish(child === first);
      }
      const left = childOf(parent, first, second), right = childOf(other, first, second);
      if (left === first && right === second) { first = parent; second = other; }
      else if (left === second && right === first) { first = other; second = parent; }
      else invalid();
    }
    invalid();
  };
  return resolve(fiber);
}

function publicFinal(prompt, includeCitations = false, committedView = false) {
  if (document.querySelector('[data-testid="stop-button"]')) return null;
  const users = [...document.querySelectorAll('[data-message-author-role="user"]')];
  if (users.length !== 1) return null;
  // Long user bubbles can add presentation controls. Bind the current row's
  // structured public source instead of trimming those controls from text.
  if (users[0].textContent !== prompt) {
    const user = users[0], id = user.getAttribute("data-message-id");
    const key = Object.keys(user).find(k => k.startsWith("__reactFiber$"));
    let fiber = key ? user[key] : null, matched = false;
    for (let depth = 0; fiber && depth < 45; depth++, fiber = fiber.return) {
      if (committedView) fiber = currentPublicFiber(fiber);
      const props = fiber.memoizedProps;
      if (!props || typeof props !== "object") continue;
      const message = props.message;
      if (id && message?.id === id && message.author?.role === "user") {
        const content = message.content;
        if (content?.content_type !== "text" || !Array.isArray(content.parts)
            || content.parts.length !== 1 || content.parts[0] !== prompt)
          throw new Error("web_user_turn_mismatch");
        matched = true;
      }
      if (Array.isArray(props.allMessages) || (props.turn && typeof props.turn === "object")) break;
    }
    if (!matched) throw new Error("web_user_source_unavailable");
  }
  const rows = [...document.querySelectorAll('[data-message-author-role="assistant"][data-message-id]')];
  if (rows.length === 0) return null;
  const found = new Map();
  for (const row of rows) {
    const rowId = row.getAttribute("data-message-id");
    const seeds = [row, ...row.querySelectorAll(".markdown")];
    for (const seed of seeds) {
      const key = Object.keys(seed).find(k => k.startsWith("__reactFiber$"));
      let fiber = key ? seed[key] : null;
      for (let depth = 0; fiber && depth < 45; depth++, fiber = fiber.return) {
        if (committedView) fiber = currentPublicFiber(fiber);
        const props = fiber.memoizedProps;
        if (!props || typeof props !== "object") continue;
        const candidate = props.message;
        if (candidate && candidate.id === rowId && candidate.author?.role === "assistant"
            && candidate.channel === "final" && candidate.end_turn === true
            && candidate.status === "finished_successfully"
            && (candidate.recipient == null || candidate.recipient === "all")) {
          const meta = candidate.metadata;
          if (meta != null && (typeof meta !== "object" || Array.isArray(meta))) throw new Error("web_message_metadata_invalid");
          const hidden = {};
          for (const name of ["is_visually_hidden", "is_visually_hidden_from_conversation"]) {
            const flag = meta?.[name];
            if (flag != null && flag !== false) throw new Error("web_hidden_message_rejected");
            if (flag !== undefined) hidden[name] = flag;
          }
          const content = candidate.content;
          if (!content || content.content_type !== "text" || !Array.isArray(content.parts)
              || content.parts.length === 0 || content.parts.length > 1024
              || content.parts.some(p => typeof p !== "string")) throw new Error("web_text_parts_invalid");
          const result = { id: rowId, author: { role: "assistant" }, recipient: candidate.recipient ?? null,
            channel: "final", end_turn: true, status: candidate.status, metadata: hidden,
            content: { content_type: "text", parts: content.parts.slice() } };
          if (includeCitations) {
            const references = meta?.content_references ?? [];
            if (!Array.isArray(references) || references.length > 128)
              throw new Error("web_public_citations_invalid");
            // Preserve only the observed public reference fields. Do not read
            // snippets, search queries, prompt_text or unrelated account data.
            const textField = (value, maximum) => {
              if (typeof value !== "string" || value.length > maximum)
                throw new Error("web_public_citation_field_invalid");
              return value;
            };
            const sources = values => {
              if (!Array.isArray(values) || values.length > 64)
                throw new Error("web_public_citation_sources_invalid");
              return values.map(value => ({ title: textField(value?.title, 2048), url: textField(value?.url, 8192) }));
            };
            result.public_references = references.map(reference => {
              if (!reference || typeof reference !== "object") throw new Error("web_public_citations_invalid");
              const value = { type: textField(reference.type, 64),
                matched_text: textField(reference.matched_text, 2048) };
              for (const key of ["start_idx", "end_idx"]) {
                if (!Number.isSafeInteger(reference[key]) || reference[key] < 0 || reference[key] > 1024 * 1024)
                  throw new Error("web_public_citation_position_invalid");
                value[key] = reference[key];
              }
              if (reference.items != null) value.items = sources(reference.items);
              if (reference.sources != null) value.sources = sources(reference.sources);
              if (reference.type === "url") {
                value.title = textField(reference.title, 2048);
                value.item = sources([reference.item])[0];
              }
              return value;
            });
          }
          const encoded = JSON.stringify(result);
          if (new TextEncoder().encode(encoded).length > 1024 * 1024) throw new Error("web_public_message_too_large");
          if (found.has(rowId) && found.get(rowId).encoded !== encoded) throw new Error("web_public_message_contradiction");
          found.set(rowId, { encoded, result });
        }
        // Do not traverse turn-wide message lists or account/store objects.
        if (Array.isArray(props.allMessages) || (props.turn && typeof props.turn === "object")) break;
      }
    }
  }
  if (found.size > 1) throw new Error("web_final_message_ambiguous");
  return found.size === 1 ? found.values().next().value.result : null;
}

function publicUserBindingShape(prompt, committedView = false) {
  const users = [...document.querySelectorAll('[data-message-author-role="user"]')];
  if (users.length !== 1) return null;
  const user = users[0], id = user.getAttribute('data-message-id');
  const key = Object.keys(user).find(k => k.startsWith('__reactFiber$'));
  let fiber = key ? user[key] : null;
  for (let depth = 0; fiber && depth < 45; depth++, fiber = fiber.return) {
    if (committedView) fiber = currentPublicFiber(fiber);
    const props = fiber.memoizedProps, message = props?.message;
    if (id && message?.id === id && message.author?.role === 'user') {
      const content = message.content;
      if (content?.content_type !== 'text' || !Array.isArray(content.parts)
          || content.parts.length !== 1 || typeof content.parts[0] !== 'string')
        return { supportedTextShape: false };
      const text = content.parts[0];
      if (text.length > 1024 * 1024 || prompt.length > 65536)
        return { supportedTextShape: false };
      let firstDifference = 0, sharedSuffix = 0;
      while (firstDifference < Math.min(text.length, prompt.length)
          && text[firstDifference] === prompt[firstDifference]) firstDifference++;
      while (sharedSuffix < Math.min(text.length, prompt.length) - firstDifference
          && text[text.length - 1 - sharedSuffix] === prompt[prompt.length - 1 - sharedSuffix]) sharedSuffix++;
      let sourceIndex = 0, promptIndex = 0;
      while (sourceIndex < text.length) {
        if (text[sourceIndex] === prompt[promptIndex]) { sourceIndex++; promptIndex++; }
        else if (text[sourceIndex] === "\\") sourceIndex++;
        else break;
      }
      // Fixed counts only: neither arbitrary prefixes nor differing characters
      // leave the public row. Diagnostics never relax publicFinal's comparison.
      const count = (value, character) => value.split(character).length - 1;
      return { supportedTextShape: true, exact: text === prompt, promptOffset: text.indexOf(prompt),
        sourceLength: text.length, promptLength: prompt.length,
        firstDifference: text === prompt ? -1 : firstDifference, sharedSuffix,
        sourceSpaces: count(text, " "), promptSpaces: count(prompt, " "),
        sourceLineFeeds: count(text, "\n"), promptLineFeeds: count(prompt, "\n"),
        sourceNbsp: count(text, "\u00a0"), promptNbsp: count(prompt, "\u00a0"),
        sourceBackslashes: count(text, "\\"), promptBackslashes: count(prompt, "\\"),
        backslashInsertionsOnly: sourceIndex === text.length && promptIndex === prompt.length };
    }
    if (Array.isArray(props?.allMessages) || (props?.turn && typeof props.turn === 'object')) break;
  }
  return null;
}

function publicInterruptionState(connectorName = null) {
  // Read only rendered UI, not assistant claims about a safety check. Dated
  // selector/confirmation wording reference: codex-chatgpt-web browser-worker.ts
  // e85e3693. No approval, denial, retry, permission or account action occurs here.
  if (connectorName !== null && (typeof connectorName !== 'string'
      || !/^[A-Za-z0-9\u3400-\u4dbf\u4e00-\u9fff][A-Za-z0-9\u3400-\u4dbf\u4e00-\u9fff -]{0,63}(?![\s\S])/.test(connectorName)))
    throw new Error('web_connector_name_invalid');
  const visible = element => {
    if (!element || !element.getClientRects().length
        || element.closest('[hidden],[inert],[aria-hidden="true"],.sr-only,.visually-hidden,[data-testid="visually-hidden"]')) return false;
    // Accessibility announcements can retain a layout rectangle. Only actual
    // displayed UI may interrupt a turn; do not infer visibility from size.
    // Computed visibility already includes inheritance and allows a visible
    // descendant to override a hidden ancestor.
    const visibility = getComputedStyle(element).visibility;
    if (visibility === 'hidden' || visibility === 'collapse') return false;
    for (let node = element; node; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.display === 'none' || style.contentVisibility === 'hidden') return false;
    }
    return true;
  };
  const uiText = element => {
    // Only short rendered alerts/headings are inspected. Never export their
    // text, call arguments or arbitrary page content into diagnostics.
    const text = element.innerText;
    return typeof text === 'string' && text.length <= 4096 ? text : '';
  };
  const alerts = [...document.querySelectorAll('[role="alert"]')].filter(visible).slice(0, 16);
  const dialogs = [...document.querySelectorAll('[role="dialog"]')].filter(visible).slice(0, 16);
  const cards = [...document.querySelectorAll('[data-testid="tool-approval-card"]')].filter(visible);
  const confirmation = connectorName === null ? null : 'Allow ChatGPT to use ' + connectorName + '?';
  const connectorDialogs = confirmation === null ? [] : dialogs.filter(dialog =>
    [...dialog.querySelectorAll('h1,h2,h3,[role="heading"]')].slice(0, 8)
      .some(heading => visible(heading) && uiText(heading).trim() === confirmation));
  const notices = [...alerts, ...dialogs].map(uiText);
  return {
    approvalCards: Math.min(10000, cards.length), connectorDialogs: connectorDialogs.length,
    sessionExpired: notices.some(text => /Your session has expired|你的工作階段已過期|您的工作階段已過期|你的会话已过期|您的会话已过期/i.test(text)),
    subscriptionUnavailable: alerts.some(element => /failed to load subscription|unable to load subscription|未能加载订阅/i.test(uiText(element))),
    responseError: [...document.querySelectorAll('[data-testid="regenerate-thread-error-button"]')].some(visible)
      || alerts.some(element => /something went wrong/i.test(uiText(element)))
  };
}

function inspectionSnapshot(messageId) {
  // Fixed rendered notices and exact public message identity only. Reply DOM
  // text can lag the committed final; the host owns the validated text parts.
  if (typeof messageId !== 'string' || !messageId || messageId.length > 256)
    throw new Error('web_inspection_message_invalid');
  const visible = element => !!element && element.getClientRects().length > 0
    && !element.closest('[hidden],[inert],[aria-hidden="true"]');
  const rows = [...document.querySelectorAll('[data-message-author-role="assistant"][data-message-id]')]
    .filter(element => element.getAttribute('data-message-id') === messageId && visible(element));
  if (rows.length !== 1) throw new Error('web_inspection_message_ambiguous');
  const cards = [...document.querySelectorAll('[role="alert"],[data-testid="tool-approval-card"]')].filter(visible);
  if (cards.length > 16)
    throw new Error('web_inspection_snapshot_bound');
  const notices = cards.map(card => card.innerText);
  if (notices.some(notice => typeof notice !== 'string' || notice.length > 4096))
    throw new Error('web_inspection_snapshot_bound');
  return { notices };
}

function publicGenerationState(committedView = false) {
  // Counts and fixed flags only. Observe the current public rows; never read
  // source message text, reasoning contents, account stores or arbitrary errors.
  const visible = e => !!e && e.getClientRects().length > 0;
  const rows = [...document.querySelectorAll('[data-message-author-role="assistant"]')];
  const finals = new Set(), finished = new Set(), currentFinals = new Set(), currentFinished = new Set();
  const observe = (message, id, targets, completed) => {
    if (id && message?.id === id && message.author?.role === "assistant"
        && message.channel === "final" && (message.recipient == null || message.recipient === "all")
        && !message.metadata?.is_visually_hidden && !message.metadata?.is_visually_hidden_from_conversation) {
      targets.add(id);
      if (message.status === "finished_successfully" && message.end_turn === true) completed.add(id);
    }
  };
  for (const row of rows.slice(0, 8)) {
    const id = row.getAttribute("data-message-id");
    for (const seed of [row, ...row.querySelectorAll(".markdown")].slice(0, 8)) {
      const key = Object.keys(seed).find(k => k.startsWith("__reactFiber$"));
      let fiber = key ? seed[key] : null;
      for (let depth = 0; fiber && depth < 45; depth++, fiber = fiber.return) {
        const props = fiber.memoizedProps;
        if (!props || typeof props !== "object") continue;
        observe(props.message, id, finals, finished);
        const currentProps = (committedView ? currentPublicFiber(fiber) : fiber).memoizedProps;
        observe(currentProps?.message, id, currentFinals, currentFinished);
        if (Array.isArray(props.allMessages) || (props.turn && typeof props.turn === "object")
            || Array.isArray(currentProps?.allMessages) || (currentProps?.turn && typeof currentProps.turn === "object")) break;
      }
    }
  }
  const stop = document.querySelector('[data-testid="stop-button"]');
  const alerts = [...document.querySelectorAll('[role="alert"]')].filter(visible).slice(0, 16);
  const renderedTextLength = Math.min(1024 * 1024, rows.slice(0, 8).reduce((total, row) => total
    + [...row.querySelectorAll('.markdown')].slice(0, 8).filter(visible)
      .reduce((length, element) => length + (element.textContent || '').length, 0), 0));
  return { userRows: Math.min(10000, document.querySelectorAll('[data-message-author-role="user"]').length),
    assistantRows: Math.min(10000, rows.length), finalRows: finals.size, finishedFinalRows: finished.size,
    currentFinalRows: currentFinals.size, currentFinishedFinalRows: currentFinished.size,
    renderedTextLength,
    stopPresent: !!stop, stopVisible: visible(stop),
    subscriptionWarning: alerts.some(e => /未能加载订阅|unable to load subscription/i.test(e.textContent || "")),
    errorAlert: alerts.some(e => /something went wrong/i.test(e.textContent || "")) };
}

function publicMessageShape() {
  const rows = [...document.querySelectorAll('[data-message-author-role="assistant"]')];
  const shapes = [];
  for (const row of rows.slice(0, 8)) {
    const rowId = row.getAttribute("data-message-id");
    for (const seed of [row, ...row.querySelectorAll(".markdown")].slice(0, 8)) {
      const key = Object.keys(seed).find(k => k.startsWith("__reactFiber$"));
      let fiber = key ? seed[key] : null;
      for (let depth = 0; fiber && depth < 45; depth++, fiber = fiber.return) {
        const props = fiber.memoizedProps;
        if (!props || typeof props !== "object") continue;
        const message = props.message;
        if (message && typeof message === "object" && shapes.length < 24) {
          shapes.push({ role: message.author?.role ?? null, channel: message.channel ?? null,
            status: message.status ?? null, endTurn: message.end_turn ?? null,
            matchesRow: !!rowId && message.id === rowId,
            publicContentType: message.author?.role === "assistant" && message.channel === "final"
              ? message.content?.content_type ?? null : null });
        }
        if (Array.isArray(props.allMessages) || (props.turn && typeof props.turn === "object")) break;
      }
    }
  }
  return { rowCount: rows.length, idRowCount: rows.filter(e => e.hasAttribute("data-message-id")).length, shapes };
}

function publicCitationShape(committedView = false) {
  // Research-only shape projection of the current public final row. Never
  // inspect analysis/tool messages, turn stores or arbitrary metadata values.
  let remaining = 512;
  const describe = (value, depth = 0) => {
    if (--remaining < 0) return { kind: "limit" };
    if (value === null) return { kind: "null" };
    if (typeof value === "string") return { kind: "string", length: value.length };
    if (typeof value !== "object") return { kind: typeof value };
    if (Array.isArray(value)) return { kind: "array", length: value.length,
      items: depth < 5 ? value.slice(0, 4).map(item => describe(item, depth + 1)) : [] };
    return { kind: "object", fields: depth < 5 ? Object.fromEntries(Object.keys(value)
      .filter(key => /^[a-zA-Z_][a-zA-Z0-9_]{0,63}$/.test(key)).slice(0, 24)
      .map(key => [key, describe(value[key], depth + 1)])) : {} };
  };
  const observations = [];
  for (const row of [...document.querySelectorAll('[data-message-author-role="assistant"][data-message-id]')].slice(0, 8)) {
    const id = row.getAttribute("data-message-id");
    const key = Object.keys(row).find(key => key.startsWith("__reactFiber$"));
    let fiber = key ? row[key] : null;
    for (let depth = 0; fiber && depth < 45; depth++, fiber = fiber.return) {
      if (committedView) fiber = currentPublicFiber(fiber);
      const props = fiber.memoizedProps, candidate = props?.message;
      if (candidate?.id === id && candidate.author?.role === "assistant" && candidate.channel === "final"
          && candidate.end_turn === true && candidate.status === "finished_successfully"
          && (candidate.recipient == null || candidate.recipient === "all")) {
        const meta = candidate.metadata;
        if (meta && [meta.is_visually_hidden, meta.is_visually_hidden_from_conversation]
            .every(flag => flag == null || flag === false)) {
          observations.push(Object.fromEntries(["citations", "content_references", "search_result_groups"]
            .filter(name => Object.hasOwn(meta, name)).map(name => [name, describe(meta[name])])));
        }
        break;
      }
      if (Array.isArray(props?.allMessages) || (props?.turn && typeof props.turn === "object")) break;
    }
  }
  return { observations };
}

module.exports = { controls, freshChatControls, pluginMaintenanceReady, startFreshChat, enableTemporaryChat, currentPublicFiber, publicGenerationState, publicInterruptionState, inspectionSnapshot, focusModelMenu, clickModelChooser, chooseModel, effortState,
  backgroundModelInput, backgroundMenuKey, composerFocused,
  focusEffort, connectorAccessState, connectorMenuChoice, selectedConnector, composerPrefix, focusComposer, composerMatches, sendOnce, cancelGeneration, publicFinal, publicMessageShape, publicUserBindingShape, publicCitationShape };

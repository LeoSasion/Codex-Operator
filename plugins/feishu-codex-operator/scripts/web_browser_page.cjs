"use strict";

// These fixed page operations accept data only. No caller-supplied JavaScript,
// authentication material, private reasoning or general DOM dump crosses out.
function uniqueComposer() {
  const legacy = [...document.querySelectorAll('#prompt-textarea')];
  if (legacy.length) {
    return legacy.length === 1 && legacy[0].getAttribute('contenteditable') === 'true'
      && legacy[0].getClientRects().length > 0 ? legacy[0] : null;
  }
  const visible = element => element.getClientRects().length > 0
    && !element.closest('[hidden],[inert],[aria-hidden="true"],[role="menu"][data-state="closed"]');
  const role = [...document.querySelectorAll('[role="textbox"][contenteditable="true"]')]
    .filter(visible);
  const editable = [...document.querySelectorAll('[contenteditable="true"]')]
    .filter(visible);
  return role.length === 1 && editable.length === 1 && role[0] === editable[0]
    ? role[0] : null;
}
function eligibleModelButtons(composer) {
  const form = composer?.closest('form');
  if (!form) return [];
  const legacy = [...document.querySelectorAll('button[aria-haspopup="menu"][data-tone="neutral"],button[data-testid="model-switcher-dropdown-button"]')];
  if (legacy.length) {
    const visible = legacy.filter(element => element.getClientRects().length > 0);
    return visible.length === 1 && form.contains(visible[0]) ? visible : [];
  }
  const accessible = [...document.querySelectorAll('button[aria-label="选择 ChatGPT 模型"],button[aria-label="Choose ChatGPT model"]')]
    .filter(element => element.getClientRects().length > 0
      && !element.closest('[hidden],[inert],[aria-hidden="true"],[role="menu"][data-state="closed"]'));
  if (accessible.length !== 1) return [];
  const button = accessible[0];
  const ariaDisabled = button.getAttribute('aria-disabled');
  return form.contains(button) && button.getAttribute('aria-haspopup') === 'menu'
    && !button.disabled && (ariaDisabled === null || ariaDisabled === 'false')
    ? accessible : [];
}
function controls(modelLabels = ["GPT-5.6 Sol"]) {
  const visible = e => !!e && e.getClientRects().length > 0;
  // The picker retains both panels and closing animations with layout boxes.
  // Inert/hidden panels are not usable controls, even when their bounds remain.
  const menuVisible = e => visible(e)
    && !e.closest('[hidden],[inert],[aria-hidden="true"],[role="menu"][data-state="closed"]');
  const composer = uniqueComposer();
  const form = composer?.closest("form");
  const modelButtons = eligibleModelButtons(composer);
  const chooser = [...document.querySelectorAll('[role="menuitem"]')].filter(e => menuVisible(e) && ["选择模型", "Choose model"].includes(e.getAttribute("aria-label")));
  const options = [...document.querySelectorAll('[role="menuitemradio"]')].filter(e => menuVisible(e) && modelLabels.includes(e.textContent.trim()));
  const send = form?.querySelector('[data-testid="send-button"]')
    || [...(form?.querySelectorAll('button[type="submit"]') || [])]
      .filter(e => ['发送', 'Send'].includes(e.getAttribute('aria-label')))[0];
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
    modernRowCount: document.querySelectorAll('[data-chatgpt-search-unit-key]').length,
    sendReady: visible(send) && !send.disabled && send.getAttribute("aria-disabled") !== "true" };
}
function startupControlStructure() {
  // Failed hidden preparation only: fixed selector shape, no DOM text or attributes
  // beyond the old editor's editability. This never chooses or clicks a control.
  const bucket = count => count === 0 ? "zero" : count === 1 ? "one" : "multiple";
  const visibleCount = elements => {
    let count = 0;
    for (const element of elements) {
      if (element.getClientRects().length > 0 && ++count > 1) break;
    }
    return bucket(count);
  };
  const legacy = document.querySelectorAll('#prompt-textarea');
  const model = document.querySelectorAll('button[aria-haspopup="menu"][data-tone="neutral"],button[data-testid="model-switcher-dropdown-button"]');
  const roleEditors = [...document.querySelectorAll('[role="textbox"][contenteditable="true"]')]
    .filter(element => element.getClientRects().length > 0);
  const editorForm = roleEditors.length === 1 ? roleEditors[0].closest('form') : null;
  const buttonCandidates = document.querySelectorAll('button,[role="button"]');
  const exactNames = ['选择 ChatGPT 模型', 'Choose ChatGPT model'];
  const matched = [];
  if (buttonCandidates.length <= 256) {
    for (const element of buttonCandidates) {
      if (element.getClientRects().length === 0) continue;
      const sources = [];
      if (exactNames.includes(element.getAttribute('aria-label'))) sources.push('aria_label');
      if (exactNames.includes(element.getAttribute('title'))) sources.push('title');
      const text = element.textContent;
      if (typeof text === 'string' && text.length <= 64 && exactNames.includes(text.trim()))
        sources.push('exact_text');
      if (sources.length > 0) matched.push({element, sources});
      if (matched.length > 1) break;
    }
  }
  const selected = buttonCandidates.length <= 256 && matched.length === 1 ? matched[0] : null;
  const selectedHaspopup = selected?.element.getAttribute('aria-haspopup');
  const selectedDisabled = selected?.element.disabled;
  return {
    readyState: ["loading", "interactive", "complete"].includes(document.readyState)
      ? document.readyState : "unknown",
    legacyEditorCount: bucket(legacy.length),
    legacyEditorEditable: legacy.length === 1
      ? legacy[0].getAttribute('contenteditable') === 'true' ? "yes" : "no" : "unknown",
    legacyEditorRect: legacy.length === 1
      ? legacy[0].getClientRects().length > 0 ? "yes" : "no" : "unknown",
    testIdEditorVisible: visibleCount(document.querySelectorAll('[data-testid="prompt-textarea"]')),
    roleTextboxEditableVisible: visibleCount(document.querySelectorAll('[role="textbox"][contenteditable="true"]')),
    editableVisible: visibleCount(document.querySelectorAll('[contenteditable="true"]')),
    textareaVisible: visibleCount(document.querySelectorAll('textarea')),
    globalModelTotal: bucket(model.length),
    globalModelVisible: visibleCount(model),
    editorFormExists: roleEditors.length === 1 ? editorForm ? 'yes' : 'no' : 'unknown',
    accessibleModelCount: buttonCandidates.length > 256 ? 'unknown' : bucket(matched.length),
    accessibleModelSource: selected ? selected.sources.length === 1 ? selected.sources[0]
      : 'multiple' : 'unknown',
    accessibleModelTag: selected ? selected.element.tagName === 'BUTTON' ? 'button' : 'other'
      : 'unknown',
    accessibleModelInEditorForm: selected && roleEditors.length === 1
      ? editorForm && editorForm.contains(selected.element) ? 'yes' : 'no' : 'unknown',
    accessibleModelHaspopup: selected ? selectedHaspopup === 'menu' ? 'menu'
      : selectedHaspopup === null ? 'absent' : 'other' : 'unknown',
    accessibleModelDisabled: selected ? selectedDisabled === true
      || selected.element.getAttribute('aria-disabled') === 'true' ? 'yes'
      : selectedDisabled === false || selected.element.getAttribute('aria-disabled') === 'false'
        ? 'no' : 'unknown' : 'unknown',
  };
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
function startFreshChat(expectedPrompt = null, expectedId = null) {
  const composer = uniqueComposer();
  const users = document.querySelectorAll('[data-message-author-role="user"]');
  const assistants = document.querySelectorAll('[data-message-author-role="assistant"]');
  const modernRows = document.querySelectorAll('[data-chatgpt-search-unit-key]');
  const legacyIdle = !modernRows.length && users.length === 1 && assistants.length === 1;
  // The current renderer no longer exposes data-message-author-role. Recheck
  // the exact completed public turn immediately before navigating away from it.
  const modernFinal = modernRows.length && users.length === 0 && assistants.length === 0
    && typeof expectedPrompt === 'string' && typeof expectedId === 'string'
    ? modernPublicFinal(expectedPrompt, false, true) : null;
  const modernIdle = !!modernFinal && modernFinal.id === expectedId;
  if (!composer || composer.textContent !== ''
      || (!legacyIdle && !modernIdle)
      || [...document.querySelectorAll('[data-testid="stop-button"]')].some(e => e.getClientRects().length))
    throw new Error('web_new_chat_idle_page_required');
  const links = [...document.querySelectorAll('a[data-testid="create-new-chat-button"]')]
    .filter(e => e.getClientRects().length);
  const buttons = [...document.querySelectorAll('nav[aria-label="首页"] button,nav[aria-label="Home"] button,nav[aria-label="聊天记录"] button,nav[aria-label="Chat history"] button')]
    .filter(e => e.getClientRects().length
      && /^(新聊天|New chat)$/.test((e.textContent || '').trim()));
  // The old UI has one or two equivalent home links; the current sidebar has
  // one exact public button. Never choose among mixed or ambiguous controls.
  if (links.length && !buttons.length && links.length <= 2
      && links.every(e => e.getAttribute('href') === '/'
        && e.getAttribute('aria-disabled') !== 'true' && !e.getAttribute('target')
        && /^(新聊天|New chat)(CtrlShiftO)?$/.test((e.textContent || '').trim()))) {
    links[0].click();
    return;
  }
  if (links.length || buttons.length !== 1 || buttons[0].getAttribute('type') !== 'button'
      || buttons[0].disabled || buttons[0].getAttribute('aria-disabled') === 'true'
      || buttons[0].getAttribute('href') || buttons[0].getAttribute('target')
      || buttons[0].closest('[hidden],[inert],[aria-hidden="true"]'))
    throw new Error('web_new_chat_control_ambiguous');
  buttons[0].click();
}
function freshChatControlStructure() {
  // Diagnostic after a rejected New chat selection only. Return fixed categories,
  // never page text, URLs, attributes or conversation identities.
  const bucket = count => count === 0 ? 'zero' : count === 1 ? 'one' : 'multiple';
  const visible = e => e.getClientRects().length > 0;
  const links = [...document.querySelectorAll('a[data-testid="create-new-chat-button"]')].filter(visible);
  const navButtons = [...document.querySelectorAll('nav[aria-label="首页"] button,nav[aria-label="Home"] button,nav[aria-label="聊天记录"] button,nav[aria-label="Chat history"] button')]
    .filter(visible);
  const buttons = navButtons.filter(e => /^(新聊天|New chat)$/.test((e.textContent || '').trim()));
  const all = test => links.length ? links.every(test) ? 'yes' : 'no' : 'unknown';
  const button = buttons.length === 1 ? buttons[0] : null;
  const attr = name => button ? button.getAttribute(name) : null;
  const type = attr('type'), ariaDisabled = attr('aria-disabled');
  return { legacyLinks: bucket(links.length),
    legacyRootHref: all(e => e.getAttribute('href') === '/'),
    legacyLabel: all(e => /^(新聊天|New chat)(CtrlShiftO)?$/.test((e.textContent || '').trim())),
    legacyEnabled: all(e => e.getAttribute('aria-disabled') !== 'true'
      && !e.getAttribute('target')),
    navButtons: bucket(navButtons.length), namedButtons: bucket(buttons.length),
    buttonType: !button ? 'unknown' : type === 'button' ? 'button' : type === null ? 'absent' : 'other',
    buttonDisabled: !button ? 'unknown' : button.disabled ? 'yes' : 'no',
    buttonAriaDisabled: !button ? 'unknown' : ariaDisabled === 'true' ? 'yes'
      : ariaDisabled === null || ariaDisabled === 'false' ? 'no' : 'other',
    buttonHref: !button ? 'unknown' : attr('href') ? 'present' : 'absent',
    buttonTarget: !button ? 'unknown' : attr('target') ? 'present' : 'absent',
    buttonHiddenAncestor: !button ? 'unknown'
      : button.closest('[hidden],[inert],[aria-hidden="true"]') ? 'yes' : 'no' };
}
function emptyFreshChat() {
  const composer = uniqueComposer();
  return !!composer && composer.textContent === ''
    && document.querySelectorAll('[data-message-author-role],[data-chatgpt-search-unit-key]').length === 0
    && ![...document.querySelectorAll('[data-testid="stop-button"]')]
      .some(e => e.getClientRects().length);
}
function enableTemporaryChat() {
  const composer = uniqueComposer();
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
  const found = eligibleModelButtons(uniqueComposer());
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
  const found = eligibleModelButtons(uniqueComposer());
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
  const composer = uniqueComposer();
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
function eligibleEffortContainer() {
  const visible = element => element.getClientRects().length > 0
    && !element.closest('[hidden],[inert],[aria-hidden="true"],[role="menu"][data-state="closed"]');
  const legacy = [...document.querySelectorAll('[data-model-reasoning-effort-slider]')];
  if (legacy.length) {
    const candidates = legacy.filter(visible);
    return candidates.length === 1 ? candidates[0] : null;
  }
  // The observed current menu wraps its slider in this exact named control.
  // An unrelated page slider must never become the model-effort target.
  const candidates = [...document.querySelectorAll('[data-model-picker-power-slider]')].filter(visible);
  if (candidates.length !== 1) return null;
  // The current page marks the slider span itself aria-hidden while its
  // enclosing menuitem remains visible and keyboard-operable.  Do not treat
  // that self annotation as a hidden menu; hidden ancestors still disqualify it.
  const sliders = [...candidates[0].querySelectorAll('[role="slider"]')].filter(element =>
    element.getClientRects().length > 0
    && !element.closest('[hidden],[inert],[role="menu"][data-state="closed"]')
    && !element.parentElement?.closest('[aria-hidden="true"]'));
  const choosers = [...document.querySelectorAll('[role="menuitem"]')]
    .filter(element => visible(element)
      && ['选择模型', 'Choose model'].includes(element.getAttribute('aria-label')));
  const menu = sliders.length === 1 ? sliders[0].closest('[role="menu"]') : null;
  return sliders.length === 1 && sliders[0].closest('[role="menuitem"]')
    && visible(sliders[0].closest('[role="menuitem"]')) && menu
    && choosers.length === 1 && choosers[0].closest('[role="menu"]') === menu
    ? candidates[0] : null;
}
function effortState() {
  const container = eligibleEffortContainer();
  if (!container) return null;
  const sliders = container.querySelectorAll('[role="slider"]');
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
    locked: !!container.querySelector('[data-locked="true"],[aria-disabled="true"]') };
}
function effortRangeShape() {
  // Failure-only, fixed shape probe. Never return labels, DOM, or request text.
  const bucket = count => count === 0 ? 'zero' : count === 1 ? 'one' : 'multiple';
  const visible = element => element.getClientRects().length > 0
    && !element.closest('[hidden],[inert],[aria-hidden="true"],[role="menu"][data-state="closed"]');
  const containers = [...document.querySelectorAll('[data-model-reasoning-effort-slider]')]
    .filter(visible);
  const newContainers = document.querySelectorAll('[data-model-picker-power-slider]');
  const newVisible = [...newContainers].filter(visible);
  const container = containers.length === 1 ? containers[0] : null;
  const sliders = container ? [...container.querySelectorAll('[role="slider"]')] : [];
  const slider = sliders.length === 1 ? sliders[0] : null;
  const globalSliders = document.querySelectorAll('[role="slider"]');
  const onlyGlobalSlider = globalSliders.length === 1 ? globalSliders[0] : null;
  const visibleSliders = [];
  for (const element of globalSliders) {
    if (visible(element)) visibleSliders.push(element);
    if (visibleSliders.length > 1) break;
  }
  const globalSlider = visibleSliders.length === 1 ? visibleSliders[0] : null;
  const ownerMenuitem = globalSlider?.closest('[role="menuitem"]');
  const ownerMenu = globalSlider?.closest('[role="menu"]');
  const choosers = [];
  for (const element of document.querySelectorAll('[role="menuitem"]')) {
    if (visible(element) && ['选择模型', 'Choose model'].includes(element.getAttribute('aria-label')))
      choosers.push(element);
    if (choosers.length > 1) break;
  }
  const chooserMenu = choosers.length === 1 ? choosers[0].closest('[role="menu"]') : null;
  const digit = (element, name) => {
    if (!element) return 'unknown';
    const value = element.getAttribute(name);
    return value === null ? 'absent' : /^[0-9]$/.test(value) ? Number(value) : 'other';
  };
  return {containerCount: bucket(containers.length),
    newContainerTotal: bucket(newContainers.length), newContainerVisible: bucket(newVisible.length),
    sliderCount: container ? bucket(sliders.length) : 'unknown',
    min: digit(slider, 'aria-valuemin'), max: digit(slider, 'aria-valuemax'),
    now: digit(slider, 'aria-valuenow'),
    locked: container ? container.querySelector('[data-locked="true"],[aria-disabled="true"]')
      ? 'yes' : 'no' : 'unknown',
    globalSliderTotal: bucket(globalSliders.length), globalSliderVisible: bucket(visibleSliders.length),
    globalMin: digit(globalSlider, 'aria-valuemin'), globalMax: digit(globalSlider, 'aria-valuemax'),
    globalNow: digit(globalSlider, 'aria-valuenow'),
    globalSliderRect: onlyGlobalSlider ? onlyGlobalSlider.getClientRects().length > 0 ? 'yes' : 'no' : 'unknown',
    globalSliderHidden: onlyGlobalSlider ? onlyGlobalSlider.closest('[hidden]') ? 'yes' : 'no' : 'unknown',
    globalSliderInert: onlyGlobalSlider ? onlyGlobalSlider.closest('[inert]') ? 'yes' : 'no' : 'unknown',
    globalSliderAriaHidden: onlyGlobalSlider ? onlyGlobalSlider.closest('[aria-hidden="true"]') ? 'yes' : 'no' : 'unknown',
    globalSliderClosedMenu: onlyGlobalSlider ? onlyGlobalSlider.closest('[role="menu"][data-state="closed"]') ? 'yes' : 'no' : 'unknown',
    globalSliderInNewContainer: onlyGlobalSlider && newVisible.length === 1
      ? onlyGlobalSlider.closest('[data-model-picker-power-slider]') === newVisible[0] ? 'yes' : 'no' : 'unknown',
    ownerMenuitem: globalSlider ? ownerMenuitem ? 'yes' : 'no' : 'unknown',
    ownerMenu: globalSlider ? ownerMenu ? 'yes' : 'no' : 'unknown',
    sameMenuAsChooser: globalSlider && ownerMenu && chooserMenu
      ? ownerMenu === chooserMenu ? 'yes' : 'no' : 'unknown'};
}
function focusEffort() {
  const container = eligibleEffortContainer();
  if (!container) throw new Error("web_effort_control_ambiguous");
  const control = container.querySelector('[role="slider"]')?.closest('[role="menuitem"]');
  if (!control) throw new Error("web_effort_control_missing");
  control.focus();
  if (document.activeElement !== control) throw new Error("web_effort_focus_failed");
}
function connectorAccessState() {
  // The initial temporary page can render before account plugin access loads.
  // Read only the public setting; never change personalization or permissions.
  const labels = ['个性化', '不个性化'];
  const controls = [...document.querySelectorAll('button')]
    .filter(e => e.getClientRects().length && !e.closest('[hidden],[inert],[aria-hidden="true"]')
      && (labels.includes(e.getAttribute('aria-label'))
        || (e.getAttribute('aria-label') === null && e.getAttribute('aria-haspopup') === 'menu'
          && labels.includes(e.textContent.trim()))));
  if (controls.length !== 1) return 'unknown';
  const label = controls[0].getAttribute('aria-label') ?? controls[0].textContent.trim();
  return label === '个性化' ? 'enabled' : 'disabled';
}
function connectorMenuChoice(name, query, activate = false, expectedId) {
  // Match the complete ASCII/CJK label, including a true end-of-input check.
  if (typeof name !== 'string' || !/^[A-Za-z0-9\u3400-\u4dbf\u4e00-\u9fff][A-Za-z0-9\u3400-\u4dbf\u4e00-\u9fff -]{0,63}(?![\s\S])/.test(name)
      || query !== '@' + name.split(' ')[0] || typeof activate !== 'boolean'
      || typeof expectedId !== 'string' || !/^plugin:asdk_app_[a-f0-9]{32}$/.test(expectedId))
    throw new Error("web_connector_query_invalid");
  const composer = uniqueComposer();
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
  if (matches.length) {
    if (activate) matches[0].click();
    return { name, id: expectedId, activated: activate };
  }
  if (rows.length) return null;
  // The current menu exposes a label but no app ID. This is only a provisional
  // pick: the caller must validate the exact ID on the resulting pill before
  // adding prompt text or sending anything. Duplicate labels fail closed.
  const current = [...document.querySelectorAll('[data-mention-list-scroll-area] button[data-list-navigation-item="true"]')]
    .filter(e => e.getClientRects().length && e.getAttribute('aria-disabled') !== 'true'
      && !e.closest('[hidden],[inert],[aria-hidden="true"]'));
  if (current.length > 512) throw new Error("web_connector_menu_too_large");
  const candidates = current.filter(e => [...e.querySelectorAll('span')]
    .some(label => label.textContent === name));
  if (candidates.length > 1) throw new Error("web_connector_menu_ambiguous");
  if (!candidates.length) return null;
  if (activate) candidates[0].click();
  return { name, id: null, activated: activate, identityPending: true };
}
function connectorPillState(expectedName) {
  if (typeof expectedName !== 'string' || !/^[A-Za-z0-9\u3400-\u4dbf\u4e00-\u9fff][A-Za-z0-9\u3400-\u4dbf\u4e00-\u9fff -]{0,63}(?![\s\S])/.test(expectedName))
    throw new Error("web_connector_name_invalid");
  const composer = uniqueComposer();
  if (!composer) throw new Error("web_composer_missing");
  const pills = composer.querySelectorAll('[data-inline-selection-pill]');
  const current = composer.querySelectorAll('span[app-mention-path]');
  if (!pills.length && !current.length) return null;
  if (pills.length && current.length) throw new Error("web_connector_mention_ambiguous");
  if (current.length) {
    if (current.length !== 1 || composer.querySelectorAll('[data-inline-selection-pill-cursor-target]').length)
      throw new Error("web_connector_mention_ambiguous");
    const pill = current[0], path = pill.getAttribute('app-mention-path');
    const label = pill.getAttribute('data-prompt-link-label');
    const paragraph = pill.parentElement, text = paragraph?.childNodes[1];
    if (!/^app:\/\/asdk_app_[a-f0-9]{32}$/.test(path || '')
        || pill.getAttribute('contenteditable') !== 'false'
        || pill.getAttribute('app-mention-display-name') !== expectedName
        || pill.getAttribute('data-prompt-link-href') !== path
        || !/^\$[a-z0-9-]{1,32}$/.test(label || '')
        || pill.getAttribute('app-mention-name') !== label.slice(1)
        || pill.textContent !== expectedName
        || paragraph?.tagName !== 'P' || paragraph.parentElement !== composer
        || paragraph.childNodes.length < 2 || paragraph.childNodes.length > 3
        || paragraph.childNodes[0] !== pill
        || (paragraph.childNodes.length === 3
          && (paragraph.childNodes[2].tagName !== 'SPAN'
            || paragraph.childNodes[2].getAttribute('data-prompt-literal-paste') !== ''))
        || text?.nodeType !== 3
        || !(text.textContent.startsWith(' ') || text.textContent.startsWith('\u00a0')))
      throw new Error("web_connector_mention_mismatch");
    return { id: 'plugin:' + path.slice(6), name: expectedName,
      prefix: expectedName + ' ', publicPrefix: '[' + label + '](' + path + ')\u00a0' };
  }
  const cursors = composer.querySelectorAll('[data-inline-selection-pill-cursor-target]');
  if (pills.length !== 1 || cursors.length !== 1) throw new Error("web_connector_mention_ambiguous");
  const pill = pills[0], cursor = cursors[0], id = pill.getAttribute('data-id');
  if (!/^plugin:asdk_app_[a-f0-9]{32}$/.test(id || '')
      || pill.getAttribute('contenteditable') !== 'false'
      || pill.getAttribute('data-system-hint-type') !== id
      || pill.getAttribute('data-symbol') !== 'ecosystemMention'
      || pill.getAttribute('data-keyword') !== expectedName || pill.textContent !== expectedName
      || cursor.getAttribute('contenteditable') !== 'false' || cursor.textContent !== '\uFEFF')
    throw new Error("web_connector_mention_mismatch");
  return { id, name: expectedName, prefix: '\uFEFF' + expectedName + ' ',
    publicPrefix: '@' + expectedName + ' ' };
}
function selectedConnector(expectedName) {
  const state = connectorPillState(expectedName);
  if (!state) return null;
  if (uniqueComposer().querySelectorAll('[data-prompt-literal-paste]').length)
    throw new Error("web_connector_mention_mismatch");
  if (uniqueComposer().textContent !== state.prefix) throw new Error("web_connector_mention_mismatch");
  return { id: state.id, name: state.name, publicPrefix: state.publicPrefix };
}
function composerPrefix(mention) {
  const composer = uniqueComposer();
  if (!composer) throw new Error("web_composer_missing");
  if (mention == null) {
    if (composer.textContent !== "") throw new Error("web_empty_composer_required");
    return "";
  }
  const state = connectorPillState(mention.name);
  if (!state || state.id !== mention.id) throw new Error("web_connector_mention_mismatch");
  if (composer.querySelectorAll('[data-prompt-literal-paste]').length)
    throw new Error("web_connector_composer_not_empty");
  if (composer.textContent !== state.prefix) throw new Error("web_connector_composer_not_empty");
  return state.prefix;
}
function focusComposer(prefix = "", replaceAppSeparator = false) {
  const composer = uniqueComposer();
  if (!composer || composer.textContent !== prefix) throw new Error("web_empty_composer_required");
  const current = composer.querySelectorAll('span[app-mention-path]');
  if (current.length > 1) throw new Error("web_connector_mention_ambiguous");
  let currentTail = null;
  if (current.length) {
    const state = connectorPillState(current[0].getAttribute('app-mention-display-name'));
    if (!state || state.prefix !== prefix) throw new Error("web_connector_mention_mismatch");
    currentTail = current[0].parentElement.childNodes[1];
  }
  composer.focus();
  if (document.activeElement !== composer) throw new Error("web_composer_focus_failed");
  const range = document.createRange();
  if (currentTail) {
    // Replace the one checked placeholder separator with the exact separator
    // and request text. The editor may otherwise retain it or consume it,
    // producing two spaces or none after the app pill.
    if (replaceAppSeparator) {
      if (currentTail.textContent !== ' ') throw new Error("web_connector_mention_mismatch");
      range.setStart(currentTail, 0);
      range.setEnd(currentTail, 1);
    } else {
      range.setStart(currentTail, currentTail.textContent.length);
      range.collapse(true);
    }
  } else {
    if (replaceAppSeparator) throw new Error("web_connector_mention_mismatch");
    range.selectNodeContents(composer);
    range.collapse(false);
  }
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
}
function composerMatches(text, prefix = "", mention = null) {
  const composer = uniqueComposer();
  if (!composer || document.activeElement !== composer) return false;
  const pills = composer.querySelectorAll('[data-inline-selection-pill]');
  const cursors = composer.querySelectorAll('[data-inline-selection-pill-cursor-target]');
  const current = composer.querySelectorAll('span[app-mention-path]');
  const literalPastes = composer.querySelectorAll('[data-prompt-literal-paste]');
  // The observed editor represents each inserted LF line as a direct P child,
  // including empty lines. textContent drops these boundaries; innerText adds
  // layout-dependent breaks around the application pill. Validate each node
  // against its exact original line instead of rewriting the submitted text.
  const paragraphs = [...composer.childNodes], lines = (prefix + text).split('\n');
  const exactParagraphs = literalPastes.length === 0
    && paragraphs.length > 0 && paragraphs.length <= 1024
    && paragraphs.length === lines.length && paragraphs.every((p, index) => {
      if (p.nodeType !== 1 || p.tagName !== 'P') return false;
      const exact = p.textContent === lines[index];
      // The current contenteditable represents the sole separator immediately
      // after an app pill as NBSP while editing. Bind that one DOM encoding to
      // the exact pill and text node; the posted public message must still
      // match the bound app-link projection before accepting any result.
      const encodedSeparator = index === 0 && !!mention && current.length === 1
        && prefix === mention.name + ' ' && p.childNodes.length === 2
        && p.childNodes[0] === current[0] && p.childNodes[1].nodeType === 3
        && p.childNodes[1].textContent === '\u00a0' + text.split('\n')[0];
      if (!exact && !encodedSeparator) return false;
      const breaks = p.querySelectorAll('br');
      return breaks.length === 0 || (breaks.length === 1 && p.textContent === '');
    });
  // The current editor keeps a pasted multi-line literal inside one SPAN,
  // with BR nodes carrying LF bytes. Reconstruct only these exact, bounded
  // public nodes; arbitrary markup or missing boundaries must not pass.
  const structuredText = () => {
    if (paragraphs.length !== 1 || paragraphs[0].nodeType !== 1
        || paragraphs[0].tagName !== 'P' || !paragraphs[0].childNodes
        || paragraphs[0].childNodes.length > 1024) return null;
    const allowedPill = mention && current.length === 1 ? current[0] : null;
    let value = '';
    const append = node => {
      if (node.nodeType === 3) return node.textContent;
      if (node === allowedPill) return node.textContent;
      if (node.tagName !== 'SPAN' || node.getAttribute('data-prompt-literal-paste') !== ''
          || node.attributes.length !== 1 || node.childNodes.length > 1024) return null;
      let literal = '';
      for (const child of node.childNodes) {
        if (child.nodeType === 3) literal += child.textContent;
        else if (child.tagName === 'BR' && child.attributes.length === 0
            && child.childNodes.length === 0) literal += '\n';
        else return null;
        if (literal.length > 1024 * 1024) return null;
      }
      return literal;
    };
    for (const node of paragraphs[0].childNodes) {
      const part = append(node);
      if (part === null || typeof part !== 'string') return null;
      value += part;
      if (value.length > 1024 * 1024) return null;
    }
    return value;
  };
  const exactStructuredText = structuredText() === prefix + text;
  // A plain multiline paste also becomes one P per source line. innerText can
  // add layout breaks, so accept only the exact ordered paragraph structure.
  if (mention == null) return prefix === '' && pills.length === 0 && cursors.length === 0
    && current.length === 0
    && (composer.innerText === text || exactParagraphs || exactStructuredText);
  let state;
  try { state = connectorPillState(mention.name); }
  catch (error) {
    if (error?.message === 'web_connector_mention_mismatch'
        || error?.message === 'web_connector_mention_ambiguous') return false;
    throw error;
  }
  return !!state && state.id === mention.id && state.prefix === prefix
    && (exactParagraphs || exactStructuredText);
}
function promptMismatchShape(text, prefix = "") {
  // Failure-only, fixed categories. Never return the prompt or editor text.
  const composer = uniqueComposer();
  if (!composer || typeof text !== 'string' || typeof prefix !== 'string') return null;
  const bucket = count => count === 0 ? 'zero' : count === 1 ? 'one'
    : count <= 8 ? 'few' : 'many';
  const kind = node => node?.nodeType === 3 ? 'text'
    : node?.tagName === 'BR' ? 'break'
    : node?.getAttribute?.('app-mention-path') ? 'app_pill'
    : node?.getAttribute?.('data-prompt-literal-paste') === '' ? 'literal'
    : 'other';
  const paragraphs = [...composer.childNodes];
  const first = paragraphs[0], nodes = [...(first?.childNodes || [])];
  const literal = [...composer.querySelectorAll('[data-prompt-literal-paste]')];
  const literalNodes = [...(literal[0]?.childNodes || [])];
  const expected = prefix + text;
  const lines = expected.split('\n');
  return { paragraphs: bucket(paragraphs.length), nodes: bucket(nodes.length),
    nodeKinds: nodes.slice(0, 8).map(kind), literalPastes: bucket(literal.length),
    literalKinds: literalNodes.slice(0, 8).map(kind),
    paragraphCount: Math.min(9, paragraphs.length), expectedLines: Math.min(9, lines.length),
    lineMatches: paragraphs.slice(0, 8).map((p, index) =>
      p.nodeType === 1 && p.tagName === 'P' && p.textContent === lines[index]),
    firstExpectedEndsCR: lines[0]?.endsWith('\r') === true,
    firstMatchesWithoutCR: lines[0]?.endsWith('\r') === true
      && first?.textContent === lines[0].slice(0, -1),
    firstStartsWithPrefix: typeof first?.textContent === 'string'
      && first.textContent.startsWith(prefix),
    firstPillMatchesName: nodes[0]?.textContent === prefix.trimEnd(),
    firstNodeMatchesTailWithSpace: nodes[1]?.nodeType === 3
      && nodes[1].textContent === ' ' + text.split('\n')[0],
    firstNodeMatchesTailNoSpace: nodes[1]?.nodeType === 3
      && nodes[1].textContent === text.split('\n')[0],
    firstNodeStartsWithSpace: nodes[1]?.nodeType === 3
      && nodes[1].textContent.startsWith(' '),
    firstNodeStartsWithNbsp: nodes[1]?.nodeType === 3
      && nodes[1].textContent.startsWith('\u00a0'),
    firstNodeMatchesTailWithNbsp: nodes[1]?.nodeType === 3
      && nodes[1].textContent === '\u00a0' + text.split('\n')[0],
    firstNodeMatchesTailWithTwoSpaces: nodes[1]?.nodeType === 3
      && nodes[1].textContent === '  ' + text.split('\n')[0],
    firstMatchesWithoutSeparator: prefix.endsWith(' ')
      && first?.textContent === prefix.slice(0, -1) + text.split('\n')[0],
    firstMatchesWithNbspSeparator: prefix.endsWith(' ')
      && first?.textContent === prefix.slice(0, -1) + '\u00a0' + text.split('\n')[0],
    secondNodeKinds: [...(paragraphs[1]?.childNodes || [])].slice(0, 8).map(kind),
    innerTextExact: composer.innerText === expected,
    textContentExact: composer.textContent === expected,
    expectedNewlines: bucket((expected.match(/\n/g) || []).length),
    renderedNewlines: bucket(((composer.innerText || '').match(/\n/g) || []).length) };
}
function sendOnce() {
  // A route can change between the host's readiness check and the click. A
  // retained modern conversation must never receive this new task's input.
  if (document.querySelectorAll('[data-message-author-role],[data-chatgpt-search-unit-key]').length)
    throw new Error("web_fresh_page_required");
  const form = uniqueComposer()?.closest("form");
  const legacy = [...(form?.querySelectorAll('[data-testid="send-button"]') || [])];
  const current = legacy.length ? [] : [...(form?.querySelectorAll('button[type="submit"]') || [])]
    .filter(e => ['发送', 'Send'].includes(e.getAttribute('aria-label')));
  const buttons = [...legacy, ...current].filter(e => e.getClientRects().length
    && !e.disabled && e.getAttribute("aria-disabled") !== "true"
    && !e.closest('[hidden],[inert],[aria-hidden="true"]'));
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
      else if (!!left !== !!right) {
        // A completed row can retain its old DOM seed after React removes
        // that seed from one parent's child list. Prove the sole remaining
        // child belongs to the current parent before reading its props.
        const owner = left ? parent : other;
        if (resolve(owner, level + 1) !== owner) invalid();
        return finish((left || right) === first);
      }
      else invalid();
    }
    invalid();
  };
  return resolve(fiber);
}

function modernPublicItem(role, committedView = false) {
  // The current renderer binds a visible message unit to one item, rather
  // than exposing the former message row. Read only that row's item and the
  // containing turn's terminal flags; never walk a turn-wide message list.
  const rows = [...document.querySelectorAll('[data-chatgpt-search-unit-key]')]
    .filter(row => row.getAttribute('data-chatgpt-search-unit-key')?.endsWith(':' + role));
  if (!rows.length) return null;
  if (rows.length !== 1) throw new Error('web_public_message_ambiguous');
  const row = rows[0], key = row.getAttribute('data-chatgpt-search-unit-key');
  const rawIds = row.getAttribute('data-chatgpt-search-message-ids');
  const ids = typeof rawIds === 'string' ? rawIds.trim().split(/\s+/) : [];
  if (!row.getClientRects().length || row.closest('[hidden],[inert],[aria-hidden="true"]')
      || !/^[A-Za-z0-9_-]{1,80}:[0-9]{1,4}:(?:user|assistant)$/.test(key || '')
      || !ids.length || ids.length > 8
      || !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(ids[0])
      || ids.some(id => id !== ids[0])) throw new Error('web_public_message_identity_invalid');
  const id = ids[0];
  if (role === 'user') {
    if (row.querySelectorAll('[data-user-message-bubble="true"]').length !== 1)
      throw new Error('web_public_message_identity_invalid');
  } else {
    const selected = row.querySelectorAll('[data-chatgpt-selection-message-id]');
    // During a tool step the assistant unit can exist before its final
    // selection marker. It is not a completed public answer yet.
    if (selected.length === 0) return null;
    if (selected.length !== 1 || selected[0].getAttribute('data-chatgpt-selection-message-id') !== id)
      throw new Error('web_public_message_identity_invalid');
  }
  const fiberKey = Object.keys(row).find(name => name.startsWith('__reactFiber$'));
  let fiber = fiberKey ? row[fiberKey] : null, item = null, turn = null;
  for (let depth = 0; fiber && depth < 45; depth++, fiber = fiber.return) {
    const current = committedView ? currentPublicFiber(fiber) : fiber;
    const props = current.memoizedProps;
    if (props?.item?.messageId === id && props.item.type === role + '-message')
      item ??= props.item;
    if (props?.entry?.turn && turn === null) turn = props.entry.turn;
    if (item && turn) break;
  }
  if (!item || !turn) throw new Error('web_public_message_source_unavailable');
  return { id, item, turn };
}

function modernIdentityShape() {
  // Failure-only public DOM structure; never export IDs, labels or messages.
  const rows = [...document.querySelectorAll('[data-chatgpt-search-unit-key]')]
    .filter(row => row.getAttribute('data-chatgpt-search-unit-key')?.endsWith(':assistant'));
  const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
  return { assistantRows: Math.min(9, rows.length), rows: rows.slice(0, 4).map(row => {
    const key = row.getAttribute('data-chatgpt-search-unit-key');
    const raw = row.getAttribute('data-chatgpt-search-message-ids');
    const bounded = typeof raw === 'string' && raw.length <= 2048;
    const ids = bounded ? raw.trim().split(/\s+/).filter(Boolean) : [];
    const selected = [...row.querySelectorAll('[data-chatgpt-selection-message-id]')];
    const chosen = selected.length === 1
      ? selected[0].getAttribute('data-chatgpt-selection-message-id') : null;
    return { keyPattern: /^[A-Za-z0-9_-]{1,80}:[0-9]{1,4}:assistant$/.test(key || ''),
      visible: !!row.getClientRects().length,
      hidden: !!row.closest('[hidden],[inert],[aria-hidden="true"]'),
      idsBounded: bounded, idsCount: Math.min(9, ids.length),
      allIdsUuid: ids.length > 0 && ids.every(id => uuid.test(id)),
      allIdsEqual: ids.length > 0 && ids.every(id => id === ids[0]),
      selectedCount: Math.min(9, selected.length), selectedUuid: uuid.test(chosen || ''),
      selectedFirst: !!chosen && chosen === ids[0],
      selectedLast: !!chosen && chosen === ids[ids.length - 1],
      selectedAny: !!chosen && ids.includes(chosen) };
  }) };
}

function projectPublicReferences(references) {
  if (!Array.isArray(references) || references.length > 128)
    throw new Error('web_public_citations_invalid');
  // Both observed renderers use these public reference fields. Never export
  // snippets, search queries, prompt_text or unrelated account data.
  const textField = (value, maximum) => {
    if (typeof value !== 'string' || value.length > maximum)
      throw new Error('web_public_citation_field_invalid');
    return value;
  };
  const sources = values => {
    if (!Array.isArray(values) || values.length > 64)
      throw new Error('web_public_citation_sources_invalid');
    return values.map(value => ({ title: textField(value?.title, 2048),
      url: textField(value?.url, 8192) }));
  };
  return references.map(reference => {
    if (!reference || typeof reference !== 'object' || Array.isArray(reference))
      throw new Error('web_public_citations_invalid');
    const value = { type: textField(reference.type, 64),
      matched_text: textField(reference.matched_text, 2048) };
    for (const key of ['start_idx', 'end_idx']) {
      if (!Number.isSafeInteger(reference[key]) || reference[key] < 0
          || reference[key] > 1024 * 1024)
        throw new Error('web_public_citation_position_invalid');
      value[key] = reference[key];
    }
    if (reference.items != null) value.items = sources(reference.items);
    if (reference.sources != null) value.sources = sources(reference.sources);
    if (reference.type === 'url') {
      value.title = textField(reference.title, 2048);
      value.item = sources([reference.item])[0];
    }
    return value;
  });
}

function modernPublicFinal(prompt, includeCitations = false, committedView = false) {
  const currentItem = role => {
    try { return modernPublicItem(role, committedView); }
    catch (error) {
      // A row in React's concurrent pending branch is not a committed answer.
      // Wait for a later stable observation; never accept its current props.
      if (committedView && error?.message === 'web_public_current_branch_unavailable') return null;
      throw error;
    }
  };
  const user = currentItem('user');
  if (!user) return null;
  if (typeof user.item.message !== 'string' || user.item.message !== prompt)
    throw new Error('web_user_turn_mismatch');
  const final = currentItem('assistant');
  if (!final) return null;
  // Identical prompt text and a completed assistant item cannot bind a reply
  // from an earlier turn. Both visible units must share their exact turn.
  if (final.turn !== user.turn) return null;
  const message = final.item;
  if (message.completed !== true || message.phase !== 'final_answer'
      || message.latestMessageId !== final.id
      || !Array.isArray(message.sourceMessageIds)
      || message.sourceMessageIds.length !== 1 || message.sourceMessageIds[0] !== final.id
      || final.turn.status !== 'complete'
      || !Number.isFinite(final.turn.workCompletedAtMs) || final.turn.workCompletedAtMs <= 0)
    return null;
  if (typeof message.content !== 'string' || message.structuredOutput != null)
    throw new Error('web_public_content_unsupported');
  const references = message.contentReferences;
  // This renderer's public source is one exact content string, unlike the
  // earlier parts array. No split, trim or reconstruction is permitted.
  const result = { id: final.id, author: { role: 'assistant' }, recipient: null,
    channel: 'final', end_turn: true, status: 'finished_successfully',
    metadata: { operator_web_renderer: 'modern_content_references_v1' },
    content: { content_type: 'text', parts: [message.content] } };
  if (includeCitations) result.public_references = projectPublicReferences(references ?? []);
  if (new TextEncoder().encode(JSON.stringify(result)).length > 1024 * 1024)
    throw new Error('web_public_message_too_large');
  return result;
}

function publicFinal(prompt, includeCitations = false, committedView = false) {
  if (document.querySelector('[data-testid="stop-button"]')) return null;
  const users = [...document.querySelectorAll('[data-message-author-role="user"]')];
  if (!users.length && document.querySelector('[data-chatgpt-search-unit-key]'))
    return modernPublicFinal(prompt, includeCitations, committedView);
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
          if (includeCitations) result.public_references = projectPublicReferences(meta?.content_references ?? []);
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
  if (!users.length && document.querySelector('[data-chatgpt-search-unit-key]')) {
    const user = modernPublicItem('user', committedView);
    if (!user) return null;
    const source = user.item.message;
    if (typeof source !== 'string' || source.length > 1024 * 1024 || prompt.length > 65536)
      return { supportedTextShape: false };
    let firstDifference = 0;
    while (firstDifference < Math.min(source.length, prompt.length)
        && source[firstDifference] === prompt[firstDifference]) firstDifference++;
    const appHead = /^\[\$[a-z0-9-]{1,32}\]\(app:\/\/asdk_app_[a-f0-9]{32}\)/.exec(prompt)?.[0];
    // The editor's one app separator has two public text encodings. This
    // classifies only that character; the bound app link and every body byte
    // must already match. The host must recheck the selected exact projection.
    const appSeparatorOnly = !!appHead && source !== prompt && source.startsWith(appHead)
      && [' ', '\u00a0'].includes(source[appHead.length])
      && [' ', '\u00a0'].includes(prompt[appHead.length])
      && source.slice(appHead.length + 1) === prompt.slice(appHead.length + 1);
    return { supportedTextShape: true, exact: source === prompt,
      appSeparatorOnly,
      sourceLength: source.length, promptLength: prompt.length,
      firstDifference: source === prompt ? -1 : firstDifference };
  }
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
  const legacyRows = [...document.querySelectorAll('[data-message-author-role="assistant"][data-message-id]')];
  const rows = legacyRows
    .filter(element => element.getAttribute('data-message-id') === messageId && visible(element));
  const modernRows = document.querySelectorAll('[data-chatgpt-search-unit-key]');
  if (modernRows.length && legacyRows.length === 0) {
    const current = modernPublicItem('assistant', true);
    if (!current || current.id !== messageId) throw new Error('web_inspection_message_ambiguous');
  } else if (modernRows.length || rows.length !== 1) {
    throw new Error('web_inspection_message_ambiguous');
  }
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

module.exports = { uniqueComposer, eligibleModelButtons, eligibleEffortContainer, controls, startupControlStructure, freshChatControls, freshChatControlStructure, pluginMaintenanceReady, startFreshChat, enableTemporaryChat, currentPublicFiber, publicGenerationState, publicInterruptionState, inspectionSnapshot, focusModelMenu, clickModelChooser, chooseModel, effortState, effortRangeShape,
  backgroundModelInput, backgroundMenuKey, composerFocused, emptyFreshChat,
  focusEffort, connectorAccessState, connectorMenuChoice, connectorPillState, selectedConnector, composerPrefix, focusComposer, composerMatches, promptMismatchShape, sendOnce, cancelGeneration, modernPublicItem, modernIdentityShape, projectPublicReferences, modernPublicFinal, publicFinal, publicMessageShape, publicUserBindingShape, publicCitationShape };

/*
 * FoxMCP Firefox Extension - Content Script
 * Copyright (c) 2024 FoxMCP Project
 * Licensed under the MIT License - see LICENSE file for details
 */

// Content script for page interaction
console.log('FoxMCP content script loaded');

function expireFileHandle(handles, fileId, delay) {
  setTimeout(() => handles.delete(fileId), delay);
}

// Elements a snapshot lists. Anything clickable or editable, plus headings so
// the listing reads as an outline of the page rather than a bag of controls.
const INTERACTIVE_SELECTOR = [
  'a[href]', 'button', 'input', 'select', 'textarea', 'summary', 'label',
  '[role=button]', '[role=link]', '[role=checkbox]', '[role=radio]', '[role=switch]',
  '[role=tab]', '[role=menuitem]', '[role=option]', '[role=combobox]', '[role=textbox]',
  '[role=row]', '[contenteditable=""]', '[contenteditable=true]', '[tabindex]:not([tabindex="-1"])',
  'h1', 'h2', 'h3'
].join(',');

const REF_ATTR = 'data-foxmcp-ref';
let nextRef = 1;

function isVisible(el) {
  const rect = el.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) {
    return false;
  }
  const style = (el.ownerDocument.defaultView || window).getComputedStyle(el);
  return style.visibility !== 'hidden' && style.display !== 'none' && style.opacity !== '0';
}

// Every root a page's elements can live in: the document, the open shadow roots
// inside it, and the documents of same-origin iframes (a cross-origin frame is
// out of reach). Web components and embedded editors hide their controls there.
function searchRoots(root = document, roots = []) {
  roots.push(root);
  for (const el of root.querySelectorAll('*')) {
    if (el.shadowRoot) {
      searchRoots(el.shadowRoot, roots);
    }
    if (el.tagName === 'IFRAME' || el.tagName === 'FRAME') {
      try {
        if (el.contentDocument) searchRoots(el.contentDocument, roots);
      } catch (error) {
        // cross-origin
      }
    }
  }
  return roots;
}

// A ref stays on its element across snapshots, so a ref read from one
// snapshot still works after the page re-renders other parts of itself.
function refFor(el) {
  let ref = el.getAttribute(REF_ATTR);
  if (!ref) {
    ref = 'r' + nextRef++;
    el.setAttribute(REF_ATTR, ref);
  }
  return ref;
}

const BUTTON_INPUT_TYPES = ['button', 'submit', 'reset'];

function oneLine(text, max) {
  return (text || '').replace(/\s+/g, ' ').trim().slice(0, max);
}

// A field's label, so a form reads as "Email" rather than as a row of blanks,
// and its current value, which is what tells a client what is already filled in.
function describe(el) {
  const role = el.getAttribute('role') || el.tagName.toLowerCase();
  const isField = ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)
    && !BUTTON_INPUT_TYPES.includes(el.type);
  const name = oneLine(el.getAttribute('aria-label')
    || (isField ? (el.labels && el.labels[0] && el.labels[0].innerText) || el.placeholder || el.title
      : el.innerText || el.value || el.title || el.alt), 80);
  const extras = [];
  if (el.type && el.tagName === 'INPUT') extras.push('type=' + el.type);
  if (isField && el.type !== 'password' && el.type !== 'checkbox' && el.type !== 'radio'
      && el.type !== 'file') {
    const value = el.tagName === 'SELECT'
      ? Array.from(el.selectedOptions).map(option => option.text).join(', ')
      : el.value;
    if (value) extras.push(`value="${oneLine(value, 40)}"`);
  }
  if (el.disabled) extras.push('disabled');
  if (el.required) extras.push('required');
  if (el.readOnly) extras.push('readonly');
  if (el.checked || el.getAttribute('aria-checked') === 'true') extras.push('checked');
  if (el.getAttribute('aria-selected') === 'true') extras.push('selected');
  const expanded = el.getAttribute('aria-expanded');
  if (expanded) extras.push(expanded === 'true' ? 'expanded' : 'collapsed');
  if (el.getRootNode().activeElement === el) extras.push('focused');
  return `[${refFor(el)}] ${role} "${name}"${extras.length ? ' (' + extras.join(', ') + ')' : ''}`;
}

function inViewport(el) {
  const rect = el.getBoundingClientRect();
  const view = el.ownerDocument.defaultView || window;
  return rect.bottom > 0 && rect.right > 0 && rect.top < view.innerHeight && rect.left < view.innerWidth;
}

function snapshot(maxElements, viewportOnly) {
  const lines = [];
  for (const root of searchRoots()) {
    let titled = root === document;
    for (const el of root.querySelectorAll(INTERACTIVE_SELECTOR)) {
      if (!isVisible(el) || (viewportOnly && !inViewport(el))) continue;
      if (!titled) {
        titled = true;
        lines.push(`-- ${root.host ? 'inside ' + root.host.tagName.toLowerCase() + ' (shadow DOM)' : 'frame ' + (root.location?.href || '')}`);
      }
      lines.push(describe(el));
      if (lines.length >= maxElements) {
        lines.push(`... truncated at ${maxElements} elements`);
        return lines.join('\n');
      }
    }
  }
  return lines.join('\n');
}

function findTarget({ ref, selector }) {
  const find = root => ref ? root.querySelector(`[${REF_ATTR}="${CSS.escape(ref)}"]`) : root.querySelector(selector);
  let el = find(document);
  if (!el) {
    for (const root of searchRoots().slice(1)) {
      el = find(root);
      if (el) break;
    }
  }
  if (!el) {
    throw new Error(ref ? `No element with ref ${ref}; take a new snapshot` : `No element matches ${selector}`);
  }
  return el;
}

// Sites listen on pointerdown or mousedown as often as on click (Google Drive's
// menus open on mousedown), so the whole sequence is dispatched at the element's
// centre rather than calling el.click(). A double click repeats the sequence
// with the click count in `detail` and ends with dblclick, which is what opens
// a folder in Google Drive; a lone dblclick event is ignored there.
function clickElement(el, clicks = 1) {
  el.scrollIntoView({ block: 'center', inline: 'center' });
  const rect = el.getBoundingClientRect();
  const init = {
    bubbles: true, cancelable: true, composed: true, view: window, button: 0,
    clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2
  };
  el.dispatchEvent(new PointerEvent('pointerover', init));
  el.dispatchEvent(new MouseEvent('mouseover', init));
  for (let detail = 1; detail <= clicks; detail++) {
    el.dispatchEvent(new PointerEvent('pointerdown', { ...init, detail, buttons: 1 }));
    el.dispatchEvent(new MouseEvent('mousedown', { ...init, detail, buttons: 1 }));
    if (typeof el.focus === 'function') el.focus();
    el.dispatchEvent(new PointerEvent('pointerup', { ...init, detail }));
    el.dispatchEvent(new MouseEvent('mouseup', { ...init, detail }));
    el.dispatchEvent(new MouseEvent('click', { ...init, detail }));
  }
  if (clicks === 2) {
    el.dispatchEvent(new MouseEvent('dblclick', { ...init, detail: 2 }));
  }
}

// insertText goes through the editor's own input path, so frameworks that track
// value through input events (React, Vue) see the change. Setting .value directly
// is the fallback for inputs where the command is refused.
function typeInto(el, text, clear) {
  el.scrollIntoView({ block: 'center' });
  el.focus();
  if (clear) {
    if (el.isContentEditable) {
      document.execCommand('selectAll');
    } else if (typeof el.select === 'function') {
      el.select();
    }
  }
  if (document.execCommand('insertText', false, text)) {
    return;
  }
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
  setter.call(el, clear ? text : el.value + text);
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

// Events a script dispatches are not trusted, and a few sites ignore them. After
// an action this watches the page for a moment and says whether anything
// reacted, so a client can tell a click that worked from one that did nothing.
// A navigation ends the wait at once: the page is about to be replaced.
function watchReaction(action, windowMs = 400) {
  return new Promise(resolve => {
    let changed = false;
    const observer = new MutationObserver(records => {
      // The agent's own overlay moves while it works; it is not the page reacting.
      if (records.some(r => !(r.target.id === OVERLAY_ID || r.target.getRootNode?.().host?.id === OVERLAY_ID))) {
        changed = true;
      }
    });
    observer.observe(document, { subtree: true, childList: true, attributes: true, characterData: true });
    const finish = reaction => {
      observer.disconnect();
      window.removeEventListener('pagehide', onLeave);
      resolve(reaction);
    };
    const onLeave = () => finish('page navigating');
    window.addEventListener('pagehide', onLeave);
    action();
    setTimeout(() => finish(changed ? 'page changed' : 'no visible reaction'), windowMs);
  });
}

// What a pointer moving onto an element fires: enter events reach every
// ancestor the pointer newly enters, which is what opens hover menus.
function hoverElement(el) {
  el.scrollIntoView({ block: 'center', inline: 'center' });
  const rect = el.getBoundingClientRect();
  const init = {
    bubbles: true, cancelable: true, composed: true, view: window,
    clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2
  };
  const chain = [];
  for (let node = el; node && node.nodeType === 1; node = node.parentElement) chain.unshift(node);
  for (const node of chain) {
    node.dispatchEvent(new PointerEvent('pointerenter', { ...init, bubbles: false }));
    node.dispatchEvent(new MouseEvent('mouseenter', { ...init, bubbles: false }));
  }
  el.dispatchEvent(new PointerEvent('pointerover', init));
  el.dispatchEvent(new MouseEvent('mouseover', init));
  el.dispatchEvent(new PointerEvent('pointermove', init));
  el.dispatchEvent(new MouseEvent('mousemove', init));
}

// A drag and drop as a page's HTML5 handlers see it, with a shared
// DataTransfer, plus the mouse events that libraries built on them use.
function dragElement(source, destination) {
  source.scrollIntoView({ block: 'center', inline: 'center' });
  const from = source.getBoundingClientRect();
  const to = destination.getBoundingClientRect();
  const at = (rect) => ({ clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 });
  const base = { bubbles: true, cancelable: true, composed: true, view: window };
  let transfer;
  try {
    transfer = new window.wrappedJSObject.DataTransfer();
  } catch (error) {
    transfer = undefined;
  }
  const dragEvent = (type, rect) => {
    const init = { ...base, ...at(rect) };
    try {
      return new DragEvent(type, transfer ? { ...init, dataTransfer: transfer } : init);
    } catch (error) {
      return new DragEvent(type, init);
    }
  };
  source.dispatchEvent(new PointerEvent('pointerdown', { ...base, ...at(from), button: 0, buttons: 1 }));
  source.dispatchEvent(new MouseEvent('mousedown', { ...base, ...at(from), button: 0, buttons: 1 }));
  source.dispatchEvent(dragEvent('dragstart', from));
  source.dispatchEvent(dragEvent('drag', from));
  destination.dispatchEvent(new MouseEvent('mousemove', { ...base, ...at(to), buttons: 1 }));
  destination.dispatchEvent(dragEvent('dragenter', to));
  destination.dispatchEvent(dragEvent('dragover', to));
  destination.dispatchEvent(dragEvent('drop', to));
  source.dispatchEvent(dragEvent('dragend', to));
  destination.dispatchEvent(new PointerEvent('pointerup', { ...base, ...at(to), button: 0 }));
  destination.dispatchEvent(new MouseEvent('mouseup', { ...base, ...at(to), button: 0 }));
}

// Picks an option of a <select> by value, then by its visible text, and tells
// the page through the events a person's choice would fire.
function selectOption(el, wanted) {
  if (el.tagName !== 'SELECT') {
    throw new Error('Target must be a <select>');
  }
  const wantedList = Array.isArray(wanted) ? wanted : [wanted];
  const options = Array.from(el.options);
  const chosen = wantedList.map(item => {
    const option = options.find(o => o.value === item) || options.find(o => oneLine(o.text, 200) === item)
      || options.find(o => oneLine(o.text, 200).toLowerCase() === String(item).toLowerCase());
    if (!option) {
      throw new Error(`No option "${item}" in ${describe(el)}; options: `
        + options.slice(0, 20).map(o => `"${oneLine(o.text, 40)}"`).join(', '));
    }
    return option;
  });
  if (chosen.length > 1 && !el.multiple) {
    throw new Error('Several options given for a <select> that is not multiple');
  }
  for (const option of options) option.selected = chosen.includes(option);
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

// Sets one form field to a value, whatever kind of field it is.
function fillField(el, value) {
  if (el.tagName === 'SELECT') {
    selectOption(el, value);
  } else if (el.tagName === 'INPUT' && (el.type === 'checkbox' || el.type === 'radio')) {
    const wanted = value === true || String(value).toLowerCase() === 'true';
    if (el.checked !== wanted) clickElement(el);
  } else {
    typeInto(el, String(value), true);
  }
}

function pressKey(el, key) {
  const init = { key, bubbles: true, cancelable: true, composed: true };
  const notCancelled = el.dispatchEvent(new KeyboardEvent('keydown', init));
  el.dispatchEvent(new KeyboardEvent('keyup', init));
  // A synthetic Enter does not submit a form, so do what the browser would.
  if (key === 'Enter' && notCancelled && el.form && el.tagName !== 'TEXTAREA') {
    el.form.requestSubmit();
  }
}

// Many sites (Google Drive among them) open the file dialog by calling click()
// on an <input type=file> they create on the spot, and a native dialog is not
// something an extension can fill in. While armed, this swaps the page's own
// click() and showPicker() so the next file input is handed back here instead
// of opening the dialog. It goes through wrappedJSObject because the page's
// prototypes are invisible from the content script's side.
function captureNextFileInput(timeoutMs) {
  const proto = window.wrappedJSObject.HTMLInputElement.prototype;
  const originalClick = proto.click;
  const originalShowPicker = proto.showPicker;
  return new Promise((resolve, reject) => {
    const restore = () => {
      proto.click = originalClick;
      proto.showPicker = originalShowPicker;
    };
    const timer = setTimeout(() => {
      restore();
      reject(new Error('The trigger did not open a file dialog'));
    }, timeoutMs);
    const intercept = exportFunction(function () {
      if (this.type !== 'file') {
        return originalClick.call(this);
      }
      clearTimeout(timer);
      restore();
      // Inputs created just for the dialog are often never attached, and a
      // detached element cannot be found again by ref.
      if (!this.isConnected) {
        this.hidden = true;
        document.body.appendChild(this);
      }
      resolve(this);
    }, window);
    proto.click = intercept;
    proto.showPicker = intercept;
  });
}

// webkitRelativePath is what tells a page the files came from a folder (and
// which subfolder each sits in), so it is set where the page reads it.
function setInputFiles(el, files, relativePaths) {
  if (el.tagName !== 'INPUT' || el.type !== 'file') {
    throw new Error('Target must be an <input type=file>');
  }
  // Files built in the extension belong to it, and the page gets "Permission
  // denied" reading them. Cloned into the page and set through the page's own
  // DataTransfer, they are ordinary files as far as the page can tell.
  const transfer = new window.wrappedJSObject.DataTransfer();
  for (const file of files) {
    transfer.items.add(cloneInto(file, window));
  }
  el.wrappedJSObject.files = transfer.files;
  const pageFiles = el.wrappedJSObject.files;
  // A browser only reports folder paths for inputs that pick folders, so a
  // folder given to a plain file input arrives as loose files, as it would.
  for (let i = 0; i < pageFiles.length; i++) {
    if (el.webkitdirectory && relativePaths[i]) {
      Object.defineProperty(pageFiles[i], 'webkitRelativePath', {
        value: relativePaths[i], configurable: true
      });
    }
  }
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  return Array.from({ length: pageFiles.length },
    (_, i) => pageFiles[i].webkitRelativePath || pageFiles[i].name);
}

// Overlay shown while an agent acts on the tab: a glowing border, a label and a
// cursor that moves to each element before it is clicked or typed into. It is
// purely visual (pointer-events: none) and fades once the agent goes quiet, so
// the tab looks normal again when the person takes over.
const OVERLAY_ID = 'foxmcp-agent-overlay';
const OVERLAY_IDLE_MS = 6000;
const CURSOR_MOVE_MS = 350;
let overlayTimer = null;
let cursorPos = null;

function overlayRoot() {
  let host = document.getElementById(OVERLAY_ID);
  if (!host) {
    host = document.createElement('div');
    host.id = OVERLAY_ID;
    host.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:2147483647;';
    const root = host.attachShadow({ mode: 'open' });
    root.innerHTML = `
      <style>
        :host { transition: opacity .4s; }
        .glow { position:fixed; inset:0; box-shadow: inset 0 0 0 2px rgba(217,119,87,.9), inset 0 0 22px rgba(217,119,87,.5); }
        .label { position:fixed; left:50%; bottom:14px; transform:translateX(-50%); display:flex; align-items:center; gap:8px;
          padding:7px 14px; border-radius:999px; background:rgba(28,25,23,.92); color:#fff;
          font:500 13px/1 system-ui, sans-serif; box-shadow:0 2px 10px rgba(0,0,0,.3); white-space:nowrap; }
        .dot { width:8px; height:8px; border-radius:50%; background:rgb(217,119,87); }
        .cursor { position:fixed; left:0; top:0; width:22px; height:22px; opacity:0; filter:drop-shadow(0 1px 2px rgba(0,0,0,.45)); }
        .ripple { position:fixed; width:28px; height:28px; margin:-14px 0 0 -14px; border-radius:50%;
          border:2px solid rgb(217,119,87); animation:ripple .45s ease-out forwards; }
        @keyframes ripple { from { transform:scale(.3); opacity:1; } to { transform:scale(1.4); opacity:0; } }
      </style>
      <div class="glow"></div>
      <div class="label"><span class="dot"></span>AI agent is working in this tab</div>
      <svg class="cursor" viewBox="0 0 22 22" xmlns="http://www.w3.org/2000/svg">
        <path d="M2 1.5 L2 18 L6.6 13.9 L9.6 20.5 L12.5 19.2 L9.6 12.7 L15.8 12.7 Z" fill="rgb(217,119,87)" stroke="#fff" stroke-width="1.4" stroke-linejoin="round"/>
      </svg>`;
    document.documentElement.appendChild(host);
  }
  return host;
}

function showOverlay() {
  const host = overlayRoot();
  host.style.opacity = '1';
  host.style.visibility = 'visible';
  clearTimeout(overlayTimer);
  overlayTimer = setTimeout(() => { host.style.opacity = '0'; }, OVERLAY_IDLE_MS);
}

async function moveCursorTo(el, press) {
  el.scrollIntoView({ block: 'center', inline: 'center' });
  const rect = el.getBoundingClientRect();
  const to = { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  const from = cursorPos || to;
  cursorPos = to;
  const root = overlayRoot().shadowRoot;
  const cursor = root.querySelector('.cursor');
  cursor.style.transition = 'none';
  cursor.style.opacity = '1';
  cursor.style.transform = `translate(${from.x}px, ${from.y}px)`;
  cursor.getBoundingClientRect();
  cursor.style.transition = `transform ${CURSOR_MOVE_MS}ms cubic-bezier(.3,.7,.4,1)`;
  cursor.style.transform = `translate(${to.x}px, ${to.y}px)`;
  await new Promise(resolve => setTimeout(resolve, CURSOR_MOVE_MS));
  if (press) {
    const ripple = document.createElement('div');
    ripple.className = 'ripple';
    ripple.style.left = to.x + 'px';
    ripple.style.top = to.y + 'px';
    root.appendChild(ripple);
    setTimeout(() => ripple.remove(), 500);
  }
}

// A native alert, confirm or prompt blocks the page and nothing in an
// extension can answer it, so while handling is on the page's own functions are
// replaced: they record the dialog and answer it as the client chose. This lasts
// until the page navigates, which discards the replacements.
const dialogState = { mode: 'off', promptText: null, log: [], originals: null };

function setDialogHandling(mode, promptText) {
  const page = window.wrappedJSObject;
  dialogState.promptText = promptText ?? null;
  if (mode === 'off') {
    if (dialogState.originals) {
      Object.assign(page, dialogState.originals);
      dialogState.originals = null;
    }
    dialogState.mode = 'off';
    return;
  }
  dialogState.mode = mode;
  if (dialogState.originals) {
    return;
  }
  dialogState.originals = { alert: page.alert, confirm: page.confirm, prompt: page.prompt };
  const record = (type, message, extra) => dialogState.log.push(
    { type, message: String(message ?? ''), accepted: dialogState.mode === 'accept', ...extra });
  page.alert = exportFunction(function (message) {
    record('alert', message);
  }, window);
  page.confirm = exportFunction(function (message) {
    record('confirm', message);
    return dialogState.mode === 'accept';
  }, window);
  page.prompt = exportFunction(function (message, fallback) {
    record('prompt', message, { default: fallback ?? '' });
    return dialogState.mode === 'accept' ? (dialogState.promptText ?? fallback ?? '') : null;
  }, window);
}

// The page's console output and uncaught errors, kept from the moment a client
// first asks. Wrapping console on every page from the start would change stack
// locations and cost time for pages nobody is debugging, so it waits to be asked.
const CONSOLE_LIMIT = 500;
const consoleState = { armed: false, entries: [] };

function formatConsoleArg(value) {
  if (value === undefined) return 'undefined';
  if (value === null || typeof value !== 'object') return String(value);
  try {
    if (value instanceof window.wrappedJSObject.Error) return value.stack || String(value);
    return JSON.stringify(value);
  } catch (error) {
    return Object.prototype.toString.call(value);
  }
}

function addConsoleEntry(level, message) {
  consoleState.entries.push({ level, message: message.slice(0, 2000), time: new Date().toISOString() });
  if (consoleState.entries.length > CONSOLE_LIMIT) consoleState.entries.shift();
}

function armConsole() {
  if (consoleState.armed) return;
  consoleState.armed = true;
  const page = window.wrappedJSObject;
  for (const level of ['log', 'info', 'warn', 'error', 'debug']) {
    const original = page.console[level];
    page.console[level] = exportFunction(function (...args) {
      addConsoleEntry(level, args.map(formatConsoleArg).join(' '));
      return original.apply(this, args);
    }, window);
  }
  window.addEventListener('error', event => addConsoleEntry('uncaught',
    `${event.message} (${event.filename}:${event.lineno}:${event.colno})`));
  window.addEventListener('unhandledrejection', event => addConsoleEntry('uncaught',
    'Unhandled promise rejection: ' + formatConsoleArg(event.reason)));
}

// Listen for messages from background script
browser.runtime.onMessage.addListener((request, sender, sendResponse) => {
  const { action, script, data } = request;

  console.log('📨 Content script received message:', action,
    action === 'storeFile' ? { fileId: data.fileId } : data);

  try {
    switch (action) {
      case 'prepareFile': {
        const fileId = data.fileId;
        const pending = globalThis.foxmcpPendingFiles ||= new Set();
        pending.add(fileId);
        expireFileHandle(pending, fileId, 120000);
        sendResponse({ ready: true });
        break;
      }

      case 'storeFile': {
        const fileId = data.fileId;
        if (!globalThis.foxmcpPendingFiles?.delete(fileId)) {
          throw new Error('Target document changed or the file load expired');
        }
        const files = globalThis.foxmcpFiles ||= new Map();
        files.set(fileId, data.file);
        expireFileHandle(files, fileId, 300000);
        sendResponse({ fileId });
        break;
      }

      case 'extractText':
        sendResponse({ text: document.body.innerText });
        break;

      case 'extractHTML':
        sendResponse({ html: document.documentElement.outerHTML });
        break;

      case 'getPageTitle':
        sendResponse({ title: document.title });
        break;

      case 'getPageURL':
        sendResponse({ url: window.location.href });
        break;

      case 'executeScript':
        try {
          const result = eval(script);
          sendResponse({ result });
        } catch (error) {
          sendResponse({ error: error.message });
        }
        break;

      case 'snapshot':
        showOverlay();
        sendResponse({ snapshot: snapshot(data.maxElements || 300, !!data.viewportOnly), url: location.href, title: document.title });
        break;

      case 'click': {
        const el = findTarget(data);
        showOverlay();
        moveCursorTo(el, true)
          .then(() => watchReaction(() => clickElement(el, data.doubleClick ? 2 : 1)))
          .then(reaction => sendResponse({ clicked: describe(el), reaction }))
          .catch(error => sendResponse({ error: error.message }));
        break;
      }

      case 'type': {
        const el = findTarget(data);
        showOverlay();
        moveCursorTo(el, true)
          .then(() => {
            typeInto(el, data.text, data.clear !== false);
            if (data.submit) pressKey(el, 'Enter');
            sendResponse({ typed: describe(el) });
          })
          .catch(error => sendResponse({ error: error.message }));
        break;
      }

      case 'console': {
        const wasArmed = consoleState.armed;
        armConsole();
        let entries = consoleState.entries.filter(entry =>
          (!data.level || entry.level === data.level || (data.level === 'error' && entry.level === 'uncaught'))
          && (!data.pattern || entry.message.includes(data.pattern)));
        entries = entries.slice(-(data.limit || 50));
        if (data.clear) consoleState.entries.length = 0;
        sendResponse({ started: !wasArmed, entries });
        break;
      }

      case 'dialogs': {
        if (data.mode === 'accept' || data.mode === 'dismiss' || data.mode === 'off') {
          setDialogHandling(data.mode, data.promptText);
        }
        const log = dialogState.log.splice(0);
        sendResponse({ mode: dialogState.mode, dialogs: log });
        break;
      }

      case 'hover': {
        const el = findTarget(data);
        showOverlay();
        moveCursorTo(el, false)
          .then(() => {
            hoverElement(el);
            sendResponse({ hovered: describe(el) });
          })
          .catch(error => sendResponse({ error: error.message }));
        break;
      }

      case 'drag': {
        const source = findTarget(data);
        const destination = findTarget({ ref: data.toRef, selector: data.toSelector });
        showOverlay();
        moveCursorTo(source, true)
          .then(() => moveCursorTo(destination, false))
          .then(() => {
            dragElement(source, destination);
            sendResponse({ dragged: describe(source), to: describe(destination) });
          })
          .catch(error => sendResponse({ error: error.message }));
        break;
      }

      case 'scroll': {
        showOverlay();
        if (data.ref || data.selector) {
          const el = findTarget(data);
          el.scrollIntoView({ block: 'center', inline: 'center', behavior: 'instant' });
          sendResponse({ scrolledTo: describe(el), x: Math.round(scrollX), y: Math.round(scrollY) });
        } else {
          const view = { innerHeight, innerWidth };
          const amount = data.amount ?? 0.8;
          const px = amount <= 3 ? amount * (data.direction === 'left' || data.direction === 'right'
            ? view.innerWidth : view.innerHeight) : amount;
          const [dx, dy] = { up: [0, -px], down: [0, px], left: [-px, 0], right: [px, 0],
            top: [0, -1e9], bottom: [0, 1e9] }[data.direction] || [0, px];
          window.scrollBy({ left: dx, top: dy, behavior: 'instant' });
          const max = document.documentElement.scrollHeight - innerHeight;
          sendResponse({ x: Math.round(scrollX), y: Math.round(scrollY), maxY: Math.max(Math.round(max), 0) });
        }
        break;
      }

      case 'selectOption': {
        const el = findTarget(data);
        showOverlay();
        moveCursorTo(el, false)
          .then(() => {
            selectOption(el, data.values);
            sendResponse({ selected: describe(el) });
          })
          .catch(error => sendResponse({ error: error.message }));
        break;
      }

      case 'fillForm': {
        showOverlay();
        (async () => {
          const done = [];
          for (const field of data.fields) {
            const el = findTarget(field);
            await moveCursorTo(el, true);
            fillField(el, field.value);
            done.push(describe(el));
          }
          sendResponse({ filled: done });
        })().catch(error => sendResponse({ error: error.message }));
        break;
      }

      case 'pressKey': {
        const el = data.ref || data.selector ? findTarget(data) : (document.activeElement || document.body);
        showOverlay();
        pressKey(el, data.key);
        sendResponse({ pressed: data.key });
        break;
      }

      // Where an element is in the viewport, so a screenshot can be cropped to it.
      case 'elementRect': {
        const el = findTarget(data);
        el.scrollIntoView({ block: 'center', inline: 'center' });
        const rect = el.getBoundingClientRect();
        sendResponse({ rect: { x: rect.left, y: rect.top, width: rect.width, height: rect.height },
                       described: describe(el) });
        break;
      }

      // One look at whether what content_wait waits for is on the page now.
      case 'checkWait': {
        let found = true;
        if (data.selector) found = !!document.querySelector(data.selector);
        if (found && data.text) found = (document.body?.innerText || '').includes(data.text);
        sendResponse({ found });
        break;
      }

      case 'captureFileInput': {
        const trigger = findTarget({ ref: data.triggerRef, selector: data.triggerSelector });
        showOverlay();
        const captured = captureNextFileInput(data.timeoutMs || 3000);
        moveCursorTo(trigger, true)
          .then(() => clickElement(trigger))
          .then(() => captured)
          .then(input => sendResponse({ ref: refFor(input), multiple: input.multiple, directory: input.webkitdirectory }))
          .catch(error => sendResponse({ error: error.message }));
        break;
      }

      case 'setFiles': {
        const el = findTarget(data);
        showOverlay();
        const paths = setInputFiles(el, data.files, data.relativePaths || []);
        sendResponse({ count: paths.length, paths: paths.slice(0, 5), target: describe(el) });
        break;
      }

      // Hidden while a screenshot is taken, so the capture shows the page as
      // it is rather than with the agent's border and cursor on top.
      case 'overlayVisibility': {
        const host = document.getElementById(OVERLAY_ID);
        if (host) host.style.visibility = data.visible ? 'visible' : 'hidden';
        sendResponse({ ok: true });
        break;
      }

      default:
        sendResponse({ error: `Unknown content action: ${action}` });
    }
  } catch (error) {
    sendResponse({ error: error.message });
  }

  return true; // Keep message channel open for async response
});

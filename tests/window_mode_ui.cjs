const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const { JSDOM } = require(path.join(root, '.build/chatbox/node_modules/jsdom'));
const ts = require(path.join(root, '.build/chatbox/node_modules/typescript'));
const source = fs.readFileSync(path.join(root, 'chatbox/window-mode-preload.cjs'), 'utf8');
const pause = () => new Promise(resolve => setTimeout(resolve, 0));
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const ping = deferred(), commands = [], listeners = new Map();
const ipc = {
  invoke: (channel, argument) => {
    if (channel === 'slidepilot:controls') { assert.equal(argument, 'ping'); return ping.promise; }
    assert.equal(channel, 'slidepilot:mode');
    const reply = deferred(); commands.push({ argument, ...reply }); return reply.promise;
  },
  on: (channel, listener) => { listeners.set(channel, listener); },
};
const dom = new JSDOM('<!doctype html><html><head></head><body><header><div class="controls self-start">Original controls</div></header><main id="composer"></main></body></html>', { url: 'file:///SlidePilot/index.html', runScripts: 'outside-only' });
const { window } = dom;
const location = window.location.href;
window.require = name => { assert.equal(name, 'electron'); return { ipcRenderer: ipc }; };
let sidebarEvents = 0;
window.addEventListener('slidepilot:sidebar', () => { sidebarEvents++; });
vm.runInContext(source, dom.getInternalVMContext());
const host = state => listeners.get('slidepilot:state')({}, state);

function testRendererSidebarHook() {
  const renderer = new JSDOM('<!doctype html><html data-sp-mode="sidebar"><body></body></html>', { url: 'file:///SlidePilot/index.html#/session/retained-chat' });
  try {
    const updates = [];
    const session = Object.freeze({ id: 'retained-chat', messages: Object.freeze(['Existing message']) });
    const draft = Object.freeze({ text: 'Unsent presentation request', pictureKeys: Object.freeze(['retained-attachment']) });
    const state = { showSidebar: true, session, draft, setShowSidebar(value) { updates.push(value); state.showSidebar = value; } };
    const original = JSON.stringify({ session: state.session, draft: state.draft });
    const route = renderer.window.location.href;
    const module = ts.transpileModule(fs.readFileSync(path.join(root, 'chatbox/window-mode.ts'), 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
      fileName: 'window-mode.ts', reportDiagnostics: true,
    });
    assert.equal((module.diagnostics || []).filter(item => item.category === ts.DiagnosticCategory.Error).length, 0, 'Production renderer hook transpiles');
    const scope = vm.createContext({
      window: renderer.window, document: renderer.window.document, exports: {},
      require: name => { if(name === './sidebar.css') return {}; assert.equal(name, '@/stores/uiStore'); return { uiStore: { getState: () => state } }; },
    });
    vm.runInContext(module.outputText, scope, { filename: 'window-mode.ts' });
    assert.deepEqual(updates, [false], 'Initial sidebar host state closes chat history immediately');
    assert.equal(state.showSidebar, false);
    state.showSidebar = true;
    renderer.window.dispatchEvent(new renderer.window.Event('slidepilot:sidebar'));
    assert.deepEqual(updates, [false, false], 'Later sidebar event closes chat history again');
    assert.equal(state.showSidebar, false);
    assert.equal(state.session, session, 'Selected session identity is retained');
    assert.equal(state.draft, draft, 'Unsent draft identity is retained');
    assert.equal(JSON.stringify({ session: state.session, draft: state.draft }), original, 'Session and draft values are unchanged');
    assert.equal(renderer.window.location.href, route, 'Collapsing history does not change the current route');
  } finally { renderer.window.close(); }
}

(async () => {
  await pause();
  let button = window.document.querySelector('.sp-window-mode');
  const controls = window.document.querySelector('.controls.self-start');
  assert(button, 'Mode action mounts beside the native window controls');
  assert.equal(button.parentElement, controls.parentElement);
  assert.equal(controls.previousElementSibling, button, 'Mode action occupies the original PagePilot title-bar position');
  assert.equal(button.compareDocumentPosition(controls) & window.Node.DOCUMENT_POSITION_FOLLOWING, window.Node.DOCUMENT_POSITION_FOLLOWING);
  assert.equal(window.document.querySelector('#composer').children.length, 0, 'No composer controls are added');
  assert.equal(button.title, '收起为 PowerPoint 侧边栏');
  assert.equal(button.querySelector('svg').getAttribute('width'), '18');
  host({ mode: 'window', revision: 1 });

  const docking = button.onclick();
  assert.equal(commands[0].argument, 'sidebar');
  assert.equal(button.disabled, true);
  assert.equal(window.document.documentElement.dataset.spMode, 'window', 'Pending request does not switch optimistically');
  await button.onclick();
  assert.equal(commands.length, 1, 'Pending action prevents duplicate requests');
  commands[0].resolve({ mode: 'sidebar', revision: 2 });
  await docking;
  assert.equal(window.document.documentElement.dataset.spMode, 'sidebar');
  assert.equal(window.getComputedStyle(controls).display, 'none');
  assert.equal(window.getComputedStyle(button).display, 'grid');
  assert.equal(button.title, '弹出为独立窗口');
  assert.equal(sidebarEvents, 1);
  assert.equal(button.disabled, false);

  ping.resolve({ mode: 'window', revision: 0 });
  await pause();
  assert.equal(window.document.documentElement.dataset.spMode, 'sidebar', 'Late initial ping cannot revert a newer state');

  const undocking = button.onclick();
  assert.equal(commands[1].argument, 'window');
  commands[1].resolve({ mode: 'window', revision: 3 });
  await undocking;
  assert.equal(window.document.documentElement.dataset.spMode, 'window');
  assert.notEqual(window.getComputedStyle(controls).display, 'none');
  assert.equal(button.title, '收起为 PowerPoint 侧边栏');

  const failure = button.onclick();
  commands[2].reject(Error('Dock request rejected'));
  await failure;
  assert.equal(window.document.documentElement.dataset.spMode, 'window', 'Failure preserves the confirmed mode');
  assert.equal(button.disabled, false);
  assert(button.title.includes('Dock request rejected'));
  const status = window.document.getElementById(button.getAttribute('aria-describedby'));
  assert.equal(status.hidden, false);
  assert.equal(status.getAttribute('role'), 'status');
  assert(status.textContent.includes('Dock request rejected'), 'Failure is visible and announced');

  const staleReply = button.onclick();
  host({ mode: 'window', revision: 6 });
  commands[3].resolve({ mode: 'sidebar', revision: 5 });
  await staleReply;
  assert.equal(window.document.documentElement.dataset.spMode, 'window', 'Newer host state wins over a stale response');
  host({ mode: 'sidebar', revision: 2 });
  assert.equal(window.document.documentElement.dataset.spMode, 'window', 'Old pushed revisions are ignored');
  host({ mode: 'sidebar', revision: 7 });
  assert.equal(window.document.documentElement.dataset.spMode, 'sidebar');
  assert.equal(sidebarEvents, 2);
  assert.equal(window.location.href, location, 'Mode changes do not navigate or reload');

  const replacement = window.document.createElement('header');
  replacement.innerHTML = '<div class="controls self-start">Remounted controls</div>';
  controls.parentElement.replaceWith(replacement);
  await pause();
  button = replacement.querySelector('.sp-window-mode');
  assert(button, 'Mode action returns after a React title-bar remount');
  assert.equal(button.title, '弹出为独立窗口');
  assert.equal(window.document.querySelectorAll('.sp-window-mode').length, 1);
  testRendererSidebarHook();
  console.log('PASS window mode UI: source layout, window/sidebar round trip, pending lock, no optimistic switch, visible error, stale ping/reply/push, remount, no reload; actual renderer TypeScript: initial and event-driven sidebar collapse preserves session/draft');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => dom.window.close());

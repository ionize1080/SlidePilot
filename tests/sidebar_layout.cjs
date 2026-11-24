// DOM + responsive CSS contracts for compact sidebars. JSDOM does not perform
// pixel layout: this intentionally does not claim real Chromium visual coverage.
'use strict'
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const assert = require('node:assert/strict')
const root = path.resolve(__dirname, '..')
const dependencies = path.resolve(process.argv[2] || path.join(root, '.build/chatbox'))
const { JSDOM } = require(path.join(dependencies, 'node_modules/jsdom'))
const ts = require(path.join(dependencies, 'node_modules/typescript'))
const read = name => fs.readFileSync(path.join(root, name), 'utf8')
const pause = () => new Promise(resolve => setTimeout(resolve, 0))
const css = read('chatbox/SlidePilotControls.css') + '\n' + read('chatbox/sidebar.css')
const workspace = read('chatbox/workspace-ui.js')
const input = fs.readFileSync(path.join(dependencies, 'src/renderer/components/InputBox/InputBox.tsx'), 'utf8')
for (const hook of ['sp-input-toolbar', 'sp-input-tools', 'sp-input-model']) assert(input.includes(hook), 'Responsive CSS must attach to the real input: ' + hook)
const header = fs.readFileSync(path.join(dependencies, 'src/renderer/components/layout/Header.tsx'), 'utf8')
for (const hook of ['sp-chat-title', 'sp-thread-label', 'sp-chat-title-edit']) assert(header.includes(hook), 'Responsive CSS must attach to the real header: ' + hook)
for (const [file, hooks] of [
  ['routes/index.tsx', ['sp-home-page', 'sp-home-promotion', 'sp-home-welcome', 'sp-home-composer', 'sp-sidebar-setup', "navigateToSettings('/provider')"]],
  ['components/layout/Page.tsx', ['sp-page-content']],
  ['routes/session/$sessionId.tsx', ['sp-session-root']],
  ['components/chat/MessageList.tsx', ['sp-message-list']],
  ['routes/__root.tsx', ['sp-main-column']],
  ['components/InputBox/InputBox.tsx', ['sp-composer']],
]) {
  const text = fs.readFileSync(path.join(dependencies, 'src/renderer', file), 'utf8')
  for (const hook of hooks) assert(text.includes(hook), 'Compact layout must attach to production ' + file + ': ' + hook)
}

// JSDOM does not evaluate viewport media queries. Select the real CSS rules for
// a requested width, then let its CSS cascade evaluate the fixture's styles.
function rulesForViewport(text, width, height) {
  const sheetDom = new JSDOM('<!doctype html><style></style>')
  sheetDom.window.document.querySelector('style').textContent = text
  function collect(rules) {
    return Array.from(rules).map(rule => {
      if (rule.type === 1) return rule.cssText
      if (rule.type !== 4) return ''
      const query = rule.conditionText
      if (!/width|height/.test(query)) return ''
      const bounds = [...query.matchAll(/(max|min)-(width|height)\s*:\s*(\d+(?:\.\d+)?)px/g)]
      assert(bounds.length, 'Unrecognized viewport query needs an explicit test update: ' + query)
      return bounds.every(([, side, dimension, value]) => {
        const actual = dimension === 'width' ? width : height
        return side === 'max' ? actual <= Number(value) : actual >= Number(value)
      }) ? collect(rule.cssRules) : ''
    }).join('\n')
  }
  const selected = collect(sheetDom.window.document.querySelector('style').sheet.cssRules)
  sheetDom.window.close()
  return selected
}

async function check(width, height = 720, mode = 'sidebar') {
  const dom = new JSDOM(`<!doctype html><html data-sp-mode="${mode}"><head></head><body>
    <header><span class="sp-chat-title">An intentionally long presentation title</span><span class="sp-thread-label">An intentionally long branch title</span><button class="sp-chat-title-edit">Edit</button></header>
    <main class="sp-main-column"><section class="sp-home-page"><div class="title-bar">Title</div><div class="sp-page-content"><div class="sp-home">
    <div class="sp-sidebar-setup"><strong>SlidePilot</strong><button>Model &amp; API settings</button></div><div class="sp-home-promotion">Upstream promotional panel</div><div class="sp-home-welcome">Welcome</div>
    <div class="sp-home-composer"><div class="sp-composer"><textarea id="message-input">Keep this draft while docking</textarea>
    <div class="sp-input-toolbar" style="display:flex"><div class="sp-input-tools" style="display:flex">
      <button id="attachment">Attach</button><div class="sp-chat-controls"><span id="slidepilot-toolbar-slot"></span><button class="sp-approval-switch">Approve</button><button class="sp-chat-settings">Settings</button><span class="sp-control-error">A long actionable diagnostic that must wrap without hiding the model</span></div>
    </div><div class="sp-input-model" style="display:flex;min-width:0"><button id="model">qwen3.8-flash</button></div></div></div></div></div></div></section>
    <section class="sp-session-root"><div class="title-bar">Conversation</div><div class="sp-message-list">Scrollable messages</div><div class="sp-composer">Session composer</div></section></main>
  </body></html>`, { url: 'file:///SlidePilot/index.html', runScripts: 'outside-only' })
  try {
    const { window } = dom
    Object.defineProperty(window, 'innerWidth', { value: width, configurable: true })
    Object.defineProperty(window, 'innerHeight', { value: height, configurable: true })
    const style = window.document.createElement('style'); style.textContent = rulesForViewport(css, width, height); window.document.head.append(style)
    const get = selector => window.getComputedStyle(window.document.querySelector(selector))
    if (width <= 560) {
      assert.equal(get('.sp-input-toolbar').flexWrap, 'wrap', 'Tools and model need independent lines at ' + width)
      assert.equal(get('.sp-input-tools').flexWrap, 'wrap', 'Additional tools must wrap at ' + width)
      assert.equal(get('.sp-input-tools').minWidth, '0')
      assert.equal(get('.sp-input-model').width, '100%', 'Model receives a full accessible row at ' + width)
      assert.equal(get('.sp-input-model').maxWidth, '100%')
      assert.equal(get('.sp-control-error').whiteSpace, 'normal', 'Long errors must not force horizontal overflow')
      assert.equal(get('.sp-control-error').overflowWrap, 'anywhere')
      assert.equal(get('.sp-thread-label').display, 'none', 'A long thread badge cannot squeeze title actions out of the sidebar')
      assert.equal(get('.sp-chat-title').minWidth, '0')
      assert.equal(get('.sp-chat-title-edit').flexShrink, '0', 'The title edit action retains a click target')
    } else {
      assert.notEqual(get('.sp-input-model').width, '100%', 'Wide windows retain their upstream toolbar layout')
    }
    if (mode === 'sidebar') {
      assert.equal(get('.sp-home-promotion').display, 'none', 'Promotions cannot push the compact composer below the viewport')
      assert.equal(get('.sp-sidebar-setup').display, 'flex', 'The original model settings entry remains available')
      assert.equal(get('.sp-home-page>.sp-page-content').overflow, 'hidden', 'The home page cannot scroll the composer out of view')
      assert.equal(get('.sp-main-column').minHeight, '0')
      assert.equal(get('.sp-home-composer').flexShrink, '0', 'The composer retains space instead of shrinking behind content')
      assert.equal(get('.sp-home-composer').marginTop, 'auto')
      assert.equal(get('.sp-composer').flexGrow, '0')
      assert.equal(get('.sp-session-root>.sp-message-list').flexGrow, '1')
      assert.equal(get('.sp-session-root>.sp-message-list').minHeight, '0', 'Messages use remaining space independently of the composer')
      if (height <= 480) {
        assert.equal(get('.sp-home-welcome').display, 'none', 'Short task panes reserve height for conversation controls')
        assert.equal(get('#message-input').maxHeight, '72px')
      } else assert.notEqual(get('.sp-home-welcome').display, 'none')
    } else {
      assert.notEqual(get('.sp-home-promotion').display, 'none', 'Standalone home behavior is unchanged')
      assert.notEqual(get('.sp-home-welcome').display, 'none', 'Short standalone windows are not treated as Office panes')
      assert.equal(get('.sp-sidebar-setup').display, 'none')
    }
    for (const selector of ['#message-input', '#model', '#attachment', '.sp-chat-settings']) {
      assert.notEqual(get(selector).display, 'none', selector + ' stays available')
      assert.notEqual(get(selector).visibility, 'hidden', selector + ' stays visible')
    }

    let sidebar = true, writes = 0
    window.exports = {}
    window.require = name => {
      if (name === './sidebar.css') return {}
      assert.equal(name, '@/stores/uiStore')
      return { uiStore: { getState: () => ({ setShowSidebar(value) { writes++; sidebar = value } }) } }
    }
    const modeCode = ts.transpileModule(read('chatbox/window-mode.ts'), { compilerOptions: { target: ts.ScriptTarget.ES2021, module: ts.ModuleKind.CommonJS } }).outputText
    vm.runInContext(modeCode, dom.getInternalVMContext())
    assert.equal(sidebar, mode !== 'sidebar', 'Initial compact history behavior follows the confirmed host mode')
    sidebar = true
    const beforeEvent = writes
    window.dispatchEvent(new window.Event('slidepilot:sidebar'))
    assert.equal(sidebar, false, 'Docking collapses chat history just as PagePilot does')
    assert.equal(writes, beforeEvent + 1)
    assert.equal(window.document.querySelector('#message-input').value, 'Keep this draft while docking')
    assert.equal(window.document.querySelector('#model').textContent, 'qwen3.8-flash')

    window.slidepilotWorkspaceSession = () => 'layout-test'
    window.slidepilotFiles = { summary: async () => ({ entries: [], sourceCount: 0, collections: [], next_cursor: null }) }
    vm.runInContext(workspace, dom.getInternalVMContext())
    await pause()
    const element = window.document.querySelector('slidepilot-workspace')
    assert(element, 'The actual workspace component mounts at ' + width)
    const trigger = element.shadowRoot.getElementById('trigger')
    assert(trigger.getAttribute('aria-label'), 'Compact workspace action retains its accessible name')
    assert.equal(element.shadowRoot.querySelectorAll('nav button').length, 3, 'All source organization actions are retained')
    const panelCss = element.shadowRoot.querySelector('style').textContent
    const panelStyle = window.document.createElement('style'); panelStyle.textContent = rulesForViewport(panelCss, width, height); window.document.head.append(panelStyle)
    const nav = window.document.createElement('nav'); nav.innerHTML = '<button>One</button><button>Two</button><button>Three</button>'; window.document.body.append(nav)
    assert.equal(window.getComputedStyle(nav).flexWrap, 'wrap', 'Three source actions can wrap inside a narrow popover')
    assert.notEqual(window.getComputedStyle(nav.firstElementChild).flexBasis, '0%', 'Action buttons retain a usable line basis')
    const triggerTop = height - 150
    element.getBoundingClientRect = () => ({ left: width - 100, top: triggerTop, right: width - 30, bottom: triggerTop + 32, width: 70, height: 32 })
    element.place()
    const panel = element.shadowRoot.getElementById('panel')
    const left = Number.parseFloat(panel.style.left)
    const panelWidth = Math.min(372, width - 20)
    assert(left >= 10 && left + panelWidth <= width - 10, 'Popover placement remains inside horizontal viewport margins')
    assert(Number.parseFloat(panel.style.maxHeight) <= triggerTop - 22)
    console.log('PASS ' + width + 'x' + height + ' ' + mode + ': compact home/session CSS, original settings entry, model/draft retention and workspace placement')
  } finally { dom.window.close() }
}

;(async () => {
  await check(242, 388)
  for (const width of [340, 360, 400, 480]) await check(width)
  await check(800, 720, 'window')
  await check(242, 388, 'window')
  console.log('NOTE: DOM/CSS contract regression only; actual Chromium pixel layout still requires desktop acceptance.')
})().catch(error => { console.error(error); process.exitCode = 1 })

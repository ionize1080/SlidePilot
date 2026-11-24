const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const assert = require('node:assert/strict')
const { JSDOM } = require(path.resolve('.build/chatbox/node_modules/jsdom'))

const source = fs.readFileSync('chatbox/workspace-ui.js', 'utf8')
const pause = () => new Promise(resolve => setTimeout(resolve, 0))
let current = 'chat-a', chooser, chooseCalls = 0, moveCalls = 0, openCalls = []
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
const dom = new JSDOM('<!doctype html><html><body><span id="slidepilot-toolbar-slot"></span></body></html>', { runScripts: 'outside-only', url: 'file:///SlidePilot/index.html' })
const { window } = dom
window.slidepilotWorkspaceSession = () => current
window.slidepilotFiles = {
  summary: async session => ({ entries: session === 'chat-b' ? [{ id:'results:demo', name:'Draft.pptx', kind:'file', size:2000, generated:true, supported:true }] : [{ id:'source:', name:'Reference.txt', kind:'file', size:100, supported:true }], sourceCount:session === 'chat-b' ? 1 : 2, maxFileMB:100, collections:[], next_cursor:null }),
  preferences: async () => { throw Error('Preference read failed') },
  choose: async () => { chooseCalls++; return chooser.promise },
  move: async () => { moveCalls++; return {} },
  open: async (session, id) => { openCalls.push([session,id]); return {opened:true} },
}
vm.runInContext(source, dom.getInternalVMContext())

;(async () => {
  await pause()
  const element = window.document.querySelector('slidepilot-workspace')
  assert(element, 'Workspace mounts in the source-derived toolbar slot')
  const $ = id => element.shadowRoot.getElementById(id)
  assert.equal($('badge').textContent, '2')
  assert.equal(element.shadowRoot.querySelector('.name').textContent, 'Reference.txt')
  vm.runInContext(source, dom.getInternalVMContext())
  assert.equal(window.document.querySelectorAll('slidepilot-workspace').length, 1, 'Repeated script initialization is safe')

  await $('settings').onclick()
  assert.equal($('status').textContent, 'Preference read failed', 'Preference failure is surfaced')
  assert.equal($('panel').getAttribute('aria-busy'), 'false')
  assert.equal($('save').disabled, false, 'Failure releases controls')

  chooser = deferred()
  const pending = element.choose(false)
  await element.choose(false)
  assert.equal(chooseCalls, 1, 'Double activation opens exactly one native chooser')
  assert.equal($('add').disabled, true)
  assert.equal($('close').disabled, false, 'Popover can close during pending work')
  chooser.resolve({added:[],errors:[]})
  await pending
  assert.equal($('add').disabled, false)

  chooser = deferred()
  const stale = element.choose(false)
  current = 'chat-b'
  window.dispatchEvent(new window.Event('slidepilot:session'))
  await pause()
  assert.equal(element.shadowRoot.querySelector('.name').textContent, 'Draft.pptx')
  chooser.resolve({added:[],errors:[{name:'Old reference',message:'Old session error'}]})
  await stale
  assert(!element.shadowRoot.textContent.includes('Old session error'), 'Late chooser result cannot change the new chat')
  assert.equal($('badge').textContent, '1')

  const open = element.shadowRoot.querySelector('[aria-label="打开演示文稿 Draft.pptx"]')
  assert(open, 'Generated presentation has a labelled open action')
  await open.onclick()
  assert.deepEqual(openCalls, [['chat-b','results:demo']])

  element.drop({preventDefault(){},stopPropagation(){},dataTransfer:{files:[],getData:()=>JSON.stringify({session:'chat-a',ids:['source:']})}}, '')
  await pause()
  assert.equal(moveCalls, 0, 'Cross-chat reference drag is rejected')
  assert.equal($('status').textContent, '请在同一聊天内整理资料')
  assert.equal($('panel').getAttribute('aria-busy'), 'false')
  console.log('PASS workspace UI: mount/idempotence, preferences errors, chooser single-flight, stale-chat isolation, generated PPTX open, cross-chat drag rejection')
})().catch(error => { console.error(error); process.exitCode = 1 }).finally(() => dom.window.close())

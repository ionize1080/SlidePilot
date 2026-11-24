const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm'), assert = require('node:assert/strict')
const root = path.resolve(__dirname, '..'), modules = path.join(root, '.build/chatbox/node_modules')
const {JSDOM} = require(path.join(modules, 'jsdom'))
const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', {url:'file:///SlidePilot/index.html'})
global.window = dom.window; global.document = dom.window.document; global.navigator = dom.window.navigator
global.IS_REACT_ACT_ENVIRONMENT = true
const React = require(path.join(modules, 'react')), {createRoot} = require(path.join(modules, 'react-dom/client'))
const jsx = require(path.join(modules, 'react/jsx-runtime')), ts = require(path.join(modules, 'typescript'))
const deferred = () => {let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve}}
const calls = [], waits = []; let poll
window.electronAPI = {invoke:async(channel,action)=>{assert.equal(channel,'slidepilot:controls');calls.push(action);const item=deferred();waits.push({action,...item});return item.promise}}
const scope = {window,Event:window.Event,exports:{},setInterval:callback=>{poll=callback;return 1},clearInterval:()=>{},require:name=>{
  if(name==='react')return React
  if(name==='react/jsx-runtime')return jsx
  if(name==='@mantine/core')return {Tooltip:({children})=>children}
  if(name==='lucide-react')return {Settings2:props=>jsx.jsx('svg',props),ShieldAlert:props=>jsx.jsx('svg',props),ShieldCheck:props=>jsx.jsx('svg',props)}
  if(name==='@/stores/settingsStore')return {useLanguage:()=> 'zh-Hans'}
  if(name==='@/packages/slidepilot/workspace')return {synchronizeWorkspace:async()=>({})}
  if(name.startsWith('@/packages/slidepilot/')||name.endsWith('.css'))return {}
  throw Error(name)
}}
vm.createContext(scope)
vm.runInContext(ts.transpileModule(fs.readFileSync(path.join(root,'chatbox/SlidePilotControls.tsx'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText,scope)
const view=createRoot(document.getElementById('root')), Control=scope.exports.default
const state=(revision,automatic,document='Deck.pptx')=>({revision,automatic,document,workspace:'C:/Workspace',hasDeck:true})
const tick=()=>new Promise(resolve=>setImmediate(resolve))
;(async()=>{
  await React.act(async()=>{view.render(jsx.jsx(Control,{sessionId:'a'}));await tick()})
  await React.act(async()=>{waits.shift().resolve(state(1,false));await tick()})
  const toggle=document.querySelector('[role=switch]')
  assert.equal(toggle.getAttribute('aria-checked'),'false')
  await React.act(async()=>{toggle.click();toggle.click();await tick()})
  assert.equal(calls.filter(x=>x==='ui_approval').length,1,'Native owns both confirmations; frontend sends only one request')
  assert(toggle.disabled)
  const approval=waits.shift()
  await React.act(async()=>{void poll();await tick()})
  await React.act(async()=>{waits.shift().resolve(state(3,true));await tick()})
  assert.equal(toggle.getAttribute('aria-checked'),'false','Pending native confirmation preserves the displayed approval state')
  await React.act(async()=>{approval.resolve(state(2,true));await tick()})
  assert.equal(toggle.getAttribute('aria-checked'),'true','Newest host state applies immediately after confirmation, even when ping arrived first')
  assert(toggle.classList.contains('is-automatic'),'Automatic approval has a persistent red shield state')
  await React.act(async()=>{void poll();await tick()})
  await React.act(async()=>{waits.shift().resolve(state(2,false));await tick()})
  assert.equal(toggle.getAttribute('aria-checked'),'true','An older ping cannot reverse approved state')
  await React.act(async()=>{void poll();await tick()})
  await React.act(async()=>{waits.shift().resolve(state(4,false,'Other.pptx'));await tick()})
  assert.equal(toggle.getAttribute('aria-checked'),'false','New presentation host state clears automatic approval')
  await React.act(async()=>{document.querySelector('.sp-chat-settings').click();await tick()})
  assert.equal(calls.at(-1),'ui_settings')
  await React.act(async()=>{waits.shift().resolve(state(5,false));await tick();view.unmount()})
  dom.window.close()
  console.log('PASS chat controls: one native approval request, pending state, red shield, revision ordering, presentation reset and product settings')
})().catch(error=>{console.error(error);process.exitCode=1;dom.window.close()})

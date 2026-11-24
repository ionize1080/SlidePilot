'use strict'
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict')
const root=path.resolve(__dirname,'..'),{JSDOM}=require(path.join(root,'.build/chatbox/node_modules/jsdom'))
const dom=new JSDOM(fs.readFileSync(path.join(root,'chatbox/settings.html'),'utf8'),{runScripts:'outside-only',url:'file:///SlidePilot/settings.html'})
const {window}=dom;let saved='sidebar',refresh,fail=false,delayRead,delayWrite
const writes=[]
const pause=()=>new Promise(done=>setImmediate(done))
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return{promise,resolve}}
window.requestAnimationFrame=callback=>callback()
window.slidepilotSettings={
  onRefresh:callback=>{refresh=callback},
  read:async()=>delayRead?delayRead.promise:{theme:0,mode:saved,version:'test',office:'16.0'},
  ready:async()=>({}),workspace:async()=>({maxFileMB:100,searchDepth:3}),
  write:async value=>{writes.push(value);if(fail)throw Error('Open a presentation first');if(delayWrite)await delayWrite.promise;if(value.mode)saved=value.mode;return{mode:saved}},
  provider:async()=>({}),open:async()=>({}),
}
vm.runInContext(fs.readFileSync(path.join(root,'chatbox/settings.js'),'utf8'),dom.getInternalVMContext())
const button=mode=>window.document.querySelector(`[data-mode=${mode}]`)
;(async()=>{
  await pause()
  assert.equal(button('sidebar').getAttribute('aria-pressed'),'true','Saved sidebar preference appears on first load')
  delayWrite=deferred();button('window').click();button('window').click();await pause()
  assert.equal(writes.length,1,'Mode change is single-flight')
  assert.equal(button('sidebar').getAttribute('aria-pressed'),'true','No optimistic state before host acceptance')
  delayWrite.resolve();delayWrite=undefined;await pause()
  assert.equal(button('window').getAttribute('aria-pressed'),'true')
  assert(window.document.getElementById('status').textContent.includes('下次打开'))
  fail=true;button('sidebar').click();await pause()
  assert.equal(button('window').getAttribute('aria-pressed'),'true')
  assert(window.document.getElementById('status').classList.contains('error'))
  fail=false;saved='sidebar';await refresh()
  assert.equal(button('sidebar').getAttribute('aria-pressed'),'true','Reopening settings reflects a change made in the chat title bar')
  delayRead=deferred();const oldRefresh=refresh();button('window').click();await pause()
  delayRead.resolve({mode:'sidebar'});delayRead=undefined;await oldRefresh
  assert.equal(button('window').getAttribute('aria-pressed'),'true','Late refresh cannot overwrite a newly confirmed selection')
  assert(writes.every(value=>Object.keys(value).length===1&&Object.hasOwn(value,'mode')),'Mode cards cannot overwrite pending theme or API settings')
  dom.window.close()
  console.log('PASS settings mode selection: saved preference, immediate acknowledged switch, single-flight, failure, external refresh and stale response protection')
})().catch(error=>{console.error(error);process.exitCode=1;dom.window.close()})

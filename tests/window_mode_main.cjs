'use strict'
const assert = require('node:assert/strict')
const {createWindowModes} = require('../chatbox/window-mode-main.cjs')
const flags=[], messages=[], calls=[]
const handle=Buffer.alloc(8);handle.writeBigUInt64LE(123456789n)
const content={id:77,session:'preserved-chat',draft:'Unsent text',request:{streaming:true},send:(channel,value)=>messages.push([channel,value])}
const win={webContents:content,isDestroyed:()=>false,getNativeWindowHandle:()=>handle}
for(const name of ['setHasShadow','setSkipTaskbar','setMovable','setMaximizable','setMinimizable'])win[name]=value=>flags.push([name,value])
for(const name of ['loadURL','loadFile','destroy','close','reload'])win[name]=()=>{throw Error('Mode changes must preserve the existing window and chat')}
let saved='sidebar',revision=0,rejectSidebar=false
const mode=createWindowModes({primary:()=>win,host:async(action,args)=>{
  calls.push([action,args])
  if(action==='ai_ready')assert.equal(args.handle,'123456789')
  else {assert.equal(action,'ai_mode');if(rejectSidebar&&args.mode==='sidebar')throw Error('Open a presentation first');saved=args.mode}
  return {mode:saved,revision:++revision,document:'Example.pptx'}
}})
;(async()=>{
  await mode.ready()
  assert.equal(calls[0][0],'ai_ready')
  assert.equal(messages.at(-1)[1].mode,'sidebar','Saved preference applies to the same HWND at startup')
  assert.deepEqual(flags.slice(-5),[['setHasShadow',false],['setSkipTaskbar',true],['setMovable',false],['setMaximizable',false],['setMinimizable',false]])
  await mode.change('window')
  assert.equal(messages.at(-1)[1].mode,'window')
  assert.deepEqual(flags.slice(-5),[['setHasShadow',true],['setSkipTaskbar',false],['setMovable',true],['setMaximizable',true],['setMinimizable',true]])
  const count=flags.length
  mode.apply({mode:'sidebar',revision:1})
  assert.equal(flags.length,count,'Old host state cannot reverse the latest mode')
  rejectSidebar=true
  await assert.rejects(mode.change('sidebar'),/Open a presentation/)
  assert.equal(saved,'window');assert.equal(flags.length,count)
  await assert.rejects(mode.change('embed'),/Unknown/)
  rejectSidebar=false
  await Promise.all([mode.change('sidebar'),mode.change('window')])
  assert.deepEqual(calls.slice(-2).map(call=>call[1].mode),['sidebar','window'])
  assert.equal(saved,'window')
  assert.equal(win.webContents,content)
  assert.equal(content.session,'preserved-chat');assert.equal(content.draft,'Unsent text');assert(content.request.streaming)
  assert(messages.every(message=>message[0]==='slidepilot:state'))
  console.log('PASS Electron mode lifecycle: real HWND handshake, saved startup preference, same webContents/session/draft/stream, two-way flags, failed switch and stale-state protection')
})().catch(error=>{console.error(error);process.exitCode=1})

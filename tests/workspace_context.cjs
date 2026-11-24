// Run the source-level integration, including Chatbox's actual new-chat handler.
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const assert = require('node:assert/strict')
const root = path.resolve(__dirname, '..')
const chatbox = path.join(root, '.build/chatbox')
const ts = require(path.join(chatbox, 'node_modules/typescript'))
const esbuild = require(path.join(chatbox, 'node_modules/esbuild'))
const source = fs.readFileSync(path.join(root, 'chatbox/workspace.ts'), 'utf8')
const transpile = text => ts.transpileModule(text, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
const saved = new Map(), events = []
let context = { workspace_id: 'a'.repeat(32), sourceCount: 2 }, reads = 0
const scope = {
  exports: {}, TextEncoder, Event, setTimeout,
  window: {
    location: { hash: '#/session/existing%20chat' },
    electronAPI: {invoke:async (channel,id)=>{assert.equal(channel,'slidepilot:bind-workspace');assert.equal(id,context.workspace_id);events.push('bound-workspace')}},
    dispatchEvent: event => events.push(event.type),
    slidepilotFiles: {
      context: async session => { assert.equal(session, 'existing chat'); return { ...context } },
      add: async (session, files) => { assert.equal(session, 'existing chat'); assert.equal(files.length, 1); return { workspace_id: context.workspace_id, added: [{id: 'file:', name:'Evidence.txt', kind:'file'}], errors: [] } },
    },
  },
  require: name => {
    if (name === '@shared/types') return { TOKEN_CACHE_KEYS: {default:'default'} }
    if (name === '@/packages/mcp/controller') return {mcpController:{getServer:id=> {assert.equal(id, 'slidepilot-workspace'); return {getAvailableTools:()=>({workspace_list:{}})}}}}
    if (name === '@/packages/token') return {estimateTokens:text=>text.length/4}
    if (name === '@/storage') return {default:{setBlob:async(k,v)=>saved.set(k,v),setItem:async(k,v)=>saved.set(k,v)}}
    throw Error('Unexpected dependency: '+name)
  },
}
vm.createContext(scope)
vm.runInContext(transpile(source), scope)
const api = scope.exports

;(async () => {
  assert.equal(api.workspaceSession(), 'existing chat')
  const image = {type:'image',storageKey:'existing-image'}
  const raw = Object.freeze({id:'u1',role:'user',contentParts:Object.freeze([{type:'text',text:'Read the relevant evidence'},image])})
  const captured = await api.captureWorkspace(raw)
  assert.equal(captured.slidepilotWorkspace.workspace_id, context.workspace_id)
  assert(events.includes('bound-workspace'), 'The host binds workspace identity before messages are submitted')
  assert.equal(raw.slidepilotWorkspace, undefined)
  const system = {id:'s',role:'system',contentParts:[{type:'text',text:'Rules'}]}
  const call = {id:'a',role:'assistant',contentParts:[{type:'tool-call',toolCallId:'call-1'}]}
  const tool = {id:'t',role:'tool',contentParts:[{type:'tool-result',toolCallId:'call-1'}]}
  const expanded = api.expandWorkspace([system,captured,call,tool])
  assert.equal(expanded[0], system)
  assert.equal(expanded[1].contentParts[1], image)
  assert.equal(expanded[2], call)
  assert.equal(expanded[3], tool)
  assert(!expanded.slice(1).some(m=>m.role==='system'), 'Compatible providers must not receive trailing system context')
  assert.equal(captured.contentParts.length, 2, 'Expanding context never rewrites stored history')
  context = {workspace_id:'b'.repeat(32),sourceCount:0}
  const second = await api.captureWorkspace({...raw,id:'u2'})
  const continued = api.expandWorkspace([captured,call,tool,second])
  assert.equal(continued[0], captured)
  assert(JSON.stringify(continued[3]).includes(context.workspace_id))
  assert(!JSON.stringify(continued[3]).includes('a'.repeat(32)))
  const file = {name:'Evidence.txt',text:async()=>{reads++;throw Error('must not read whole attachment')}}
  const attachment = await api.preprocessWorkspaceFile(file)
  assert.equal(reads, 0)
  assert(!attachment.error)
  assert(attachment.content.includes('content has not been read'))
  assert(attachment.content.includes('file_id'))
  assert(saved.has(attachment.storageKey))
  assert(events.includes('slidepilot:files'))

  // The real Zod schema must retain workspace identity across reload/migration.
  const schemaCode = esbuild.buildSync({entryPoints:[path.join(chatbox,'src/shared/types/session.ts')],bundle:true,write:false,platform:'node',format:'cjs',logLevel:'silent'}).outputFiles[0].text
  const schemaScope = {module:{exports:{}},exports:{},require}
  schemaScope.exports = schemaScope.module.exports
  vm.runInNewContext(schemaCode,schemaScope)
  const restored = schemaScope.module.exports.MessageSchema.parse(JSON.parse(JSON.stringify(captured)))
  assert.equal(restored.slidepilotWorkspace.workspace_id, captured.slidepilotWorkspace.workspace_id)

  // Extract the actual source handler; do not test a rewritten facsimile.
  const home = fs.readFileSync(path.join(chatbox,'src/renderer/routes/index.tsx'),'utf8')
  const ast = ts.createSourceFile('index.tsx',home,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX)
  let handler
  const find = node => { if(ts.isVariableDeclaration(node)&&node.name.getText(ast)==='handleSubmit') handler=node.initializer.arguments[0].getText(ast);ts.forEachChild(node,find) }
  find(ast)
  assert(handler)
  let bound = false
  const order = []
  scope.window.slidepilotFiles.adopt = async (from,to,id) => { await Promise.resolve();assert.equal(from,'new');assert.equal(to,'created-chat');assert.equal(id,context.workspace_id);bound=true;order.push('bound') }
  const homeScope = {
    session:{name:'New',messages:[]},newSessionState:{},sessionWebBrowsingMap:{},
    createSessionStore:async()=>({id:'created-chat'}),
    adoptWorkspace:api.adoptWorkspace,
    switchCurrentSession:id=>{assert(bound,'Workspace must bind before navigation remounts the input');order.push('navigated')},
    submitNewUserMessage:(id,args)=>{assert(bound);assert.equal(args.newUserMsg.slidepilotWorkspace.workspace_id,context.workspace_id);order.push('submitted')},
  }
  vm.createContext(homeScope)
  const submit = vm.runInContext(transpile('('+handler+')'),homeScope)
  await submit({constructedMessage:second})
  assert.deepEqual(order,['bound','navigated','submitted'])

  // A slow context response from the previous tab cannot rebind the host.
  const delayed = () => { let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve} }
  const slowContext=delayed(), bindings=[]
  scope.window.slidepilotFiles.context=async session=>session==='a'?slowContext.promise:{workspace_id:'b'.repeat(32),sourceCount:0}
  scope.window.electronAPI.invoke=async(channel,id)=>bindings.push(id)
  scope.window.location.hash='#/session/a'
  const stale=api.synchronizeWorkspace('a').catch(error=>error.name)
  scope.window.location.hash='#/session/b'
  await api.synchronizeWorkspace('b')
  slowContext.resolve({workspace_id:'a'.repeat(32),sourceCount:0})
  assert.equal(await stale,'WorkspaceChangedError')
  assert.deepEqual(bindings,['b'.repeat(32)])

  // Already-started IPC binds finish in order; the latest chat is bound last.
  const slowBind=delayed();bindings.length=0
  scope.window.slidepilotFiles.context=async session=>({workspace_id:session.repeat(32),sourceCount:0})
  scope.window.electronAPI.invoke=async(channel,id)=>{bindings.push(id);if(id==='a'.repeat(32))await slowBind.promise}
  scope.window.location.hash='#/session/a'
  const oldBind=api.synchronizeWorkspace('a').catch(error=>error.name)
  await new Promise(resolve=>setImmediate(resolve))
  scope.window.location.hash='#/session/b'
  const newBind=api.synchronizeWorkspace('b')
  await new Promise(resolve=>setImmediate(resolve))
  assert.deepEqual(bindings,['a'.repeat(32)])
  slowBind.resolve()
  assert.equal(await oldBind,'WorkspaceChangedError')
  await newBind
  assert.deepEqual(bindings,['a'.repeat(32),'b'.repeat(32)])
  console.log('PASS workspace source integration: capture, immutable context, schema persistence, reference-only attachments, first-send adoption and ordered host binding across rapid chat switches')
})().catch(error=>{console.error(error);process.exitCode=1})

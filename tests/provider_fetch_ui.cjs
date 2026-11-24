// Exercise the production provider fetch hook and JSX, with synthetic responses only.
'use strict'
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm'), assert = require('node:assert/strict')
const root = path.resolve(__dirname, '..'), modules = path.join(root, '.build/chatbox/node_modules')
const ts = require(path.join(modules, 'typescript')), { JSDOM } = require(path.join(modules, 'jsdom'))
const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { url: 'file:///SlidePilot/index.html' })
global.window = dom.window; global.document = dom.window.document
Object.defineProperty(global, 'navigator', { value: dom.window.navigator, configurable: true })
global.IS_REACT_ACT_ENVIRONMENT = true
const React = require(path.join(modules, 'react')), { createRoot } = require(path.join(modules, 'react-dom/client'))
const jsx = require(path.join(modules, 'react/jsx-runtime'))
const tick = () => new Promise(resolve => setImmediate(resolve))
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
const compile = (source, fileName = 'actual.tsx') => {
  const result = ts.transpileModule(source, { fileName, reportDiagnostics: true, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } })
  assert.equal((result.diagnostics || []).filter(item => item.category === ts.DiagnosticCategory.Error).length, 0)
  return result.outputText
}
function find(node, predicate) {
  if (predicate(node)) return node
  return ts.forEachChild(node, child => find(child, predicate))
}
const readAst = file => ts.createSourceFile(file, fs.readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true, file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS)
const declared = (statement, name) => ts.isVariableStatement(statement) && statement.declarationList.declarations.some(item => {
  if (ts.isIdentifier(item.name)) return item.name.text === name
  return ts.isArrayBindingPattern(item.name) && item.name.elements.some(part => ts.isBindingElement(part) && ts.isIdentifier(part.name) && part.name.text === name)
})
const route = readAst(path.join(root, '.build/chatbox/src/renderer/routes/settings/provider/$providerId.tsx'))
const body = find(route, node => ts.isBlock(node) && node.statements.some(statement => declared(statement, 'handleFetchModels')))
assert(body, 'Production provider fetch implementation must exist')
const start = body.statements.findIndex(statement => declared(statement, 'fetchingModels'))
const end = body.statements.findIndex(statement => declared(statement, 'handleFetchModels'))
assert(start >= 0 && end > start, 'Capture actual fetch hooks, connection effect and handler together')
const extractStatement = name => {
  const statement = body.statements.find(item => declared(item, name))
  assert(statement, `Production statement ${name} exists`)
  return statement.getText(route)
}
const attribute = (node, name) => node.openingElement.attributes.properties.find(item => ts.isJsxAttribute(item) && item.name.getText(route) === name)
const expression = item => item?.initializer && ts.isJsxExpression(item.initializer) ? item.initializer.expression?.getText(route) : undefined
const fetchButton = find(route, node => ts.isJsxElement(node) && node.openingElement.tagName.getText(route) === 'Button' && expression(attribute(node, 'onClick')) === 'handleFetchModels')
const status = find(route, node => ts.isJsxExpression(node) && node.expression && ts.isBinaryExpression(node.expression) && ts.isIdentifier(node.expression.left) && node.expression.left.text === 'modelFetchStatus')
const modal = find(route, node => ts.isJsxElement(node) && node.openingElement.tagName.getText(route) === 'AdaptiveModal' && expression(attribute(node, 'opened')) === '!!fetchedModels')
assert(fetchButton && status && modal, 'Use actual Fetch button, accessible feedback and fetched-model modal JSX')

// Use the production URL normalizer, not a reimplemented endpoint matcher.
const util = readAst(path.join(root, '.build/chatbox/src/shared/utils/llm_utils.ts'))
const normalizer = find(util, node => ts.isFunctionDeclaration(node) && node.name?.text === 'normalizeOpenAIApiHostAndPath')
assert(normalizer)
const normalized = {}
vm.runInNewContext(compile(normalizer.getText(util), 'normalizer.ts'), { exports: normalized })
const helper = {}
vm.runInNewContext(compile(fs.readFileSync(path.join(root, 'chatbox/provider-models.ts'), 'utf8'), 'provider-models.ts'), {
  exports: helper, URL, AbortController, DOMException, setTimeout, clearTimeout,
  require: name => { assert.equal(name, '@shared/utils/llm_utils'); return normalized },
})

const requests = [], saved = [], checked = []
const request = { apiRequest: options => { const reply = deferred(); requests.push({ options, ...reply }); return reply.promise } }
let latest
const harness = `
  const {useState,useRef,useEffect}=require('react');
  export default function FetchHarness(props) {
    const {baseInfo,providerId,providerSettings,language,displayModels,settings,handleCheckModel,capture}=props;
    const setProviderSettings=props.setProviderSettings;
    ${body.statements.slice(start, end + 1).map(item => item.getText(route)).join('\n')}
    ${extractStatement('selectedTestModel')}
    ${extractStatement('checkModel')}
    ${extractStatement('handleCheckApiKey')}
    capture({handleFetchModels,fetchingModels,fetchedModels,modelFetchStatus,setSelectedTestModel,checkModel,handleCheckApiKey});
    return <>${fetchButton.getText(route)}${status.getText(route)}${modal.getText(route)}</>;
  }
`
const scope = {
  exports: {}, AbortController, DOMException, ...helper,
  createModelDependencies: async () => ({ request }),
  getProviderDefinition: () => undefined,
  forceRefreshRegistry: async () => { throw Error('Unexpected registry call') },
  getModelSettingUtil: () => ({ getMergeOptionGroups: async () => { throw Error('Unexpected generic catalogue call') } }),
  t: text => text, IconRefresh: () => null, ScalableIcon: () => null,
  Button: ({ children, onClick, disabled, 'aria-busy': busy }) => jsx.jsx('button', { onClick, disabled, 'aria-busy': busy, children }),
  Text: ({ children, role, 'aria-live': live }) => jsx.jsx('p', { role, 'aria-live': live, children }),
  AdaptiveModal: ({ opened, children }) => opened ? jsx.jsx('section', { 'data-fetched-models': true, children }) : null,
  ModelList: ({ models, displayedModelIds }) => jsx.jsx('ul', { children: models.map(model => jsx.jsx('li', { 'data-model-id': model.modelId, 'data-existing': displayedModelIds?.includes(model.modelId) || false, children: model.modelId }, model.modelId)) }),
  require: name => { if (name === 'react') return React; if (name === 'react/jsx-runtime') return jsx; throw Error(name) },
}
vm.createContext(scope)
vm.runInContext(compile(harness, 'provider-fetch-harness.tsx'), scope)
const Component = scope.exports.default, view = createRoot(document.getElementById('root'))
const endpoint = 'https://token-plan.maas.qianwenaiapi.com/compatible-mode/v1'
const models = Object.freeze([Object.freeze({ modelId: 'qwen3.8-flash' }), Object.freeze({ modelId: 'qwen3.8-max' })])
let props = {
  baseInfo: { id: 'openai', name: 'OpenAI', defaultSettings: { apiHost: endpoint } }, providerId: 'openai',
  providerSettings: { apiHost: endpoint, apiKey: 'synthetic-test-key', useProxy: true }, language: 'zh-Hans',
  displayModels: models, settings: { defaultChatModel: { provider: 'openai', model: 'qwen3.8-max' } },
  handleCheckModel: async model => { checked.push(model.modelId) }, setProviderSettings: value => { saved.push(value) },
  capture: value => { latest = value },
}
const render = async changes => {
  props = { ...props, ...changes }
  await React.act(async () => { view.render(jsx.jsx(Component, props)); await tick() })
}
const startFetch = async () => {
  const count = requests.length
  await React.act(async () => { void latest.handleFetchModels(); await tick() })
  assert.equal(requests.length, count + 1)
  return requests.at(-1)
}
const respond = async (item, rows) => {
  await React.act(async () => { item.resolve({ ok: true, status: 200, json: async () => ({ data: rows }) }); await tick() })
}
const assertNoSavedChanges = () => { assert.equal(saved.length, 0, 'Fetching never silently changes the saved model list'); assert.equal(props.displayModels, models) }

;(async () => {
  await render({})
  await React.act(async () => { const button = document.querySelector('button'); button.click(); button.click(); void latest.handleFetchModels(); await tick() })
  assert.equal(requests.length, 1, 'DOM clicks and direct reentry share the real single-flight lock')
  assert.equal(document.querySelector('button').disabled, true)
  assert.equal(document.querySelector('button').getAttribute('aria-busy'), 'true')
  assert.equal(requests[0].options.url, endpoint + '/models')
  assert.equal(requests[0].options.useProxy, false, 'Built-in OpenAI uses its actual non-relay transport setting')
  await respond(requests[0], models.map(model => ({ id: model.modelId })))
  assert.equal(latest.modelFetchStatus.kind, 'success')
  assert(document.querySelector('[role=status]').textContent.includes('全部已在当前列表中'))
  assert.equal(document.querySelectorAll('[data-fetched-models] [data-existing=true]').length, 2, 'All-existing results still open the fetched-model list')
  assert.equal(document.querySelector('button').disabled, false)
  assertNoSavedChanges()

  const oldHost = await startFetch()
  await render({ providerSettings: { ...props.providerSettings, apiHost: endpoint + '/' } })
  assert.equal(oldHost.options.signal.aborted, true, 'Editing the host aborts the real request')
  await respond(oldHost, [{ id: 'stale-host-model' }])
  assert.equal(latest.fetchedModels, undefined)
  assert.equal(latest.modelFetchStatus, undefined)

  const oldKey = await startFetch()
  await render({ providerSettings: { ...props.providerSettings, apiKey: 'synthetic-replacement-key' } })
  assert.equal(oldKey.options.signal.aborted, true, 'Editing the key aborts the real request')
  await respond(oldKey, [{ id: 'stale-key-model' }])
  assert.equal(latest.fetchedModels, undefined)
  assert.equal(latest.modelFetchStatus, undefined)

  const oldProvider = await startFetch()
  await render({ providerId: 'qwen', baseInfo: { id: 'qwen', defaultSettings: { apiHost: endpoint } } })
  assert.equal(oldProvider.options.signal.aborted, true, 'Switching providers invalidates the previous request')
  const currentProvider = await startFetch()
  assert.equal(currentProvider.options.useProxy, true, 'Built-in Qwen preserves its configured proxy choice')
  await respond(oldProvider, [{ id: 'other-provider-model' }])
  assert.equal(latest.fetchingModels, true, 'Old completion cannot clear a newer request loading state')
  assert.equal(latest.fetchedModels, undefined)
  await respond(currentProvider, [{ id: 'qwen3.8-flash' }])
  assert.equal(latest.fetchedModels[0].modelId, 'qwen3.8-flash')
  assert(!document.body.textContent.includes('other-provider-model'))

  const empty = await startFetch()
  await respond(empty, [])
  assert.equal(latest.modelFetchStatus.kind, 'empty')
  assert(document.querySelector('[role=status]').textContent.includes('空模型列表'))
  assert.equal(document.querySelector('[data-fetched-models]'), null)
  assertNoSavedChanges()

  const denied = await startFetch()
  await React.act(async () => { denied.resolve({ ok: false, status: 401, json: async () => { throw Error('Error response body must not be read') } }); await tick() })
  assert.equal(latest.modelFetchStatus.kind, 'error')
  assert(document.querySelector('[role=alert]').textContent.includes('HTTP 401'))
  assert.equal(document.querySelector('button').disabled, false)
  const unsafe = await startFetch()
  await React.act(async () => { unsafe.reject(Error('secret-synthetic-leak Authorization Bearer synthetic-replacement-key')); await tick() })
  const errorText = document.querySelector('[role=alert]').textContent
  assert(errorText.includes('无法连接模型服务'))
  assert(!errorText.includes('secret-synthetic-leak') && !errorText.includes('synthetic-replacement-key'), 'Raw provider error details and keys never enter visible feedback')
  assertNoSavedChanges()

  await render({ providerId: 'custom-provider-synthetic', baseInfo: { id: 'custom-provider-synthetic', type: 'openai', isCustom: true, defaultSettings: {} } })
  const custom = await startFetch()
  assert.equal(custom.options.useProxy, true, 'Custom OpenAI-compatible providers preserve their configured proxy choice')
  await respond(custom, [{ id: 'qwen3.8-flash' }])

  await render({ providerId: 'qwen', baseInfo: { id: 'qwen', defaultSettings: { apiHost: endpoint } }, settings: { defaultChatModel: { provider: 'qwen', model: 'qwen3.8-max' } } })
  await React.act(async () => { await latest.handleCheckApiKey(); await tick() })
  assert.equal(checked.at(-1), 'qwen3.8-max', 'Check tests the current valid model instead of always using the first')
  await render({ settings: { defaultChatModel: { provider: 'qwen', model: 'removed-model' } } })
  await React.act(async () => { await latest.handleCheckApiKey(); await tick() })
  assert.equal(checked.at(-1), 'qwen3.8-flash', 'Removed current model falls back to a visible model')
  await render({ settings: { defaultChatModel: { provider: 'different-provider', model: 'qwen3.8-max' } } })
  await React.act(async () => { await latest.handleCheckApiKey(); latest.setSelectedTestModel('qwen3.8-max'); await tick() })
  assert.equal(checked.at(-1), 'qwen3.8-flash', 'Another provider default cannot select this provider test model')
  await React.act(async () => { await latest.handleCheckApiKey(); await tick() })
  assert.equal(checked.at(-1), 'qwen3.8-max', 'Valid explicit test choice is retained')
  const checks = checked.length
  await React.act(async () => { await latest.handleCheckApiKey('not-visible'); await tick() })
  assert.equal(checked.length, checks, 'An invisible explicit model is rejected')
  await render({ displayModels: [] })
  await React.act(async () => { await latest.handleCheckApiKey(); await tick() })
  assert.equal(checked.length, checks, 'An empty current model list cannot run a stale model test')

  await React.act(async () => { view.unmount(); await tick() })
  console.log('PASS provider Fetch UI from production AST + real helper: single-flight; host/key cancellation; provider isolation; openai/Qwen/custom proxy choices; all-existing success; visible empty/safe errors; current valid Check model selection; saved settings untouched; no network')
})().catch(async error => { console.error(error); process.exitCode = 1; await React.act(async () => { view.unmount(); await tick() }) }).finally(() => dom.window.close())

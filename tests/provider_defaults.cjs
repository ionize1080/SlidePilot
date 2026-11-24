'use strict'
// Synthetic configuration only; never reads the user's profile or performs a request.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { createRequire } = require('node:module')
const root = path.resolve(__dirname, '..')
const source = path.resolve(process.argv[2] || path.join(root, '.build/chatbox'))
const dependencies = createRequire(path.join(source, 'package.json'))
const ts = dependencies('typescript')
const bootstrap = fs.readFileSync(path.join(root, 'chatbox/bootstrap.cjs'), 'utf8')
const context = { python: 'runtime', server: 'server', referenceServer: 'reference' }
vm.runInNewContext(bootstrap.slice(bootstrap.indexOf('function config(saved)'), bootstrap.indexOf('\nlet primary')) + '\nglobalThis.normalize = config', context)
const normalize = value => JSON.parse(JSON.stringify(context.normalize(value)))
const host = 'https://token-plan.maas.qianwenaiapi.com/compatible-mode/v1'
const sentinel = 'synthetic-credential'
const plain = value => JSON.parse(JSON.stringify(value))

const empty = { providers: { openai: { apiHost: host, apiKey: sentinel, models: [], useProxy: false }, other: { apiKey: 'other-synthetic', models: [{ modelId: 'other' }] } }, defaultChatModel: { provider: 'openai', model: 'qwen3.8-flash' }, proxy: 'unchanged' }
const snapshot = JSON.stringify(empty)
const repaired = normalize(empty)
assert.equal(JSON.stringify(empty), snapshot, 'repair must not mutate saved objects')
assert.deepEqual(repaired.providers.openai.models.map(m => m.modelId), ['qwen3.8-flash', 'qwen3.8-max'])
assert.equal(repaired.providers.openai.apiKey, sentinel)
assert.equal(repaired.providers.openai.useProxy, false)
assert.deepEqual(repaired.providers.other, empty.providers.other)
assert.deepEqual(repaired.defaultChatModel, empty.defaultChatModel)
assert.equal(repaired.proxy, empty.proxy)
const chosen = { ...empty, providers: { openai: { ...empty.providers.openai, models: [{ modelId: 'my-chosen-model', nickname: 'mine', capabilities: ['vision'] }] } }, defaultChatModel: { provider: 'other', model: 'user-default' } }
assert.deepEqual(normalize(chosen).providers.openai, chosen.providers.openai, 'nonempty user list remains exact')
assert.deepEqual(normalize(chosen).defaultChatModel, chosen.defaultChatModel)
for (const apiHost of ['https://api.openai.com/v1', 'https://other.invalid/v1', 'https://token-plan.maas.qianwenaiapi.com.evil.invalid/compatible-mode/v1', 'http://token-plan.maas.qianwenaiapi.com/compatible-mode/v1', '']) {
  const provider = { apiHost, apiKey: sentinel, models: [], useProxy: true }
  assert.deepEqual(normalize({ providers: { openai: provider } }).providers.openai, provider)
}
const implicitOpenAI = { apiKey: sentinel, models: [{ modelId: 'gpt-chosen' }] }
assert.deepEqual(normalize({ providers: { openai: implicitOpenAI } }).providers.openai, implicitOpenAI, 'do not repoint an existing provider without an explicit host')
const oauth = { apiHost: host, activeAuthMode: 'oauth', models: [] }
assert.deepEqual(normalize({ providers: { openai: oauth } }).providers.openai, oauth)
assert.equal(normalize({}).providers.openai.apiHost, host)
assert.equal(normalize({}).defaultChatModel.model, 'qwen3.8-flash')

function loadTs(filename, mockRequire) {
  const output = ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2021, module: ts.ModuleKind.CommonJS }, reportDiagnostics: true })
  assert.equal(output.diagnostics?.length || 0, 0)
  const exports = {}
  vm.runInNewContext(output.outputText, { exports, require: mockRequire, URL, AbortController, DOMException, setTimeout, clearTimeout, Response }, { filename })
  return exports
}
const normalization = loadTs(path.join(source, 'src/shared/utils/llm_utils.ts'), () => ({ ModelProviderEnum: {} }))
const helper = loadTs(path.join(root, 'chatbox/provider-models.ts'), name => {
  assert.equal(name, '@shared/utils/llm_utils')
  return normalization
})
const builtin = { id: 'openai', type: 'openai' }
const custom = { id: 'custom-provider-fixture', type: 'openai', isCustom: true }
const qwen = { id: 'qwen', type: 'openai' }
const url = host + '/models'
for (const provider of [builtin, custom, qwen]) {
  assert.equal(helper.tokenPlanModelsUrl(provider, { apiHost: host }), url)
  assert.equal(helper.tokenPlanModelsUrl(provider, { apiHost: host + '/' }), url)
  assert.equal(helper.tokenPlanModelsUrl(provider, { apiHost: host + '/chat/completions' }), url)
  assert.equal(helper.tokenPlanModelsUrl(provider, { apiHost: host, activeAuthMode: 'oauth' }), undefined)
}
assert.equal(helper.tokenPlanModelsUrl(custom, { apiHost: 'https://token-plan.maas.qianwenaiapi.com', apiPath: '/compatible-mode/v1/chat/completions' }), url)
assert.equal(helper.tokenPlanModelsUrl(custom, { apiHost: host, apiPath: '/responses' }), undefined)
assert.equal(helper.tokenPlanModelsUrl(builtin, { apiHost: host, apiPath: '/responses' }), url, 'built-in factory ignores apiPath')
for (const invalid of ['https://api.openai.com/v1', 'https://token-plan.maas.qianwenaiapi.com.evil.invalid/compatible-mode/v1', host + '?secret=synthetic', host + '#suffix', 'https://synthetic:credential@token-plan.maas.qianwenaiapi.com/compatible-mode/v1', host.replace('https:', 'http:')]) {
  assert.equal(helper.tokenPlanModelsUrl(custom, { apiHost: invalid }), undefined)
}
assert.equal(helper.tokenPlanModelsUrl({ id: 'claude', type: 'claude' }, { apiHost: host }), undefined)
const models = [{ modelId: 'qwen3.8-flash' }, { modelId: 'qwen3.8-max' }]
assert.equal(helper.selectTestModel(models, 'qwen3.8-max', { provider: 'openai', model: 'qwen3.8-flash' }, 'openai'), 'qwen3.8-max')
assert.equal(helper.selectTestModel(models, 'deleted-model', { provider: 'openai', model: 'qwen3.8-max' }, 'openai'), 'qwen3.8-max')
assert.equal(helper.selectTestModel(models, undefined, { provider: 'other', model: 'qwen3.8-max' }, 'openai'), 'qwen3.8-flash')
assert.equal(helper.selectTestModel([], 'gpt-default', { provider: 'openai', model: 'qwen3.8-flash' }, 'openai'), undefined)

async function main() {
  let requests = []
  const request = { apiRequest: async options => {
    requests.push(options)
    return Response.json({ data: [{ id: 'actual-remote-only' }, { id: 'actual-remote-only' }, { id: 'second-model' }, { nope: true }] })
  } }
  const list = await helper.fetchTokenPlanModels(url, { apiKey: sentinel, models, useProxy: false }, request, new AbortController().signal)
  assert.deepEqual(plain(list), [{ modelId: 'actual-remote-only', type: 'chat' }, { modelId: 'second-model', type: 'chat' }], 'only the authenticated remote list, never saved/GPT fallback models')
  assert.equal(requests.length, 1)
  assert.equal(requests[0].url, url)
  assert.equal(requests[0].method, 'GET')
  assert.equal(requests[0].headers.Authorization, 'Bearer ' + sentinel)
  assert.equal(requests[0].retry, 0)
  assert.equal(requests[0].useProxy, false)
  assert(requests[0].signal instanceof AbortSignal)
  await helper.fetchTokenPlanModels(url, { apiKey: sentinel, useProxy: true }, request, new AbortController().signal)
  assert.equal(requests[1].useProxy, true, 'explicit compatible provider proxy choice remains intact')
  assert.deepEqual(plain(await helper.fetchTokenPlanModels(url, { apiKey: sentinel }, { apiRequest: async () => Response.json({ data: [] }) }, new AbortController().signal)), [])
  for (const status of [401, 403, 404, 405, 429, 500]) {
    const rejected = { apiRequest: async () => new Response(sentinel + ' sensitive backend body', { status }) }
    await assert.rejects(() => helper.fetchTokenPlanModels(url, { apiKey: sentinel }, rejected, new AbortController().signal), error => {
      assert.equal(error.kind, 'http'); assert.equal(error.status, status)
      for (const chinese of [true, false]) { const text = helper.modelFetchErrorText(error, chinese); assert(text.includes('HTTP ' + status)); assert(!text.includes(sentinel)); assert(!text.includes('backend')) }
      return true
    })
  }
  const rawFailure = new Error('Status Code 401 sensitive ' + sentinel)
  assert(helper.modelFetchErrorText(rawFailure, true).includes('HTTP 401'))
  assert(!helper.modelFetchErrorText(rawFailure, false).includes(sentinel))
  for (const response of [Response.json({ error: sentinel }), Response.json({ data: [{ id: '' }] }), new Response('invalid-json')]) {
    await assert.rejects(() => helper.fetchTokenPlanModels(url, { apiKey: sentinel }, { apiRequest: async () => response }, new AbortController().signal), error => error.kind === 'invalid')
  }
  await assert.rejects(() => helper.fetchTokenPlanModels(url, { apiKey: '' }, request, new AbortController().signal), error => error.kind === 'key')
  await assert.rejects(() => helper.fetchTokenPlanModels(url, { apiKey: sentinel }, { apiRequest: async () => { throw new TypeError('fetch failed sensitive ' + sentinel) } }, new AbortController().signal), error => error.kind === 'network' && !helper.modelFetchErrorText(error, true).includes(sentinel))
  let timeoutSignal
  await assert.rejects(() => helper.fetchTokenPlanModels(url, { apiKey: sentinel }, { apiRequest: options => { timeoutSignal = options.signal; return new Promise(() => {}) } }, new AbortController().signal, 15), error => error.kind === 'timeout')
  assert.equal(timeoutSignal.aborted, true)
  const abort = new AbortController()
  const cancelled = helper.fetchTokenPlanModels(url, { apiKey: sentinel }, { apiRequest: () => new Promise(() => {}) }, abort.signal)
  abort.abort()
  await assert.rejects(cancelled, error => error.name === 'AbortError')
  await assert.rejects(() => helper.fetchTokenPlanModels(url, { apiKey: sentinel }, request, abort.signal), error => error.name === 'AbortError')
  console.log('PASS TokenPlan defaults, exact endpoint matching, provider preservation, current test selection, authenticated live-only GET, safe HTTP/network/empty/timeout and cancellation contracts')
}
main().catch(error => { console.error(error); process.exitCode = 1 })

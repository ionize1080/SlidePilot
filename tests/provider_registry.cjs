// Exercise native provider discovery using real source modules and an in-memory HTTP adapter.
// Never reads a profile or credential file, and never performs a network request.
'use strict'
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const root = path.resolve(__dirname, '..')
const source = path.resolve(process.argv[2] || path.join(root, '.build/chatbox'))
const ts = require(path.join(root, '.build/chatbox/node_modules/typescript'))
function load(file, modules) {
  const output = ts.transpileModule(fs.readFileSync(path.join(source, 'src', file), 'utf8'), {
    compilerOptions: { target: ts.ScriptTarget.ES2021, module: ts.ModuleKind.CommonJS }, reportDiagnostics: true,
  })
  assert.equal(output.diagnostics?.length || 0, 0)
  const exports = {}
  vm.runInNewContext(output.outputText, { exports, require(id) {
    assert(Object.hasOwn(modules, id), `Unexpected import in ${file}: ${id}`)
    return modules[id]
  } }, { filename: file })
  return exports
}
const never = () => { throw Error('Unexpected SDK/network call') }
class AbstractModel { constructor(options, dependencies) { this.options = options; this.dependencies = dependencies } }
class ApiError extends Error {}
const types = { ModelProviderEnum: { OpenAI: 'openai' }, ModelProviderType: { OpenAI: 'openai' } }
const oauth = load('shared/oauth/index.ts', {})
const normalization = load('shared/utils/llm_utils.ts', { '../types': types })
const remote = load('shared/models/openai-compatible.ts', {
  '@ai-sdk/openai-compatible': { createOpenAICompatible: never }, ai: {},
  './abstract-ai-sdk': { default: AbstractModel }, './errors': { ApiError },
  './utils/fetch-proxy': { createFetchWithProxy: never },
})
const openai = load('shared/providers/definitions/models/openai.ts', {
  '@ai-sdk/openai': { createOpenAI: never }, ai: {},
  '../../../models/abstract-ai-sdk': { default: AbstractModel },
  '../../../models/openai-compatible': remote,
  '../../../models/utils/fetch-proxy': { createFetchWithProxy: never },
  '../../../utils/llm_utils': normalization,
})
const { openaiProvider } = load('shared/providers/definitions/openai.ts', {
  '../../types': types, '../../oauth': oauth, '../registry': { defineProvider: value => value },
  './models/openai': openai, './models/openai-responses': { default: class { constructor() { never() } } },
})
let stored = {}, captured, failure, requests = [], resolvedPlatforms = [], mergedProviders
const wrappedProvider = { ...openaiProvider, createModel(config) { captured = config; return openaiProvider.createModel(config) } }
const dependencies = { platformType: 'desktop', request: { async apiRequest(request) {
  requests.push(request)
  if (failure) throw failure
  return { async json() { return { data: [{ id: 'qwen3.8-flash' }, { id: 'synthetic-new-model' }] } } }
} } }
const { default: RegistrySettingUtil } = load('renderer/packages/model-setting-utils/registry-setting-util.ts', {
  '@shared/oauth': {
    mergeSharedOAuthProviderSettings(provider, providers) { mergedProviders = providers; return oauth.mergeSharedOAuthProviderSettings(provider, providers) },
    resolveEffectiveApiKey(settings, platform) { resolvedPlatforms.push(platform); return oauth.resolveEffectiveApiKey(settings, platform) },
  },
  '@/stores/settingsStore': { settingsStore: { getState: () => ({ providers: stored }) } },
  '@shared/providers': { getProviderDefinition: id => id === 'openai' ? wrappedProvider : undefined },
  '../../../shared/providers': { getProviderDefinition: id => id === 'openai' ? wrappedProvider : undefined },
  '@/adapters': { createModelDependencies: async () => dependencies }, './base-config': { default: class {} },
})

;(async () => {
  const util = new RegistrySettingUtil('openai')
  const base = 'https://token-plan.maas.qianwenaiapi.com/compatible-mode/v1'
  stored = { openai: { apiKey: 'synthetic-old', apiHost: 'https://old.invalid/v1', models: [{ modelId: 'old-model' }] }, other: { apiKey: 'synthetic-other' } }
  const snapshot = JSON.stringify(stored)
  const edited = { apiKey: 'synthetic-current', apiHost: ` ${base}/chat/completions `, models: [], apiPath: '/chat/completions' }
  const models = await util.listProviderModels(edited)
  assert.equal(requests.length, 1)
  assert.equal(requests[0].url, base + '/models')
  assert.equal(requests[0].method, 'GET')
  assert.equal(requests[0].headers.Authorization, 'Bearer ' + edited.apiKey)
  assert.equal(requests[0].useProxy, false)
  assert.equal(models.length, 2)
  assert.equal(models[1].modelId, 'synthetic-new-model')
  assert.equal(captured.formattedApiPath, '/chat/completions')
  assert.equal(captured.providerSetting.apiKey, edited.apiKey)
  assert.equal(captured.globalSettings.providers.other, stored.other)
  assert.equal(mergedProviders.other, stored.other)
  assert.equal(JSON.stringify(stored), snapshot, 'discovery must not mutate saved providers')
  assert.equal(captured.model.modelId, openaiProvider.defaultSettings.models[0].modelId)
  assert.deepEqual(resolvedPlatforms, ['desktop'])

  await util.listProviderModels({ apiKey: '', models: [{ modelId: 'explicit-model' }] })
  assert.equal(requests.at(-1).headers.Authorization, 'Bearer ', 'cleared input must not restore an old key')
  assert.equal(captured.model.modelId, 'explicit-model')
  assert.equal(captured.formattedApiHost, 'https://old.invalid/v1')

  dependencies.platformType = undefined
  await util.listProviderModels({ apiKey: 'synthetic-next', apiHost: base })
  assert.equal(resolvedPlatforms.at(-1), 'desktop')
  const requestCount = requests.length
  assert.equal((await new RegistrySettingUtil('missing').listProviderModels({})).length, 0)
  assert.equal(requests.length, requestCount)

  failure = new ApiError('HTTP 401')
  await assert.rejects(util.listProviderModels(edited), error => error === failure)
  console.log('PASS: native model discovery resolves current credentials, preserves provider settings, normalizes GET /models, and propagates failure; no network.')
})().catch(error => { console.error(error.message); process.exitCode = 1 })

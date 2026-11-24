import type { ProviderBaseInfo, ProviderModelInfo, ProviderSettings } from '@shared/types'
import type { RequestAdapter } from '@shared/types/adapters'
import { normalizeOpenAIApiHostAndPath } from '@shared/utils/llm_utils'

/** Only this exact OpenAI-compatible service bypasses Chatbox's merged catalogue. */
export function tokenPlanModelsUrl(provider: Pick<ProviderBaseInfo, 'id' | 'type' | 'isCustom'>, settings: ProviderSettings): string | undefined {
  if (settings.activeAuthMode === 'oauth') return undefined
  if (!['openai', 'qwen'].includes(provider.id) && !(provider.isCustom && provider.type === 'openai')) return undefined
  const normalized = normalizeOpenAIApiHostAndPath({
    apiHost: settings.apiHost,
    apiPath: provider.isCustom ? settings.apiPath : undefined,
  })
  try {
    const endpoint = new URL(normalized.apiHost + normalized.apiPath)
    if (endpoint.origin !== 'https://token-plan.maas.qianwenaiapi.com' || endpoint.username || endpoint.password ||
        endpoint.search || endpoint.hash || endpoint.pathname !== '/compatible-mode/v1/chat/completions') return undefined
    return endpoint.origin + '/compatible-mode/v1/models'
  } catch {
    return undefined
  }
}

type FetchFailure = 'key' | 'http' | 'network' | 'timeout' | 'invalid'
export class ModelFetchError extends Error {
  constructor(public readonly kind: FetchFailure, public readonly status?: number) {
    super(kind)
    this.name = 'ModelFetchError'
  }
}

/** Never show response bodies, credentials, or arbitrary server/network exception text. */
export function modelFetchErrorText(error: unknown, chinese: boolean): string {
  const failure = safeFetchError(error)
  if (failure.kind === 'key') return chinese ? '请先填写此服务商的 API 密钥，再获取模型。' : 'Enter this provider’s API key before fetching models.'
  if (failure.kind === 'timeout') return chinese ? '获取超时（30 秒）。请检查网络和代理后重试。' : 'The model request timed out (30 seconds). Check your network and proxy, then retry.'
  if (failure.kind === 'invalid') return chinese ? '服务返回的不是有效模型列表；现有模型未变更。' : 'The service did not return a valid model list. Your saved models are unchanged.'
  if (failure.kind === 'http') {
    const hint = failure.status === 401 || failure.status === 403
      ? (chinese ? '请检查密钥及此服务的访问权限。' : 'Check the API key and access to this service.')
      : failure.status === 404 || failure.status === 405
        ? (chinese ? '此服务未提供模型列表接口，可手动添加模型。' : 'This service does not provide a model-list endpoint. Add models manually.')
        : failure.status === 429
          ? (chinese ? '请求受到限流，请稍后重试。' : 'The service rate-limited this request. Try again later.')
          : (chinese ? '服务暂时无法返回列表，请稍后重试。' : 'The service could not return a list. Try again later.')
    return `HTTP ${failure.status} · ${hint}`
  }
  return chinese ? '无法连接模型服务。请检查 API 地址、网络、代理和证书后重试。' : 'Could not connect to the model service. Check the API address, network, proxy, and certificate, then retry.'
}

function safeFetchError(error: unknown): ModelFetchError {
  if (error instanceof ModelFetchError) return error
  const details = error && typeof error === 'object' ? error as { status?: unknown; statusCode?: unknown; message?: unknown } : {}
  const numeric = Number(details.status ?? details.statusCode)
  const match = typeof details.message === 'string' ? details.message.match(/\b(?:Status Code|HTTP)\s+(\d{3})\b/i) : undefined
  const status = Number.isInteger(numeric) && numeric >= 400 && numeric <= 599 ? numeric : Number(match?.[1])
  return Number.isInteger(status) && status >= 400 && status <= 599
    ? new ModelFetchError('http', status) : new ModelFetchError('network')
}

export async function fetchTokenPlanModels(
  url: string,
  settings: ProviderSettings,
  request: RequestAdapter,
  signal: AbortSignal,
  timeoutMs = 30_000
): Promise<ProviderModelInfo[]> {
  if (signal.aborted) throw signal.reason || new DOMException('Aborted', 'AbortError')
  if (!settings.apiKey?.trim()) throw new ModelFetchError('key')
  const controller = new AbortController()
  let rejectCancelled: (reason: unknown) => void = () => {}
  const cancelled = new Promise<never>((_resolve, reject) => { rejectCancelled = reject })
  const abort = () => {
    controller.abort(signal.reason)
    rejectCancelled(signal.reason || new DOMException('Aborted', 'AbortError'))
  }
  signal.addEventListener('abort', abort, { once: true })
  let timedOut = false
  let timer: ReturnType<typeof setTimeout> | undefined
  const deadline = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => {
      timedOut = true
      controller.abort()
      reject(new ModelFetchError('timeout'))
    }, timeoutMs)
  })
  try {
    const operation = async () => {
      const response = await request.apiRequest({
        url, method: 'GET', headers: { Authorization: `Bearer ${settings.apiKey}` },
        signal: controller.signal, retry: 0, useProxy: settings.useProxy,
      })
      if (!response.ok) throw new ModelFetchError('http', response.status)
      let data: unknown
      try { data = await response.json() } catch { throw new ModelFetchError('invalid') }
      if (!data || typeof data !== 'object' || !Array.isArray((data as { data?: unknown }).data)) throw new ModelFetchError('invalid')
      const rows = (data as { data: unknown[] }).data
      const models: ProviderModelInfo[] = []
      const ids = new Set<string>()
      for (const row of rows) {
        const id = row && typeof row === 'object' ? (row as { id?: unknown }).id : undefined
        if (typeof id !== 'string' || !id.trim() || id.length > 256 || /[\x00-\x1f\x7f]/.test(id)) continue
        const modelId = id.trim()
        if (!ids.has(modelId)) { ids.add(modelId); models.push({ modelId, type: 'chat' }) }
      }
      if (rows.length && !models.length) throw new ModelFetchError('invalid')
      return models
    }
    return await Promise.race([operation(), deadline, cancelled])
  } catch (error) {
    if (signal.aborted) throw signal.reason || new DOMException('Aborted', 'AbortError')
    if (timedOut) throw new ModelFetchError('timeout')
    throw safeFetchError(error)
  } finally {
    clearTimeout(timer)
    signal.removeEventListener('abort', abort)
  }
}

/** A test must always refer to a model visible in the current provider's list. */
export function selectTestModel(models: ProviderModelInfo[], selected: string | undefined,
  current: { provider: string; model: string } | undefined, providerId: string): string | undefined {
  const exists = (id: string | undefined) => id && models.some(model => model.modelId === id)
  if (exists(selected)) return selected
  if (current?.provider === providerId && exists(current.model)) return current.model
  return models[0]?.modelId
}

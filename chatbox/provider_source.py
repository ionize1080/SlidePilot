"""Narrow, reversible provider settings fixes for the pinned Chatbox source."""
from pathlib import Path
import shutil

FILE = "src/renderer/routes/settings/provider/$providerId.tsx"
HOOKS = [
    ("import { type ChangeEvent, useState } from 'react'",
     "import { type ChangeEvent, useEffect, useRef, useState } from 'react'"),
    ("import platform from '@/platform'",
     "import platform from '@/platform'\nimport { fetchTokenPlanModels, modelFetchErrorText, selectTestModel, tokenPlanModelsUrl } from '@/packages/slidepilot/provider-models'"),
    ("models: baseInfo?.defaultSettings?.models,",
     "models: baseInfo && tokenPlanModelsUrl(baseInfo, { ...baseInfo.defaultSettings, ...providerSettings })\n        ? ['qwen3.8-flash', 'qwen3.8-max'].map(modelId => ({ modelId, capabilities: ['tool_use'] } as ProviderModelInfo))\n        : baseInfo?.defaultSettings?.models,"),
    ("""  const [fetchingModels, setFetchingModels] = useState(false)
  const [fetchedModels, setFetchedModels] = useState<ProviderModelInfo[]>()

  const handleFetchModels = async () => {
    if (!baseInfo) return

    try {
      setFetchedModels(undefined)
      setFetchingModels(true)
      const providerDefinition = getProviderDefinition(baseInfo.id)
      if (providerDefinition?.modelsDevProviderId) {
        await forceRefreshRegistry()
      }
      const modelConfig = getModelSettingUtil(baseInfo.id, baseInfo.isCustom ? baseInfo.type : undefined)
      const modelList = await modelConfig.getMergeOptionGroups({
        ...baseInfo?.defaultSettings,
        ...providerSettings,
      })

      if (modelList.length) {
        setFetchedModels(modelList)
      } else {
        addToast(t('Failed to fetch models'))
      }
      setFetchingModels(false)
    } catch (error) {
      console.error('Failed to fetch models', error)
      setFetchedModels(undefined)
      setFetchingModels(false)
    }
  }""",
     """  const [fetchingModels, setFetchingModels] = useState(false)
  const [fetchedModels, setFetchedModels] = useState<ProviderModelInfo[]>()
  const [modelFetchStatus, setModelFetchStatus] = useState<{ kind: 'loading' | 'success' | 'empty' | 'error'; text: string }>()
  const modelFetchRequest = useRef<AbortController | null>(null)
  // Editing the connection or changing provider invalidates any outstanding result.
  // The signature lives only in memory; credentials never enter status text or logs.
  const modelFetchSignature = JSON.stringify([providerId, providerSettings?.apiHost, providerSettings?.apiPath,
    providerSettings?.apiKey, providerSettings?.useProxy, providerSettings?.activeAuthMode,
    providerSettings?.oauth?.accessToken, baseInfo?.type, baseInfo?.defaultSettings?.apiHost])
  const latestModelFetchSignature = useRef(modelFetchSignature)
  latestModelFetchSignature.current = modelFetchSignature
  useEffect(() => {
    modelFetchRequest.current?.abort()
    modelFetchRequest.current = null
    setFetchingModels(false)
    setFetchedModels(undefined)
    setModelFetchStatus(undefined)
    return () => { modelFetchRequest.current?.abort(); modelFetchRequest.current = null }
  }, [modelFetchSignature])

  const handleFetchModels = async () => {
    if (!baseInfo || modelFetchRequest.current) return
    const controller = new AbortController()
    modelFetchRequest.current = controller
    const signature = modelFetchSignature
    const current = () => modelFetchRequest.current === controller && !controller.signal.aborted &&
      latestModelFetchSignature.current === signature
    const chinese = language.startsWith('zh')
    const connection = { ...baseInfo.defaultSettings, ...providerSettings }
    const tokenPlanUrl = tokenPlanModelsUrl(baseInfo, connection)
    setFetchedModels(undefined)
    setFetchingModels(true)
    setModelFetchStatus({ kind: 'loading', text: chinese ? '正在获取模型列表…' : 'Fetching model list…' })
    try {
      let modelList: ProviderModelInfo[]
      if (tokenPlanUrl) {
        const dependencies = await createModelDependencies()
        if (!current()) return
        // Match the existing model factory: built-in OpenAI never enables the relay.
        modelList = await fetchTokenPlanModels(tokenPlanUrl,
          baseInfo.id === 'openai' ? { ...connection, useProxy: false } : connection,
          dependencies.request, controller.signal)
      } else {
        const providerDefinition = getProviderDefinition(baseInfo.id)
        if (providerDefinition?.modelsDevProviderId) await forceRefreshRegistry()
        if (!current()) return
        const modelConfig = getModelSettingUtil(baseInfo.id, baseInfo.isCustom ? baseInfo.type : undefined)
        modelList = await modelConfig.getMergeOptionGroups(connection)
      }
      if (!current()) return
      if (!modelList.length) {
        setModelFetchStatus({ kind: 'empty', text: chinese
          ? '服务返回了空模型列表。现有模型未变更；可手动添加模型或稍后重试。'
          : 'The service returned an empty list. Your saved models are unchanged; add a model manually or retry later.' })
        return
      }
      setFetchedModels(modelList)
      const newCount = modelList.filter(model => !displayModels.some(saved => saved.modelId === model.modelId)).length
      setModelFetchStatus({ kind: 'success', text: chinese
        ? `已获取 ${modelList.length} 个模型${newCount ? `，可新增 ${newCount} 个。` : '，全部已在当前列表中。'}`
        : `Fetched ${modelList.length} models. ${newCount ? `${newCount} can be added.` : 'All are already in your list.'}` })
    } catch (error) {
      if (current()) setModelFetchStatus({ kind: 'error', text: modelFetchErrorText(error, chinese) })
    } finally {
      if (modelFetchRequest.current === controller) {
        modelFetchRequest.current = null
        setFetchingModels(false)
      }
    }
  }"""),
    ("  const checkModel =\n    selectedTestModel || baseInfo?.defaultSettings?.models?.[0]?.modelId || providerSettings?.models?.[0]?.modelId",
     "  const checkModel = selectTestModel(displayModels, selectedTestModel, settings.defaultChatModel, providerId)"),
    ("""                loading={fetchingModels}
                variant="light""",
     """                loading={fetchingModels}
                disabled={fetchingModels}
                aria-busy={fetchingModels}
                variant="light"""),
    ("""          <ModelList
            models={displayModels}""",
     """          {modelFetchStatus && (
            <Text size="xs" role={modelFetchStatus.kind === 'error' ? 'alert' : 'status'} aria-live="polite"
              c={modelFetchStatus.kind === 'error' ? 'red' : modelFetchStatus.kind === 'success' ? 'teal' : 'dimmed'}>
              {modelFetchStatus.text}
            </Text>
          )}
          <ModelList
            models={displayModels}"""),
    ("""          <ModelList
            models={fetchedModels || []}""",
     """          {modelFetchStatus?.kind === 'success' && <Text size="sm" c="teal" mb="sm" role="status">{modelFetchStatus.text}</Text>}
          <ModelList
            models={fetchedModels || []}"""),
]


def restore(src: Path):
    path = src / FILE
    if not path.is_file():
        return
    value = path.read_text(encoding="utf-8")
    for before, after in reversed(HOOKS):
        if before in value and (after in before or after not in value):
            continue
        if after in value:
            if value.count(after) != 1:
                raise RuntimeError("Ambiguous provider settings restore anchor")
            value = value.replace(after, before)
    path.write_text(value, encoding="utf-8")


def apply(src: Path):
    root = Path(__file__).resolve().parent
    target = src / "src/renderer/packages/slidepilot"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / "provider-models.ts", target / "provider-models.ts")
    path = src / FILE
    value = path.read_text(encoding="utf-8")
    for before, after in HOOKS:
        if after in value and (before in after or before not in value):
            continue
        if value.count(before) != 1:
            raise RuntimeError("Pinned provider settings anchor changed: " + before[:90])
        value = value.replace(before, after)
    path.write_text(value, encoding="utf-8")

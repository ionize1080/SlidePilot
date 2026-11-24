"""Keep native model discovery on the same credential path as normal chat."""
from pathlib import Path
import argparse


IMPORTS = """import { mergeSharedOAuthProviderSettings, resolveEffectiveApiKey } from '@shared/oauth'
import { settingsStore } from '@/stores/settingsStore'
"""
ORIGINAL = """    const model: ProviderModelInfo = settings.models?.[0] || definition.defaultSettings?.models?.[0] || { modelId: '' }
    const dependencies = await createModelDependencies()

    const modelInstance = definition.createModel({
      settings: { provider: this.provider, modelId: model.modelId },
      globalSettings: { providers: { [this.provider]: settings } } as Parameters<
        typeof definition.createModel
      >[0]['globalSettings'],
      config: { uuid: '' },
      dependencies,
      providerSetting: settings,
      formattedApiHost: settings.apiHost || definition.defaultSettings?.apiHost || '',
      model,
    })"""
REPLACEMENT = """    // Use the same credential resolution as chat, with current form edits taking precedence.
    const storedProviders = settingsStore.getState().providers || {}
    const providers = {
      ...storedProviders,
      [this.provider]: { ...storedProviders[this.provider], ...settings },
    }
    const providerSetting = mergeSharedOAuthProviderSettings(this.provider, providers)
    const model: ProviderModelInfo = providerSetting.models?.[0] || definition.defaultSettings?.models?.[0] || { modelId: '' }
    const dependencies = await createModelDependencies()
    const isOAuthActive = providerSetting.activeAuthMode === 'oauth' && !!providerSetting.oauth?.accessToken
    const formattedApiHost = (
      (isOAuthActive ? '' : providerSetting.apiHost) || definition.defaultSettings?.apiHost || ''
    ).trim()

    const modelInstance = definition.createModel({
      settings: { provider: this.provider, modelId: model.modelId },
      globalSettings: { providers: { ...providers, [this.provider]: providerSetting } } as Parameters<
        typeof definition.createModel
      >[0]['globalSettings'],
      config: { uuid: '' },
      dependencies,
      providerSetting,
      formattedApiHost,
      formattedApiPath: providerSetting.apiPath || definition.defaultSettings?.apiPath || '',
      model,
      effectiveApiKey: resolveEffectiveApiKey(providerSetting, dependencies.platformType || 'desktop'),
    })"""


def replace_once(text: str, old: str, new: str, name: str) -> str:
    if new in text:
        return text
    if text.count(old) != 1:
        raise RuntimeError(f"Chatbox {name} changed; review the provider discovery patch before rebuilding.")
    return text.replace(old, new, 1)


def apply(src: Path):
    src = Path(src)
    target = src / "src/renderer/packages/model-setting-utils/registry-setting-util.ts"
    text = target.read_text(encoding="utf-8")
    revised = replace_once(text, ORIGINAL, REPLACEMENT, "registry model discovery")
    if IMPORTS not in revised:
        revised = IMPORTS + revised

    types = src / "src/shared/providers/types.ts"
    types_text = types.read_text(encoding="utf-8")
    types_new = types_text if "  effectiveApiKey: string\n" in types_text else replace_once(
        types_text,
        "  /** The selected model configuration */\n  model: ProviderModelInfo",
        "  /** Credentials resolved with the same rules as normal chat. */\n  effectiveApiKey: string\n  /** The selected model configuration */\n  model: ProviderModelInfo",
        "provider credentials",
    )
    adapters = src / "src/shared/types/adapters.ts"
    adapters_text = adapters.read_text(encoding="utf-8")
    adapters_new = replace_once(
        adapters_text,
        "export interface ModelDependencies {\n",
        "export interface ModelDependencies {\n  platformType?: string\n",
        "model platform metadata",
    )
    for path, old, new in [(target, text, revised), (types, types_text, types_new), (adapters, adapters_text, adapters_new)]:
        if old != new:
            path.write_text(new, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    apply(parser.parse_args().source)

import { Tooltip } from '@mantine/core'
import { Settings2, ShieldAlert, ShieldCheck } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useLanguage } from '@/stores/settingsStore'
import { synchronizeWorkspace } from '@/packages/slidepilot/workspace'
import '@/packages/slidepilot/workspace-ui'
import './SlidePilotControls.css'

type State = { workspace: string; automatic: boolean; hasDeck: boolean; document?: string; revision?: number; approvalPending?: boolean }
export default function SlidePilotControls({ sessionId }: { sessionId?: string }) {
  const zh = useLanguage().startsWith('zh')
  const [state, setState] = useState<State>()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const working = useRef(false)
  const revision = useRef(-1)
  const pendingState = useRef<State>()
  const mounted = useRef(true)
  const accept = (value: State, fromCommand = false) => {
    if (!mounted.current || (value.revision ?? 0) < revision.current) return
    revision.current = value.revision ?? 0
    if (working.current && !fromCommand) pendingState.current = value
    setState(current => working.current && !fromCommand && current ? { ...value, automatic: current.automatic } : value)
  }
  const command = async (action: 'ui_approval' | 'ui_settings') => {
    if (working.current) return
    working.current = true
    pendingState.current = undefined
    setBusy(true)
    try {
      accept(await window.electronAPI.invoke('slidepilot:controls', action), true)
      setError('')
    } catch (e) { if (mounted.current) setError(String(e).slice(0, 400)) }
    finally {
      working.current = false
      if (pendingState.current) accept(pendingState.current, true)
      pendingState.current = undefined
      if (mounted.current) setBusy(false)
    }
  }
  useEffect(() => {
    mounted.current = true
    let pending = false
    const refresh = async () => {
      if (pending) return
      pending = true
      try { accept(await window.electronAPI.invoke('slidepilot:controls', 'ping')) } catch { /* Host may be switching presentations. */ }
      finally { pending = false }
    }
    void refresh()
    const timer = setInterval(refresh, 3000)
    window.addEventListener('slidepilot:bound', refresh)
    return () => { mounted.current = false; clearInterval(timer); window.removeEventListener('slidepilot:bound', refresh) }
  }, [])
  useEffect(() => {
    window.dispatchEvent(new Event('slidepilot:session'))
    void synchronizeWorkspace(sessionId || 'new').catch(error => {
      if (mounted.current && error?.name !== 'WorkspaceChangedError') setError(String(error).slice(0, 400))
    })
  }, [sessionId])
  const automatic = !!state?.automatic
  const approvalLabel = automatic
    ? (zh ? '自动批准已开启 · 点击恢复逐次确认' : 'Automatic approval is on · Click to review each edit')
    : (zh ? '逐次确认 · 开启自动批准前需完成两次确认' : 'Review each edit · Two confirmations to enable automatic approval')
  const approvalHint = state?.document ? `${approvalLabel}\n${zh ? '仅当前演示文稿：' : 'This presentation only: '}${state.document}` : approvalLabel
  return <div className="sp-chat-controls">
    <span id="slidepilot-toolbar-slot" />
    <Tooltip label={approvalHint} withArrow multiline maw={300}>
      <button type="button" className={`sp-approval-switch ${automatic ? 'is-automatic' : ''}`}
        role="switch" aria-checked={automatic} aria-label={approvalLabel}
        disabled={busy || !state?.hasDeck || state?.approvalPending} onClick={() => void command('ui_approval')}>
        {automatic ? <ShieldAlert size={20} strokeWidth={1.7} fill="currentColor" fillOpacity={0.1} /> : <ShieldCheck size={20} strokeWidth={1.7} />}
        {automatic && <span>{zh ? '自动' : 'Auto'}</span>}
      </button>
    </Tooltip>
    <Tooltip label={zh ? 'SlidePilot 设置' : 'SlidePilot settings'} withArrow>
      <button type="button" className="sp-chat-settings" aria-label={zh ? '打开 SlidePilot 设置' : 'Open SlidePilot settings'} disabled={busy} onClick={() => void command('ui_settings')}><Settings2 size={19} strokeWidth={1.7} /></button>
    </Tooltip>
    {error && <span className="sp-control-error" role="alert" title={error}>{error}</span>}
  </div>
}

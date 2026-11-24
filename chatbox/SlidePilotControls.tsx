import { Button, Group } from '@mantine/core'
import { useEffect, useState } from 'react'

type State = { workspace: string; automatic: boolean; hasDeck: boolean }
export default function SlidePilotControls() {
  const [state, setState] = useState<State>()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const command = async (action: string) => {
    setBusy(true)
    try {
      setState(await window.electronAPI.invoke('slidepilot:controls', action))
      setError('')
    } catch (e) { setError(String(e)) }
    finally { setBusy(false) }
  }
  useEffect(() => {
    let live = true
    const refresh = () => window.electronAPI.invoke('slidepilot:controls', 'ping')
      .then((value: State) => { if (live) setState(value) }).catch(() => {})
    refresh()
    const timer = setInterval(refresh, 3000)
    return () => { live = false; clearInterval(timer) }
  }, [])
  return <Group gap="xs" wrap="wrap">
    <Button variant="subtle" size="compact-sm" disabled={busy} onClick={() => command('ui_workspace')}>
      工作空间 · {state?.workspace || '选择资料文件夹'}
    </Button>
    <Button variant={state?.automatic ? 'light' : 'subtle'} color={state?.automatic ? 'teal' : 'gray'}
      size="compact-sm" aria-pressed={!!state?.automatic} disabled={busy || !state?.hasDeck}
      onClick={() => command('ui_approval')}>{state?.automatic ? '自动批准' : '逐次审批'}</Button>
    {error && <span role="alert">{error}</span>}
  </Group>
}

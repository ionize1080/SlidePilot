'use strict'

// The Office host owns docking and persistence. Electron keeps this same window
// and webContents alive; changing modes must never recreate or navigate a chat.
function createWindowModes({ primary, host }) {
  let current, revision = -1
  let changes = Promise.resolve()
  function apply(state) {
    if (!state || !['window', 'sidebar'].includes(state.mode)) return state
    if (Number.isSafeInteger(state.revision) && state.revision < revision) return state
    const win = primary()
    if (!win || win.isDestroyed()) return state
    if (Number.isSafeInteger(state.revision)) revision = state.revision
    if (state.mode !== current) {
      const docked = state.mode === 'sidebar'
      win.setHasShadow(!docked)
      win.setSkipTaskbar(docked)
      win.setMovable(!docked)
      win.setMaximizable(!docked)
      win.setMinimizable(!docked)
      current = state.mode
    }
    win.webContents.send('slidepilot:state', state)
    return state
  }
  async function ready() {
    const win = primary()
    if (!win || win.isDestroyed()) throw Error('The assistant window is not available.')
    const bytes = win.getNativeWindowHandle()
    const handle = String(bytes.length === 8 ? bytes.readBigUInt64LE() : bytes.readUInt32LE())
    return apply(await host('ai_ready', { handle }))
  }
  function change(mode) {
    if (!['window', 'sidebar'].includes(mode)) return Promise.reject(Error('Unknown assistant display mode.'))
    const next = changes.catch(() => {}).then(async () => apply(await host('ai_mode', { mode })))
    changes = next
    return next
  }
  return { apply, ready, change }
}

module.exports = { createWindowModes }

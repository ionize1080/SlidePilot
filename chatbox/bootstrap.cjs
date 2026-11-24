'use strict'
const { app, ipcMain, dialog } = require('electron')
const fs = require('node:fs')
const net = require('node:net')
const path = require('node:path')
const root = path.resolve(__dirname, '..')
const pipe = process.env.SLIDEPILOT_PIPE
const token = process.env.SLIDEPILOT_TOKEN
const uiToken = process.env.SLIDEPILOT_UI_TOKEN
if (!/^SlidePilot-[a-f0-9]{32}$/.test(pipe || '') || !/^[A-F0-9]{64}$/.test(token || '')) {
  throw Error('Open SlidePilot from the PowerPoint ribbon.')
}
const python = path.join(root, 'Runtime', 'python.exe')
const server = path.join(root, 'engine', 'server.py')
const referenceServer = path.join(root, 'engine', 'reference_server.py')
const workspaceFolder = path.join(app.getPath('appData'), 'SlidePilot', 'Workspaces')
const profile = path.join(app.getPath('appData'), 'SlidePilot', 'Chatbox')
fs.mkdirSync(profile, { recursive: true })
const logs = path.join(process.env.LOCALAPPDATA || app.getPath('appData'), 'SlidePilot', 'logs')
function startupLog(message) {
  try {
    fs.mkdirSync(logs, { recursive: true })
    const file = path.join(logs, 'assistant-startup.log')
    if (fs.existsSync(file) && fs.statSync(file).size > 1024 * 1024) fs.writeFileSync(file, '')
    const safe = String(message).split(token).join('[session]').split(uiToken || '__none__').join('[ui-session]')
    fs.appendFileSync(file, new Date().toISOString() + ' ' + safe + '\n')
  } catch { /* Diagnostics must never prevent the assistant opening. */ }
}
startupLog('Starting assistant; Electron ' + process.versions.electron)
app.setName('SlidePilot')
// Identify the source-built Chatbox client while retaining SlidePilot's product identity.
if (app.userAgentFallback) {
  const base = app.userAgentFallback.replace(/\s(?:Electron|SlidePilot|Chatbox|slidepilot-chatbox)\/[^\s]+/gi, '')
  app.userAgentFallback = base.trim() + ' Chatbox/1.20.3 SlidePilot/0.1.0'
}
app.setPath('userData', profile)
app.setPath('sessionData', profile)
app.setAppUserModelId('SlidePilot.PowerPoint.Assistant')
app.setAsDefaultProtocolClient = () => false
app.setLoginItemSettings = () => {}
Object.defineProperty(app, 'isPackaged', { get: () => true })
Object.defineProperty(process, 'resourcesPath', { value: path.join(__dirname, 'resources') })

function config(saved) {
  saved = saved || {}
  const tokenPlanHost = 'https://token-plan.maas.qianwenaiapi.com/compatible-mode/v1'
  // Repair only the initial SlidePilot service or an explicitly configured TokenPlan
  // endpoint. An existing provider's keys, proxy, host and nonempty list are retained.
  const previousOpenAI = saved.providers?.openai
  const openai = previousOpenAI && Object.keys(previousOpenAI).length
    ? { ...previousOpenAI } : { apiHost: tokenPlanHost }
  const isTokenPlan = typeof openai.apiHost === 'string' &&
    openai.apiHost.trim().replace(/\/+$/, '') === tokenPlanHost && openai.activeAuthMode !== 'oauth'
  if (isTokenPlan && (!Array.isArray(openai.models) || openai.models.length === 0)) {
    openai.models = ['qwen3.8-flash', 'qwen3.8-max'].map(modelId => ({ modelId, capabilities: ['tool_use'] }))
  }
  return { language: 'zh-Hans', ...saved, autoUpdate: false,
    providers: { ...saved.providers, openai },
    defaultChatModel: saved.defaultChatModel || (isTokenPlan ? { provider: 'openai', model: openai.models[0].modelId } : undefined),
    mcp: { ...saved.mcp, enabledBuiltinServers: [], servers: [
      { id: 'slidepilot', name: 'SlidePilot', enabled: true,
        transport: { type: 'stdio', command: python, args: ['-B', server] } },
      { id: 'slidepilot-workspace', name: 'SlidePilot Workspace', enabled: true,
        transport: { type: 'stdio', command: python, args: ['-B', referenceServer] } }
    ] } }
}
let primary
require('./workspace-main.cjs').install({ipcMain, dialog, shell: require('electron').shell,
  primary: () => primary, folder: workspaceFolder, root})
function trusted(event) {
  if (!primary || event.sender !== primary.webContents || event.senderFrame !== primary.webContents.mainFrame ||
      !event.senderFrame.url.startsWith('file:')) throw Error('Invalid assistant window')
}
let pendingPing
function host(action, fields = {}) {
  if (action === 'ping' && pendingPing) return pendingPing
  const request = new Promise((resolve, reject) => {
    let socket, retry, done = false
    const connectUntil = Date.now() + 5000
    // A workspace picker/approval can remain open until the user decides.
    const timeout = setTimeout(() => finish(Error(action === 'ping'
      ? 'PowerPoint is busy. Close any open dialog and try again.'
      : 'The PowerPoint dialog is still open. Close it before trying again.')), action === 'ping' ? 5500 : 10 * 60 * 1000)
    function finish(error, result) {
      if (done) return
      done = true
      clearTimeout(timeout)
      clearTimeout(retry)
      if (socket) socket.destroy()
      error ? reject(error) : resolve(result)
    }
    function connect() {
      if (done) return
      let received = '', connected = false
      socket = net.createConnection('\\\\.\\pipe\\' + pipe)
      socket.setEncoding('utf8')
      socket.on('connect', () => {
        connected = true
        socket.write(JSON.stringify({ ...fields, action, token, uiToken }) + '\n')
      })
      socket.on('data', chunk => {
        received += chunk
        if (received.length > 262144) return finish(Error('Host reply too large'))
        const newline = received.indexOf('\n')
        if (newline >= 0) {
          try { const r = JSON.parse(received.slice(0, newline)); finish(r.error ? Error(r.error) : null, r.result) }
          catch (error) { finish(error) }
        }
      })
      socket.on('error', error => {
        // Retry only before connecting: an already-sent mutation must never repeat.
        if (!connected && ['EBUSY', 'ENOENT', 'ECONNREFUSED'].includes(error.code) && Date.now() < connectUntil) {
          socket.destroy()
          retry = setTimeout(connect, 150)
        } else finish(error)
      })
      socket.on('end', () => { if (!received.includes('\n')) finish(Error('PowerPoint closed the connection')) })
    }
    connect()
  })
  if (action === 'ping') {
    pendingPing = request
    request.then(() => { pendingPing = undefined }, () => { pendingPing = undefined })
  }
  return request
}
let providerRevision = -1
const windowModes = require('./window-mode-main.cjs').createWindowModes({ primary: () => primary, host })
let workspaceBinding = Promise.resolve()
ipcMain.handle('slidepilot:bind-workspace', (event, workspaceId) => {
  trusted(event)
  if (typeof workspaceId !== 'string' || !/^[a-f0-9]{32}$/.test(workspaceId)) throw Error('Invalid workspace ID')
  // Preserve interaction order if the user switches chats twice while Office is busy.
  const next = workspaceBinding.then(() => host('ui_workspace_binding', {workspaceId}))
  workspaceBinding = next.catch(() => {})
  return next.then(applyHostState)
})
function applyHostState(result) {
  windowModes.apply(result)
  if (result?.provider && result.revision !== providerRevision && primary && !primary.isDestroyed()) {
    providerRevision = result.revision
    if (primary.isMinimized()) primary.restore()
    primary.show()
    primary.focus()
    primary.webContents.send('navigate-to', '/settings/provider')
  }
  return result
}
ipcMain.handle('slidepilot:controls', async (event, action) => {
  trusted(event)
  if (!['ping','ui_workspace','ui_approval','ui_settings'].includes(action)) throw Error('Unknown control')
  return applyHostState(await host(action))
})
ipcMain.handle('slidepilot:mode', async (event, mode) => {
  trusted(event)
  return windowModes.change(mode)
})
const handle = ipcMain.handle.bind(ipcMain)
ipcMain.handle = (channel, handler) => {
  if (channel === 'getSettings') return handle(channel, async (...args) => config(await handler(...args)))
  if (channel === 'getStoreValue') return handle(channel, async (event, key, ...args) => {
    const v = await handler(event, key, ...args)
    return key === 'settings' ? config(v) : v
  })
  if (channel === 'install-update' || channel === 'ensureAutoLaunch') return handle(channel, () => false)
  if (channel === 'mcp:stdio-transport:create') return handle(channel, (event, params) => {
    trusted(event)
    if (params.command !== python || params.args?.length !== 2 || params.args[0] !== '-B' || ![server, referenceServer].includes(params.args[1]))
      throw Error('Unknown portable MCP server')
    return handler(event, { command: python, args: ['-B', params.args[1]], env: {
      SLIDEPILOT_WORKSPACES: workspaceFolder,
      SLIDEPILOT_PIPE: pipe, SLIDEPILOT_TOKEN: token, SLIDEPILOT_STAGE: process.env.SLIDEPILOT_STAGE,
      SYSTEMROOT: process.env.SystemRoot, TEMP: process.env.TEMP, TMP: process.env.TEMP, PYTHONIOENCODING: 'utf-8'
    } })
  })
  return handle(channel, handler)
}
app.on('browser-window-created', (_event, window) => {
  if (primary) return
  primary = window
  try { require('./provider-diagnostics.cjs').observe(window.webContents.session.webRequest, startupLog) }
  catch { startupLog('Qwen desktop diagnostics unavailable') }
  window.setMinimumSize(320, 240)
  window.hookWindowMessage(0x8047, () => {
    if (window.isMinimized()) window.restore()
    window.show()
    window.focus()
  })
  window.webContents.on('will-navigate', (event, url) => { if (!url.startsWith('file:')) event.preventDefault() })
  window.once('ready-to-show', async () => {
    startupLog('Assistant window ready')
    try { await windowModes.ready() }
    catch (error) {
      startupLog('Assistant host attachment failed: ' + error.message)
      dialog.showErrorBox('SlidePilot', 'The assistant could not attach to PowerPoint. Keep PowerPoint open and try switching the window mode again.\n' + error.message)
    }
  })
  window.webContents.on('did-fail-load', (_event, code, description, _url, isMainFrame) => {
    if (isMainFrame && code !== -3) {
      startupLog('Renderer load failed: ' + code + ' ' + description)
      dialog.showErrorBox('SlidePilot', 'The assistant page could not load. Run SlidePilot.Setup.exe to check the portable files.\n' + description)
    }
  })
  window.webContents.on('render-process-gone', (_event, details) => {
    if (details.reason === 'clean-exit') return
    startupLog('Renderer stopped: ' + details.reason + ' (' + details.exitCode + ')')
    dialog.showErrorBox('SlidePilot', 'The assistant stopped unexpectedly. Reopen AI Assistant from PowerPoint. Your presentations are unchanged.\n' + details.reason)
    app.quit()
  })
  window.on('closed', () => app.quit())
})
// An open review dialog can occupy the host pipe for several minutes.
// Test process lifetime independently so a pending review keeps its window.
const hostPid = Number(process.env.SLIDEPILOT_HOST_PID)
const health = setInterval(() => {
  // Settings may request the provider page while the chat input is unmounted.
  if (primary && !primary.isDestroyed() && !primary.webContents.isLoadingMainFrame()) {
    host('ping').then(applyHostState).catch(() => {})
  }
  if (!Number.isSafeInteger(hostPid) || hostPid <= 0) return
  try { process.kill(hostPid, 0) } catch (error) { if (error.code === 'ESRCH') app.quit() }
}, 3000)
health.unref()
try { require('./dist/main/main.js') }
catch (error) {
  startupLog(error.stack || error.message)
  dialog.showErrorBox('SlidePilot', 'The AI assistant could not start. Run SlidePilot.Setup.exe to check the portable files.\n' + error.message)
  app.exit(1)
}

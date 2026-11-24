'use strict'
const { app, ipcMain } = require('electron')
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
const profile = path.join(app.getPath('appData'), 'SlidePilot', 'Chatbox')
fs.mkdirSync(profile, { recursive: true })
app.setName('SlidePilot')
app.setPath('userData', profile)
app.setPath('sessionData', profile)
app.setAppUserModelId('SlidePilot.PowerPoint.Assistant')
app.setAsDefaultProtocolClient = () => false
app.setLoginItemSettings = () => {}
Object.defineProperty(app, 'isPackaged', { get: () => true })
Object.defineProperty(process, 'resourcesPath', { value: path.join(__dirname, 'resources') })

function config(saved) {
  saved = saved || {}
  const qwen = { apiHost: 'https://token-plan.maas.qianwenaiapi.com/compatible-mode/v1',
    models: ['qwen3.8-flash', 'qwen3.8-max'].map(modelId => ({ modelId, capabilities: ['tool_use'] })) }
  return { language: 'zh-Hans', ...saved, autoUpdate: false,
    providers: { ...saved.providers, openai: { ...qwen, ...saved.providers?.openai } },
    defaultChatModel: saved.defaultChatModel || { provider: 'openai', model: 'qwen3.8-flash' },
    mcp: { ...saved.mcp, enabledBuiltinServers: [], servers: [{
      id: 'slidepilot', name: 'SlidePilot', enabled: true,
      transport: { type: 'stdio', command: python, args: ['-B', server] }
    }] } }
}
let primary
function trusted(event) {
  if (!primary || event.sender !== primary.webContents || event.senderFrame !== primary.webContents.mainFrame ||
      !event.senderFrame.url.startsWith('file:')) throw Error('Invalid assistant window')
}
function host(action) {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection('\\\\.\\pipe\\' + pipe)
    let received = ''
    socket.setEncoding('utf8')
    socket.on('connect', () => socket.write(JSON.stringify({ action, token, uiToken }) + '\n'))
    socket.on('data', chunk => {
      received += chunk
      if (received.length > 262144) return socket.destroy(Error('Host reply too large'))
      if (received.includes('\n')) {
        socket.end()
        try { const r = JSON.parse(received); r.error ? reject(Error(r.error)) : resolve(r.result) }
        catch (error) { reject(error) }
      }
    })
    socket.on('error', reject)
    socket.on('end', () => { if (!received.includes('\n')) reject(Error('PowerPoint closed the connection')) })
  })
}
ipcMain.handle('slidepilot:controls', (event, action) => {
  trusted(event)
  if (!['ping','ui_workspace','ui_approval'].includes(action)) throw Error('Unknown control')
  return host(action)
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
    if (params.command !== python || params.args?.length !== 2 || params.args[0] !== '-B' || params.args[1] !== server)
      throw Error('Unknown portable MCP server')
    return handler(event, { command: python, args: ['-B', server], env: {
      SLIDEPILOT_PIPE: pipe, SLIDEPILOT_TOKEN: token, SLIDEPILOT_STAGE: process.env.SLIDEPILOT_STAGE,
      SYSTEMROOT: process.env.SystemRoot, TEMP: process.env.TEMP, TMP: process.env.TEMP, PYTHONIOENCODING: 'utf-8'
    } })
  })
  return handle(channel, handler)
}
app.on('browser-window-created', (_event, window) => {
  if (primary) return
  primary = window
  window.webContents.on('will-navigate', (event, url) => { if (!url.startsWith('file:')) event.preventDefault() })
  window.on('closed', () => app.quit())
})
// An open review dialog can occupy the host pipe for several minutes.
// Test process lifetime independently so a pending review keeps its window.
const hostPid = Number(process.env.SLIDEPILOT_HOST_PID)
const health = setInterval(() => {
  if (!Number.isSafeInteger(hostPid) || hostPid <= 0) return
  try { process.kill(hostPid, 0) } catch (error) { if (error.code === 'ESRCH') app.quit() }
}, 3000)
health.unref()
require('./dist/main/main.js')

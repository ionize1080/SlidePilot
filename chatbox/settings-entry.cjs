'use strict'
const { app, BrowserWindow, ipcMain, screen } = require('electron')
const fs = require('node:fs')
const path = require('node:path')
const net = require('node:net')
const pipe = process.env.SLIDEPILOT_PIPE
const token = process.env.SLIDEPILOT_TOKEN
const uiToken = process.env.SLIDEPILOT_UI_TOKEN
if (!/^SlidePilot-[a-f0-9]{32}$/.test(pipe || '') || !/^[A-F0-9]{64}$/.test(token || '') ||
    !/^[A-F0-9]{64}$/.test(uiToken || '')) throw Error('Open settings from the SlidePilot ribbon.')
const profile = path.join(app.getPath('appData'), 'SlidePilot')
const settingsProfile = path.join(profile, 'Settings')
const workspaceFolder = path.join(profile, 'Workspaces')
const workspaceSettings = require('./workspace-main.cjs')
fs.mkdirSync(settingsProfile, { recursive: true })
app.setName('SlidePilot Settings')
app.setPath('userData', settingsProfile)
app.setPath('sessionData', settingsProfile)
app.setAppUserModelId('SlidePilot.PowerPoint.Settings')

let win, quitting = false, idle
function host(action, args = {}) {
  return new Promise((resolve, reject) => {
    let socket, retry, complete = false
    const deadline = Date.now() + 5000
    const timeout = setTimeout(() => finish(Error('PowerPoint is busy. Close any review dialog, then try again.')), 6500)
    function finish(error, result) {
      if (complete) return
      complete = true
      clearTimeout(timeout); clearTimeout(retry)
      if (socket) socket.destroy()
      error ? reject(error) : resolve(result)
    }
    function connect() {
      if (complete) return
      let connected = false, reply = ''
      socket = net.createConnection('\\\\.\\pipe\\' + pipe)
      socket.setEncoding('utf8')
      socket.on('connect', () => { connected = true; socket.write(JSON.stringify({ ...args, action, token, uiToken }) + '\n') })
      socket.on('data', chunk => {
        reply += chunk
        if (reply.length > 262144) return finish(Error('Unexpected settings response.'))
        const end = reply.indexOf('\n')
        if (end >= 0) {
          try { const value = JSON.parse(reply.slice(0, end)); finish(value.error ? Error(value.error) : null, value.result) }
          catch { finish(Error('Invalid settings response.')) }
        }
      })
      socket.on('error', error => {
        if (complete) return
        if (!connected && ['EBUSY', 'ENOENT', 'ECONNREFUSED'].includes(error.code) && Date.now() < deadline) {
          socket.destroy(); retry = setTimeout(connect, 150)
        } else finish(error)
      })
      socket.on('end', () => { if (!reply.includes('\n')) finish(Error('PowerPoint closed the connection.')) })
    }
    connect()
  })
}
function trusted(event) {
  if (!win || win.isDestroyed() || event.sender !== win.webContents ||
      event.senderFrame !== win.webContents.mainFrame || !event.senderFrame.url.startsWith('file:')) throw Error('Invalid settings window.')
}
function ready() {
  const handle = win.getNativeWindowHandle()
  return host('settings_ready', { handle: String(handle.length === 8 ? handle.readBigUInt64LE() : handle.readUInt32LE()) })
}
ipcMain.handle('slidepilot:settings', async (event, action, args) => {
  trusted(event)
  if (action === 'ready') return ready()
  if (action === 'read') return host('settings_read')
  if (action === 'write') {
    const value = {}
    if (Object.prototype.hasOwnProperty.call(args || {}, 'theme')) {
      if (!Number.isInteger(args.theme) || args.theme < 0 || args.theme > 2) throw Error('Choose an icon palette.')
      value.theme = args.theme
    }
    if (Object.prototype.hasOwnProperty.call(args || {}, 'mode')) {
      if (!['sidebar', 'window'].includes(args.mode)) throw Error('Choose an assistant display mode.')
      value.mode = args.mode
    }
    if (!Object.keys(value).length) throw Error('No settings were selected.')
    return host('settings_write', value)
  }
  if (action === 'provider') return host('settings_provider')
  if (action === 'open') {
    if (!['logs', 'backups', 'deployment'].includes(args?.target)) throw Error('Unknown product location.')
    return host('settings_open', { target: args.target })
  }
  throw Error('Unknown settings command.')
})
ipcMain.handle('slidepilot:workspace-preferences', async (event, value) => {
  trusted(event)
  if (value === undefined) return workspaceSettings.preferences(workspaceFolder)
  if (!value || !Number.isInteger(value.maxFileMB) || value.maxFileMB < 1 || value.maxFileMB > 1024 ||
      !Number.isInteger(value.searchDepth) || value.searchDepth < 1 || value.searchDepth > 12) throw Error('Check the workspace limits.')
  return workspaceSettings.savePreferences(workspaceFolder, { maxFileMB: value.maxFileMB, searchDepth: value.searchDepth })
})
app.on('before-quit', () => { quitting = true; clearTimeout(idle) })
app.whenReady().then(() => {
  const area = screen.getDisplayNearestPoint(screen.getCursorScreenPoint()).workArea
  win = new BrowserWindow({ title: 'SlidePilot · 设置', show: false, width: Math.min(920, area.width - 32),
    height: Math.min(740, area.height - 32), minWidth: Math.min(660, area.width - 32), minHeight: Math.min(480, area.height - 32),
    autoHideMenuBar: true, backgroundColor: '#f6f8f9', webPreferences: { preload: path.join(__dirname, 'settings-preload.cjs'),
      sandbox: true, contextIsolation: true, nodeIntegration: false } })
  win.webContents.on('will-navigate', event => event.preventDefault())
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  win.on('close', event => {
    if (quitting) return
    event.preventDefault(); win.hide(); clearTimeout(idle)
    idle = setTimeout(() => { if (!win.isVisible()) app.quit() }, 120000); idle.unref()
  })
  win.on('show', () => { clearTimeout(idle); win.webContents.send('slidepilot:settings-refresh') })
  win.hookWindowMessage(0x8047, () => {
    clearTimeout(idle); if (win.isMinimized()) win.restore(); win.show(); win.focus()
    win.webContents.send('slidepilot:settings-refresh')
    ready().catch(() => {})
  })
  win.once('ready-to-show', () => { win.show(); ready().catch(() => {}) })
  win.loadFile(path.join(__dirname, 'settings.html'))
})
app.on('window-all-closed', () => app.quit())
const hostPid = Number(process.env.SLIDEPILOT_HOST_PID)
const health = setInterval(() => {
  if (!Number.isSafeInteger(hostPid) || hostPid < 1) return
  try { process.kill(hostPid, 0) } catch (error) { if (error.code === 'ESRCH') app.quit() }
}, 3000)
health.unref()

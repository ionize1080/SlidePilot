// Run with the packaged electron.exe, this file, then the extracted SlidePilot directory.
const { app } = require('electron')
const { randomBytes, randomUUID } = require('node:crypto')
const fs = require('node:fs')
const net = require('node:net')
const os = require('node:os')
const path = require('node:path')
const readline = require('node:readline')

const bundle = path.resolve(process.argv[2])
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'SlidePilot-renderer-'))
app.setPath('appData', profile)
const pipe = 'SlidePilot-' + randomUUID().replaceAll('-', '')
const token = randomBytes(32).toString('hex').toUpperCase()
Object.assign(process.env, {
  SLIDEPILOT_PIPE: pipe, SLIDEPILOT_TOKEN: token, SLIDEPILOT_UI_TOKEN: randomBytes(32).toString('hex').toUpperCase(),
  SLIDEPILOT_STAGE: profile, SLIDEPILOT_HOST_PID: String(process.pid)
})
const begin = Date.now()
let renderer = false
let controls = false
function finish() {
  if (renderer && controls) {
    console.log('Chatbox renderer and workspace controls ready in ' + (Date.now() - begin) + ' ms')
    app.exit(0)
  }
}
app.on('browser-window-created', (_event, window) => {
  window.webContents.on('did-finish-load', () => {
    renderer = new URL(window.webContents.getURL()).pathname.endsWith('/renderer/index.html')
    if (renderer) console.log('Packaged renderer loaded')
    finish()
  })
  window.webContents.on('render-process-gone', (_event, details) => {
    console.error('Renderer exited: ' + details.reason)
    app.exit(1)
  })
})
const host = net.createServer(socket => {
  socket.on('error', () => {})
  readline.createInterface({ input: socket }).once('line', line => {
    const request = JSON.parse(line)
    const ok = request.token === token && request.action === 'ping'
    socket.end(JSON.stringify(ok ? { result: { workspace: 'QA', hasDeck: true, automatic: false } }
                              : { error: 'Unsupported test request' }) + '\n')
    if (ok) controls = true
    finish()
  })
})
host.listen('\\\\.\\pipe\\' + pipe, () => require(path.join(bundle, 'Chatbox', 'bootstrap.cjs')))
setTimeout(() => { console.error('Chatbox startup timed out', { renderer, controls }); app.exit(1) }, 35000).unref()

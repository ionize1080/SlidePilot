'use strict'
// Exercise the actual Electron settings IPC boundaries without opening a window.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { EventEmitter } = require('node:events')
const handlers = new Map(), requests = [], preferenceWrites = []
const mainFrame = { url: 'file:///SlidePilot/Chatbox/settings.html' }
const webContents = { mainFrame }
const window = { isDestroyed: () => false, webContents, getNativeWindowHandle: () => Buffer.alloc(8) }
const event = { sender: webContents, senderFrame: mainFrame }
const settings = { maxFileMB: 100, searchDepth: 3 }
const electron = {
  app: { getPath: () => 'fixture-profile', setName() {}, setPath() {}, setAppUserModelId() {}, on() {}, whenReady: () => ({ then() {} }) },
  ipcMain: { handle: (name, fn) => handlers.set(name, fn) }, BrowserWindow: function () {}, screen: {},
}
const workspace = {
  preferences: folder => { assert.equal(folder, path.join('fixture-profile', 'SlidePilot', 'Workspaces')); return settings },
  savePreferences: (folder, value) => { assert.equal(folder, path.join('fixture-profile', 'SlidePilot', 'Workspaces')); preferenceWrites.push(value); return value },
}
const net = { createConnection: pipe => {
  assert.equal(pipe, '\\\\.\\pipe\\SlidePilot-' + 'a'.repeat(32))
  const socket = new EventEmitter()
  socket.setEncoding = () => {}; socket.destroy = () => {}
  socket.write = value => { requests.push(JSON.parse(value)); queueMicrotask(() => socket.emit('data', JSON.stringify({ result: { ok: true } }) + '\n')) }
  queueMicrotask(() => socket.emit('connect'))
  return socket
} }
const file = path.resolve(__dirname, '../chatbox/settings-entry.cjs')
const context = {
  require: name => ({ electron, 'node:fs': { mkdirSync() {} }, 'node:path': path, 'node:net': net, './workspace-main.cjs': workspace })[name],
  process: { env: { SLIDEPILOT_PIPE: 'SlidePilot-' + 'a'.repeat(32), SLIDEPILOT_TOKEN: 'A'.repeat(64), SLIDEPILOT_UI_TOKEN: 'B'.repeat(64) } },
  __dirname: path.dirname(file), setTimeout, clearTimeout, setInterval: () => ({ unref() {} }), Buffer,
}
vm.createContext(context)
vm.runInContext(fs.readFileSync(file, 'utf8') + '\nthis.setWindow = value => { win = value };', context)
context.setWindow(window)
const command = handlers.get('slidepilot:settings'), preferences = handlers.get('slidepilot:workspace-preferences')
let checks = 0
async function reject(fn, message) { await assert.rejects(fn); checks++; if (requests.length) assert.equal(requests.at(-1).token, 'A'.repeat(64), message) }
async function main() {
  await reject(() => command({ sender: {}, senderFrame: mainFrame }, 'read'), 'Unrelated renderer must be refused')
  await reject(() => command({ sender: webContents, senderFrame: { url: mainFrame.url } }, 'read'), 'Child frames must be refused')
  await reject(() => command(event, 'write', { theme: 1.5 }), 'Fractional themes must be refused')
  await reject(() => command(event, 'write', { theme: 3 }), 'Unknown themes must be refused')
  await reject(() => command(event, 'open', { target: 'C:\\arbitrary.exe' }), 'Only fixed product locations may open')
  assert.equal(requests.length, 0); checks++
  await command(event, 'write', { theme: 2, apiKey: 'must-not-forward' })
  assert.deepEqual(requests.pop(), { theme: 2, action: 'settings_write', token: 'A'.repeat(64), uiToken: 'B'.repeat(64) }); checks++
  await command(event, 'provider')
  assert.equal(requests.pop().action, 'settings_provider'); checks++
  assert.deepEqual(await preferences(event), settings); checks++
  for (const value of [{ maxFileMB: 0, searchDepth: 3 }, { maxFileMB: 1025, searchDepth: 3 }, { maxFileMB: 100, searchDepth: 13 }, { maxFileMB: 100, searchDepth: 1.5 }]) await reject(() => preferences(event, value))
  await preferences(event, { maxFileMB: 64, searchDepth: 2, apiKey: 'must-not-persist' })
  assert.deepEqual(JSON.parse(JSON.stringify(preferenceWrites)), [{ maxFileMB: 64, searchDepth: 2 }]); checks++
  await reject(() => command(event, 'unknown'))
  console.log(checks + ' settings trust, preferences and native-provider routing checks passed.')
}
main().catch(error => { console.error(error); process.exitCode = 1 })

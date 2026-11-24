'use strict'
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')
const { WorkspaceStore, install, preferences, savePreferences, extensions } = require('../chatbox/workspace-main.cjs')
const root = path.resolve(__dirname, '..')
const base = path.join(root, '.build')
fs.mkdirSync(base, { recursive: true })
const temporary = fs.mkdtempSync(path.join(base, 'workspace-store-test-'))
async function main() {
  const source = path.join(temporary, 'source.md')
  fs.writeFileSync(source, 'Original source evidence')
  const original = fs.readFileSync(source)
  const folder = path.join(temporary, 'Workspaces')
  const store = new WorkspaceStore(folder, root)
  const session = 'chat-one'
  const group = (name, parent = '') => { store.collection(session, 'create', { name, parent }); return 'virtual:' + store.get(session).collections.at(-1).id }
  const a = group('Research'), b = group('Finance'), c = group('Deposits', a)
  const item = store.add(session, [source]).added[0].id
  assert.equal(store.add(session, [source]).added[0].id, item)
  store.move(session, [item], c)
  assert.equal(store.get(session).sources[0].parent, c.slice(8))
  store.move(session, [a], b)
  assert.throws(() => store.move(session, [b], c))
  store.collection(session, 'rename', { id: a, name: 'Source research' })
  store.collection(session, 'delete', { id: a })
  assert.equal(store.get(session).sources.length, 0)
  assert.deepEqual(fs.readFileSync(source), original)
  store.add('new-chat', [source])
  const captured = store.get('new-chat').id
  store.adopt('new-chat', 'saved-chat', captured)
  assert.equal(store.get('saved-chat').id, captured)
  assert.notEqual(store.get('new-chat').id, captured)
  assert.equal(preferences(folder).maxFileMB, 100)
  assert.deepEqual(savePreferences(folder, { maxFileMB: 80, searchDepth: 4 }), { maxFileMB: 80, searchDepth: 4 })
  assert.throws(() => savePreferences(folder, { maxFileMB: 0 }))
  assert(!extensions.includes('doc'))
  assert(extensions.includes('docx'))
  const id = store.get(session).id
  const results = path.join(folder, 'results', id)
  fs.mkdirSync(results, { recursive: true })
  const result = path.join(results, 'Harbour.PPTX')
  fs.writeFileSync(result, 'generated test presentation')
  const resultId = 'results:' + Buffer.from('Harbour.PPTX').toString('base64url')
  assert.equal(store.resultPath(session, resultId), result)
  assert.throws(() => store.resultPath(session, 'results:' + Buffer.from('../source.md').toString('base64url')))
  const frame = { url: 'file:///assistant/index.html' }
  const webContents = { mainFrame: frame }
  const window = { webContents }
  let handler, opened
  install({ ipcMain: { handle(channel, fn) { assert.equal(channel, 'slidepilot:workspace'); handler = fn } },
    dialog: {}, shell: { async openPath(value) { opened = value; return '' } }, primary: () => window, folder, root })
  const event = { sender: webContents, senderFrame: frame }
  assert.equal((await handler(event, 'context', { session })).workspace_id, id)
  assert.deepEqual(await handler(event, 'open', { session, id: resultId }), { opened: true })
  assert.equal(opened, result)
  await assert.rejects(handler({ sender: {}, senderFrame: frame }, 'context', { session }), /Invalid sender/)
  await assert.rejects(handler(event, 'open', { session, id: item }))
  console.log('PASS workspace store: isolated sessions, source grants, folders/moves, adoption, preferences, protected result opening, trusted IPC, original-file preservation')
}
main().finally(() => {
  const relative = path.relative(base, path.resolve(temporary))
  assert(relative && !relative.startsWith('..') && !path.isAbsolute(relative))
  fs.rmSync(temporary, { recursive: true, force: true })
}).catch(error => { console.error(error); process.exitCode = 1 })

// Run against the unpacked release. Only the PowerPoint approval host is a fixture.
'use strict'
const assert = require('node:assert/strict')
const crypto = require('node:crypto')
const fs = require('node:fs')
const net = require('node:net')
const os = require('node:os')
const path = require('node:path')
const readline = require('node:readline')
const { spawn } = require('node:child_process')
const { once } = require('node:events')

async function main() {
  const bundle = path.resolve(process.argv[2])
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'SlidePilot-qa-'))
  const workspace = path.join(tmp, 'workspace')
  const stage = path.join(tmp, 'stage')
  fs.cpSync(path.join(bundle, 'examples', 'workspace'), workspace, { recursive: true })
  fs.mkdirSync(stage)
  const pipe = 'SlidePilot-' + crypto.randomUUID().replaceAll('-', '')
  const token = crypto.randomBytes(32).toString('hex').toUpperCase()
  let denied = false
  const host = net.createServer(socket => {
    socket.on('error', () => {})
    readline.createInterface({ input: socket }).once('line', line => {
      try {
        const request = JSON.parse(line)
        assert.equal(request.token, token)
        let result
        if (request.action === 'context') {
          result = { workspace, document: 'Fixture', binding: 'bound', version: '14.0', automatic: false }
        } else {
          assert.equal(request.operation, 'commit_draft')
          assert.equal(request.binding, 'bound')
          if (denied) throw Error('User denied this operation')
          const args = request.args
          const input = path.join(stage, args.stage + '.pptx')
          assert.equal(crypto.createHash('sha256').update(fs.readFileSync(input)).digest('hex'), args.sha256)
          const folder = path.join(workspace, '_SlidePilot', 'drafts')
          fs.mkdirSync(folder, { recursive: true })
          fs.copyFileSync(input, path.join(folder, args.filename), fs.constants.COPYFILE_EXCL)
          result = { file: '_SlidePilot/drafts/' + args.filename }
        }
        socket.end(JSON.stringify({ result }) + '\n')
      } catch (error) {
        socket.end(JSON.stringify({ error: error.message }) + '\n')
      }
    })
  })
  host.listen('\\\\.\\pipe\\' + pipe)
  await once(host, 'listening')
  const child = spawn(path.join(bundle, 'Runtime', 'python.exe'), ['-B', path.join(bundle, 'engine', 'server.py')], {
    cwd: bundle, windowsHide: true,
    env: { ...process.env, SLIDEPILOT_PIPE: pipe, SLIDEPILOT_TOKEN: token, SLIDEPILOT_STAGE: stage },
    stdio: ['pipe', 'pipe', 'inherit']
  })
  const lines = readline.createInterface({ input: child.stdout })[Symbol.asyncIterator]()
  let next = 0
  async function request(method, params = {}) {
    const id = ++next
    child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n')
    const reply = JSON.parse((await lines.next()).value)
    assert.equal(id, reply.id)
    if (reply.error) throw Error(reply.error.message)
    return reply.result
  }
  async function call(name, args = {}) {
    const result = await request('tools/call', { name, arguments: args })
    if (result.isError) throw Error(result.content[0].text)
    return JSON.parse(result.content[0].text)
  }
  const timeout = setTimeout(() => child.kill(), 45000)
  try {
    assert.equal((await request('initialize', { protocolVersion: '2025-03-26' })).protocolVersion, '2025-03-26')
    child.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
    const { tools } = await request('tools/list')
    assert.ok(tools.find(t => t.name === 'deck_compose'))
    assert.equal((await call('capabilities')).classicDraftVariants, 78)
    assert.equal((await call('workspace_list')).total, 2)
    const csv = await call('workspace_read', { file: 'deposits.csv' })
    const params = { filename: 'Brief.pptx', plan: { slides: [{ title: 'Quarterly deposits',
      chart: { type: 'xlColumnClustered', dataRef: { file: 'deposits.csv', sha256: csv.sha256, category: 'Quarter',
        series: [{ column: 'Retail deposits (SGD m)' }, { column: 'Business deposits (SGD m)' }] } },
      sources: [{ file: csv.file, sha256: csv.sha256, locator: 'row 5', quote: 'Q4 | 142 | 94' }] }] } }
    const deck = await call('deck_compose', params)
    const edited = await call('chart_patch_copy', { file: deck.file, index: 1, filename: 'Edited.pptx', cells: [{ cell: 'B5', value: 155 }] })
    assert.equal((await call('deck_inspect', { file: edited.file })).charts.length, 1)
    assert.ok((await call('chart_inspect', { file: edited.file, index: 1, contains: 'numCache', limit: 200 })).nodes.some(n => n.text === '155'))
    await assert.rejects(call('deck_compose', params), /exist/i)
    denied = true
    await assert.rejects(call('deck_compose', { ...params, filename: 'Rejected.pptx' }), /denied/i)
    assert.deepEqual(fs.readdirSync(stage), [])
    assert.deepEqual((await call('draft_list')).files, ['Brief.pptx', 'Edited.pptx'])
    console.log('Portable stdio, named pipe, sources, validated compose, edit, duplicate and denial passed.')
  } finally {
    clearTimeout(timeout)
    const shutdown = child.exitCode === null ? once(child, 'close') : Promise.resolve()
    child.stdin.end()
    await shutdown
    host.close()
    const cleanup = fs.realpathSync(tmp)
    assert.equal(path.dirname(cleanup), fs.realpathSync(os.tmpdir()))
    assert.ok(path.basename(cleanup).startsWith('SlidePilot-qa-'))
    fs.rmSync(cleanup, { recursive: true, force: true })
  }
}
main().catch(error => { console.error(error.message); process.exitCode = 1 })

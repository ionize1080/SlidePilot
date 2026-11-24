// Real pinned AI SDK adapters, synthetic responses only: no network and no credentials.
'use strict'
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { createRequire } = require('node:module')
const root = path.resolve(__dirname, '..')
const source = path.resolve(process.argv[2] || path.join(root, '.build/chatbox'))
const dependencies = createRequire(path.join(source, 'package.json'))
const ts = dependencies('typescript')
const moduleExports = {}
const compiled = ts.transpileModule(fs.readFileSync(path.join(root, 'chatbox/slidepilot-openai-compat.ts'), 'utf8'), {
  compilerOptions: { target: ts.ScriptTarget.ES2021, module: ts.ModuleKind.CommonJS, strict: true }, reportDiagnostics: true,
})
assert(!compiled.diagnostics?.length)
vm.runInNewContext(compiled.outputText, { exports: moduleExports, Request, Response, Headers, TransformStream, TextDecoder, TextEncoder, URL })
const { liftToolImages, normalizeToolEventStream, createSlidePilotCompatFetch } = moduleExports
const { createOpenAI } = dependencies('@ai-sdk/openai')
const { createOpenAICompatible } = dependencies('@ai-sdk/openai-compatible')
const encoder = new TextEncoder()
const chunk = (delta, finish_reason = null) => ({ id: 'synthetic', object: 'chat.completion.chunk', created: 1, model: 'synthetic-model', choices: [{ index: 0, delta, finish_reason }] })
const frames = [
  chunk({ role: 'assistant', content: '开始📊', tool_calls: [{ index: 0, id: 'call_a', type: 'function' }] }),
  chunk({ tool_calls: [{ index: 0, function: { name: 'workspace_', arguments: '' } }, { index: 1, function: { name: 'deck_', arguments: '' } }] }),
  chunk({ tool_calls: [{ index: 0, function: { name: 'read', arguments: '' } }, { index: 1, id: 'call_b', function: { name: 'inspect', arguments: '' } }] }),
  chunk({ tool_calls: [{ index: 0, function: { arguments: '{"file":' } }] }),
  chunk({ tool_calls: [{ index: 1, function: { arguments: '{"file":"Deck.pptx"}' } }, { index: 0, function: { arguments: '"brief.md"}' } }] }),
  chunk({ tool_calls: [{ index: 0, id: 'call_a' }] }),
  chunk({}, 'tool_calls'),
  { id: 'synthetic', object: 'chat.completion.chunk', created: 1, model: 'synthetic-model', choices: [], usage: { prompt_tokens: 10, completion_tokens: 20, total_tokens: 30 } },
]
const wire = list => list.map(frame => 'data: ' + (typeof frame === 'string' ? frame : JSON.stringify(frame)) + '\r\n\r\n').join('')
const response = list => {
  const bytes = encoder.encode(': heartbeat\r\n\r\n' + wire(list))
  let position = 0
  return new Response(new ReadableStream({
    pull(controller) {
      if (position === bytes.length) return controller.close()
      const size = bytes.length > 65536 ? 16384 : 1 + position % 17
      controller.enqueue(bytes.slice(position, position += Math.min(size, bytes.length - position)))
    },
  }), { headers: { 'content-type': 'text/event-stream', 'x-synthetic': 'yes' } })
}
const adapters = {
  openai: fetch => createOpenAI({ apiKey: 'synthetic-not-a-key', baseURL: 'https://synthetic.invalid/v1', fetch }).chat('synthetic-model'),
  compatible: fetch => createOpenAICompatible({ name: 'synthetic', apiKey: 'synthetic-not-a-key', baseURL: 'https://synthetic.invalid/v1', fetch }).chatModel('synthetic-model'),
}
const prompt = [{ role: 'user', content: [{ type: 'text', text: 'Synthetic test' }] }]
async function stream(adapter, fetch) {
  const result = await adapter(fetch).doStream({ prompt })
  const parts = []
  for await (const part of result.stream) { if (part.type === 'error') throw part.error; parts.push(part) }
  return parts
}
const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=='
const image = { type: 'image-data', mediaType: 'image/png', data: png }
const tool = (id, content) => ({ role: 'tool', tool_call_id: id, content: JSON.stringify(content) })

async function main() {
  for (const [name, adapter] of Object.entries(adapters)) {
    let baselineRejected = false
    try { await stream(adapter, async () => response([...frames, '[DONE]'])) } catch { baselineRejected = true }
    assert(baselineRejected, name + ': upstream must reproduce the split-header failure')
    const parts = await stream(adapter, createSlidePilotCompatFetch(async () => response([...frames, '[DONE]'])))
    assert.equal(parts.filter(p => p.type === 'text-delta').map(p => p.delta).join(''), '开始📊')
    const calls = parts.filter(p => p.type === 'tool-call').map(p => ({ id: p.toolCallId, name: p.toolName, input: JSON.parse(p.input) })).sort((a, b) => a.id.localeCompare(b.id))
    assert.deepEqual(calls, [{ id: 'call_a', name: 'workspace_read', input: { file: 'brief.md' } }, { id: 'call_b', name: 'deck_inspect', input: { file: 'Deck.pptx' } }])
    assert.equal(parts.filter(p => p.type === 'tool-input-start').length, 2)
    assert.equal(parts.filter(p => p.type === 'finish').length, 1)
    const normal = [chunk({ tool_calls: [{ index: 0, id: 'normal', type: 'function', function: { name: 'workspace_list', arguments: '{}' } }] }), chunk({}, 'tool_calls'), '[DONE]']
    assert.equal((await stream(adapter, createSlidePilotCompatFetch(async () => response(normal)))).filter(p => p.type === 'tool-call').length, 1)
    console.log('PASS ' + name + ': reproduced upstream failure; fragmented UTF-8, interleaved tool headers, complete arguments and ordinary streams work')
  }
  for (const list of [
    [chunk({ tool_calls: [{ index: 0, id: 'unfinished' }] }), '[DONE]'],
    [chunk({ tool_calls: [{ index: 0, id: 'unfinished' }] })],
    [chunk({ tool_calls: [{ index: 0, id: 'first' }] }), chunk({ tool_calls: [{ index: 0, id: 'changed' }] })],
    [chunk({ tool_calls: [{ index: 0, id: 'a', function: { name: 'read', arguments: '{}' } }] }), chunk({ tool_calls: [{ index: 0, function: { name: 'write', arguments: '' } }] })],
    [chunk({ tool_calls: [{ index: -1, id: 'a' }] })],
    [chunk({ tool_calls: [{ index: 0, id: 'a', function: { name: 'x'.repeat(257) } }] })],
    [chunk({ tool_calls: [{ index: 0, id: 'a', function: { arguments: 'x'.repeat(1024 * 1024 + 1) } }] })],
  ]) {
    await assert.rejects(() => new Response(response(list).body.pipeThrough(normalizeToolEventStream())).text())
  }
  console.log('PASS incomplete/changed/oversized tool metadata fails explicitly; no guessed tool names or indexes')

  const original = [{ role: 'assistant', content: null, tool_calls: [{ id: 'a' }, { id: 'b' }] }, tool('a', [image]), tool('b', { content: [{ type: 'text', text: 'page 2' }, image] }), { role: 'assistant', content: 'next' }]
  const before = JSON.stringify(original)
  const lifted = liftToolImages(original)
  assert.equal(JSON.stringify(original), before)
  assert.deepEqual(Array.from(lifted, m => m.role), ['assistant', 'tool', 'tool', 'user', 'assistant'])
  assert.equal(lifted[1].tool_call_id, 'a'); assert.equal(lifted[2].tool_call_id, 'b')
  assert.equal(lifted[3].content.filter(p => p.type === 'image_url').length, 2)
  assert(!lifted[1].content.includes(png))
  assert(lifted[3].content[0].text.includes('untrusted'))
  const denied = [tool('a', { isError: true, content: [image] })]
  assert.equal(liftToolImages(denied), denied)
  const limited = liftToolImages([tool('a', Array(9).fill(image))])
  assert.equal(limited[1].content.filter(p => p.type === 'image_url').length, 8)
  assert(JSON.parse(limited[0].content)[0].text.includes('Earlier image omitted'))
  assert(JSON.parse(limited[0].content)[8].text.includes('Image delivered'))
  for (const bad of [{ ...image, data: 'bad payload' }, { ...image, mediaType: 'image/svg+xml' }, { ...image, data: 'a'.repeat(4 * 1024 * 1024 + 4) }]) {
    const result = liftToolImages([tool('a', [bad])]); assert.equal(result.length, 1); assert(result[0].content.includes('Image rejected'))
  }
  console.log('PASS tool images are bounded, immutable, and lifted only after all adjacent tool results; citations and call IDs survive')

  for (const [name, adapter] of Object.entries(adapters)) {
    let sent
    const fetch = createSlidePilotCompatFetch(async (_url, init) => {
      sent = JSON.parse(init.body)
      return new Response(JSON.stringify({ id: 'synthetic', created: 1, model: 'synthetic-model', choices: [{ index: 0, message: { role: 'assistant', content: 'OK' }, finish_reason: 'stop' }], usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 } }), { headers: { 'content-type': 'application/json' } })
    })
    await adapter(fetch).doGenerate({ prompt: [
      { role: 'user', content: [{ type: 'text', text: 'Read two pages' }] },
      { role: 'assistant', content: ['a', 'b'].map(id => ({ type: 'tool-call', toolCallId: id, toolName: 'workspace_view', input: { page: id } })) },
      { role: 'tool', content: ['a', 'b'].map(id => ({ type: 'tool-result', toolCallId: id, toolName: 'workspace_view', output: { type: 'content', value: [{ type: 'text', text: id + ' source' }, image] } })) },
    ] })
    assert.deepEqual(sent.messages.map(m => m.role), ['user', 'assistant', 'tool', 'tool', 'user'])
    assert.equal(sent.messages.at(-1).content.filter(p => p.type === 'image_url').length, 2)
    assert(sent.messages[2].content.includes('a source'))
    console.log('PASS ' + name + ': real SDK converts MCP image outputs to an actual following vision message')
  }
  const error = new Response('not authorized', { status: 401 })
  assert.equal(await createSlidePilotCompatFetch(async () => error)('https://synthetic.invalid/v1/chat/completions', { method: 'POST' }), error)
  const other = response([...frames, '[DONE]'])
  assert.equal(await createSlidePilotCompatFetch(async () => other)('https://synthetic.invalid/v1/messages', { method: 'POST' }), other)
  const abort = new AbortController()
  await createSlidePilotCompatFetch(async (_url, init) => {
    assert.equal(init.signal, abort.signal)
    assert.equal(init.headers.authorization, 'Bearer synthetic-not-a-key')
    assert(!Object.hasOwn(init.headers, 'content-length'))
    return new Response('{}')
  })('https://synthetic.invalid/v1/chat/completions', { method: 'POST', signal: abort.signal, headers: { Authorization: 'Bearer synthetic-not-a-key', 'Content-Length': '1' }, body: JSON.stringify({ messages: [tool('a', [image])] }) })
  let cancelled = false
  const cancellable = await createSlidePilotCompatFetch(async () => new Response(new ReadableStream({ cancel() { cancelled = true } }), { headers: { 'content-type': 'text/event-stream' } }))('https://synthetic.invalid/v1/chat/completions', { method: 'POST' })
  await cancellable.body.cancel()
  await new Promise(resolve => setImmediate(resolve))
  assert(cancelled)
  let sourceController
  const immediate = new ReadableStream({ start(controller) { sourceController = controller } }).pipeThrough(normalizeToolEventStream()).getReader()
  sourceController.enqueue(encoder.encode(wire([chunk({ content: 'immediate' })])))
  assert(new TextDecoder().decode((await immediate.read()).value).includes('immediate'))
  sourceController.close(); await immediate.read()
  console.log('PASS error/other transports pass through; text streams before the source closes')
}
main().catch(error => { console.error(error); process.exitCode = 1 })

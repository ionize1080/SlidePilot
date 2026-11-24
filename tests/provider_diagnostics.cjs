'use strict'
const assert = require('node:assert/strict')
const { observe } = require('../chatbox/provider-diagnostics.cjs')

const base = 'https://token-plan.maas.qianwenaiapi.com/compatible-mode/v1'
const lines = []
let completed, failed
function checkFilter(filter) {
  assert.deepEqual(filter.urls, [base + '/chat/completions*', base + '/models*'])
}
observe({
  onCompleted(filter, handler) { checkFilter(filter); completed = handler },
  onErrorOccurred(filter, handler) { checkFilter(filter); failed = handler }
}, line => lines.push(line))

const request = {
  method: 'POST', url: base + '/chat/completions?key=sensitive-query', statusCode: 200,
  get requestHeaders() { throw Error('must not inspect request headers') },
  get responseHeaders() { throw Error('must not inspect response headers') },
  get uploadData() { throw Error('must not inspect upload data') }
}
completed(request)
completed({ method: 'OPTIONS', url: base + '/chat/completions', statusCode: 204 })
completed({ method: 'GET', url: base + '/models/', statusCode: 403 })
failed({ method: 'POST', url: request.url, statusCode: 0, error: 'net::ERR_PROXY_CONNECTION_FAILED' })
failed({ method: 'POST', url: request.url, statusCode: 200, error: 'net::ERR_CONNECTION_RESET' })
failed({ method: 'POST', url: request.url, error: 'net::ERR_PRIVATE_INFORMATION' })
for (const url of [base + '/messages', base + '/models-embeddings', base + '/models/secret',
  'https://unrelated.example/compatible-mode/v1/models', 'invalid']) {
  completed({ method: 'GET', url, statusCode: 200 })
}
completed({ method: 'DELETE', url: base + '/models', statusCode: 200 })
assert.deepEqual(lines, [
  'Qwen desktop POST chat HTTP 200',
  'Qwen desktop OPTIONS chat HTTP 204',
  'Qwen desktop GET models HTTP 403',
  'Qwen desktop POST chat net::ERR_PROXY_CONNECTION_FAILED',
  'Qwen desktop POST chat HTTP 200, net::ERR_CONNECTION_RESET',
  'Qwen desktop POST chat unclassified network error'
])
console.log('Desktop Qwen outcome diagnostic and redaction checks passed.')

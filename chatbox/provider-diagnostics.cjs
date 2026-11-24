'use strict'

const origin = 'https://token-plan.maas.qianwenaiapi.com'
const routes = new Map([
  ['/compatible-mode/v1/chat/completions', { label: 'chat', method: 'POST' }],
  ['/compatible-mode/v1/models', { label: 'models', method: 'GET' }]
])
const filter = { urls: [...routes.keys()].map(path => origin + path + '*') }
// Only record known Chromium network error identifiers, never free-form error text.
const knownErrors = new Set(`
  ABORTED FAILED BLOCKED_BY_CLIENT BLOCKED_BY_ADMINISTRATOR ACCESS_DENIED NETWORK_ACCESS_DENIED
  INTERNET_DISCONNECTED NETWORK_CHANGED NAME_NOT_RESOLVED NAME_RESOLUTION_FAILED DNS_TIMED_OUT
  CONNECTION_CLOSED CONNECTION_RESET CONNECTION_REFUSED CONNECTION_ABORTED CONNECTION_FAILED
  CONNECTION_TIMED_OUT TIMED_OUT ADDRESS_UNREACHABLE PROXY_CONNECTION_FAILED TUNNEL_CONNECTION_FAILED
  NO_SUPPORTED_PROXIES MANDATORY_PROXY_CONFIGURATION_FAILED PROXY_AUTH_UNSUPPORTED PROXY_AUTH_REQUESTED
  SSL_PROTOCOL_ERROR SSL_VERSION_OR_CIPHER_MISMATCH SSL_CLIENT_AUTH_CERT_NEEDED
  CERT_AUTHORITY_INVALID CERT_COMMON_NAME_INVALID CERT_DATE_INVALID CERT_INVALID CERT_REVOKED
  EMPTY_RESPONSE INVALID_RESPONSE CONTENT_LENGTH_MISMATCH INCOMPLETE_CHUNKED_ENCODING
  HTTP2_PROTOCOL_ERROR QUIC_PROTOCOL_ERROR TOO_MANY_REDIRECTS
`.trim().split(/\s+/).map(name => 'net::ERR_' + name))

function record(details, failed, log) {
  let url
  try { url = new URL(details.url) } catch { return }
  if (url.origin !== origin) return
  const route = routes.get(url.pathname.replace(/\/$/, ''))
  if (!route || (details.method !== route.method && details.method !== 'OPTIONS')) return
  const status = details.statusCode
  const outcomes = []
  if (Number.isInteger(status) && status >= 100 && status <= 599) outcomes.push('HTTP ' + status)
  if (failed) outcomes.push(knownErrors.has(details.error) ? details.error : 'unclassified network error')
  if (!outcomes.length) outcomes.push('no HTTP status')
  log('Qwen desktop ' + details.method + ' ' + route.label + ' ' + outcomes.join(', '))
}

function observe(webRequest, log) {
  // Pinned Chatbox uses onHeadersReceived. These terminal events are observational.
  webRequest.onCompleted(filter, details => record(details, false, log))
  webRequest.onErrorOccurred(filter, details => record(details, true, log))
}

module.exports = { observe }

'use strict'
const $ = id => document.getElementById(id)
let theme = 0, mode = 'window', busy = false, modeBusy = false, loaded = false, modeRequest = 0
function status(text, error = false) { $('status').textContent = text; $('status').classList.toggle('error', error) }
function palette() { document.querySelectorAll('[data-theme]').forEach(button => button.setAttribute('aria-pressed', String(Number(button.dataset.theme) === theme))) }
function displayMode() { document.querySelectorAll('[data-mode]').forEach(button => { button.setAttribute('aria-pressed', String(button.dataset.mode === mode)); button.disabled = modeBusy || !loaded }) }
async function refreshMode() {
  if (!loaded || modeBusy) return
  const request = ++modeRequest
  try { const current = await window.slidepilotSettings.read(); if (!modeBusy && request === modeRequest && ['window','sidebar'].includes(current.mode)) { mode=current.mode; displayMode() } } catch { /* Preserve pending edits if PowerPoint is busy. */ }
}
window.slidepilotSettings.onRefresh(refreshMode)
window.addEventListener('focus', refreshMode)
document.querySelectorAll('[data-tab]').forEach(button => button.addEventListener('click', () => {
  document.querySelectorAll('[data-tab],main section').forEach(item => item.classList.remove('active'))
  document.querySelectorAll('[data-tab]').forEach(item => item.removeAttribute('aria-current'))
  button.classList.add('active'); button.setAttribute('aria-current', 'page'); $(button.dataset.tab).classList.add('active')
}))
document.querySelectorAll('[data-theme]').forEach(button => button.addEventListener('click', () => {
  theme = Number(button.dataset.theme); palette(); if (loaded) status('配色已选择，保存后应用到 PowerPoint 工具栏。')
}))
document.querySelectorAll('[data-mode]').forEach(button => button.addEventListener('click', async () => {
  if (!loaded || modeBusy || button.dataset.mode === mode) return
  const requested = button.dataset.mode
  modeRequest++
  modeBusy = true; displayMode(); status('正在切换助手窗口…')
  try {
    const saved = await window.slidepilotSettings.write({ mode: requested })
    mode = saved.mode || requested; displayMode()
    status(mode === 'sidebar' ? '已切换为 PowerPoint 侧边栏，下次打开会沿用此方式。' : '已切换为独立窗口，下次打开会沿用此方式。')
  } catch (error) { status('未能切换，保持原来的窗口方式。' + (error?.message ? ' ' + error.message : ''), true) }
  finally { modeBusy = false; displayMode() }
}))
const colors = [ ['#26534a', '#23997d', '#c9eae0'], ['#2b4370', '#4671d6', '#d3dff9'], ['#313843', '#515e6f', '#d8dee4'] ]
function svgNode(name, attrs) { const node = document.createElementNS('http://www.w3.org/2000/svg', name); for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value); return node }
document.querySelectorAll('[data-theme]').forEach(button => {
  const [ink, accent, faint] = colors[Number(button.dataset.theme)]
  button.querySelectorAll('[data-icon]').forEach(svg => {
    svg.setAttribute('viewBox', '0 0 32 32'); svg.setAttribute('aria-hidden', 'true')
    const style = { fill: faint, stroke: ink, 'stroke-width': 1.65, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }
    if (svg.dataset.icon === 'settings') {
      const points = []
      for (let i = 0; i < 8; i++) for (const offset of [-0.34, -0.17, 0.17, 0.34]) {
        const angle = i * Math.PI / 4 + offset, radius = Math.abs(offset) < 0.2 ? 12.4 : 9.8
        points.push(`${16 + Math.cos(angle) * radius},${16 + Math.sin(angle) * radius}`)
      }
      svg.append(svgNode('polygon', { ...style, points: points.join(' ') }), svgNode('circle', { cx: 16, cy: 16, r: 4, fill: 'none', stroke: accent, 'stroke-width': 2 }))
    } else {
      svg.append(svgNode('path', { ...style, d: 'M7.5 5h17A4.5 4.5 0 0 1 29 9.5v10a4.5 4.5 0 0 1-4.5 4.5H12l-5 4v-4.1A4.5 4.5 0 0 1 3 19.5v-10A4.5 4.5 0 0 1 7.5 5Z' }), svgNode('path', { d: 'M10 12h10M10 17h6', fill: 'none', stroke: ink, 'stroke-width': 1.65, 'stroke-linecap': 'round' }), svgNode('path', { d: 'M25 1l1.5 3.5L30 6l-3.5 1.5L25 11l-1.5-3.5L20 6l3.5-1.5Z', fill: accent }))
    }
  })
})
async function load() {
  try {
    const [host, workspace] = await Promise.all([window.slidepilotSettings.read(), window.slidepilotSettings.workspace()])
    theme = host.theme; mode = host.mode === 'sidebar' ? 'sidebar' : 'window'; palette(); $('version').textContent = host.version; $('versionLabel').textContent = 'Version ' + host.version
    $('office').textContent = host.office; $('workspaceLimit').value = workspace.maxFileMB; $('workspaceDepth').value = workspace.searchDepth
    loaded = true; displayMode(); $('save').disabled = false; status('设置已就绪。')
    requestAnimationFrame(() => window.slidepilotSettings.ready().catch(() => {}))
  } catch { status('无法读取设置。请保持 PowerPoint 打开，关闭审批对话框后重新打开设置。', true) }
}
$('save').addEventListener('click', async () => {
  if (busy || modeBusy || !loaded) return
  const maxFileMB = Number($('workspaceLimit').value), searchDepth = Number($('workspaceDepth').value)
  if (!Number.isInteger(maxFileMB) || maxFileMB < 1 || maxFileMB > 1024 || !Number.isInteger(searchDepth) || searchDepth < 1 || searchDepth > 12) {
    status('请输入有效范围：文件上限 1–1024 MB，递归深度 1–12 层。', true); return
  }
  busy = true; $('save').disabled = true; status('正在保存…')
  try {
    await window.slidepilotSettings.workspace({ maxFileMB, searchDepth })
    await window.slidepilotSettings.write({ theme })
    status('已保存，图标与工作空间偏好立即生效。')
  } catch { status('保存未完成。请检查 PowerPoint 状态后重试；已经保存的偏好会保留。', true) }
  finally { busy = false; $('save').disabled = false }
})
$('provider').addEventListener('click', async () => {
  $('provider').disabled = true
  try { await window.slidepilotSettings.provider(); status('已打开 Chatbox 原生模型设置。') }
  catch { status('暂时无法打开 AI 助手，请关闭 PowerPoint 中的对话框后重试。', true) }
  finally { $('provider').disabled = false }
})
document.querySelectorAll('[data-open]').forEach(button => button.addEventListener('click', async () => {
  button.disabled = true
  try { await window.slidepilotSettings.open(button.dataset.open); status('已打开。') }
  catch { status('无法打开，请检查安装文件与文件夹访问权限。', true) }
  finally { button.disabled = false }
}))
load()

// Window controls adapted from PagePilot preload.cjs at
// 01f5e69c799c4fdeb7b28c444450f1e9e1318fee. Appended to the sandboxed preload.
(() => {
  const { ipcRenderer: ipc } = require('electron');
  let state = { mode: 'window', revision: 0 };
  let busy = false, error = '', statusSequence = 0, receivedHostState = false;

  const validMode = value => value === 'window' || value === 'sidebar';
  const revision = value => Number.isSafeInteger(value) && value >= 0 ? value : 0;
  const message = value => String(value?.message || value || '无法切换窗口模式').replace(/^Error:\s*/, '').slice(0, 240);

  function updateButton(button) {
    const label = state.mode === 'sidebar' ? '弹出为独立窗口' : '收起为 PowerPoint 侧边栏';
    button.title = error ? `${label} · ${error}` : label;
    button.setAttribute('aria-label', label);
    button.setAttribute('aria-busy', String(busy));
    button.disabled = busy;
    button.classList.toggle('has-error', !!error);
    button.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">' +
      (state.mode === 'sidebar'
        ? '<path d="M14 4h6v6M20 4l-9 9M10 5H5v14h14v-5"/>'
        : '<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M14 5v14M7 12h4m-2-2 2 2-2 2"/>') + '</svg>';
    const status = document.getElementById(button.dataset.statusId);
    if (status) {
      status.textContent = error ? `窗口切换失败：${error}` : '';
      status.title = status.textContent;
      status.hidden = !error;
      if (error) button.setAttribute('aria-describedby', status.id);
      else button.removeAttribute('aria-describedby');
    }
  }

  function render() {
    if (!document?.documentElement) return;
    document.documentElement.dataset.spMode = state.mode;
    document.querySelectorAll('.sp-window-mode').forEach(updateButton);
  }

  function accept(value) {
    if (!value || !validMode(value.mode) || revision(value.revision) < state.revision) return false;
    const changed = value.mode !== state.mode;
    state = { mode: value.mode, revision: revision(value.revision) };
    receivedHostState = true;
    if (changed) error = '';
    render();
    if (changed && state.mode === 'sidebar') window.dispatchEvent(new Event('slidepilot:sidebar'));
    return true;
  }

  async function switchMode() {
    if (busy) return;
    const target = state.mode === 'sidebar' ? 'window' : 'sidebar';
    busy = true;
    error = '';
    render();
    try {
      const next = await ipc.invoke('slidepilot:mode', target);
      if (!validMode(next?.mode)) throw Error('PowerPoint 未返回有效的窗口模式，请重试。');
      accept(next);
    } catch (cause) {
      error = message(cause);
    } finally {
      busy = false;
      render();
    }
  }

  function mount() {
    if (!document?.body) return;
    let created = false;
    for (const controls of document.querySelectorAll('.controls.self-start')) {
      if (!controls.parentElement || controls.parentElement.querySelector('.sp-window-mode')) continue;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'sp-window-mode';
      button.onclick = switchMode;
      const status = document.createElement('span');
      status.id = `sp-window-mode-status-${++statusSequence}`;
      status.className = 'sp-window-mode-status';
      status.setAttribute('role', 'status');
      status.setAttribute('aria-live', 'polite');
      status.hidden = true;
      button.dataset.statusId = status.id;
      controls.before(status, button);
      created = true;
    }
    if (created) render();
  }

  function install() {
    if (!document?.body || document.getElementById('slidepilot-window-mode-style')) return;
    const style = document.createElement('style');
    style.id = 'slidepilot-window-mode-style';
    style.textContent = `
      html[data-sp-mode="sidebar"] .controls.self-start{display:none!important}
      .sp-window-mode{border:0;background:transparent;color:var(--chatbox-tint-secondary,#64748b);width:32px;height:36px;display:grid;place-items:center;cursor:pointer;-webkit-app-region:no-drag;border-radius:8px;flex-shrink:0}
      .sp-window-mode:hover{background:#899b9818!important}
      .sp-window-mode:focus-visible{outline:2px solid currentColor;outline-offset:2px}
      .sp-window-mode:disabled{cursor:wait;opacity:.55}
      .sp-window-mode.has-error{color:#b34343}
      .sp-window-mode-status{align-self:center;max-width:min(240px,30vw);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#b34343;font:11px/1.4 "Segoe UI","Microsoft YaHei UI",sans-serif;-webkit-app-region:no-drag}
      .sp-window-mode-status[hidden]{display:none}
    `;
    document.head.append(style);
    new MutationObserver(mount).observe(document.body, { childList: true, subtree: true });
    mount();
    render();
  }

  ipc.on('slidepilot:state', (_event, value) => { accept(value); });
  ipc.invoke('slidepilot:controls', 'ping').then(accept).catch(cause => {
    if (receivedHostState) return;
    error = `无法读取窗口状态：${message(cause)}`;
    render();
  });
  if (document.readyState === 'loading') window.addEventListener('DOMContentLoaded', install, { once: true });
  else install();
})();

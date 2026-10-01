/**
 * ui/island.js — Dynamic System Island for Carnaval.
 * 
 * Top-level morphing status pill that expands to reveal system telemetry,
 * real-time events, and quick recovery actions.
 */

import { getIcon } from './icons.js';

let islandEl = null;
let currentTimeout = null;
let currentState = {
  status: 'healthy',
  label: 'Cardinal Ready',
  meta: 'FunPay Connected',
  details: null,
};

export function initIsland() {
  if (document.getElementById('system-island-container')) return;

  const container = document.createElement('div');
  container.id = 'system-island-container';

  islandEl = document.createElement('div');
  islandEl.className = 'system-island liquid-glass state-healthy';
  islandEl.setAttribute('role', 'status');
  islandEl.setAttribute('aria-live', 'polite');
  islandEl.tabIndex = 0;

  renderIslandContent();

  islandEl.addEventListener('click', toggleExpand);
  islandEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      toggleExpand();
    }
  });

  container.appendChild(islandEl);
  document.body.prepend(container);
}

function renderIslandContent(expanded = false) {
  if (!islandEl) return;

  const dotClass = `island-status-dot ${currentState.status}`;

  if (!expanded) {
    islandEl.classList.remove('expanded');
    islandEl.innerHTML = `
      <div class="${dotClass}"></div>
      <span class="island-label">${escapeHtml(currentState.label)}</span>
      <span class="island-meta">${escapeHtml(currentState.meta || '')}</span>
    `;
  } else {
    islandEl.classList.add('expanded');
    islandEl.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between; width: 100%; border-bottom: 1px solid var(--outline); padding-bottom: 8px;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <div class="${dotClass}"></div>
          <strong style="font-size: 14px; color: var(--on);">${escapeHtml(currentState.label)}</strong>
        </div>
        <button id="island-close-btn" class="spring-tap" style="background: none; border: none; cursor: pointer; color: var(--muted); padding: 4px;" aria-label="Свернуть">
          ${getIcon('close', 'icon-sm')}
        </button>
      </div>
      <div style="margin-top: 10px; font-size: 12px; color: var(--muted); line-height: 1.5;">
        ${escapeHtml(currentState.details || currentState.meta || 'Все подсистемы работают в штатном режиме.')}
      </div>
      <div style="display: flex; gap: 8px; margin-top: 12px;">
        <a href="#/profile" class="btn btn-sm btn-ghost spring-tap" style="flex: 1; text-align: center; text-decoration: none; padding: 6px; border-radius: var(--r1); background: var(--track); color: var(--on); font-size: 12px;">
          ${getIcon('profile', 'icon-sm')} Профиль
        </a>
        <a href="#/updates" class="btn btn-sm btn-ghost spring-tap" style="flex: 1; text-align: center; text-decoration: none; padding: 6px; border-radius: var(--r1); background: var(--track); color: var(--on); font-size: 12px;">
          ${getIcon('update', 'icon-sm')} Центр обновлений
        </a>
      </div>
    `;

    const closeBtn = islandEl.querySelector('#island-close-btn');
    if (closeBtn) {
      closeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        renderIslandContent(false);
      });
    }
  }
}

function toggleExpand() {
  const isExpanded = islandEl?.classList.contains('expanded');
  renderIslandContent(!isExpanded);
}

export function updateIsland({ status = 'healthy', label = 'Ready', meta = '', details = null, transient = false, durationMs = 4000 }) {
  currentState = { status, label, meta, details };
  if (!islandEl) initIsland();

  if (islandEl) {
    islandEl.className = `system-island liquid-glass state-${status}`;
    renderIslandContent(islandEl.classList.contains('expanded'));
  }

  if (transient) {
    if (currentTimeout) clearTimeout(currentTimeout);
    currentTimeout = setTimeout(() => {
      currentState = { status: 'healthy', label: 'Cardinal Ready', meta: 'В сети', details: null };
      renderIslandContent(false);
    }, durationMs);
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

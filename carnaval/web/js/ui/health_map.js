/**
 * ui/health_map.js — Interactive Topology Health Map for Carnaval.
 * 
 * Renders live DAG of all active services with real-time status pulses
 * and 1-click contextual recovery triggers.
 */

import { getIcon } from './icons.js';
import * as api from '../api.js';

export async function renderHealthMap(containerEl) {
  if (!containerEl) return;

  containerEl.innerHTML = `
    <div style="padding: 16px; text-align: center; color: var(--muted); font-size: 13px;">
      <div class="shimmer" style="height: 140px; border-radius: var(--r2);"></div>
    </div>
  `;

  try {
    const topology = await api.request('GET', '/api/live/topology', { allowRelogin: false });
    renderTopologyGraph(containerEl, topology?.nodes || []);
  } catch (e) {
    renderTopologyError(containerEl, e?.message || 'Не удалось связаться с сервером');
  }
}

function renderTopologyError(containerEl, errorMessage) {
  containerEl.innerHTML = `
    <div class="topology-container" style="padding: 14px 10px;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
        <span style="font-size: 13px; font-weight: 600; color: var(--on); display: flex; align-items: center; gap: 6px;">
          ${getIcon('activity', 'icon-sm')} Карта сервисов
        </span>
        <span style="font-size: 11px; color: var(--err);">Сбой сети</span>
      </div>
      <div class="liquid-glass" style="padding: 24px 16px; border-radius: var(--r2); text-align: center; display: flex; flex-direction: column; align-items: center; gap: 10px; border-left: 3px solid var(--err);">
        <div style="color: var(--err);">${getIcon('alert', 'icon-md')}</div>
        <div style="font-size: 14px; font-weight: 600; color: var(--on);">Топология недоступна</div>
        <div style="font-size: 12px; color: var(--muted); max-width: 320px; line-height: 1.4;">${escapeHtml(errorMessage || 'Не удалось получить актуальный статус сервисов. Проверьте соединение с сервером.')}</div>
        <button id="retry-health-map-btn" class="btn btn-sm btn-primary spring-tap" style="margin-top: 4px; padding: 6px 16px; font-size: 12px; border-radius: var(--r1); display: inline-flex; align-items: center; gap: 6px; cursor: pointer;">
          ${getIcon('refresh', 'icon-xs')} Повторить попытку
        </button>
      </div>
    </div>
  `;
  containerEl.querySelector('#retry-health-map-btn')?.addEventListener('click', () => {
    renderHealthMap(containerEl);
  });
}

function renderTopologyGraph(containerEl, nodes) {
  containerEl.innerHTML = `
    <div class="topology-container" style="padding: 14px 10px;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
        <span style="font-size: 13px; font-weight: 600; color: var(--on); display: flex; align-items: center; gap: 6px;">
          ${getIcon('activity', 'icon-sm')} Карта сервисов
        </span>
        <span style="font-size: 11px; color: var(--muted);">Realtime DAG</span>
      </div>
      <div class="topology-grid" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px;"></div>
      <div id="topology-node-sheet" style="margin-top: 14px; display: none;"></div>
    </div>
  `;

  const grid = containerEl.querySelector('.topology-grid');
  const sheet = containerEl.querySelector('#topology-node-sheet');

  nodes.forEach(node => {
    const card = document.createElement('div');
    const pulseClass = `node-pulse-${node.status || 'healthy'}`;
    card.className = `topology-node-card liquid-glass ${pulseClass} spring-tap`;
    card.style.cssText = 'padding: 12px; border-radius: var(--r2); cursor: pointer; display: flex; flex-direction: column; align-items: center; text-align: center; gap: 6px;';

    const statusColorMap = {
      healthy: 'var(--ok, #1B6E4A)',
      warning: 'var(--warn, #D97706)',
      error: 'var(--err, #BA1B3D)',
      inactive: 'var(--muted, #71717A)',
      unknown: 'var(--muted, #71717A)',
      unavailable: 'var(--err, #BA1B3D)',
      degraded: 'var(--warn, #D97706)',
    };
    const color = statusColorMap[node.status] || 'var(--muted)';
    const nodeLabel = node.label || node.name || node.id || 'Узел';

    card.innerHTML = `
      <div style="color: ${color};">${getIcon(node.icon || 'system', 'icon-md')}</div>
      <div style="font-size: 12px; font-weight: 600; color: var(--on); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%;">
        ${escapeHtml(nodeLabel)}
      </div>
      <div style="font-size: 10px; color: var(--muted); text-transform: uppercase;">
        ${escapeHtml(node.status || 'unknown')}
      </div>
    `;

    card.addEventListener('click', () => {
      renderNodeDetails(sheet, node);
    });

    grid.appendChild(card);
  });
}

function renderNodeDetails(sheetEl, node) {
  sheetEl.style.display = 'block';
  sheetEl.className = 'liquid-glass';
  sheetEl.style.cssText = 'padding: 14px; border-radius: var(--r2); margin-top: 12px; border-left: 3px solid var(--primary);';

  const nodeLabel = node.label || node.name || node.id || 'Узел';
  const nodeDetails = node.exact_reason || node.details || 'Сервис функционирует в штатном режиме.';
  const recAction = node.recovery_action;
  const recLabel = recAction?.label || node.recovery_action_label || 'Восстановить';

  sheetEl.innerHTML = `
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
      <strong style="font-size: 13px; color: var(--on);">${escapeHtml(nodeLabel)}</strong>
      <button id="close-node-sheet" style="background: none; border: none; color: var(--muted); cursor: pointer;">${getIcon('close', 'icon-sm')}</button>
    </div>
    <div style="font-size: 12px; color: var(--muted); line-height: 1.4;">${escapeHtml(nodeDetails)}</div>
    ${recAction ? `
      <button id="node-recovery-btn" class="btn btn-sm btn-primary spring-tap" style="margin-top: 10px; font-size: 12px; padding: 6px 12px; border-radius: var(--r1); cursor: pointer;">
        ${escapeHtml(recLabel)}
      </button>
    ` : ''}
  `;

  sheetEl.querySelector('#close-node-sheet').addEventListener('click', () => {
    sheetEl.style.display = 'none';
  });

  const recBtn = sheetEl.querySelector('#node-recovery-btn');
  if (recBtn && recAction) {
    recBtn.addEventListener('click', async () => {
      if (recAction.endpoint) {
        try {
          await api.request('POST', recAction.endpoint, {}, { allowRelogin: false });
          recBtn.disabled = true;
          recBtn.textContent = 'Запрос отправлен';
        } catch (err) {
          recBtn.textContent = 'Ошибка: ' + (err.message || err);
        }
      }
    });
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

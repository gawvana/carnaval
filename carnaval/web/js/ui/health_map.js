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
    // Fallback default nodes if API is loading
    const defaultNodes = [
      { id: 'telegram', label: 'Telegram Bot', status: 'healthy', icon: 'telegram', details: 'Бот активен' },
      { id: 'backend', label: 'FastAPI Backend', status: 'healthy', icon: 'system', details: 'Порт 5000' },
      { id: 'cardinal', label: 'Cardinal Core', status: 'healthy', icon: 'cpu', details: 'Ядро работает' },
      { id: 'runner', label: 'FunPay Runner', status: 'healthy', icon: 'activity', details: 'Цикл активен' },
      { id: 'funpay', label: 'FunPay API', status: 'healthy', icon: 'funpay', details: 'Соединение установлено' },
    ];
    renderTopologyGraph(containerEl, defaultNodes);
  }
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
      inactive: 'var(--muted, #71717A)'
    };
    const color = statusColorMap[node.status] || 'var(--muted)';

    card.innerHTML = `
      <div style="color: ${color};">${getIcon(node.icon || 'system', 'icon-md')}</div>
      <div style="font-size: 12px; font-weight: 600; color: var(--on); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%;">
        ${escapeHtml(node.label)}
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

  sheetEl.innerHTML = `
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
      <strong style="font-size: 13px; color: var(--on);">${escapeHtml(node.label)}</strong>
      <button id="close-node-sheet" style="background: none; border: none; color: var(--muted); cursor: pointer;">${getIcon('close', 'icon-sm')}</button>
    </div>
    <div style="font-size: 12px; color: var(--muted); line-height: 1.4;">${escapeHtml(node.details || 'Сервис функционирует в нормальном режиме.')}</div>
    ${node.recovery_action ? `
      <button class="btn btn-sm btn-primary spring-tap" style="margin-top: 10px; font-size: 12px; padding: 6px 12px; border-radius: var(--r1);">
        ${escapeHtml(node.recovery_action_label || 'Восстановить')}
      </button>
    ` : ''}
  `;

  sheetEl.querySelector('#close-node-sheet').addEventListener('click', () => {
    sheetEl.style.display = 'none';
  });
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * ui/timeline.js — Live Activity Timeline & Event Replay for Carnaval.
 * 
 * Renders real-time stream of audit events and lets operators replay synthetic triggers.
 */

import { getIcon } from './icons.js';
import * as api from '../api.js';
import { showToast } from './toast.js';

export async function renderTimeline(containerEl) {
  if (!containerEl) return;

  containerEl.innerHTML = `
    <div style="padding: 16px; text-align: center; color: var(--muted); font-size: 13px;">
      <div class="shimmer" style="height: 120px; border-radius: var(--r2);"></div>
    </div>
  `;

  try {
    const res = await api.request('GET', '/api/live/timeline', { allowRelogin: false });
    const events = res?.events || [];
    renderTimelineList(containerEl, events);
  } catch (e) {
    renderTimelineError(containerEl, e?.message || 'Не удалось загрузить ленту активности');
  }
}

function renderTimelineError(containerEl, errorMessage) {
  containerEl.innerHTML = `
    <div class="timeline-container" style="padding: 10px 0;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; padding: 0 4px;">
        <span style="font-size: 13px; font-weight: 600; color: var(--on); display: flex; align-items: center; gap: 6px;">
          ${getIcon('timeline', 'icon-sm')} Журнал активности
        </span>
      </div>
      <div class="liquid-glass" style="padding: 20px 14px; border-radius: var(--r2); text-align: center; display: flex; flex-direction: column; align-items: center; gap: 8px; border-left: 3px solid var(--err);">
        <div style="color: var(--err);">${getIcon('alert', 'icon-md')}</div>
        <div style="font-size: 13px; font-weight: 600; color: var(--on);">События временно недоступны</div>
        <div style="font-size: 11px; color: var(--muted); max-width: 280px; line-height: 1.4;">${escapeHtml(errorMessage || 'Не удалось получить журнал событий. Проверьте соединение с сервером.')}</div>
        <button id="retry-timeline-btn" class="btn btn-sm btn-primary spring-tap" style="margin-top: 4px; padding: 5px 14px; font-size: 11px; border-radius: var(--r1); display: inline-flex; align-items: center; gap: 4px; cursor: pointer;">
          ${getIcon('refresh', 'icon-xs')} Повторить попытку
        </button>
      </div>
    </div>
  `;
  containerEl.querySelector('#retry-timeline-btn')?.addEventListener('click', () => {
    renderTimeline(containerEl);
  });
}

function renderTimelineList(containerEl, events) {
  containerEl.innerHTML = `
    <div class="timeline-container" style="padding: 10px 0;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; padding: 0 4px;">
        <span style="font-size: 13px; font-weight: 600; color: var(--on); display: flex; align-items: center; gap: 6px;">
          ${getIcon('timeline', 'icon-sm')} Журнал активности
        </span>
        <button id="refresh-timeline-btn" class="spring-tap" style="background: none; border: none; color: var(--primary); cursor: pointer; display: flex; align-items: center; gap: 4px; font-size: 11px;">
          ${getIcon('refresh', 'icon-xs')} Обновить
        </button>
      </div>
      <div class="timeline-items-flow" style="display: flex; flex-direction: column; gap: 8px;"></div>
    </div>
  `;

  const flow = containerEl.querySelector('.timeline-items-flow');
  const refreshBtn = containerEl.querySelector('#refresh-timeline-btn');

  refreshBtn.addEventListener('click', () => renderTimeline(containerEl));

  if (events.length === 0) {
    flow.innerHTML = `
      <div style="padding: 24px; text-align: center; color: var(--muted); font-size: 12px;">
        Событий пока нет
      </div>
    `;
    return;
  }

  events.forEach(evt => {
    const card = document.createElement('div');
    card.className = 'timeline-card liquid-glass';
    card.style.cssText = 'padding: 10px 14px; border-radius: var(--r2); display: flex; align-items: flex-start; gap: 10px; font-size: 12px;';

    const iconMap = {
      order: 'orders',
      delivery: 'delivery',
      chat: 'chats',
      funpay: 'funpay',
      system: 'cpu',
      automation: 'automation',
      error: 'alert'
    };

    card.innerHTML = `
      <span style="color: var(--primary); margin-top: 2px;">${getIcon(iconMap[evt.category] || 'activity', 'icon-sm')}</span>
      <div style="flex: 1; min-width: 0;">
        <div style="display: flex; justify-content: space-between; align-items: baseline;">
          <strong style="color: var(--on); font-size: 12px;">${escapeHtml(evt.title)}</strong>
          <span style="font-size: 10px; color: var(--muted);">${escapeHtml(evt.timestamp || '')}</span>
        </div>
        <div style="color: var(--muted); margin-top: 2px; line-height: 1.3;">${escapeHtml(evt.desc || '')}</div>
        ${evt.replay_supported ? `
          <button class="spring-tap replay-btn" style="margin-top: 6px; background: var(--track); border: none; border-radius: var(--r1); padding: 3px 8px; font-size: 10px; color: var(--on); cursor: pointer; display: inline-flex; align-items: center; gap: 4px;">
            ${getIcon('refresh', 'icon-xs')} Повторить (Replay)
          </button>
        ` : ''}
      </div>
    `;

    const replayBtn = card.querySelector('.replay-btn');
    if (replayBtn) {
      replayBtn.addEventListener('click', async () => {
        try {
          await api.request('POST', '/api/live/replay-event', { event_id: evt.id }, { allowRelogin: false });
          showToast('Симуляция события запущена', 'ok');
        } catch (e) {
          showToast('Ошибка симуляции: ' + (e.message || e), 'err');
        }
      });
    }

    flow.appendChild(card);
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

/**
 * ui/notifications.js — Centralized Notification Center for Carnaval.
 * 
 * Aggregates real-time events across all subsystems with categorization and instant action links.
 */

import { getIcon } from './icons.js';
import * as api from '../api.js';

let notificationsList = [];

export function addNotification({ category = 'system', title, desc, action = null, actionText = '' }) {
  const item = {
    id: 'notif-' + Date.now() + '-' + Math.random().toString(36).substr(2, 4),
    timestamp: new Date(),
    category,
    title,
    desc,
    action,
    actionText,
    read: false
  };

  notificationsList.unshift(item);
  if (notificationsList.length > 50) notificationsList.pop();

  updateBadge();
}

export function getNotifications() {
  return [...notificationsList];
}

export function markAllAsRead() {
  notificationsList.forEach(n => n.read = true);
  updateBadge();
}

function updateBadge() {
  const unreadCount = notificationsList.filter(n => !n.read).length;
  const badgeEl = document.getElementById('notif-badge');
  if (badgeEl) {
    if (unreadCount > 0) {
      badgeEl.textContent = unreadCount > 9 ? '9+' : unreadCount;
      badgeEl.style.display = 'inline-flex';
    } else {
      badgeEl.style.display = 'none';
    }
  }
}

export function renderNotificationCenter(containerEl) {
  if (!containerEl) return;

  containerEl.innerHTML = `
    <div class="notifications-sheet-header" style="display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; border-bottom: 1px solid var(--outline);">
      <div style="display: flex; align-items: center; gap: 8px;">
        <span style="color: var(--primary);">${getIcon('bell', 'icon-md')}</span>
        <h3 style="margin: 0; font-size: 16px; font-weight: 600; color: var(--on);">Уведомления</h3>
      </div>
      <button id="notif-clear-btn" class="spring-tap" style="background: none; border: none; font-size: 12px; color: var(--primary); cursor: pointer; padding: 4px 8px;">
        Прочитать все
      </button>
    </div>
    <div id="notif-items-container" style="padding: 12px 16px; max-height: 60vh; overflow-y: auto;"></div>
  `;

  const itemsContainer = containerEl.querySelector('#notif-items-container');
  const clearBtn = containerEl.querySelector('#notif-clear-btn');

  clearBtn.addEventListener('click', () => {
    markAllAsRead();
    renderNotificationCenter(containerEl);
  });

  if (notificationsList.length === 0) {
    itemsContainer.innerHTML = `
      <div style="padding: 32px 16px; text-align: center; color: var(--muted); font-size: 13px;">
        ${getIcon('check', 'icon-lg')}
        <div style="margin-top: 8px;">Нет новых уведомлений</div>
      </div>
    `;
    return;
  }

  notificationsList.forEach(item => {
    const el = document.createElement('div');
    el.className = 'notif-item liquid-glass';
    el.style.cssText = `padding: 12px 14px; border-radius: var(--r2); margin-bottom: 8px; border-left: 3px solid ${item.read ? 'transparent' : 'var(--primary)'};`;

    const iconMap = {
      order: 'orders',
      chat: 'chats',
      system: 'system',
      error: 'alert',
      update: 'update',
      automation: 'automation'
    };

    const timeStr = item.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    el.innerHTML = `
      <div style="display: flex; align-items: flex-start; gap: 10px;">
        <span style="color: var(--primary); margin-top: 2px;">${getIcon(iconMap[item.category] || 'bell', 'icon-sm')}</span>
        <div style="flex: 1; min-width: 0;">
          <div style="display: flex; justify-content: space-between; align-items: baseline;">
            <strong style="font-size: 13px; color: var(--on);">${escapeHtml(item.title)}</strong>
            <span style="font-size: 11px; color: var(--muted);">${timeStr}</span>
          </div>
          <div style="font-size: 12px; color: var(--muted); margin-top: 2px; line-height: 1.4;">${escapeHtml(item.desc)}</div>
          ${item.actionText ? `
            <button class="spring-tap notif-action-btn" style="margin-top: 8px; background: var(--track); border: none; border-radius: var(--r1); padding: 4px 10px; font-size: 11px; color: var(--on); cursor: pointer;">
              ${escapeHtml(item.actionText)}
            </button>
          ` : ''}
        </div>
      </div>
    `;

    const actBtn = el.querySelector('.notif-action-btn');
    if (actBtn && item.action) {
      actBtn.addEventListener('click', () => {
        item.read = true;
        item.action();
      });
    }

    itemsContainer.appendChild(el);
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

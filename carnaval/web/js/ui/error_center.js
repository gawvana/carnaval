/**
 * ui/error_center.js — Deterministic Smart Error Center for Carnaval.
 * 
 * Translates technical backend errors into clear explanations with 1-click recovery actions.
 * Zero generic errors, zero fake diagnoses.
 */

import { getIcon } from './icons.js';
import * as api from '../api.js';
import { showToast } from './toast.js';

const ERROR_MAP = {
  FUNPAY_ACCOUNT_NOT_INITIALIZED: {
    title: 'FunPay не инициализирован',
    cause: 'Сессия FunPay не активирована или истек Golden Key (Account.get() вернул ошибку).',
    actionText: 'Переподключить FunPay',
    actionIcon: 'reconnect',
    onAction: async () => {
      try {
        await api.request('POST', '/api/account/reconnect', { allowRelogin: false });
        showToast('Запрос на переподключение отправлен', 'ok');
      } catch (e) {
        showToast('Ошибка переподключения: ' + (e.message || e), 'err');
      }
    }
  },
  NETWORK_ERROR: {
    title: 'Сетевая ошибка FunPay',
    cause: 'Не удалось установить соединение с серверами funpay.com (таймаут или блокировка IP).',
    actionText: 'Проверить прокси',
    actionIcon: 'proxy',
    onAction: () => {
      window.location.hash = '#/more';
    }
  },
  PANEL_LOCKED: {
    title: 'Панель управления заблокирована',
    cause: 'Для выполнения этого действия требуется ввести мастер-пароль панели (PIN).',
    actionText: 'Разблокировать',
    actionIcon: 'unlock',
    onAction: () => {
      window.location.hash = '#/profile';
    }
  },
  MAINTENANCE_MODE_ACTIVE: {
    title: 'Включен режим обслуживания',
    cause: 'Автоматические операции и доставка временно приостановлены для безопасных работ.',
    actionText: 'Управление режимами',
    actionIcon: 'maintenance',
    onAction: () => {
      window.location.hash = '#/updates';
    }
  },
  SAFE_MODE_ACTIVE: {
    title: 'Активирован Safe Mode',
    cause: 'Система запущена в аварийном режиме: сторонние плагины и кастомные правила отключены.',
    actionText: 'Открыть центр системы',
    actionIcon: 'shield',
    onAction: () => {
      window.location.hash = '#/updates';
    }
  },
};

export function renderErrorCard(errorCode, containerEl, customMessage = '') {
  if (!containerEl) return;

  const info = ERROR_MAP[errorCode] || {
    title: 'Системное предупреждение',
    cause: customMessage || 'Произошла непредвиденная ошибка при выполнении операции.',
    actionText: 'Повторить попытку',
    actionIcon: 'refresh',
    onAction: () => window.location.reload()
  };

  const card = document.createElement('div');
  card.className = 'error-smart-card liquid-glass';
  card.style.cssText = 'padding: 18px; border-radius: var(--r2); border-left: 4px solid var(--err); margin: 16px 0;';

  card.innerHTML = `
    <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 8px;">
      <span style="color: var(--err);">${getIcon('alert', 'icon-md')}</span>
      <strong style="font-size: 15px; color: var(--on);">${escapeHtml(info.title)}</strong>
    </div>
    <p style="font-size: 13px; color: var(--muted); margin: 0 0 14px 0; line-height: 1.4;">
      ${escapeHtml(info.cause)}
    </p>
    <button class="btn btn-sm btn-primary spring-tap action-btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 8px 14px; font-size: 13px; border-radius: var(--r1); cursor: pointer;">
      ${getIcon(info.actionIcon, 'icon-sm')}
      <span>${escapeHtml(info.actionText)}</span>
    </button>
  `;

  const btn = card.querySelector('.action-btn');
  if (btn) {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      info.onAction();
    });
  }

  containerEl.appendChild(card);
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * ui/command_palette.js — Global Command Palette & Unified Search for Carnaval.
 * 
 * Supports Desktop (Ctrl/Cmd + K) and Mobile quick actions without global FAB.
 */

import { getIcon } from './icons.js';
import * as api from '../api.js';

let paletteBackdrop = null;
let searchInput = null;
let resultsContainer = null;
let activeIndex = -1;
let currentItems = [];

const STATIC_COMMANDS = [
  { id: 'cmd-orders', title: 'Заказы', desc: 'Перейти к списку заказов FunPay', icon: 'orders', category: 'Навигация', action: () => navigate('#/orders') },
  { id: 'cmd-chats', title: 'Диалоги и чаты', desc: 'Открыть входящие чаты покупателей', icon: 'chats', category: 'Навигация', action: () => navigate('#/chats') },
  { id: 'cmd-profile', title: 'Профиль и аккаунт', desc: 'Управление FunPay, Telegram и безопасностью', icon: 'profile', category: 'Навигация', action: () => navigate('#/profile') },
  { id: 'cmd-updates', title: 'Центр обновлений', desc: 'Проверить обновления и управление версиями', icon: 'update', category: 'Система', action: () => navigate('#/updates') },
  { id: 'cmd-auto-lab', title: 'Лаборатория автоматизации', desc: 'Конструктор правил и симулятор выдачи', icon: 'automation', category: 'Инструменты', action: () => navigate('#/automation-lab') },
  { id: 'cmd-plugins-lab', title: 'Лаборатория плагинов', desc: 'Управление расширениями и консольными командами', icon: 'plugins', category: 'Инструменты', action: () => navigate('#/plugins-lab') },
  { id: 'cmd-reconnect', title: 'Переподключить FunPay', desc: 'Сбросить соединение и авторизоваться заново', icon: 'reconnect', category: 'Действия', action: () => triggerReconnect() },
  { id: 'cmd-backup', title: 'Создать резервную копию', desc: 'Экспорт настроек, базы и конфигураций в ZIP', icon: 'backup', category: 'Данные', action: () => triggerBackup() },
];

export function initCommandPalette() {
  if (document.getElementById('command-palette-backdrop')) return;

  paletteBackdrop = document.createElement('div');
  paletteBackdrop.id = 'command-palette-backdrop';
  paletteBackdrop.className = 'command-palette-backdrop';

  paletteBackdrop.innerHTML = `
    <div class="command-palette-box liquid-glass" role="dialog" aria-modal="true" aria-label="Командная палитра">
      <div class="command-search-header">
        <span style="color: var(--muted);">${getIcon('search', 'icon-md')}</span>
        <input type="text" class="command-search-input" placeholder="Поиск действий, заказов, чатов, плагинов..." autocomplete="off" spellcheck="false">
        <kbd style="font-size: 11px; padding: 2px 6px; border-radius: 4px; background: var(--track); color: var(--muted);">ESC</kbd>
      </div>
      <div class="command-results-list" role="listbox"></div>
    </div>
  `;

  searchInput = paletteBackdrop.querySelector('.command-search-input');
  resultsContainer = paletteBackdrop.querySelector('.command-results-list');

  // Закрытие по клику на фон
  paletteBackdrop.addEventListener('click', (e) => {
    if (e.target === paletteBackdrop) closeCommandPalette();
  });

  // Ввод поискового запроса
  searchInput.addEventListener('input', handleSearchInput);

  // Клавиатурная навигация
  paletteBackdrop.addEventListener('keydown', handleKeydown);

  document.body.appendChild(paletteBackdrop);

  // Глобальный хоткей Ctrl+K / Cmd+K
  window.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      toggleCommandPalette();
    }
    if (e.key === 'Escape' && paletteBackdrop.classList.contains('active')) {
      closeCommandPalette();
    }
  });
}

export function openCommandPalette() {
  if (!paletteBackdrop) initCommandPalette();
  paletteBackdrop.classList.add('active');
  searchInput.value = '';
  activeIndex = 0;
  renderResults(STATIC_COMMANDS);
  setTimeout(() => searchInput.focus(), 50);
}

export function closeCommandPalette() {
  if (paletteBackdrop) {
    paletteBackdrop.classList.remove('active');
  }
}

export function toggleCommandPalette() {
  if (paletteBackdrop?.classList.contains('active')) {
    closeCommandPalette();
  } else {
    openCommandPalette();
  }
}

function handleSearchInput() {
  const query = searchInput.value.trim().toLowerCase();
  if (!query) {
    renderResults(STATIC_COMMANDS);
    return;
  }

  // Локальная фильтрация команд
  const filteredCommands = STATIC_COMMANDS.filter(cmd => 
    cmd.title.toLowerCase().includes(query) || cmd.desc.toLowerCase().includes(query)
  );

  // Динамический поиск через бэкенд
  api.request('GET', `/api/search?q=${encodeURIComponent(query)}`, { allowRelogin: false })
    .then(data => {
      const remoteResults = [];
      if (data && data.results) {
        data.results.forEach(res => {
          remoteResults.push({
            id: `res-${res.category}-${res.id}`,
            title: res.title,
            desc: res.description,
            icon: res.icon || 'file',
            category: res.category_label || res.category,
            action: () => {
              if (res.route) navigate(res.route);
            }
          });
        });
      }
      renderResults([...filteredCommands, ...remoteResults]);
    })
    .catch(() => {
      renderResults(filteredCommands);
    });
}

function renderResults(items) {
  currentItems = items;
  activeIndex = items.length > 0 ? 0 : -1;
  resultsContainer.innerHTML = '';

  if (items.length === 0) {
    resultsContainer.innerHTML = `
      <div style="padding: 24px; text-align: center; color: var(--muted); font-size: 13px;">
        Ничего не найдено по заданному запросу
      </div>
    `;
    return;
  }

  items.forEach((item, index) => {
    const el = document.createElement('div');
    el.className = `command-item ${index === activeIndex ? 'selected' : ''}`;
    el.setAttribute('role', 'option');
    el.setAttribute('aria-selected', index === activeIndex ? 'true' : 'false');

    el.innerHTML = `
      <span style="color: var(--primary); display: flex; align-items: center;">${getIcon(item.icon, 'icon-sm')}</span>
      <div style="flex: 1; min-width: 0;">
        <div style="font-weight: 500; font-size: 13px; color: var(--on);">${escapeHtml(item.title)}</div>
        <div style="font-size: 11px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(item.desc)}</div>
      </div>
      <span class="command-item-badge">${escapeHtml(item.category)}</span>
    `;

    el.addEventListener('click', () => {
      closeCommandPalette();
      item.action();
    });

    resultsContainer.appendChild(el);
  });
}

function handleKeydown(e) {
  if (currentItems.length === 0) return;

  if (e.key === 'ArrowDown') {
    e.preventDefault();
    activeIndex = (activeIndex + 1) % currentItems.length;
    updateSelection();
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    activeIndex = (activeIndex - 1 + currentItems.length) % currentItems.length;
    updateSelection();
  } else if (e.key === 'Enter') {
    e.preventDefault();
    if (activeIndex >= 0 && activeIndex < currentItems.length) {
      closeCommandPalette();
      currentItems[activeIndex].action();
    }
  }
}

function updateSelection() {
  const children = resultsContainer.querySelectorAll('.command-item');
  children.forEach((el, idx) => {
    el.classList.toggle('selected', idx === activeIndex);
    el.setAttribute('aria-selected', idx === activeIndex ? 'true' : 'false');
    if (idx === activeIndex) {
      el.scrollIntoView({ block: 'nearest' });
    }
  });
}

function navigate(hash) {
  window.location.hash = hash;
}

function triggerReconnect() {
  api.request('POST', '/api/account/reconnect', { allowRelogin: false })
    .then(() => {
      import('./toast.js').then(m => m.showToast('Запущен процесс переподключения FunPay', 'ok'));
    })
    .catch(err => {
      import('./toast.js').then(m => m.showToast('Ошибка переподключения: ' + (err.message || err), 'err'));
    });
}

function triggerBackup() {
  api.request('POST', '/api/backup', { allowRelogin: false })
    .then(() => {
      import('./toast.js').then(m => m.showToast('Резервная копия успешно создана', 'ok'));
    })
    .catch(err => {
      import('./toast.js').then(m => m.showToast('Ошибка бэкапа: ' + (err.message || err), 'err'));
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

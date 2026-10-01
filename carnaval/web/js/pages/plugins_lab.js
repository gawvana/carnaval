/**
 * pages/plugins_lab.js — Plugin Control Center & Laboratory for Carnaval.
 * 
 * Manages full lifecycle of Cardinal plugins: Installed, Loaded, Enabled, Running, Failed.
 * Supports hot reload, pinning, console commands discovery, and Safe Mode isolation.
 */

import { getIcon } from '../ui/icons.js';
import * as api from '../api.js';
import { showToast } from '../ui/toast.js';

let container = null;

export async function renderPluginsLab(mountEl) {
  container = mountEl;
  container.innerHTML = `
    <div class="page-header" style="display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; border-bottom: 1px solid var(--outline);">
      <div style="display: flex; align-items: center; gap: 10px;">
        <span style="color: var(--primary);">${getIcon('plugins', 'icon-md')}</span>
        <div>
          <h2 style="margin: 0; font-size: 18px; font-weight: 700; color: var(--on);">Лаборатория плагинов</h2>
          <span style="font-size: 12px; color: var(--muted);">Управление расширениями, командами и изоляцией</span>
        </div>
      </div>
      <button id="reload-plugins-btn" class="btn btn-sm btn-primary spring-tap" style="display: inline-flex; align-items: center; gap: 6px; padding: 8px 14px; border-radius: var(--r1); font-size: 13px; cursor: pointer;">
        ${getIcon('refresh', 'icon-xs')} Перезагрузить
      </button>
    </div>

    <div class="plugins-lab-content" style="padding: 16px 20px; display: flex; flex-direction: column; gap: 14px;">
      <div class="shimmer" style="height: 140px; border-radius: var(--r2);"></div>
    </div>
  `;

  container.querySelector('#reload-plugins-btn').addEventListener('click', reloadAllPlugins);
  await loadPlugins();
}

async function loadPlugins() {
  const contentEl = container?.querySelector('.plugins-lab-content');
  if (!contentEl) return;

  try {
    const data = await api.request('GET', '/api/plugins', { allowRelogin: false });
    const plugins = data?.plugins || [];
    renderPluginsList(contentEl, plugins);
  } catch (e) {
    contentEl.innerHTML = `
      <div class="liquid-glass" style="padding: 32px; text-align: center; border-radius: var(--r2); color: var(--danger, #ff453a);">
        <div style="font-size: 14px; font-weight: 600; margin-bottom: 12px;">Не удалось загрузить список плагинов</div>
        <button id="retry-plugins-btn" class="btn btn-sm btn-ghost spring-tap" style="display: inline-flex; align-items: center; gap: 6px; padding: 6px 14px; border-radius: var(--r1); font-size: 13px; cursor: pointer; color: var(--on);">
          ${getIcon('refresh', 'icon-xs')} Повторить попытку
        </button>
      </div>
    `;
    contentEl.querySelector('#retry-plugins-btn')?.addEventListener('click', () => {
      contentEl.innerHTML = '<div class="shimmer" style="height: 140px; border-radius: var(--r2);"></div>';
      loadPlugins();
    });
  }
}

function renderPluginsList(contentEl, plugins) {
  contentEl.innerHTML = '';

  if (plugins.length === 0) {
    contentEl.innerHTML = `
      <div class="liquid-glass" style="padding: 32px; text-align: center; border-radius: var(--r2); color: var(--muted);">
        ${getIcon('plugins', 'icon-lg')}
        <div style="margin-top: 10px; font-size: 14px;">Плагины не установлены</div>
      </div>
    `;
    return;
  }

  plugins.forEach(p => {
    const card = document.createElement('div');
    card.className = 'plugin-item-card liquid-glass';
    card.style.cssText = 'padding: 16px; border-radius: var(--r2); display: flex; flex-direction: column; gap: 10px;';

    card.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: flex-start;">
        <div>
          <div style="display: flex; align-items: center; gap: 8px;">
            <strong style="font-size: 14px; color: var(--on);">${escapeHtml(p.name)}</strong>
            <span style="font-size: 11px; color: var(--muted); background: var(--track); padding: 2px 6px; border-radius: 4px;">v${escapeHtml(p.version || '1.0')}</span>
            ${p.pinned ? `<span style="color: var(--warn); display: flex;">${getIcon('star', 'icon-xs')}</span>` : ''}
          </div>
          <span style="font-size: 11px; color: var(--muted); margin-top: 2px; display: block;">Автор: ${escapeHtml(p.author || 'Неизвестен')}</span>
        </div>
        <button class="toggle-plugin-btn btn btn-sm ${p.enabled ? 'btn-primary' : 'btn-ghost'} spring-tap" style="font-size: 12px; padding: 4px 12px; border-radius: var(--r1); cursor: pointer;">
          ${p.enabled ? 'Включен' : 'Отключен'}
        </button>
      </div>

      <div style="font-size: 12px; color: var(--muted); line-height: 1.4;">
        ${escapeHtml(p.desc || 'Описание отсутствует')}
      </div>

      ${p.commands && p.commands.length > 0 ? `
        <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
          <span style="font-size: 11px; color: var(--muted);">Команды:</span>
          ${p.commands.map(cmd => `<code style="font-size: 11px; background: var(--track); padding: 2px 6px; border-radius: 4px; color: var(--primary);">${escapeHtml(cmd)}</code>`).join('')}
        </div>
      ` : ''}

      <div style="display: flex; gap: 8px; border-top: 1px solid var(--outline); padding-top: 10px; margin-top: 4px;">
        <button class="pin-plugin-btn spring-tap" style="background: none; border: none; font-size: 12px; color: var(--muted); cursor: pointer; display: flex; align-items: center; gap: 4px;">
          ${getIcon('star', 'icon-xs')} ${p.pinned ? 'Открепить' : 'Закрепить'}
        </button>
        <button class="reload-plugin-single-btn spring-tap" style="background: none; border: none; font-size: 12px; color: var(--primary); cursor: pointer; display: flex; align-items: center; gap: 4px; margin-left: auto;">
          ${getIcon('refresh', 'icon-xs')} Перезагрузить
        </button>
      </div>
    `;

    // Слушатель переключения активности
    card.querySelector('.toggle-plugin-btn').addEventListener('click', async () => {
      try {
        await api.request('POST', `/api/plugins/${encodeURIComponent(p.uuid)}/toggle`, { allowRelogin: false });
        showToast(`Плагин ${p.name} переключен`, 'ok');
        await loadPlugins();
      } catch (e) {
        showToast('Ошибка переключения: ' + (e.message || e), 'err');
      }
    });

    // Слушатель закрепления
    card.querySelector('.pin-plugin-btn').addEventListener('click', async () => {
      try {
        await api.request('POST', `/api/plugins/${encodeURIComponent(p.uuid)}/pin`, { pinned: !p.pinned }, { allowRelogin: false });
        showToast(`Статус закрепления обновлен`, 'ok');
        await loadPlugins();
      } catch (e) {
        showToast('Ошибка закрепления: ' + (e.message || e), 'err');
      }
    });

    // Слушатель перезагрузки конкретного плагина
    card.querySelector('.reload-plugin-single-btn').addEventListener('click', async () => {
      try {
        await api.request('POST', `/api/plugins/${encodeURIComponent(p.uuid)}/reload`, { allowRelogin: false });
        showToast(`Плагин ${p.name} перезагружен`, 'ok');
      } catch (e) {
        showToast('Ошибка перезагрузки: ' + (e.message || e), 'err');
      }
    });

    contentEl.appendChild(card);
  });
}

async function reloadAllPlugins() {
  showToast('Перезагрузка всех плагинов...', 'ok');
  try {
    await api.request('POST', '/api/plugins/reload-all', { allowRelogin: false });
    showToast('Все плагины успешно перезагружены', 'ok');
    await loadPlugins();
  } catch (e) {
    showToast('Ошибка перезагрузки: ' + (e.message || e), 'err');
  }
}

export function unmountPluginsLab() {
  container = null;
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

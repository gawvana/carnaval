/**
 * pages/more.js — Вкладка «Ещё» (Настройки и система)
 *
 * Архитектура iOS 27:
 *   - Иерархия: System Overview -> Categories -> Settings -> Actions
 *   - Master View: обзор системы + группированное меню категорий + быстрые настройки и действия
 *   - Detail View: выбранный раздел с навигационной полосой категорий
 *   - 100% чистый UI: без смайликов и эмодзи, только семантические SVG-иконки getIcon(...)
 *   - Нативная интеграция с Telegram BackButton
 *   - XSS безопасность (escHtml), доступность (touch target >= 44px)
 */

import * as api from '../api.js';
import { openConfirmSheet, openSheet, closeSheet } from '../ui/sheet.js';
import { showToast } from '../ui/toast.js';
import { tg, haptic } from '../tg.js';
import { getQualityTier, setQualityTier } from '../ui/tier.js';
import { getIcon } from '../ui/icons.js';

// ── Определение категорий ────────────────────────────────────────────────────

const SECTIONS = [
  {
    id: 'notifications',
    label: 'Уведомления',
    iconName: 'bell',
    iconCls: 'more-cat-icon-notif',
    desc: 'BlockList, фильтры сообщений и оповещения',
  },
  {
    id: 'greetings',
    label: 'Сообщения',
    iconName: 'message',
    iconCls: 'more-cat-icon-msg',
    desc: 'Приветствия, подтверждения заказов и отзывы',
  },
  {
    id: 'blacklist',
    label: 'Чёрный список',
    iconName: 'ban',
    iconCls: 'more-cat-icon-black',
    desc: 'Блокировка нежелательных покупателей',
  },
  {
    id: 'plugins',
    label: 'Плагины',
    iconName: 'plugins',
    iconCls: 'more-cat-icon-plugins',
    desc: 'Расширения Cardinal, включение и загрузка .py',
  },
  {
    id: 'security',
    label: 'Безопасность',
    iconName: 'security',
    iconCls: 'more-cat-icon-sec',
    desc: 'Golden Key, прокси, сессии и пароль панели',
  },
  {
    id: 'system',
    label: 'Система',
    iconName: 'settings',
    iconCls: 'more-cat-icon-sys',
    desc: 'Журнал логов, бэкапы, перезапуск бота',
  },
  {
    id: 'updates',
    label: 'Центр обновлений',
    iconName: 'update',
    iconCls: 'more-cat-icon-sys',
    desc: 'Версионирование, проверка обновлений и Safe Mode',
  },
  {
    id: 'automation-lab',
    label: 'Лаборатория авто',
    iconName: 'automation',
    iconCls: 'more-cat-icon-plugins',
    desc: 'Конструктор правил, симулятор и отладчик выдачи',
  },
  {
    id: 'plugins-lab',
    label: 'Лаборатория плагинов',
    iconName: 'plugins',
    iconCls: 'more-cat-icon-plugins',
    desc: 'Каталог расширений, консольные команды и статус',
  },
];

// Карта метаданных для секции сообщений
const GREETING_LABELS = {
  'Greetings.sendGreetings':        { label: 'Приветствие включено',         type: 'toggle' },
  'Greetings.greetingsText':        { label: 'Текст приветствия',            type: 'text'   },
  'Greetings.greetingsCooldown':    { label: 'Кулдаун приветствия (сек)',    type: 'text'   },
  'Greetings.ignoreSystemMessages': { label: 'Игнорировать системные чаты',  type: 'toggle' },
  'Greetings.onlyNewChats':         { label: 'Только для новых чатов',       type: 'toggle' },
  'OrderConfirm.sendReply':         { label: 'Авто-ответ при подтверждении', type: 'toggle' },
  'OrderConfirm.replyText':         { label: 'Текст подтверждения заказа',   type: 'text'   },
  'OrderConfirm.watermark':         { label: 'Водяной знак Cardinal',        type: 'toggle' },
  'ReviewReply.star1Reply':         { label: 'Ответ на отзыв (1 звезда)',    type: 'toggle' },
  'ReviewReply.star1ReplyText':     { label: 'Текст ответа на 1 звезду',     type: 'text'   },
  'ReviewReply.star2Reply':         { label: 'Ответ на отзыв (2 звезды)',    type: 'toggle' },
  'ReviewReply.star2ReplyText':     { label: 'Текст ответа на 2 звезды',     type: 'text'   },
  'ReviewReply.star3Reply':         { label: 'Ответ на отзыв (3 звезды)',    type: 'toggle' },
  'ReviewReply.star3ReplyText':     { label: 'Текст ответа на 3 звезды',     type: 'text'   },
  'ReviewReply.star4Reply':         { label: 'Ответ на отзыв (4 звезды)',    type: 'toggle' },
  'ReviewReply.star4ReplyText':     { label: 'Текст ответа на 4 звезды',     type: 'text'   },
  'ReviewReply.star5Reply':         { label: 'Ответ на отзыв (5 звёзд)',     type: 'toggle' },
  'ReviewReply.star5ReplyText':     { label: 'Текст ответа на 5 звёзд',      type: 'text'   },
};

let currentTabId = null;

// ── Главный рендер ──────────────────────────────────────────────────────────

export async function renderMore(container, initialSection = null) {
  container.innerHTML = `<div id="more-root"></div>`;
  const root = container.querySelector('#more-root');

  if (initialSection && SECTIONS.some(s => s.id === initialSection)) {
    await openSection(initialSection, root);
  } else {
    await renderIndexView(root);
  }
}

// ── Каталог категорий (Master View — Иерархия iOS 27) ─────────────────────────

async function renderIndexView(root) {
  currentTabId = null;
  tg.backButton.hide();

  // Загружаем общую статистику параллельно
  const [metaRes, healthRes] = await Promise.all([
    api.getMeta().catch(() => ({ version: '0.1.17' })),
    api.getHealth().catch(() => ({ status: 'error', telegram: 'unknown', funpay: 'unknown', uptime_sec: 0 })),
  ]);

  const version = metaRes.version || '0.1.17';
  const isHealthy = healthRes.status === 'ok';
  const tgStatus = healthRes.telegram === 'connected' ? 'Активен' : 'Отключён';
  const fpStatus = healthRes.funpay === 'connected' ? 'Активен' : 'Ожидание';
  const uptimeMinutes = Math.floor((healthRes.uptime_sec || 0) / 60);

  root.innerHTML = `
    <!-- 1. System Overview (Glance Card) -->
    <div class="more-glance-card">
      <div class="more-glance-top">
        <div class="more-glance-brand">
          <div class="more-glance-icon" aria-hidden="true">
            ${getIcon('cpu')}
          </div>
          <div>
            <div class="more-glance-title">FunPay Cardinal</div>
            <div class="more-glance-version">Carnaval v${escHtml(version)}</div>
          </div>
        </div>
        <div class="more-badge-live">
          <span class="more-pulse-dot"></span>
          ${isHealthy ? 'В сети' : 'Офлайн'}
        </div>
      </div>
      <div class="more-glance-grid">
        <div class="more-glance-item">
          <span class="more-glance-label">Telegram</span>
          <span class="more-glance-val">${escHtml(tgStatus)}</span>
        </div>
        <div class="more-glance-item">
          <span class="more-glance-label">FunPay</span>
          <span class="more-glance-val">${escHtml(fpStatus)}</span>
        </div>
        <div class="more-glance-item">
          <span class="more-glance-label">Аптайм</span>
          <span class="more-glance-val">${uptimeMinutes > 60 ? Math.floor(uptimeMinutes / 60) + ' ч.' : uptimeMinutes + ' мин.'}</span>
        </div>
      </div>
    </div>

    <!-- 2. Categories (Параметры и управление) -->
    <p class="more-group-label">Параметры и разделы</p>
    <div class="more-menu-card">
      ${SECTIONS.map(s => `
        <button class="more-menu-row press" data-section="${s.id}" type="button">
          <div class="more-menu-left">
            <div class="more-cat-icon-box ${s.iconCls}">
              ${getIcon(s.iconName)}
            </div>
            <div class="more-menu-texts">
              <div class="more-menu-name">${escHtml(s.label)}</div>
              <div class="more-menu-sub">${escHtml(s.desc)}</div>
            </div>
          </div>
          <div class="more-menu-right">
            <span class="more-menu-arrow">${getIcon('chevron')}</span>
          </div>
        </button>
      `).join('')}
    </div>

    <!-- 3. Settings (Быстрые настройки профиля и производительности) -->
    <p class="more-group-label">Профиль и графика</p>
    <div class="more-menu-card">
      <button class="more-menu-row press" id="open-profile-entry" type="button">
        <div class="more-menu-left">
          <div class="more-cat-icon-box" style="background:linear-gradient(135deg, var(--primary), var(--p));color:#fff">
            ${getIcon('profile')}
          </div>
          <div class="more-menu-texts">
            <div class="more-menu-name">Центр профиля и сессий</div>
            <div class="more-menu-sub">Учётные записи Telegram & FunPay, безопасность, метрики</div>
          </div>
        </div>
        <div class="more-menu-right">
          <span class="more-menu-arrow">${getIcon('chevron')}</span>
        </div>
      </button>
      <div style="padding: 12px 16px; border-top: 1px solid var(--outline)">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px">
          <span style="font-size:14px; font-weight:600; color:var(--on)">Профиль графики</span>
          <span style="font-size:12px; color:var(--muted)">Адаптивная отрисовка</span>
        </div>
        <div style="display:grid; grid-template-columns:repeat(3, 1fr); gap:8px" id="index-tier-selector">
          <button type="button" class="more-btn-sm press index-tier-btn" data-tier="SAVER" style="height:36px;font-size:12px">Эко</button>
          <button type="button" class="more-btn-sm press index-tier-btn" data-tier="BALANCED" style="height:36px;font-size:12px">Баланс</button>
          <button type="button" class="more-btn-sm press index-tier-btn" data-tier="HIGH" style="height:36px;font-size:12px">Ультра</button>
        </div>
      </div>
    </div>

    <!-- 4. Actions (Быстрые действия) -->
    <p class="more-group-label">Быстрые действия</p>
    <div class="more-menu-card" style="padding:14px; display:grid; grid-template-columns:repeat(2, 1fr); gap:10px">
      <button id="quick-backup-btn" class="more-btn-sm more-btn-primary press" style="height:42px; display:inline-flex; align-items:center; justify-content:center; gap:6px" type="button">
        ${getIcon('backup')} Бэкап
      </button>
      <button id="quick-restart-btn" class="more-btn-sm more-btn-warn press" style="height:42px; display:inline-flex; align-items:center; justify-content:center; gap:6px" type="button">
        ${getIcon('restart')} Перезапуск
      </button>
    </div>
  `;

  // Навигация по категориям
  root.querySelectorAll('.more-menu-row[data-section]').forEach(row => {
    row.addEventListener('click', () => {
      const sectionId = row.dataset.section;
      haptic('selection');
      openSection(sectionId, root);
    });
  });

  // Переход в профиль
  root.querySelector('#open-profile-entry')?.addEventListener('click', () => {
    haptic('selection');
    location.hash = 'profile';
  });

  // Быстрые кнопки бэкапа и рестарта
  root.querySelector('#quick-backup-btn')?.addEventListener('click', () => {
    haptic('selection');
    window.location.href = api.getBackupUrl();
  });

  root.querySelector('#quick-restart-btn')?.addEventListener('click', () => {
    haptic('impact', 'heavy');
    openConfirmSheet('Перезапустить Cardinal? Сервис перезагрузит процесс.', async () => {
      try {
        await api.restartCardinal(true);
        showToast('Перезапуск запущен…', 'success');
      } catch (ex) {
        showToast('Ошибка: ' + ex.message, 'error');
      }
    });
  });

  // Селектор графики
  const updateIndexTierButtons = () => {
    const active = getQualityTier();
    root.querySelectorAll('.index-tier-btn').forEach((btn) => {
      const isCur = btn.dataset.tier === active;
      btn.style.background = isCur ? 'var(--primary)' : 'var(--track)';
      btn.style.color = isCur ? 'var(--on-primary)' : 'var(--on)';
      btn.style.fontWeight = isCur ? '700' : '500';
    });
  };
  updateIndexTierButtons();

  root.querySelectorAll('.index-tier-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      haptic('impact', 'light');
      setQualityTier(btn.dataset.tier);
      updateIndexTierButtons();
      showToast(`Профиль графики: ${btn.textContent.trim()}`, 'success');
    });
  });
}

// ── Переход в секцию (Detail View) ──────────────────────────────────────────

async function openSection(sectionId, root) {
  if (sectionId === 'updates') {
    location.hash = 'updates';
    return;
  }
  if (sectionId === 'automation-lab') {
    location.hash = 'automation-lab';
    return;
  }
  if (sectionId === 'plugins-lab') {
    location.hash = 'plugins-lab';
    return;
  }

  currentTabId = sectionId;
  const sectionMeta = SECTIONS.find(s => s.id === sectionId) || SECTIONS[0];

  // Включаем нативную кнопку BackButton в Telegram
  tg.backButton.show(() => {
    haptic('selection');
    renderIndexView(root);
  });

  root.innerHTML = `
    <!-- Верхняя навигационная панель -->
    <div class="more-detail-nav">
      <button class="more-back-btn press" id="more-back" type="button" aria-label="Вернуться в меню">
        ${getIcon('chevron-left')} Назад
      </button>
      <h2 class="more-detail-title">
        <span>${getIcon(sectionMeta.iconName)}</span> ${escHtml(sectionMeta.label)}
      </h2>
      <div style="width:50px"></div>
    </div>

    <!-- Полоса быстрого переключения разделов -->
    <div class="more-pills-scroll" role="tablist" aria-label="Разделы настроек">
      ${SECTIONS.map(s => `
        <button class="more-pill-btn press${s.id === sectionId ? ' active' : ''}" data-pill="${s.id}" type="button" role="tab" aria-selected="${s.id === sectionId}">
          <span>${getIcon(s.iconName)}</span> ${escHtml(s.label)}
        </button>
      `).join('')}
    </div>

    <!-- Контейнер контента выбранной секции -->
    <div id="more-section-body">
      <div class="skel" style="height:140px;border-radius:20px;margin-top:8px"></div>
    </div>
  `;

  // Кнопка возврата в каталог
  root.querySelector('#more-back')?.addEventListener('click', () => {
    haptic('selection');
    renderIndexView(root);
  });

  // Быстрое переключение по пиллам
  root.querySelectorAll('.more-pill-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const targetId = btn.dataset.pill;
      if (targetId === currentTabId) return;
      haptic('selection');
      openSection(targetId, root);
    });
  });

  // Автоскролл полосы к активному пиллу
  const activePill = root.querySelector('.more-pill-btn.active');
  if (activePill) {
    activePill.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
  }

  const bodyEl = root.querySelector('#more-section-body');

  try {
    switch (sectionId) {
      case 'notifications': await renderNotifications(bodyEl); break;
      case 'greetings':     await renderGreetings(bodyEl);     break;
      case 'blacklist':     await renderBlacklist(bodyEl);     break;
      case 'plugins':       await renderPlugins(bodyEl);       break;
      case 'security':      await renderSecurity(bodyEl);      break;
      case 'system':        await renderSystem(bodyEl);        break;
      default:              await renderNotifications(bodyEl); break;
    }
  } catch (err) {
    console.error(`[More] Error rendering section ${sectionId}:`, err);
    bodyEl.innerHTML = `
      <div class="more-content-card">
        <div class="more-empty-state">
          <p style="color:var(--err);font-weight:600;margin:0 0 6px">Не удалось загрузить данные</p>
          <p style="font-size:13px;margin:0 0 16px">${escHtml(err.message || 'Ошибка сети')}</p>
          <button class="more-btn-sm more-btn-primary press" id="more-retry-btn" type="button">Повторить попытку</button>
        </div>
      </div>
    `;
    bodyEl.querySelector('#more-retry-btn')?.addEventListener('click', () => {
      openSection(sectionId, root);
    });
  }
}

// ── 1. Уведомления ─────────────────────────────────────────────────────────

async function renderNotifications(body) {
  const data = await api.getNotifications();
  body.innerHTML = `
    <div class="more-content-card">
      <div class="more-card-title">Фильтры и доставка уведомлений</div>
      <div id="notif-rows"></div>
    </div>
  `;
  const container = body.querySelector('#notif-rows');

  for (const [dotKey, info] of Object.entries(data)) {
    const [section, key] = dotKey.split('.');
    const row = document.createElement('div');
    row.className = 'more-toggle-row';
    row.innerHTML = `
      <span class="more-toggle-label">${escHtml(info.label)}</span>
      <label class="sw">
        <input type="checkbox" ${info.enabled ? 'checked' : ''} aria-label="${escHtml(info.label)}">
        <span class="track"></span>
      </label>
    `;

    const cb = row.querySelector('input');
    cb.addEventListener('change', async () => {
      haptic('impact', 'light');
      try {
        await api.updateNotification(section, key, cb.checked);
        showToast(cb.checked ? 'Включено' : 'Выключено', 'success');
      } catch (e) {
        cb.checked = !cb.checked;
        showToast('Ошибка сохранения: ' + e.message, 'error');
      }
    });

    container.appendChild(row);
  }
}

// ── 2. Сообщения (Greetings / OrderConfirm / ReviewReply) ───────────────────

async function renderGreetings(body) {
  const data = await api.getGreetings();
  body.innerHTML = '';

  let lastGroup = '';
  let card = null;

  for (const [dotKey, info] of Object.entries(data)) {
    const [section, key] = dotKey.split('.');
    const meta = GREETING_LABELS[dotKey] || { label: key, type: info.type };

    if (section !== lastGroup) {
      lastGroup = section;
      const labels = {
        Greetings: 'Приветствие в новых чатах',
        OrderConfirm: 'Подтверждение заказа',
        ReviewReply: 'Автоответы на отзывы',
      };

      const groupWrap = document.createElement('div');
      groupWrap.className = 'more-content-card';
      groupWrap.innerHTML = `
        <div class="more-card-title">${escHtml(labels[section] || section)}</div>
        <div class="more-group-rows"></div>
      `;
      body.appendChild(groupWrap);
      card = groupWrap.querySelector('.more-group-rows');
    }

    if (meta.type === 'toggle') {
      const row = document.createElement('div');
      row.className = 'more-toggle-row';
      row.innerHTML = `
        <span class="more-toggle-label">${escHtml(meta.label)}</span>
        <label class="sw">
          <input type="checkbox" ${info.value ? 'checked' : ''} aria-label="${escHtml(meta.label)}">
          <span class="track"></span>
        </label>
      `;

      const cb = row.querySelector('input');
      cb.addEventListener('change', async () => {
        haptic('impact', 'light');
        try {
          await api.updateGreeting(section, key, cb.checked ? '1' : '0');
          showToast('Параметр сохранён', 'success');
        } catch (e) {
          cb.checked = !cb.checked;
          showToast('Ошибка: ' + e.message, 'error');
        }
      });
      card?.appendChild(row);
    } else {
      const row = document.createElement('div');
      row.className = 'more-input-row';
      row.innerHTML = `
        <div class="more-input-label">${escHtml(meta.label)}</div>
        <div class="more-input-box">
          <input class="more-field" type="text" value="${escHtml(String(info.value || ''))}" placeholder="${escHtml(meta.label)}">
          <button class="more-btn-save press" type="button">Сохранить</button>
        </div>
      `;

      const inp = row.querySelector('input');
      const btn = row.querySelector('button');
      btn.addEventListener('click', async () => {
        haptic('impact', 'medium');
        try {
          await api.updateGreeting(section, key, inp.value);
          showToast('Сохранено', 'success');
        } catch (e) {
          showToast('Ошибка: ' + e.message, 'error');
        }
      });
      card?.appendChild(row);
    }
  }
}

// ── 3. Чёрный список ───────────────────────────────────────────────────────

async function renderBlacklist(body) {
  const { blacklist } = await api.getBlacklist();

  body.innerHTML = `
    <div class="more-content-card">
      <div class="more-card-title">Добавить в чёрный список</div>
      <div class="more-input-box" style="margin-bottom:8px">
        <input id="bl-inp" class="more-field" type="text" placeholder="@username покупателя">
        <button id="bl-add" class="more-btn-save press" style="display:inline-flex;align-items:center;gap:4px" type="button">
          ${getIcon('plus')} Добавить
        </button>
      </div>
    </div>

    <div class="more-content-card">
      <div class="more-card-title" style="display:flex;justify-content:space-between;align-items:center">
        <span>Заблокированные пользователи</span>
        <span id="bl-count" style="font-weight:600;color:var(--primary)">${blacklist.length}</span>
      </div>
      <div id="bl-list"></div>
    </div>
  `;

  const inp = body.querySelector('#bl-inp');
  const addBtn = body.querySelector('#bl-add');
  const listEl = body.querySelector('#bl-list');
  const countEl = body.querySelector('#bl-count');

  let currentList = [...blacklist];

  const renderList = (bl) => {
    countEl.textContent = String(bl.length);
    if (!bl.length) {
      listEl.innerHTML = `<div class="more-empty-state">Чёрный список пуст</div>`;
      return;
    }
    listEl.innerHTML = bl.map(u => `
      <div class="more-item-row" data-user="${escHtml(u)}">
        <div style="display:flex;align-items:center;gap:10px">
          <span style="color:var(--err);display:inline-flex;align-items:center">${getIcon('ban')}</span>
          <span class="more-item-name">@${escHtml(u)}</span>
        </div>
        <button class="more-btn-sm more-btn-danger press bl-del" data-user="${escHtml(u)}" style="display:inline-flex;align-items:center;gap:4px" type="button">
          ${getIcon('trash')} Удалить
        </button>
      </div>
    `).join('');
  };

  renderList(currentList);

  addBtn.addEventListener('click', async () => {
    const user = inp.value.trim().replace(/^@/, '');
    if (!user) {
      showToast('Введите имя пользователя', 'error');
      return;
    }
    haptic('impact', 'medium');
    try {
      await api.addToBlacklist(user);
      if (!currentList.includes(user)) {
        currentList.push(user);
      }
      renderList(currentList);
      inp.value = '';
      showToast(`@${user} добавлен в ЧС`, 'success');
    } catch (e) {
      showToast('Ошибка: ' + e.message, 'error');
    }
  });

  listEl.addEventListener('click', async (e) => {
    const btn = e.target.closest('.bl-del');
    if (!btn) return;
    const user = btn.dataset.user;
    haptic('impact', 'medium');

    openConfirmSheet(
      `Удалить @${user} из чёрного списка?`,
      async () => {
        try {
          await api.removeFromBlacklist(user);
          currentList = currentList.filter(u => u !== user);
          renderList(currentList);
          showToast(`@${user} удалён из ЧС`, 'success');
        } catch (ex) {
          showToast('Ошибка: ' + ex.message, 'error');
        }
      }
    );
  });
}

// ── 4. Плагины ─────────────────────────────────────────────────────────────

async function renderPlugins(body) {
  const { plugins } = await api.getPlugins();

  body.innerHTML = `
    <div class="more-content-card" style="display:flex;align-items:center;justify-content:space-between">
      <div>
        <div class="more-item-name">Дополнения Cardinal</div>
        <div class="more-item-sub">Загружайте проверенные Python-скрипты</div>
      </div>
      <label class="more-btn-sm more-btn-primary press" style="cursor:pointer;height:38px;padding:0 16px;border-radius:var(--rf);display:inline-flex;align-items:center;gap:6px">
        ${getIcon('plus')} Загрузить .py
        <input type="file" accept=".py" id="pl-file" style="display:none">
      </label>
    </div>

    <div class="more-content-card">
      <div class="more-card-title" style="display:flex;justify-content:space-between;align-items:center">
        <span>Установленные плагины</span>
        <span id="pl-count" style="font-weight:600;color:var(--primary)">${plugins.length}</span>
      </div>
      <div id="pl-list"></div>
    </div>
  `;

  const fileInp = body.querySelector('#pl-file');
  const listEl = body.querySelector('#pl-list');
  const countEl = body.querySelector('#pl-count');

  let currentPlugins = [...plugins];

  const renderList = (pls) => {
    countEl.textContent = String(pls.length);
    if (!pls.length) {
      listEl.innerHTML = `<div class="more-empty-state">Плагины не установлены</div>`;
      return;
    }
    listEl.innerHTML = pls.map(pl => `
      <div class="more-item-row" data-uuid="${escHtml(pl.uuid)}" style="flex-direction:column;align-items:stretch;gap:8px">
        <div style="display:flex;align-items:center;justify-content:space-between">
          <div>
            <span class="more-item-name">${escHtml(pl.name)}</span>
            <span style="font-size:12px;opacity:.5;margin-left:6px">v${escHtml(pl.version || '1.0')}</span>
            ${pl.credits ? `<div class="more-item-sub">Автор: ${escHtml(pl.credits)}</div>` : ''}
          </div>
          <div class="more-actions-group">
            <button class="more-btn-sm more-btn-danger press pl-del" data-uuid="${escHtml(pl.uuid)}" data-name="${escHtml(pl.name)}" style="display:inline-flex;align-items:center;gap:4px" type="button">
              ${getIcon('trash')} Удалить
            </button>
            <label class="sw">
              <input type="checkbox" class="pl-toggle" data-uuid="${escHtml(pl.uuid)}" ${pl.enabled ? 'checked' : ''} aria-label="Включить плагин ${escHtml(pl.name)}">
              <span class="track"></span>
            </label>
          </div>
        </div>
        ${pl.description ? `<div style="font-size:13px;color:var(--muted);line-height:1.4">${escHtml(pl.description)}</div>` : ''}
      </div>
    `).join('');
  };

  renderList(currentPlugins);

  // Переключение состояния плагина
  listEl.addEventListener('change', async (e) => {
    const cb = e.target.closest('.pl-toggle');
    if (!cb) return;
    haptic('impact', 'light');
    try {
      await api.togglePlugin(cb.dataset.uuid);
      showToast(cb.checked ? 'Плагин активирован' : 'Плагин деактивирован', 'success');
    } catch (ex) {
      cb.checked = !cb.checked;
      showToast('Ошибка: ' + ex.message, 'error');
    }
  });

  // Удаление плагина
  listEl.addEventListener('click', async (e) => {
    const delBtn = e.target.closest('.pl-del');
    if (!delBtn) return;
    const uuid = delBtn.dataset.uuid;
    const name = delBtn.dataset.name;
    haptic('impact', 'medium');

    openConfirmSheet(`Удалить плагин «${name}» с сервера?`, async () => {
      try {
        await api.deletePlugin(uuid, true);
        currentPlugins = currentPlugins.filter(p => p.uuid !== uuid);
        renderList(currentPlugins);
        showToast('Плагин удалён', 'success');
      } catch (ex) {
        showToast('Ошибка: ' + ex.message, 'error');
      }
    });
  });

  // Загрузка нового плагина с проверкой
  fileInp.addEventListener('change', async () => {
    const file = fileInp.files?.[0];
    if (!file) return;
    if (!file.name.endsWith('.py')) {
      showToast('Разрешены только .py файлы', 'error');
      return;
    }
    haptic('impact', 'medium');

    openConfirmSheet({
      title: 'Загрузка плагина',
      message: `
        <div style="background:var(--err-c);color:var(--on-err-c);padding:12px;border-radius:12px;font-size:13px;margin-bottom:12px;line-height:1.4;display:flex;align-items:flex-start;gap:8px">
          <span style="flex-shrink:0">${getIcon('alert')}</span>
          <div>
            <b>ВНИМАНИЕ</b>: Плагины исполняются сервером Python!<br>
            Загружайте только файлы из проверенных источников.
          </div>
        </div>
        Загрузить плагин <b>${escHtml(file.name)}</b>?
      `,
      confirmText: 'Загрузить',
      danger: true,
      onConfirm: async () => {
        try {
          await api.uploadPlugin(file, true);
          showToast('Плагин успешно загружен', 'success');
          const fresh = await api.getPlugins();
          currentPlugins = fresh.plugins || [];
          renderList(currentPlugins);
        } catch (ex) {
          showToast('Ошибка загрузки: ' + ex.message, 'error');
        }
      },
    });
    fileInp.value = '';
  });
}

// ── 5. Безопасность ─────────────────────────────────────────────────────────

async function renderSecurity(body) {
  const [accInfo, proxyInfo, { users: authUsers }, sessionsRes, auditRes, setupStatus] = await Promise.all([
    api.getAccountInfo().catch(() => ({})),
    api.getProxy().catch(() => ({ enabled: false, proxy_list: [] })),
    api.getAuthorizedUsers().catch(() => ({ users: [] })),
    api.getActiveSessions().catch(() => ({ sessions: [] })),
    api.getAuditLogs(10).catch(() => ({ logs: [] })),
    api.getSetupStatus().catch(() => ({})),
  ]);

  const sessions = sessionsRes.sessions || [];
  const auditLogs = auditRes.logs || [];
  const gkMasked = accInfo.golden_key_masked || (accInfo.golden_key_configured ? '••••••••••••••••' : 'Не задан');
  const hasPassword = Boolean(setupStatus?.has_password);
  const hasProxy = Boolean(setupStatus?.has_proxy || proxyInfo.enabled);

  body.innerHTML = `
    <!-- Общая сводка безопасности -->
    <div class="more-content-card">
      <div class="more-card-title">Сводка защиты</div>
      <div style="display:grid;grid-template-columns:repeat(2, 1fr);gap:10px">
        <div class="more-item-row" style="border:none;padding:4px 0">
          <span class="more-item-sub">Пароль панели:</span>
          <span style="font-weight:600;color:${hasPassword ? 'var(--ok)' : 'var(--err)'}">${hasPassword ? 'Защищён' : 'Не задан'}</span>
        </div>
        <div class="more-item-row" style="border:none;padding:4px 0">
          <span class="more-item-sub">Golden Key:</span>
          <span style="font-weight:600;color:${accInfo.golden_key_configured ? 'var(--ok)' : 'var(--warn)'}">${accInfo.golden_key_configured ? 'Настроен' : 'Не задан'}</span>
        </div>
        <div class="more-item-row" style="border:none;padding:4px 0">
          <span class="more-item-sub">Прокси:</span>
          <span style="font-weight:600;color:${hasProxy ? 'var(--ok)' : 'var(--muted)'}">${hasProxy ? 'Активен' : 'Отключён'}</span>
        </div>
        <div class="more-item-row" style="border:none;padding:4px 0">
          <span class="more-item-sub">Активные сессии:</span>
          <span style="font-weight:600;color:var(--primary)">${sessions.length}</span>
        </div>
      </div>
    </div>

    <!-- FunPay аккаунт и Golden Key -->
    <div class="more-content-card">
      <div class="more-card-title">Аккаунт FunPay</div>
      <div class="more-item-name" style="margin-bottom:4px;display:flex;align-items:center;gap:6px">
        ${getIcon('funpay')} ${escHtml(accInfo.username || 'Не подключён')} ${accInfo.id ? `(ID: ${accInfo.id})` : ''}
      </div>
      <div class="more-item-sub" style="margin-bottom:14px">Golden Key: <code>${escHtml(gkMasked)}</code></div>
      <div style="display:flex;gap:10px;flex-wrap:wrap">
        <button id="gk-btn" class="more-btn-sm more-btn-warn press" style="height:38px;padding:0 14px;display:inline-flex;align-items:center;gap:6px" type="button">
          ${getIcon('key')} Сменить Golden Key
        </button>
        ${accInfo.golden_key_configured ? `
          <button id="gk-del-btn" class="more-btn-sm more-btn-danger press" style="height:38px;padding:0 14px;display:inline-flex;align-items:center;gap:6px" type="button">
            ${getIcon('trash')} Удалить ключ
          </button>
        ` : ''}
      </div>
    </div>

    <!-- Пароль панели управления -->
    <div class="more-content-card">
      <div class="more-card-title">Пароль доступа к панели</div>
      <p class="more-item-sub" style="margin:0 0 14px;line-height:1.4">
        Защищает настройки и конфиденциальные данные авторизации по алгоритму Argon2id.
      </p>
      <button id="change-pwd-btn" class="more-btn-sm more-btn-primary press" style="height:42px;width:100%;font-size:14px;display:inline-flex;align-items:center;justify-content:center;gap:8px" type="button">
        ${getIcon('security')} Сменить мастер-пароль панели
      </button>
    </div>

    <!-- Активные сессии -->
    <div class="more-content-card">
      <div class="more-card-title" style="display:flex;justify-content:space-between">
        <span>Активные сессии</span>
        <span>${sessions.length}</span>
      </div>
      <div id="sessions-list" style="margin-bottom:12px">
        ${sessions.length ? sessions.map(s => `
          <div class="more-item-row" style="flex-direction:column;align-items:stretch;gap:4px">
            <div style="display:flex;justify-content:space-between;font-size:13px">
              <b>IP: ${escHtml(s.ip || '—')}</b>
              <span class="more-item-sub">${escHtml(s.last_active || '')}</span>
            </div>
            <div class="more-item-sub" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
              ${escHtml(s.user_agent || 'Telegram Mini App')}
            </div>
          </div>
        `).join('') : '<div class="more-empty-state">Нет других сессий</div>'}
      </div>
      <button id="logout-all-btn" class="more-btn-sm more-btn-danger press" style="height:38px;width:100%;display:inline-flex;align-items:center;justify-content:center;gap:8px" type="button">
        ${getIcon('logout')} Завершить все остальные сессии
      </button>
    </div>

    <!-- Прокси -->
    <div class="more-content-card">
      <div class="more-card-title">Прокси FunPay</div>
      <div class="more-toggle-row" style="padding-top:0">
        <span class="more-toggle-label">Использовать прокси</span>
        <label class="sw">
          <input type="checkbox" id="proxy-en" ${proxyInfo.enabled ? 'checked' : ''} aria-label="Включить прокси">
          <span class="track"></span>
        </label>
      </div>
      ${proxyInfo.current_proxy ? `
        <div class="more-item-sub" style="margin:8px 0;word-break:break-all">Активный: <code>${escHtml(proxyInfo.current_proxy)}</code></div>
      ` : ''}
      <div class="more-input-box" style="margin:10px 0 8px">
        <input id="proxy-inp" class="more-field" type="text" placeholder="http://user:pass@ip:port">
        <button id="proxy-add" class="more-btn-save press" style="display:inline-flex;align-items:center;gap:4px" type="button">
          ${getIcon('plus')} Добавить
        </button>
      </div>
      <div id="proxy-list"></div>
    </div>

    <!-- Авторизованные пользователи Telegram -->
    <div class="more-content-card">
      <div class="more-card-title" style="display:flex;justify-content:space-between;align-items:center">
        <span>Администраторы Telegram бота</span>
        <button id="au-add-btn" class="more-btn-sm more-btn-primary press" style="height:32px;padding:0 12px;font-size:12px;display:inline-flex;align-items:center;gap:6px" type="button">
          ${getIcon('plus')} Добавить пользователя
        </button>
      </div>
      <p class="more-item-sub" style="margin:0 0 10px;line-height:1.4">
        Доступ к панели предоставляется через Telegram пароль бота.
      </p>
      <div id="au-list"></div>
    </div>

    <!-- Журнал безопасности -->
    <div class="more-content-card">
      <div class="more-card-title">Журнал безопасности</div>
      <div id="audit-list">
        ${auditLogs.length ? auditLogs.map(l => `
          <div class="more-item-row">
            <div>
              <div class="more-item-name" style="color:var(--primary);font-size:13px">${escHtml(l.action)}</div>
              ${l.details ? `<div class="more-item-sub">${escHtml(l.details)}</div>` : ''}
            </div>
            <div class="more-item-sub" style="font-size:11px">${escHtml(l.created_at || '')}</div>
          </div>
        `).join('') : '<div class="more-empty-state">Журнал аудита пуст</div>'}
      </div>
    </div>
  `;

  // Смена Golden Key
  body.querySelector('#gk-btn')?.addEventListener('click', () => {
    haptic('impact', 'medium');
    openSheet('Смена Golden Key', `
      <div style="padding:16px 0">
        <p style="font-size:13px;color:var(--muted);margin-bottom:12px">
          Введите 32-значный golden_key из cookies FunPay.
        </p>
        <input id="gk-inp" type="text" class="more-field" placeholder="32-значный ключ" style="width:100%;margin-bottom:14px">
        <button class="btn press" id="gk-submit-btn" style="width:100%;background:var(--primary);color:var(--on-primary);height:44px">
          Сохранить ключ
        </button>
      </div>
    `);

    document.getElementById('gk-submit-btn')?.addEventListener('click', async () => {
      const newKey = document.querySelector('#gk-inp')?.value?.trim();
      if (!newKey) { showToast('Введите ключ', 'error'); return; }
      closeSheet();
      openConfirmSheet(
        'Сменить Golden Key? Бот переподключится к FunPay без перезапуска.',
        async () => {
          try {
            await api.changeGoldenKey(newKey, true);
            showToast('Golden Key обновлён', 'success');
            renderSecurity(body);
          } catch (ex) {
            showToast('Ошибка: ' + ex.message, 'error');
          }
        }
      );
    });
  });

  // Удаление Golden Key
  body.querySelector('#gk-del-btn')?.addEventListener('click', () => {
    haptic('impact', 'medium');
    openConfirmSheet(
      'Удалить сохранённый Golden Key? Работа с заказами будет приостановлена.',
      async () => {
        try {
          await api.deleteGoldenKey(true);
          showToast('Golden Key удалён', 'success');
          renderSecurity(body);
        } catch (ex) {
          showToast('Ошибка: ' + ex.message, 'error');
        }
      }
    );
  });

  // Смена пароля панели
  body.querySelector('#change-pwd-btn')?.addEventListener('click', () => {
    haptic('impact', 'medium');
    openSheet('Смена пароля панели', `
      <div style="display:flex;flex-direction:column;gap:10px;padding:16px 0">
        <input id="pwd-old" type="password" class="more-field" placeholder="Текущий пароль">
        <input id="pwd-new" type="password" class="more-field" placeholder="Новый пароль (мин. 6 симв.)">
        <input id="pwd-conf" type="password" class="more-field" placeholder="Повторите новый пароль">
        <button class="btn press" id="pwd-submit-btn" style="margin-top:6px;width:100%;background:var(--primary);color:var(--on-primary);height:44px">
          Сохранить пароль
        </button>
      </div>
    `);

    document.getElementById('pwd-submit-btn')?.addEventListener('click', async () => {
      const oldP = document.getElementById('pwd-old')?.value || '';
      const newP = document.getElementById('pwd-new')?.value || '';
      const confP = document.getElementById('pwd-conf')?.value || '';

      if (!oldP) { showToast('Введите текущий пароль', 'error'); return; }
      if (newP.length < 6) { showToast('Пароль должен быть от 6 символов', 'error'); return; }
      if (newP !== confP) { showToast('Пароли не совпадают', 'error'); return; }

      try {
        await api.changePassword(oldP, newP);
        closeSheet();
        showToast('Пароль панели успешно изменён', 'success');
        renderSecurity(body);
      } catch (ex) {
        showToast('Ошибка: ' + ex.message, 'error');
      }
    });
  });

  // Завершить все остальные сессии
  body.querySelector('#logout-all-btn')?.addEventListener('click', () => {
    haptic('impact', 'heavy');
    openConfirmSheet('Завершить все активные сессии на других устройствах?', async () => {
      try {
        const res = await api.logoutAll();
        showToast(`Отозвано сессий: ${res.revoked_count ?? 0}`, 'success');
        renderSecurity(body);
      } catch (ex) {
        showToast('Ошибка: ' + ex.message, 'error');
      }
    });
  });

  // Прокси: переключатель
  body.querySelector('#proxy-en')?.addEventListener('change', async (e) => {
    haptic('impact', 'light');
    try {
      await api.setProxyEnabled(e.target.checked);
      showToast(e.target.checked ? 'Прокси включён' : 'Прокси выключен', 'success');
    } catch (ex) {
      e.target.checked = !e.target.checked;
      showToast('Ошибка: ' + ex.message, 'error');
    }
  });

  // Список прокси
  let proxyList = [...proxyInfo.proxy_list];
  const proxyListEl = body.querySelector('#proxy-list');

  const renderProxyList = (list) => {
    proxyListEl.innerHTML = list.length ? list.map(p => `
      <div class="more-item-row" data-pid="${p.id}">
        <span class="more-item-name" style="flex:1;font-size:13px;overflow:hidden;text-overflow:ellipsis">${escHtml(p.proxy)}</span>
        <div class="more-actions-group">
          <button class="more-btn-sm more-btn-primary press proxy-act" data-pid="${p.id}" type="button">Выбрать</button>
          <button class="more-btn-sm more-btn-danger press proxy-del" data-pid="${p.id}" style="display:inline-flex;align-items:center;justify-content:center" type="button">${getIcon('close')}</button>
        </div>
      </div>
    `).join('') : '<div class="more-empty-state" style="padding:10px 0">Список прокси пуст</div>';
  };

  renderProxyList(proxyList);

  body.querySelector('#proxy-add')?.addEventListener('click', async () => {
    const proxy = body.querySelector('#proxy-inp')?.value.trim();
    if (!proxy) { showToast('Введите адрес прокси', 'error'); return; }
    haptic('impact', 'medium');
    try {
      await api.addProxy(proxy);
      const fresh = await api.getProxy();
      proxyList = fresh.proxy_list || [];
      renderProxyList(proxyList);
      body.querySelector('#proxy-inp').value = '';
      showToast('Прокси добавлен', 'success');
    } catch (ex) {
      showToast('Ошибка: ' + ex.message, 'error');
    }
  });

  proxyListEl.addEventListener('click', async (e) => {
    if (e.target.closest('.proxy-act')) {
      const pid = Number(e.target.closest('.proxy-act').dataset.pid);
      haptic('impact', 'light');
      try {
        await api.activateProxy(pid);
        showToast('Прокси активирован', 'success');
      } catch (ex) {
        showToast('Ошибка: ' + ex.message, 'error');
      }
    } else if (e.target.closest('.proxy-del')) {
      const pid = Number(e.target.closest('.proxy-del').dataset.pid);
      haptic('impact', 'medium');
      try {
        await api.deleteProxy(pid);
        proxyList = proxyList.filter(p => p.id !== pid);
        renderProxyList(proxyList);
        showToast('Прокси удалён', 'success');
      } catch (ex) {
        showToast('Ошибка: ' + ex.message, 'error');
      }
    }
  });

  // Авторизованные пользователи
  let auList = [...authUsers];
  const auListEl = body.querySelector('#au-list');

  const renderAuList = (list) => {
    auListEl.innerHTML = list.length ? list.map(item => {
      const uid = item && typeof item === 'object' && 'user_id' in item ? item.user_id : item;
      const meta = item && typeof item === 'object' && item.data ? item.data : {};
      const roleStr = meta.role ? ` (${meta.role})` : '';
      const commentStr = meta.comment ? ` — ${meta.comment}` : '';
      return `
        <div class="more-item-row" style="display:flex;justify-content:space-between;align-items:center;">
          <div>
            <span class="more-item-name">ID: ${escHtml(String(uid))}${escHtml(roleStr)}</span>
            ${commentStr ? `<div class="more-item-sub">${escHtml(commentStr)}</div>` : ''}
          </div>
          <button class="more-btn-sm more-btn-danger press au-del" data-uid="${escHtml(String(uid))}" style="display:inline-flex;align-items:center;gap:4px" type="button">
            ${getIcon('trash')} Отозвать
          </button>
        </div>
      `;
    }).join('') : '<div class="more-empty-state" style="padding:10px 0">Нет авторизованных администраторов</div>';
  };

  renderAuList(auList);

  body.querySelector('#au-add-btn')?.addEventListener('click', () => {
    haptic('impact', 'medium');
    openSheet('Добавить пользователя', `
      <div style="display:flex;flex-direction:column;gap:12px;padding:16px 0">
        <p style="font-size:13px;color:var(--muted);margin:0;line-height:1.4">
          Укажите Telegram ID пользователя для предоставления доступа к панели.
        </p>
        <div>
          <label style="font-size:12px;color:var(--muted);display:block;margin-bottom:4px">Telegram User ID *</label>
          <input id="au-inp-uid" type="number" class="more-field" placeholder="Например: 123456789" style="width:100%">
        </div>
        <div>
          <label style="font-size:12px;color:var(--muted);display:block;margin-bottom:4px">Роль (необязательно)</label>
          <input id="au-inp-role" type="text" class="more-field" placeholder="admin" style="width:100%">
        </div>
        <div>
          <label style="font-size:12px;color:var(--muted);display:block;margin-bottom:4px">Примечание (необязательно)</label>
          <input id="au-inp-comment" type="text" class="more-field" placeholder="Менеджер поддержки" style="width:100%">
        </div>
        <button class="btn press" id="au-submit-btn" style="margin-top:6px;width:100%;background:var(--primary);color:var(--on-primary);height:44px;font-size:14px;font-weight:600">
          Добавить пользователя
        </button>
      </div>
    `);

    document.getElementById('au-submit-btn')?.addEventListener('click', async () => {
      const uidVal = document.getElementById('au-inp-uid')?.value?.trim();
      const roleVal = document.getElementById('au-inp-role')?.value?.trim() || '';
      const commentVal = document.getElementById('au-inp-comment')?.value?.trim() || '';

      if (!uidVal || isNaN(Number(uidVal))) {
        showToast('Введите корректный Telegram ID', 'error');
        return;
      }

      const uid = Number(uidVal);
      try {
        await api.addAuthorizedUser(uid, roleVal, commentVal);
        showToast('Пользователь добавлен', 'success');
        closeSheet();
        const fresh = await api.getAuthorizedUsers().catch(() => ({ users: [] }));
        auList = fresh.users || [];
        renderAuList(auList);
      } catch (ex) {
        showToast('Ошибка: ' + (ex.message || ex), 'error');
      }
    });
  });

  auListEl.addEventListener('click', async (e) => {
    const btn = e.target.closest('.au-del');
    if (!btn) return;
    const uid = Number(btn.dataset.uid);
    haptic('impact', 'medium');

    openConfirmSheet(
      `Отозвать доступ у Telegram ID ${uid}?`,
      async () => {
        try {
          await api.removeAuthorizedUser(uid, true);
          auList = auList.filter(item => {
            const itemUid = item && typeof item === 'object' && 'user_id' in item ? item.user_id : item;
            return itemUid !== uid;
          });
          renderAuList(auList);
          showToast('Доступ отозван', 'success');
        } catch (ex) {
          showToast('Ошибка: ' + ex.message, 'error');
        }
      }
    );
  });
}

// ── 6. Система ─────────────────────────────────────────────────────────────

async function renderSystem(body) {
  body.innerHTML = `
    <!-- Действия и бэкап -->
    <div class="more-content-card">
      <div class="more-card-title">Резервное копирование и управление</div>
      <div style="display:grid;grid-template-columns:repeat(2, 1fr);gap:10px;margin-bottom:12px">
        <a id="backup-btn" class="more-btn-sm more-btn-primary press" href="${api.getBackupUrl()}" download style="height:42px;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;gap:6px">
          ${getIcon('backup')} Скачать бэкап
        </a>
        <label class="more-btn-sm more-btn-secondary press" style="cursor:pointer;height:42px;display:inline-flex;align-items:center;justify-content:center;gap:6px">
          ${getIcon('restore')} Восстановить
          <input type="file" accept=".zip" id="restore-file" style="display:none">
        </label>
      </div>
      <div style="display:grid;grid-template-columns:repeat(2, 1fr);gap:10px">
        <button id="restart-btn" class="more-btn-sm more-btn-warn press" style="height:42px;display:inline-flex;align-items:center;justify-content:center;gap:6px" type="button">
          ${getIcon('restart')} Перезапуск
        </button>
        <button id="stop-btn" class="more-btn-sm more-btn-danger press" style="height:42px;display:inline-flex;align-items:center;justify-content:center;gap:6px" type="button">
          ${getIcon('shutdown')} Выключить
        </button>
      </div>
    </div>

    <!-- Графика и производительность -->
    <div class="more-content-card">
      <div class="more-card-title">Производительность и графика</div>
      <div class="more-item-sub" style="margin-bottom:12px">Адаптивный профиль рендеринга для плавной работы и экономии аккумулятора</div>
      <div style="display:grid;grid-template-columns:repeat(3, 1fr);gap:8px" id="tier-selector">
        <button type="button" class="more-btn-sm press tier-btn" data-tier="SAVER" style="height:40px;font-size:12px">
          Эко
        </button>
        <button type="button" class="more-btn-sm press tier-btn" data-tier="BALANCED" style="height:40px;font-size:12px">
          Баланс
        </button>
        <button type="button" class="more-btn-sm press tier-btn" data-tier="HIGH" style="height:40px;font-size:12px">
          Ультра
        </button>
      </div>
    </div>

    <!-- Логи Cardinal -->
    <div class="more-content-card">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
        <div class="more-card-title" style="margin:0">Журнал Cardinal</div>
        <div style="display:flex;gap:8px">
          <button id="logs-clear" class="more-btn-sm more-btn-danger press" style="display:inline-flex;align-items:center;gap:4px" type="button">
            ${getIcon('trash')} Очистить
          </button>
          <button id="logs-refresh" class="more-btn-sm more-btn-secondary press" style="display:inline-flex;align-items:center;gap:4px" type="button">
            ${getIcon('refresh')} Обновить
          </button>
        </div>
      </div>
      <div class="more-logs-console" id="logs-box">
        <span style="opacity:.4">Загрузка логов…</span>
      </div>
    </div>
  `;

  // Quality Tier переключатель
  const updateTierButtons = () => {
    const active = getQualityTier();
    body.querySelectorAll('.tier-btn').forEach((btn) => {
      const isCur = btn.dataset.tier === active;
      btn.style.background = isCur ? 'var(--primary)' : 'var(--track)';
      btn.style.color = isCur ? 'var(--on-primary)' : 'var(--on)';
      btn.style.fontWeight = isCur ? '700' : '500';
    });
  };
  updateTierButtons();

  body.querySelectorAll('.tier-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      haptic('impact', 'light');
      setQualityTier(btn.dataset.tier);
      updateTierButtons();
      showToast(`Профиль графики: ${btn.textContent.trim()}`, 'success');
    });
  });

  // Рестарт Cardinal
  body.querySelector('#restart-btn')?.addEventListener('click', () => {
    haptic('impact', 'heavy');
    openConfirmSheet('Перезапустить Cardinal? Сервис перезагрузит процесс.', async () => {
      try {
        await api.restartCardinal(true);
        showToast('Перезапуск запущен…', 'success');
      } catch (ex) {
        showToast('Ошибка: ' + ex.message, 'error');
      }
    });
  });

  // Выключение Cardinal
  body.querySelector('#stop-btn')?.addEventListener('click', () => {
    haptic('impact', 'heavy');
    openConfirmSheet('Выключить Cardinal? Потребуется ручной запуск.', async () => {
      try {
        await api.shutdownCardinal(true);
        showToast('Выключение инициировано', 'success');
      } catch (ex) {
        showToast('Ошибка: ' + ex.message, 'error');
      }
    });
  });

  // Восстановление из архива
  const restoreInp = body.querySelector('#restore-file');
  restoreInp?.addEventListener('change', async () => {
    const file = restoreInp.files?.[0];
    if (!file) return;
    haptic('impact', 'heavy');

    openConfirmSheet({
      title: 'Восстановление бэкапа',
      message: `Восстановить конфигурацию из <b>${escHtml(file.name)}</b>?<br>Текущие конфигурационные файлы будут перезаписаны.`,
      confirmText: 'Восстановить',
      danger: true,
      onConfirm: async () => {
        try {
          await api.restoreBackup(file, true);
          showToast('Конфигурация успешно восстановлена', 'success');
        } catch (ex) {
          showToast('Ошибка: ' + ex.message, 'error');
        }
      },
    });
    restoreInp.value = '';
  });

  // Загрузка логов
  const logsBox = body.querySelector('#logs-box');
  const loadLogs = async () => {
    try {
      const { lines } = await api.getLogs(150);
      if (!lines || !lines.length) {
        logsBox.innerHTML = `<span style="opacity:.4">Логов пока нет</span>`;
        return;
      }
      logsBox.innerHTML = lines.map(l => {
        let cls = 'more-log-line-mut';
        if (l.includes('[ERROR]') || l.includes('Traceback')) cls = 'more-log-line-err';
        else if (l.includes('[WARNING]')) cls = 'more-log-line-warn';
        else if (l.includes('[INFO]')) cls = 'more-log-line-info';
        return `<div class="${cls}">${escHtml(l)}</div>`;
      }).join('');
      logsBox.scrollTop = logsBox.scrollHeight;
    } catch (ex) {
      logsBox.innerHTML = `<span style="opacity:.4">Ошибка получения логов</span>`;
    }
  };

  await loadLogs();

  body.querySelector('#logs-refresh')?.addEventListener('click', () => {
    haptic('selection');
    loadLogs();
  });

  body.querySelector('#logs-clear')?.addEventListener('click', () => {
    haptic('impact', 'medium');
    openConfirmSheet('Очистить весь файл логов?', async () => {
      try {
        await api.clearLogs(true);
        showToast('Логи очищены', 'success');
        await loadLogs();
      } catch (ex) {
        showToast('Ошибка: ' + ex.message, 'error');
      }
    });
  });
}

// ── XSS Защита ─────────────────────────────────────────────────────────────

function escHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

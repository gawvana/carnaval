/**
 * pages/more.js — вкладка «Ещё».
 *
 * Секции:
 *   0 – Уведомления   (toggle-сетка BlockList + NewMessageView)
 *   1 – Автоматизация (Greetings / OrderConfirm / ReviewReply toggle+text)
 *   2 – Чёрный список (список + добавить/удалить)
 *   3 – Плагины       (список + toggle + загрузка)
 *   4 – Безопасность  (прокси, авторизованные, golden_key)
 *   5 – Система       (логи, бэкап, рестарт, стоп)
 */

import * as api from '../api.js';
import { openConfirmSheet, openSheet, closeSheet } from '../ui/sheet.js';
import { showToast } from '../ui/toast.js';
import { haptic } from '../tg.js';

// ── Секции ──────────────────────────────────────────────────────────────────

const SECTIONS = [
  { id: 'notifications', label: 'Уведомления' },
  { id: 'greetings',     label: 'Сообщения'   },
  { id: 'blacklist',     label: 'Чёрный список'},
  { id: 'plugins',       label: 'Плагины'      },
  { id: 'security',      label: 'Безопасность' },
  { id: 'system',        label: 'Система'      },
];

// Карта: section.key → человеческое название для Greetings/OrderConfirm/ReviewReply
const GREETING_LABELS = {
  'Greetings.sendGreetings':        { label: 'Приветствие включено',         type: 'toggle' },
  'Greetings.greetingsText':        { label: 'Текст приветствия',            type: 'text'   },
  'Greetings.greetingsCooldown':    { label: 'Кулдаун (сек)',                type: 'text'   },
  'Greetings.ignoreSystemMessages': { label: 'Игнорировать системные',       type: 'toggle' },
  'Greetings.onlyNewChats':         { label: 'Только новые чаты',            type: 'toggle' },
  'OrderConfirm.sendReply':         { label: 'Подтверждение заказа',         type: 'toggle' },
  'OrderConfirm.replyText':         { label: 'Текст подтверждения',          type: 'text'   },
  'OrderConfirm.watermark':         { label: 'Водяной знак',                 type: 'toggle' },
  'ReviewReply.star1Reply':         { label: '⭐ Ответ 1 звезда',            type: 'toggle' },
  'ReviewReply.star1ReplyText':     { label: '⭐ Текст ответа 1★',           type: 'text'   },
  'ReviewReply.star2Reply':         { label: '⭐⭐ Ответ 2 звезды',          type: 'toggle' },
  'ReviewReply.star2ReplyText':     { label: '⭐⭐ Текст ответа 2★',         type: 'text'   },
  'ReviewReply.star3Reply':         { label: '⭐⭐⭐ Ответ 3 звезды',        type: 'toggle' },
  'ReviewReply.star3ReplyText':     { label: '⭐⭐⭐ Текст ответа 3★',       type: 'text'   },
  'ReviewReply.star4Reply':         { label: '⭐⭐⭐⭐ Ответ 4 звезды',      type: 'toggle' },
  'ReviewReply.star4ReplyText':     { label: '⭐⭐⭐⭐ Текст ответа 4★',     type: 'text'   },
  'ReviewReply.star5Reply':         { label: '⭐⭐⭐⭐⭐ Ответ 5 звёзд',    type: 'toggle' },
  'ReviewReply.star5ReplyText':     { label: '⭐⭐⭐⭐⭐ Текст ответа 5★',   type: 'text'   },
};

// ── Главный рендер ──────────────────────────────────────────────────────────

export async function renderMore(container) {
  container.innerHTML = `
    <div id="more-root">
      <div class="seg" id="more-seg" style="margin:16px 16px 0"></div>
      <div id="more-body" style="padding:0 16px 100px"></div>
    </div>
  `;

  const seg = container.querySelector('#more-seg');
  const body = container.querySelector('#more-body');

  // Строим сегмент
  seg.innerHTML = SECTIONS.map((s, i) =>
    `<button class="seg-btn${i === 0 ? ' active' : ''}" data-tab="${s.id}">${s.label}</button>`
  ).join('');

  let activeTab = SECTIONS[0].id;

  seg.addEventListener('click', (e) => {
    const btn = e.target.closest('.seg-btn');
    if (!btn) return;
    seg.querySelectorAll('.seg-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    activeTab = btn.dataset.tab;
    haptic('selection');
    renderTab(activeTab, body);
  });

  await renderTab(activeTab, body);
}

async function renderTab(tabId, body) {
  body.innerHTML = `<div class="skel" style="height:120px;margin-top:16px;border-radius:16px"></div>`;
  try {
    switch (tabId) {
      case 'notifications': await renderNotifications(body); break;
      case 'greetings':     await renderGreetings(body);     break;
      case 'blacklist':     await renderBlacklist(body);     break;
      case 'plugins':       await renderPlugins(body);       break;
      case 'security':      await renderSecurity(body);      break;
      case 'system':        await renderSystem(body);        break;
    }
  } catch (e) {
    body.innerHTML = `<p class="tx" style="padding:32px;opacity:.5">Ошибка загрузки: ${e.message}</p>`;
  }
}

// ── Уведомления ─────────────────────────────────────────────────────────────

async function renderNotifications(body) {
  const data = await api.getNotifications();
  body.innerHTML = `<div class="rv card glass" style="margin-top:16px;padding:20px 16px"></div>`;
  const card = body.querySelector('.card');

  for (const [dotKey, info] of Object.entries(data)) {
    const [section, key] = dotKey.split('.');
    const row = document.createElement('div');
    row.className = 'row-toggle';
    row.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:10px 0;border-bottom:1px solid var(--sep)';
    row.innerHTML = `
      <span class="tx" style="font-size:14px">${info.label}</span>
      <label class="sw">
        <input type="checkbox" ${info.enabled ? 'checked' : ''}>
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
        showToast('Ошибка: ' + e.message, 'error');
      }
    });
    card.appendChild(row);
  }
}

// ── Сообщения (Greetings / OrderConfirm / ReviewReply) ──────────────────────

async function renderGreetings(body) {
  const data = await api.getGreetings();
  body.innerHTML = '';

  let lastGroup = '';
  let card = null;

  for (const [dotKey, info] of Object.entries(data)) {
    const [section, key] = dotKey.split('.');
    const meta = GREETING_LABELS[dotKey] || { label: key, type: info.type };

    // Группировка по секции
    if (section !== lastGroup) {
      lastGroup = section;
      const heading = document.createElement('p');
      heading.className = 'tx';
      heading.style.cssText = 'font-weight:600;margin:20px 0 8px;font-size:13px;opacity:.6;text-transform:uppercase;letter-spacing:.05em';
      const labels = { Greetings: 'Приветствие', OrderConfirm: 'Подтверждение заказа', ReviewReply: 'Ответы на отзывы' };
      heading.textContent = labels[section] || section;
      body.appendChild(heading);

      card = document.createElement('div');
      card.className = 'rv card glass';
      card.style.cssText = 'padding:4px 16px;margin-bottom:8px';
      body.appendChild(card);
    }

    const row = document.createElement('div');
    row.style.cssText = 'padding:12px 0;border-bottom:1px solid var(--sep)';

    if (meta.type === 'toggle') {
      row.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:space-between">
          <span class="tx" style="font-size:14px">${meta.label}</span>
          <label class="sw">
            <input type="checkbox" ${info.value ? 'checked' : ''}>
            <span class="track"></span>
          </label>
        </div>
      `;
      const cb = row.querySelector('input');
      cb.addEventListener('change', async () => {
        haptic('impact', 'light');
        try {
          await api.updateGreeting(section, key, cb.checked ? '1' : '0');
          showToast('Сохранено', 'success');
        } catch (e) {
          cb.checked = !cb.checked;
          showToast('Ошибка: ' + e.message, 'error');
        }
      });
    } else {
      row.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
          <span class="tx" style="font-size:13px;opacity:.7">${meta.label}</span>
        </div>
        <div style="display:flex;gap:8px">
          <input class="inp" type="text" value="${escHtml(String(info.value || ''))}"
            placeholder="${meta.label}"
            style="flex:1;background:var(--bg2);border:1.5px solid var(--sep);border-radius:12px;padding:8px 12px;color:var(--tx);font-size:14px">
          <button class="press" style="padding:8px 14px;border-radius:12px;background:var(--p);color:#fff;font-size:13px;font-weight:600">Сохр.</button>
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
    }
    card?.appendChild(row);
  }
}

// ── Чёрный список ────────────────────────────────────────────────────────────

async function renderBlacklist(body) {
  const { blacklist } = await api.getBlacklist();
  body.innerHTML = `
    <div style="margin-top:16px;display:flex;gap:8px">
      <input id="bl-inp" class="inp" type="text" placeholder="@username"
        style="flex:1;background:var(--bg2);border:1.5px solid var(--sep);border-radius:14px;padding:10px 14px;color:var(--tx);font-size:14px">
      <button id="bl-add" class="press" style="padding:10px 16px;border-radius:14px;background:var(--p);color:#fff;font-weight:600;font-size:14px">+</button>
    </div>
    <div class="rv card glass" id="bl-list" style="margin-top:12px;padding:4px 16px;min-height:60px"></div>
  `;

  const inp = body.querySelector('#bl-inp');
  const addBtn = body.querySelector('#bl-add');
  const list = body.querySelector('#bl-list');

  const renderList = (bl) => {
    if (!bl.length) {
      list.innerHTML = `<p class="tx" style="padding:16px 0;opacity:.4;text-align:center;font-size:14px">Список пуст</p>`;
      return;
    }
    list.innerHTML = bl.map(u => `
      <div style="display:flex;align-items:center;justify-content:space-between;padding:12px 0;border-bottom:1px solid var(--sep)" data-user="${u}">
        <span class="tx" style="font-size:14px">@${escHtml(u)}</span>
        <button class="press bl-del" data-user="${u}" style="padding:6px 12px;border-radius:10px;background:var(--danger,#ff4d4f);color:#fff;font-size:12px">Удалить</button>
      </div>
    `).join('');
  };
  renderList(blacklist);

  let currentList = [...blacklist];

  addBtn.addEventListener('click', async () => {
    const user = inp.value.trim().replace(/^@/, '');
    if (!user) return;
    haptic('impact', 'medium');
    try {
      await api.addToBlacklist(user);
      currentList.push(user);
      renderList(currentList);
      inp.value = '';
      showToast('Добавлен в ЧС', 'success');
    } catch (e) {
      showToast('Ошибка: ' + e.message, 'error');
    }
  });

  list.addEventListener('click', async (e) => {
    const btn = e.target.closest('.bl-del');
    if (!btn) return;
    const user = btn.dataset.user;
    haptic('impact', 'medium');
    openConfirmSheet(
      `Удалить @${user} из ЧС?`,
      async () => {
        try {
          await api.removeFromBlacklist(user);
          currentList = currentList.filter(u => u !== user);
          renderList(currentList);
          showToast('Удалён из ЧС', 'success');
        } catch (ex) {
          showToast('Ошибка: ' + ex.message, 'error');
        }
      }
    );
  });
}

// ── Плагины ─────────────────────────────────────────────────────────────────

async function renderPlugins(body) {
  const { plugins } = await api.getPlugins();
  body.innerHTML = `
    <div style="margin-top:16px;display:flex;gap:8px;justify-content:flex-end">
      <label class="press" style="cursor:pointer;padding:10px 16px;border-radius:14px;background:var(--p);color:#fff;font-weight:600;font-size:14px">
        📦 Загрузить .py
        <input type="file" accept=".py" id="pl-file" style="display:none">
      </label>
    </div>
    <div class="rv card glass" id="pl-list" style="margin-top:12px;padding:4px 16px;min-height:60px"></div>
  `;

  const fileInp = body.querySelector('#pl-file');
  const list = body.querySelector('#pl-list');

  let currentPlugins = [...plugins];

  const renderList = (pls) => {
    if (!pls.length) {
      list.innerHTML = `<p class="tx" style="padding:16px 0;opacity:.4;text-align:center;font-size:14px">Плагины не найдены</p>`;
      return;
    }
    list.innerHTML = pls.map(pl => `
      <div style="padding:14px 0;border-bottom:1px solid var(--sep)" data-uuid="${pl.uuid}">
        <div style="display:flex;align-items:center;justify-content:space-between">
          <div>
            <span class="tx" style="font-weight:600;font-size:14px">${escHtml(pl.name)} <span style="opacity:.5;font-weight:400">v${escHtml(pl.version)}</span></span>
            ${pl.credits ? `<br><span class="tx" style="font-size:12px;opacity:.5">${escHtml(pl.credits)}</span>` : ''}
          </div>
          <div style="display:flex;align-items:center;gap:10px">
            <button class="press pl-del" data-uuid="${pl.uuid}" data-name="${escHtml(pl.name)}" style="padding:4px 10px;border-radius:10px;background:var(--danger,#ff4d4f);color:#fff;font-size:12px">Удалить</button>
            <label class="sw">
              <input type="checkbox" class="pl-toggle" data-uuid="${pl.uuid}" ${pl.enabled ? 'checked' : ''}>
              <span class="track"></span>
            </label>
          </div>
        </div>
        ${pl.description ? `<p class="tx" style="font-size:13px;opacity:.6;margin-top:4px">${escHtml(pl.description)}</p>` : ''}
      </div>
    `).join('');
  };
  renderList(currentPlugins);

  // Toggle
  list.addEventListener('change', async (e) => {
    const cb = e.target.closest('.pl-toggle');
    if (!cb) return;
    haptic('impact', 'light');
    try {
      await api.togglePlugin(cb.dataset.uuid);
      showToast(cb.checked ? 'Плагин включён' : 'Плагин выключен', 'success');
    } catch (ex) {
      cb.checked = !cb.checked;
      showToast('Ошибка: ' + ex.message, 'error');
    }
  });

  // Удаление плагина
  list.addEventListener('click', async (e) => {
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

  // Загрузка файла с красным предупреждением безопасности
  fileInp.addEventListener('change', async () => {
    const file = fileInp.files?.[0];
    if (!file) return;
    if (!file.name.endsWith('.py')) {
      showToast('Только .py файлы', 'error');
      return;
    }
    haptic('impact', 'medium');
    openConfirmSheet({
      title: 'Загрузка плагина',
      message: `<div style="background:var(--err-c);color:var(--err);padding:10px;border-radius:10px;font-size:13px;margin-bottom:10px;line-height:1.4">
        ⚠️ <b>ВНИМАНИЕ</b>: Плагин исполняет произвольный код на сервере!<br>
        Загружайте только файлы из проверенных источников.
      </div>Вы действительно хотите загрузить <b>${escHtml(file.name)}</b>?`,
      confirmText: 'Загрузить',
      danger: true,
      onConfirm: async () => {
        try {
          await api.uploadPlugin(file, true);
          showToast('Плагин загружен (перезапустите бота для активации)', 'success');
          const fresh = await api.getPlugins();
          currentPlugins = fresh.plugins;
          renderList(currentPlugins);
        } catch (ex) {
          showToast('Ошибка: ' + ex.message, 'error');
        }
      }
    });
    fileInp.value = '';
  });
}

// ── Безопасность ─────────────────────────────────────────────────────────────

async function renderSecurity(body) {
  const [accInfo, proxyInfo, { users: authUsers }, sessionsRes, auditRes] = await Promise.all([
    api.getAccountInfo().catch(() => ({})),
    api.getProxy().catch(() => ({ enabled: false, proxy_list: [] })),
    api.getAuthorizedUsers().catch(() => ({ users: [] })),
    api.getActiveSessions().catch(() => ({ sessions: [] })),
    api.getAuditLogs(10).catch(() => ({ logs: [] })),
  ]);

  const sessions = sessionsRes.sessions || [];
  const auditLogs = auditRes.logs || [];
  const gkMasked = accInfo.golden_key_masked || (accInfo.golden_key_configured ? '••••••••••••••••' : 'Не задан');

  body.innerHTML = `
    <!-- Аккаунт FunPay -->
    <p class="sec-title">Аккаунт FunPay</p>
    <div class="rv card glass" style="padding:16px;margin-bottom:16px">
      <div class="tx" style="font-size:14px;margin-bottom:4px">👤 <b>${escHtml(accInfo.username || '—')}</b> (ID: ${accInfo.id || '—'})</div>
      <div class="tx" style="font-size:13px;opacity:.6;margin-bottom:12px">golden_key: <code>${escHtml(gkMasked)}</code></div>
      <div style="display:flex;gap:10px">
        <button id="gk-btn" class="press" style="flex:1;padding:10px 14px;border-radius:14px;background:var(--warn,#ff9800);color:#fff;font-weight:600;font-size:13px">
          🔑 Сменить golden_key
        </button>
        ${accInfo.golden_key_configured ? `
          <button id="gk-del-btn" class="press" style="padding:10px 14px;border-radius:14px;background:var(--danger,#ff4d4f);color:#fff;font-weight:600;font-size:13px">
            Удалить
          </button>
        ` : ''}
      </div>
    </div>

    <!-- Мастер-пароль панели -->
    <p class="sec-title">Пароль панели управления</p>
    <div class="rv card glass" style="padding:16px;margin-bottom:16px">
      <p class="tx" style="font-size:12px;opacity:.6;margin-bottom:12px;line-height:1.4">
        🔒 Пароль защищает доступ к чувствительным операциям и настройкам бота (Argon2id).
      </p>
      <button id="change-pwd-btn" class="press" style="padding:10px 16px;border-radius:14px;background:var(--p);color:#fff;font-weight:600;font-size:14px;width:100%">
        🛡️ Сменить пароль панели
      </button>
    </div>

    <!-- Активные сессии -->
    <p class="sec-title">Активные сессии</p>
    <div class="rv card glass" style="padding:16px;margin-bottom:16px">
      <div id="sessions-list" style="margin-bottom:12px">
        ${sessions.length ? sessions.map(s => `
          <div style="padding:8px 0;border-bottom:1px solid var(--sep);font-size:12px" class="tx">
            <div style="display:flex;justify-content:space-between">
              <b>IP: ${escHtml(s.ip || '—')}</b>
              <span style="opacity:.6">${escHtml(s.last_active || '')}</span>
            </div>
            <div style="opacity:.5;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(s.user_agent || 'Браузер')}</div>
          </div>
        `).join('') : '<p class="tx" style="opacity:.4;font-size:13px">Нет активных сессий</p>'}
      </div>
      <button id="logout-all-btn" class="press" style="padding:8px 14px;border-radius:12px;background:var(--danger,#ff4d4f);color:#fff;font-weight:600;font-size:12px;width:100%">
        🚪 Завершить все остальные сессии
      </button>
    </div>

    <!-- Журнал аудита -->
    <p class="sec-title">Журнал безопасности</p>
    <div class="rv card glass" style="padding:16px;margin-bottom:16px">
      <div id="audit-list">
        ${auditLogs.length ? auditLogs.map(l => `
          <div style="padding:6px 0;border-bottom:1px solid var(--sep);font-size:12px" class="tx">
            <div style="display:flex;justify-content:space-between">
              <span style="font-weight:600;color:var(--p)">${escHtml(l.action)}</span>
              <span style="opacity:.5;font-size:11px">${escHtml(l.created_at || '')}</span>
            </div>
            ${l.details ? `<div style="opacity:.7;font-size:11px;margin-top:2px">${escHtml(l.details)}</div>` : ''}
          </div>
        `).join('') : '<p class="tx" style="opacity:.4;font-size:13px">Журнал пуст</p>'}
      </div>
    </div>

    <!-- Прокси -->
    <p class="sec-title">Прокси</p>
    <div class="rv card glass" style="padding:16px;margin-bottom:16px">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
        <span class="tx" style="font-size:14px">Использовать прокси</span>
        <label class="sw">
          <input type="checkbox" id="proxy-en" ${proxyInfo.enabled ? 'checked' : ''}>
          <span class="track"></span>
        </label>
      </div>
      ${proxyInfo.current_proxy
        ? `<div class="tx" style="font-size:12px;opacity:.5;margin-bottom:12px">Активный: ${escHtml(proxyInfo.current_proxy)}</div>`
        : ''}
      <div style="display:flex;gap:8px;margin-bottom:8px">
        <input id="proxy-inp" class="inp" type="text" placeholder="http://user:pass@1.2.3.4:8080"
          style="flex:1;background:var(--bg2);border:1.5px solid var(--sep);border-radius:12px;padding:8px 12px;color:var(--tx);font-size:13px">
        <button id="proxy-add" class="press" style="padding:8px 14px;border-radius:12px;background:var(--p);color:#fff;font-weight:600">+</button>
      </div>
      <div id="proxy-list"></div>
    </div>

    <!-- Авторизованные пользователи -->
    <p class="sec-title">Авторизованные пользователи</p>
    <div class="rv card glass" style="padding:16px;margin-bottom:16px">
      <p class="tx" style="font-size:12px;opacity:.6;margin-bottom:12px;line-height:1.4">
        🔒 Доступ выдаётся только через отправку секретного пароля Telegram-боту в чат. Добавление пользователей из приложения отключено в целях безопасности.
      </p>
      <div id="au-list"></div>
    </div>
  `;

  // ── Стили секций
  body.querySelectorAll('.sec-title').forEach(el => {
    el.style.cssText = 'font-weight:600;margin:16px 0 8px;font-size:13px;opacity:.6;text-transform:uppercase;letter-spacing:.05em';
    el.classList.add('tx');
  });

  // ── golden_key
  body.querySelector('#gk-btn').addEventListener('click', () => {
    haptic('impact', 'medium');
    openSheet({
      title: '🔑 Смена golden_key',
      content: `
        <p class="tx" style="font-size:13px;opacity:.6;margin-bottom:12px">⚠️ Изменение golden_key может нарушить работу бота. Убедитесь, что ключ корректный.</p>
        <input id="gk-inp" type="text" class="inp" placeholder="Новый golden_key"
          style="width:100%;background:var(--bg2);border:1.5px solid var(--sep);border-radius:12px;padding:10px 14px;color:var(--tx);font-size:14px;box-sizing:border-box">
      `,
      actions: [
        {
          label: 'Отмена', style: 'secondary',
          onClick: () => closeSheet(),
        },
        {
          label: '✅ Сменить', style: 'danger',
          onClick: async () => {
            const newKey = document.querySelector('#gk-inp')?.value?.trim();
            if (!newKey) { showToast('Введите ключ', 'error'); return; }
            closeSheet();
            openConfirmSheet(
              'Вы точно хотите сменить golden_key? Бот продолжит работу без перезапуска.',
              async () => {
                try {
                  await api.changeGoldenKey(newKey, true);
                  showToast('golden_key изменён', 'success');
                  renderSecurity(body);
                } catch (ex) {
                  showToast('Ошибка: ' + ex.message, 'error');
                }
              }
            );
          },
        },
      ],
    });
  });

  // ── Удаление golden_key
  body.querySelector('#gk-del-btn')?.addEventListener('click', () => {
    haptic('impact', 'medium');
    openConfirmSheet(
      'Вы уверены, что хотите удалить сохранённый Golden Key? Работа с аккаунтом FunPay будет приостановлена.',
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

  // ── Смена мастер-пароля панели
  body.querySelector('#change-pwd-btn')?.addEventListener('click', () => {
    haptic('impact', 'medium');
    openSheet({
      title: '🛡️ Смена пароля панели',
      content: `
        <div style="display:flex;flex-direction:column;gap:10px">
          <input id="pwd-old" type="password" class="inp" placeholder="Текущий пароль"
            style="width:100%;background:var(--bg2);border:1.5px solid var(--sep);border-radius:12px;padding:10px 14px;color:var(--tx);font-size:14px;box-sizing:border-box">
          <input id="pwd-new" type="password" class="inp" placeholder="Новый пароль (мин. 6 символов)"
            style="width:100%;background:var(--bg2);border:1.5px solid var(--sep);border-radius:12px;padding:10px 14px;color:var(--tx);font-size:14px;box-sizing:border-box">
          <input id="pwd-conf" type="password" class="inp" placeholder="Повторите новый пароль"
            style="width:100%;background:var(--bg2);border:1.5px solid var(--sep);border-radius:12px;padding:10px 14px;color:var(--tx);font-size:14px;box-sizing:border-box">
        </div>
      `,
      actions: [
        {
          label: 'Отмена', style: 'secondary',
          onClick: () => closeSheet(),
        },
        {
          label: 'Сохранить', style: 'primary',
          onClick: async () => {
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
          },
        },
      ],
    });
  });

  // ── Завершить все остальные сессии
  body.querySelector('#logout-all-btn')?.addEventListener('click', () => {
    haptic('impact', 'medium');
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

  // ── Прокси enabled toggle
  body.querySelector('#proxy-en').addEventListener('change', async (e) => {
    haptic('impact', 'light');
    try {
      await api.setProxyEnabled(e.target.checked);
      showToast(e.target.checked ? 'Прокси включён' : 'Прокси выключен', 'success');
    } catch (ex) {
      e.target.checked = !e.target.checked;
      showToast('Ошибка: ' + ex.message, 'error');
    }
  });

  // ── Список прокси
  let proxyList = [...proxyInfo.proxy_list];
  const proxyListEl = body.querySelector('#proxy-list');

  const renderProxyList = (list) => {
    proxyListEl.innerHTML = list.length
      ? list.map(p => `
          <div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--sep)" data-pid="${p.id}">
            <span class="tx" style="flex:1;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(p.proxy)}</span>
            <button class="press proxy-act" data-pid="${p.id}" style="padding:4px 10px;border-radius:10px;background:var(--p);color:#fff;font-size:12px">Выбрать</button>
            <button class="press proxy-del" data-pid="${p.id}" style="padding:4px 10px;border-radius:10px;background:var(--danger,#ff4d4f);color:#fff;font-size:12px">✕</button>
          </div>
        `).join('')
      : `<p class="tx" style="opacity:.4;font-size:13px;padding:8px 0">Нет прокси</p>`;
  };
  renderProxyList(proxyList);

  body.querySelector('#proxy-add').addEventListener('click', async () => {
    const proxy = body.querySelector('#proxy-inp').value.trim();
    if (!proxy) return;
    haptic('impact', 'medium');
    try {
      await api.addProxy(proxy);
      const fresh = await api.getProxy();
      proxyList = fresh.proxy_list;
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

  // ── Авторизованные пользователи
  let auList = [...authUsers];
  const auListEl = body.querySelector('#au-list');

  const renderAuList = (list) => {
    auListEl.innerHTML = list.length
      ? list.map(uid => `
          <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--sep)">
            <span class="tx" style="font-size:13px">${uid}</span>
            <button class="press au-del" data-uid="${uid}" style="padding:4px 10px;border-radius:10px;background:var(--danger,#ff4d4f);color:#fff;font-size:12px">Удалить</button>
          </div>
        `).join('')
      : `<p class="tx" style="opacity:.4;font-size:13px;padding:8px 0">Нет авторизованных пользователей</p>`;
  };
  renderAuList(auList);

  auListEl.addEventListener('click', async (e) => {
    const btn = e.target.closest('.au-del');
    if (!btn) return;
    const uid = Number(btn.dataset.uid);
    haptic('impact', 'medium');
    openConfirmSheet(
      `Отозвать доступ у администратора ID ${uid}? Он потеряет доступ к боту и панели.`,
      async () => {
        try {
          await api.removeAuthorizedUser(uid, true);
          auList = auList.filter(u => u !== uid);
          renderAuList(auList);
          showToast('Доступ успешно отозван', 'success');
        } catch (ex) {
          showToast('Ошибка: ' + ex.message, 'error');
        }
      }
    );
  });
}

// ── Система ─────────────────────────────────────────────────────────────────

async function renderSystem(body) {
  body.innerHTML = `
    <!-- Управление -->
    <p class="sec-title tx" style="font-weight:600;margin:16px 0 8px;font-size:13px;opacity:.6;text-transform:uppercase;letter-spacing:.05em">Управление</p>
    <div class="rv card glass" style="padding:16px;margin-bottom:16px;display:flex;gap:10px;flex-wrap:wrap">
      <a id="backup-btn" class="press" href="${api.getBackupUrl()}" download
        style="flex:1;min-width:120px;padding:12px 0;border-radius:14px;background:var(--p);color:#fff;font-weight:600;font-size:14px;text-align:center">
        💾 Скачать бэкап
      </a>
      <label class="press"
        style="cursor:pointer;flex:1;min-width:120px;padding:12px 0;border-radius:14px;background:var(--bg2);border:1px solid var(--sep);color:var(--tx);font-weight:600;font-size:14px;text-align:center">
        📥 Восстановить
        <input type="file" accept=".zip" id="restore-file" style="display:none">
      </label>
      <button id="restart-btn" class="press"
        style="flex:1;min-width:120px;padding:12px 0;border-radius:14px;background:var(--warn,#ff9800);color:#fff;font-weight:600;font-size:14px">
        🔄 Перезапуск
      </button>
      <button id="stop-btn" class="press"
        style="flex:1;min-width:120px;padding:12px 0;border-radius:14px;background:var(--danger,#ff4d4f);color:#fff;font-weight:600;font-size:14px">
        ⛔ Выключить
      </button>
    </div>

    <!-- Логи -->
    <div style="display:flex;align-items:center;justify-content:space-between;margin:16px 0 8px">
      <p class="sec-title tx" style="font-weight:600;font-size:13px;opacity:.6;text-transform:uppercase;letter-spacing:.05em;margin:0">Логи Cardinal</p>
      <div style="display:flex;gap:8px">
        <button id="logs-clear" class="press" style="padding:6px 12px;border-radius:10px;background:var(--danger,#ff4d4f);font-size:13px;color:#fff">
          🗑 Очистить
        </button>
        <button id="logs-refresh" class="press" style="padding:6px 12px;border-radius:10px;background:var(--bg2);border:1px solid var(--sep);font-size:13px;color:var(--tx)">
          ↻ Обновить
        </button>
      </div>
    </div>
    <div class="rv card glass" id="logs-box" style="padding:12px 16px;font-family:monospace;font-size:12px;max-height:400px;overflow-y:auto;word-break:break-all;line-height:1.6">
      <span class="tx" style="opacity:.4">Загрузка логов…</span>
    </div>
  `;

  // Рестарт
  body.querySelector('#restart-btn').addEventListener('click', () => {
    haptic('impact', 'heavy');
    openConfirmSheet(
      '🔄 Перезапустить Cardinal? Бот будет перезагружен.',
      async () => {
        try {
          await api.restartCardinal(true);
          showToast('Перезапуск инициирован…', 'success');
        } catch (ex) {
          showToast('Ошибка: ' + ex.message, 'error');
        }
      }
    );
  });

  // Стоп
  body.querySelector('#stop-btn').addEventListener('click', () => {
    haptic('impact', 'heavy');
    openConfirmSheet(
      '⛔ Выключить Cardinal? Бот перестанет работать до ручного запуска.',
      async () => {
        try {
          await api.shutdownCardinal(true);
          showToast('Выключение инициировано', 'success');
        } catch (ex) {
          showToast('Ошибка: ' + ex.message, 'error');
        }
      }
    );
  });

  // Логи
  const logsBox = body.querySelector('#logs-box');
  const loadLogs = async () => {
    try {
      const { lines } = await api.getLogs(150);
      if (!lines.length) {
        logsBox.innerHTML = `<span class="tx" style="opacity:.4">Логов пока нет</span>`;
        return;
      }
      logsBox.innerHTML = lines.map(l => {
        const cls = l.includes('[ERROR]') ? 'color:#ff4d4f'
          : l.includes('[WARNING]') ? 'color:#ff9800'
          : l.includes('[INFO]') ? 'color:var(--tx)'
          : 'opacity:.6;color:var(--tx)';
        return `<div style="${cls}">${escHtml(l)}</div>`;
      }).join('');
      logsBox.scrollTop = logsBox.scrollHeight;
    } catch (ex) {
      logsBox.innerHTML = `<span class="tx" style="opacity:.4">Ошибка загрузки логов</span>`;
    }
  };

  await loadLogs();

  body.querySelector('#logs-refresh').addEventListener('click', () => {
    haptic('selection');
    loadLogs();
  });

  body.querySelector('#logs-clear').addEventListener('click', () => {
    haptic('impact', 'medium');
    openConfirmSheet('Очистить всю историю логов?', async () => {
      try {
        await api.clearLogs(true);
        showToast('Логи очищены', 'success');
        loadLogs();
      } catch (ex) {
        showToast('Ошибка: ' + ex.message, 'error');
      }
    });
  });

  const restoreInp = body.querySelector('#restore-file');
  restoreInp?.addEventListener('change', async () => {
    const file = restoreInp.files?.[0];
    if (!file) return;
    haptic('impact', 'heavy');
    openConfirmSheet({
      title: 'Восстановление бэкапа',
      message: `Восстановить конфигурацию из архива <b>${escHtml(file.name)}</b>?<br>Все текущие конфиги будут перезаписаны.`,
      confirmText: 'Восстановить',
      danger: true,
      onConfirm: async () => {
        try {
          await api.restoreBackup(file, true);
          showToast('Конфигурация восстановлена', 'success');
        } catch (ex) {
          showToast('Ошибка: ' + ex.message, 'error');
        }
      }
    });
    restoreInp.value = '';
  });
}

// ── Утилиты ──────────────────────────────────────────────────────────────────

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

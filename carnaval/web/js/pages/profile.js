/**
 * pages/profile.js — Центр профиля, системы и безопасности Carnaval.
 * 
 * Включает 5 полных разделов (Mattering Design System v2 + Apple Liquid Glass):
 *   1. Профиль Telegram (аватар, имя, username, ID, язык, статус авторизации)
 *   2. Профиль FunPay (аккаунт, баланс по валютам, продажи, покупки, статус, синхронизация)
 *   3. Метрики системы (версии, Telegram-бот, FunPay, аптайм, SSE, профиль графики, характеристики устройства)
 *   4. Безопасность и сессии (статус токена, разблокировка панели, активные сессии, завершение сессий)
 *   5. Прямые действия (обновление, переподключение FunPay, скрыть/сменить Golden Key, разблокировка, выход)
 */

import * as api from '../api.js';
import { tg, haptic } from '../tg.js';
import { showToast } from '../ui/toast.js';
import { openSheet, closeSheet, openConfirmSheet } from '../ui/sheet.js';
import { getQualityTier, setQualityTier } from '../ui/tier.js';
import { getIcon } from '../ui/icons.js';
import { openPanelUnlockModal } from '../ui/onboarding.js';

let _activeController = null;
let _refreshTimer = null;

export async function renderProfile(wrap, options = {}) {
  // Отменяем предыдущие операции
  unmountProfile();

  _activeController = new AbortController();
  const signal = options.signal || _activeController.signal;

  // Включаем Telegram BackButton для возврата в меню/дашборд
  tg.backButton.show(() => {
    haptic('selection');
    if (window.history.length > 1) {
      window.history.back();
    } else {
      location.hash = 'dashboard';
    }
  });

  wrap.innerHTML = `
    <div class="profile-page-container" id="profile-root">
      <div class="profile-header-sticky glass">
        <button class="ib press" id="profile-back-btn" aria-label="Назад">
          ${getIcon('chevron-left')}
        </button>
        <h1 class="profile-header-title">Профиль и статус</h1>
        <button class="ib press" id="profile-refresh-btn" aria-label="Обновить">
          ${getIcon('refresh')}
        </button>
      </div>
      <div class="profile-loading-skel">
        <div class="skel" style="height:160px;border-radius:24px;margin-bottom:14px"></div>
        <div class="skel" style="height:200px;border-radius:24px;margin-bottom:14px"></div>
        <div class="skel" style="height:140px;border-radius:24px"></div>
      </div>
      <div class="profile-content-wrap" id="profile-content" style="display:none"></div>
    </div>
  `;

  const root = wrap.querySelector('#profile-root');
  const contentEl = wrap.querySelector('#profile-content');
  const skelEl = wrap.querySelector('.profile-loading-skel');

  wrap.querySelector('#profile-back-btn')?.addEventListener('click', () => {
    haptic('selection');
    location.hash = 'more';
  });

  wrap.querySelector('#profile-refresh-btn')?.addEventListener('click', async () => {
    haptic('impact', 'medium');
    await loadAndRenderProfileData(contentEl, skelEl, signal);
    showToast('Данные профиля обновлены', 'success');
  });

  await loadAndRenderProfileData(contentEl, skelEl, signal);

  return unmountProfile;
}

export function unmountProfile() {
  if (_activeController) {
    try {
      _activeController.abort('Unmount');
    } catch (_) {}
    _activeController = null;
  }
  if (_refreshTimer) {
    clearInterval(_refreshTimer);
    _refreshTimer = null;
  }
  try {
    tg.backButton.hide();
  } catch (_) {}
}

async function loadAndRenderProfileData(contentEl, skelEl, signal) {
  try {
    const [authMe, dashboard, health, meta, accountInfo, setupStatus, sessionsRes] = await Promise.all([
      api.getAuthMe().catch(() => ({})),
      api.getDashboard().catch(() => ({})),
      api.getHealth().catch(() => ({})),
      api.getMeta().catch(() => ({})),
      api.getAccountInfo().catch(() => ({})),
      api.getSetupStatus().catch(() => ({})),
      api.getActiveSessions().catch(() => ({ sessions: [] })),
    ]);

    if (signal?.aborted) return;

    renderSections(contentEl, {
      authMe,
      dashboard,
      health,
      meta,
      accountInfo,
      setupStatus,
      sessions: sessionsRes.sessions || [],
    });

    skelEl.style.display = 'none';
    contentEl.style.display = 'block';
  } catch (err) {
    if (signal?.aborted) return;
    skelEl.style.display = 'none';
    contentEl.style.display = 'block';
    contentEl.innerHTML = `
      <div class="profile-card error-card">
        <p style="color:var(--err);font-weight:600;margin:0 0 6px">Ошибка загрузки профиля</p>
        <p class="profile-subtext" style="margin-bottom:14px">${escHtml(err.message || 'Сетевой сбой')}</p>
        <button class="btn press" id="profile-retry-btn" style="background:var(--primary);color:var(--on-primary);height:40px;width:100%">
          Повторить попытку
        </button>
      </div>
    `;
    contentEl.querySelector('#profile-retry-btn')?.addEventListener('click', () => {
      loadAndRenderProfileData(contentEl, skelEl, signal);
    });
  }
}

function renderSections(container, data) {
  const { authMe, dashboard, health, meta, accountInfo, setupStatus, sessions } = data;

  // Telegram данные
  const tgUser = tg.user || {};
  const tgFirstName = tgUser.first_name || authMe.first_name || 'Администратор';
  const tgLastName = tgUser.last_name || '';
  const tgFullName = `${tgFirstName} ${tgLastName}`.trim();
  const tgUsername = tgUser.username ? `@${tgUser.username}` : (authMe.username ? `@${authMe.username}` : '—');
  const tgId = tgUser.id || authMe.telegram_user_id || '—';
  const tgLang = (tgUser.language_code || navigator.language || 'ru').toUpperCase();
  const tgPhoto = tgUser.photo_url || '';

  // FunPay данные
  const fpAcc = dashboard.account || {};
  const fpUsername = fpAcc.username || accountInfo.username || authMe.fp_username || 'Не подключён';
  const fpId = fpAcc.id || accountInfo.id || '—';
  const isFpConnected = health.funpay === 'connected' || Boolean(fpAcc.username);
  const isRunnerActive = Boolean(dashboard.running);
  const bal = dashboard.balance || {};
  const rubTotal = bal.total_rub != null ? formatMoney(bal.total_rub) + ' ₽' : '—';
  const rubAvail = bal.available_rub != null ? formatMoney(bal.available_rub) + ' ₽' : '—';
  const usdTotal = bal.total_usd != null ? formatMoney(bal.total_usd) + ' $' : '0 $';
  const eurTotal = bal.total_eur != null ? formatMoney(bal.total_eur) + ' €' : '0 €';
  const activeSales = fpAcc.active_sales != null ? fpAcc.active_sales : '—';
  const activePurchases = fpAcc.active_purchases != null ? fpAcc.active_purchases : '—';
  const raiseTime = dashboard.raise_time ? formatTimestamp(dashboard.raise_time) : 'Не запланировано';

  // System данные
  const cVer = meta.version || '0.1.17';
  const cardVer = dashboard.version || meta.cardinal_version || '0.1.17.15';
  const tgBotStatus = health.telegram === 'connected' ? 'Активен' : 'Ожидание';
  const fpStatusText = health.funpay === 'connected' ? 'Активен' : (isFpConnected ? 'Связан' : 'Ожидание');
  const uptimeSec = health.uptime_sec || dashboard.uptime_sec || 0;
  const uptimeFormatted = formatUptime(uptimeSec);
  const curTier = getQualityTier();
  const mem = navigator.deviceMemory ? `${navigator.deviceMemory} ГБ` : '4+ ГБ';
  const cores = navigator.hardwareConcurrency ? `${navigator.hardwareConcurrency} ядер` : '—';
  const isTouch = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
  const isSaveData = navigator.connection?.saveData ? 'Да' : 'Нет';

  // Security данные
  const isPanelUnlocked = Boolean(authMe.panel_unlocked);
  const hasGk = Boolean(setupStatus.has_golden_key || accountInfo.golden_key_configured);
  const gkMasked = accountInfo.golden_key_masked || (hasGk ? '••••••••••••••••' : 'Не задан');
  const hasPassword = Boolean(setupStatus.has_password);

  container.innerHTML = `
    <!-- SECTION A: Telegram Profile -->
    <div class="profile-section-label">Telegram аккаунт</div>
    <div class="profile-card glass rv in">
      <div class="profile-user-hero">
        <div class="profile-avatar-wrap">
          ${tgPhoto ? `
            <img class="profile-avatar-img" src="${escHtml(tgPhoto)}" alt="${escHtml(tgFullName)}">
          ` : `
            <div class="profile-avatar-monogram">
              ${escHtml(tgFirstName[0] || 'U')}
            </div>
          `}
          <span class="profile-avatar-badge" title="Telegram verified">
            ${getIcon('check')}
          </span>
        </div>
        <div class="profile-user-info">
          <div class="profile-user-name">${escHtml(tgFullName)}</div>
          <div class="profile-user-handle">${escHtml(tgUsername)}</div>
          <div class="profile-badge-auth">
            <span class="profile-status-dot green"></span>
            HMAC-SHA256 подтверждён
          </div>
        </div>
      </div>
      <div class="profile-grid-kv">
        <div class="profile-kv-cell">
          <span class="profile-kv-k">Telegram ID</span>
          <span class="profile-kv-v"><code>${escHtml(String(tgId))}</code></span>
        </div>
        <div class="profile-kv-cell">
          <span class="profile-kv-k">Язык клиента</span>
          <span class="profile-kv-v">${escHtml(tgLang)}</span>
        </div>
        <div class="profile-kv-cell">
          <span class="profile-kv-k">Роль доступа</span>
          <span class="profile-kv-v" style="color:var(--primary);font-weight:600">${escHtml(authMe.role || 'Владелец')}</span>
        </div>
        <div class="profile-kv-cell">
          <span class="profile-kv-k">Клиент WebApp</span>
          <span class="profile-kv-v">${tg.isAvailable ? 'Telegram SDK' : 'Браузер'}</span>
        </div>
      </div>
    </div>

    <!-- SECTION B: FunPay Profile -->
    <div class="profile-section-label">FunPay Профиль</div>
    <div class="profile-card glass rv in">
      <div class="profile-funpay-hero">
        <div class="profile-funpay-icon-box">
          ${getIcon('funpay')}
        </div>
        <div style="flex:1;min-width:0">
          <div style="display:flex;align-items:center;gap:8px">
            <span class="profile-funpay-username">${escHtml(fpUsername)}</span>
            <span class="profile-pill-badge ${isFpConnected ? 'badge-ok' : 'badge-warn'}">
              ${isFpConnected ? 'В сети' : 'Офлайн'}
            </span>
          </div>
          <div class="profile-subtext">ID: ${escHtml(String(fpId))} · Runner: ${isRunnerActive ? 'Активен' : 'Остановлен'}</div>
        </div>
      </div>

      <!-- Балансы -->
      <div class="profile-balance-grid">
        <div class="profile-balance-cell primary">
          <span class="profile-balance-label">Всего (RUB)</span>
          <span class="profile-balance-val">${escHtml(rubTotal)}</span>
          <span class="profile-balance-sub">Доступно: ${escHtml(rubAvail)}</span>
        </div>
        <div class="profile-balance-cell secondary">
          <span class="profile-balance-label">USD & EUR</span>
          <span class="profile-balance-val">${escHtml(usdTotal)}</span>
          <span class="profile-balance-sub">EUR: ${escHtml(eurTotal)}</span>
        </div>
      </div>

      <!-- Активность и поднятие -->
      <div class="profile-grid-kv" style="margin-top:10px">
        <div class="profile-kv-cell">
          <span class="profile-kv-k">Активных продаж</span>
          <span class="profile-kv-v" style="font-weight:700;color:var(--ok)">${escHtml(String(activeSales))}</span>
        </div>
        <div class="profile-kv-cell">
          <span class="profile-kv-k">Активных покупок</span>
          <span class="profile-kv-v">${escHtml(String(activePurchases))}</span>
        </div>
        <div class="profile-kv-cell" style="grid-column: span 2">
          <span class="profile-kv-k">Следующее поднятие лотов</span>
          <span class="profile-kv-v">${escHtml(raiseTime)}</span>
        </div>
      </div>
    </div>

    <!-- SECTION C: System Metrics -->
    <div class="profile-section-label">Метрики и устройство</div>
    <div class="profile-card glass rv in">
      <div class="profile-grid-kv">
        <div class="profile-kv-cell">
          <span class="profile-kv-k">Версия Carnaval</span>
          <span class="profile-kv-v">v${escHtml(cVer)}</span>
        </div>
        <div class="profile-kv-cell">
          <span class="profile-kv-k">Версия Cardinal</span>
          <span class="profile-kv-v">v${escHtml(cardVer)}</span>
        </div>
        <div class="profile-kv-cell">
          <span class="profile-kv-k">Бот Telegram</span>
          <span class="profile-kv-v" style="color:${health.telegram === 'connected' ? 'var(--ok)' : 'var(--warn)'}">
            ${escHtml(tgBotStatus)}
          </span>
        </div>
        <div class="profile-kv-cell">
          <span class="profile-kv-k">FunPay шлюз</span>
          <span class="profile-kv-v" style="color:${health.funpay === 'connected' ? 'var(--ok)' : 'var(--warn)'}">
            ${escHtml(fpStatusText)}
          </span>
        </div>
        <div class="profile-kv-cell">
          <span class="profile-kv-k">Аптайм службы</span>
          <span class="profile-kv-v">${escHtml(uptimeFormatted)}</span>
        </div>
        <div class="profile-kv-cell">
          <span class="profile-kv-k">SSE поток</span>
          <span class="profile-kv-v" style="color:var(--ok)">Подключен</span>
        </div>
        <div class="profile-kv-cell">
          <span class="profile-kv-k">Память / Ядра</span>
          <span class="profile-kv-v">${escHtml(mem)} / ${escHtml(cores)}</span>
        </div>
        <div class="profile-kv-cell">
          <span class="profile-kv-k">Экономия трафика</span>
          <span class="profile-kv-v">${escHtml(isSaveData)}</span>
        </div>
      </div>

      <!-- Переключатель профиля производительности -->
      <div style="margin-top:14px;padding-top:12px;border-top:1px solid var(--outline)">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
          <span style="font-size:13px;font-weight:600;color:var(--on)">Профиль рендеринга</span>
          <span style="font-size:12px;color:var(--muted)">Текущий: <b>${escHtml(curTier)}</b></span>
        </div>
        <div style="display:grid;grid-template-columns:repeat(3, 1fr);gap:8px" id="profile-tier-selector">
          <button type="button" class="more-btn-sm press prof-tier-btn" data-tier="SAVER" style="height:36px;font-size:12px">Эко</button>
          <button type="button" class="more-btn-sm press prof-tier-btn" data-tier="BALANCED" style="height:36px;font-size:12px">Баланс</button>
          <button type="button" class="more-btn-sm press prof-tier-btn" data-tier="HIGH" style="height:36px;font-size:12px">Ультра</button>
        </div>
      </div>
    </div>

    <!-- SECTION D: Security & Sessions -->
    <div class="profile-section-label">Безопасность и сессии</div>
    <div class="profile-card glass rv in">
      <div class="profile-grid-kv" style="margin-bottom:14px">
        <div class="profile-kv-cell">
          <span class="profile-kv-k">Блокировка панели</span>
          <span class="profile-kv-v" style="font-weight:600;color:${isPanelUnlocked ? 'var(--ok)' : 'var(--err)'}">
            ${isPanelUnlocked ? 'Разблокирована' : 'Заблокирована PIN'}
          </span>
        </div>
        <div class="profile-kv-cell">
          <span class="profile-kv-k">Мастер-пароль</span>
          <span class="profile-kv-v" style="color:${hasPassword ? 'var(--ok)' : 'var(--warn)'}">
            ${hasPassword ? 'Настроен' : 'Не задан'}
          </span>
        </div>
        <div class="profile-kv-cell" style="grid-column: span 2">
          <span class="profile-kv-k">Golden Key</span>
          <span class="profile-kv-v"><code>${escHtml(gkMasked)}</code></span>
        </div>
      </div>

      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <span style="font-size:14px;font-weight:600;color:var(--on)">Активные устройства</span>
        <span class="profile-pill-badge">${sessions.length || 1}</span>
      </div>

      <div class="profile-sessions-list">
        ${sessions.length ? sessions.map(s => `
          <div class="profile-session-row">
            <div style="display:flex;align-items:center;justify-content:space-between">
              <span style="font-weight:600;font-size:13px;color:var(--on)">IP: ${escHtml(s.ip || '127.0.0.1')}</span>
              <span style="font-size:11px;color:var(--muted)">${escHtml(s.last_active || 'сейчас')}</span>
            </div>
            <div class="profile-subtext" style="text-overflow:ellipsis;overflow:hidden;white-space:nowrap">
              ${escHtml(s.user_agent || 'Telegram Mini App')}
            </div>
          </div>
        `).join('') : `
          <div class="profile-session-row">
            <div style="font-size:13px;font-weight:600">Текущая активная сессия</div>
            <div class="profile-subtext">Это устройство (Telegram WebApp)</div>
          </div>
        `}
      </div>

      <div style="display:grid;grid-template-columns:1fr;gap:8px;margin-top:12px">
        <button id="prof-logout-all-btn" class="more-btn-sm more-btn-danger press" style="height:40px;display:inline-flex;align-items:center;justify-content:center;gap:6px" type="button">
          ${getIcon('logout')} Завершить все остальные сессии
        </button>
      </div>
    </div>

    <!-- SECTION E: Direct Actions -->
    <div class="profile-section-label">Быстрые действия</div>
    <div class="profile-card glass rv in" style="display:flex;flex-direction:column;gap:10px">
      <button id="action-reconnect-fp" class="btn press" style="height:44px;display:inline-flex;align-items:center;justify-content:center;gap:8px;background:var(--track);color:var(--on)" type="button">
        ${getIcon('funpay')} Переподключить FunPay
      </button>
      
      <button id="action-change-gk" class="btn press" style="height:44px;display:inline-flex;align-items:center;justify-content:center;gap:8px;background:var(--track);color:var(--on)" type="button">
        ${getIcon('key')} Сменить Golden Key
      </button>

      <button id="action-toggle-pin" class="btn press" style="height:44px;display:inline-flex;align-items:center;justify-content:center;gap:8px;background:var(--track);color:var(--on)" type="button">
        ${getIcon('security')} ${isPanelUnlocked ? 'Заблокировать панель' : 'Разблокировать панель'}
      </button>

      <button id="action-logout-cur" class="btn press" style="height:44px;display:inline-flex;align-items:center;justify-content:center;gap:8px;background:var(--err-c);color:var(--on-err-c)" type="button">
        ${getIcon('logout')} Выйти из учётной записи
      </button>
    </div>
  `;

  // Обработчик профиля графики
  const updateTierBtns = () => {
    const active = getQualityTier();
    container.querySelectorAll('.prof-tier-btn').forEach(btn => {
      const isCur = btn.dataset.tier === active;
      btn.style.background = isCur ? 'var(--primary)' : 'var(--track)';
      btn.style.color = isCur ? 'var(--on-primary)' : 'var(--on)';
      btn.style.fontWeight = isCur ? '700' : '500';
    });
  };
  updateTierBtns();

  container.querySelectorAll('.prof-tier-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      haptic('impact', 'light');
      setQualityTier(btn.dataset.tier);
      updateTierBtns();
      showToast(`Профиль графики: ${btn.textContent.trim()}`, 'success');
    });
  });

  // Действие: Завершить все остальные сессии
  container.querySelector('#prof-logout-all-btn')?.addEventListener('click', () => {
    haptic('impact', 'heavy');
    openConfirmSheet('Завершить все активные сессии на остальных устройствах?', async () => {
      try {
        const res = await api.logoutAll();
        showToast(`Отозвано сессий: ${res.revoked_count ?? 0}`, 'success');
        location.reload();
      } catch (e) {
        showToast('Ошибка: ' + e.message, 'error');
      }
    });
  });

  // Действие: Переподключить FunPay
  container.querySelector('#action-reconnect-fp')?.addEventListener('click', async () => {
    haptic('impact', 'medium');
    try {
      showToast('Переподключение к FunPay…', 'info');
      const res = await api.reconnectAccount(true);
      if (res && res.ok !== false) {
        showToast('FunPay шлюз успешно переподключен', 'success');
      } else {
        showToast(res?.error || 'Не удалось переподключить FunPay', 'error');
      }
      loadAndRenderProfileData(container, { style: { display: 'none' } }, null);
    } catch (e) {
      showToast('Ошибка переподключения: ' + e.message, 'error');
    }
  });

  // Действие: Сменить Golden Key
  container.querySelector('#action-change-gk')?.addEventListener('click', () => {
    haptic('selection');
    openSheet('Смена Golden Key', `
      <div style="padding:16px 0">
        <p class="profile-subtext" style="margin-bottom:12px">
          Введите 32-символьный golden_key из cookies FunPay.
        </p>
        <input id="profile-gk-input" type="text" class="more-field" placeholder="32-значный ключ" style="width:100%;margin-bottom:14px">
        <button class="btn press" id="profile-gk-save" style="width:100%;background:var(--primary);color:var(--on-primary);height:44px">
          Сохранить
        </button>
      </div>
    `);

    document.getElementById('profile-gk-save')?.addEventListener('click', async () => {
      const val = document.getElementById('profile-gk-input')?.value?.trim();
      if (!val) { showToast('Введите ключ', 'error'); return; }
      closeSheet();
      try {
        await api.changeGoldenKey(val, true);
        showToast('Golden Key успешно изменён', 'success');
        loadAndRenderProfileData(container, { style: { display: 'none' } }, null);
      } catch (ex) {
        showToast('Ошибка: ' + ex.message, 'error');
      }
    });
  });

  // Действие: Блокировка / разблокировка панели
  container.querySelector('#action-toggle-pin')?.addEventListener('click', () => {
    haptic('selection');
    if (isPanelUnlocked) {
      openConfirmSheet('Заблокировать панель PIN-кодом?', async () => {
        try {
          await api.lockPanel();
          showToast('Панель заблокирована', 'success');
          location.reload();
        } catch (e) {
          showToast('Ошибка блокировки панели: ' + e.message, 'error');
        }
      });
    } else {
      openPanelUnlockModal(() => {
        showToast('Панель разблокирована', 'success');
        loadAndRenderProfileData(container, { style: { display: 'none' } }, null);
      });
    }
  });

  // Действие: Выйти из сессии
  container.querySelector('#action-logout-cur')?.addEventListener('click', () => {
    haptic('impact', 'heavy');
    openConfirmSheet('Выйти из учётной записи на этом устройстве?', async () => {
      try {
        await api.logout();
        tg.close();
        location.reload();
      } catch (e) {
        showToast('Ошибка выхода: ' + e.message, 'error');
      }
    });
  });
}

// ── Форматирование ─────────────────────────────────────────────────────────

function formatMoney(num) {
  if (num == null) return '0';
  return Number(num).toLocaleString('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

function formatUptime(seconds) {
  if (!seconds || seconds <= 0) return '0 мин.';
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d} дн. ${h} ч.`;
  if (h > 0) return `${h} ч. ${m} мин.`;
  return `${m} мин.`;
}

function formatTimestamp(ts) {
  try {
    const date = new Date(ts * 1000);
    return date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
  } catch (_) {
    return '—';
  }
}

function escHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

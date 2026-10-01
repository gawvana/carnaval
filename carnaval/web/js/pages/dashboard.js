/**
 * pages/dashboard.js — Главный экран «Carnaval» на живых данных.
 * Дизайн-система: Mattering v2 (mattering.html).
 * Тональный контент, парящая стеклянная шапка, интерактивные пружинные переключатели.
 */

import { getDashboard, updateSetting, openEventStream } from '../api.js';
import { tg } from '../tg.js';
import { t } from '../i18n.js';
import { showToast } from '../ui/toast.js';
import { renderHeader } from '../ui/header.js';
import { escapeHtml } from '../ui/sanitize.js';

let _stopEvents = null;
let _raiseTimer = null;

export async function renderDashboard(wrap) {
  wrap.innerHTML = renderSkeleton();

  let data;
  try {
    data = await getDashboard();
  } catch (e) {
    wrap.innerHTML = renderError(e.message);
    return;
  }

  // Очистка предыдущего таймера
  if (_raiseTimer) clearInterval(_raiseTimer);

  wrap.innerHTML = '';

  // 1. Шапка (Sticky Glass Header)
  const username = data.account?.username || 'Cardinal';
  const header = renderHeader({
    title: 'Carnaval',
    subtitle: username,
    showThemeToggle: true,
  });
  wrap.appendChild(header);

  // 2. Контейнер контента
  const content = document.createElement('div');
  content.style.paddingTop = '68px';
  content.innerHTML = buildDashboardHTML(data);
  wrap.appendChild(content);

  // 3. Интерактивные переключатели (Mattering .sw)
  content.querySelectorAll('.sw').forEach((sw) => {
    sw.addEventListener('click', async () => {
      const key = sw.dataset.key;
      const current = sw.getAttribute('aria-checked') === 'true';
      const next = !current;

      // Оптимистичное обновление UI + тактильный отклик
      sw.setAttribute('aria-checked', String(next));
      tg.haptic.selection();

      try {
        await updateSetting('FunPay', key, next ? '1' : '0');
        showToast(`${t(key.toLowerCase(), key)}: ${next ? 'вкл' : 'выкл'}`, 'ok');
      } catch (err) {
        // Откат при ошибке
        sw.setAttribute('aria-checked', String(current));
        tg.haptic.notification('error');
        showToast(err.message || t('error_save'), 'err');
      }
    });
  });

  // 4. Таймер обратного отсчета для поднятия лотов
  initRaiseTimer(content, data.raise_time);

  // 5. Подключение к живому SSE-потоку событий
  if (_stopEvents) _stopEvents();
  _stopEvents = openEventStream((ev) => handleLiveEvent(ev, content));
}

function buildDashboardHTML(d) {
  const acc = d.account || {};
  const bal = d.balance || {};
  const tog = d.toggles || {};
  const uptime = formatUptime(d.uptime_sec || 0);

  const rubTotal = bal.total_rub != null ? `${formatCurrency(bal.total_rub)} ₽` : '—';
  const rubAvail = bal.available_rub != null ? `${formatCurrency(bal.available_rub)} ₽` : null;
  const usdTotal = bal.total_usd != null ? `${formatCurrency(bal.total_usd)} $` : '0 $';
  const eurTotal = bal.total_eur != null ? `${formatCurrency(bal.total_eur)} €` : '0 €';

  const statusBadge = d.running
    ? `<span style="display:inline-flex; align-items:center; gap:4px; color:var(--ok, #34c759); font-weight:600"><svg width="8" height="8" viewBox="0 0 8 8" fill="currentColor" aria-hidden="true" style="width:8px; height:8px"><circle cx="4" cy="4" r="4"/></svg> онлайн</span>`
    : `<span style="display:inline-flex; align-items:center; gap:4px; color:var(--err, #ff3b30); font-weight:600"><svg width="8" height="8" viewBox="0 0 8 8" fill="currentColor" aria-hidden="true" style="width:8px; height:8px"><circle cx="4" cy="4" r="4"/></svg> офлайн</span>`;

  return `
    <!-- Профиль и Баланс (Tonal Card Primary) -->
    <div class="card p rv in" style="height: auto; min-height: 140px; margin-bottom: 12px">
      <div style="display:flex; justify-content:space-between; align-items:flex-start">
        <div style="display:flex; align-items:center; gap:10px">
          <div style="width:38px; height:38px; border-radius:50%; background:var(--primary); color:var(--on-primary); display:grid; place-items:center; font-weight:800; font-size:16px">
            ${escapeHtml((acc.username || 'F')[0].toUpperCase())}
          </div>
          <div>
            <b style="font-size:17px; display:block">${escapeHtml(acc.username || 'Аккаунт не привязан')}</b>
            <span style="font-size:12px; opacity:.8; display:inline-flex; align-items:center; gap:6px">ID: ${escapeHtml(acc.id || '—')} · ${statusBadge}</span>
          </div>
        </div>
        ${acc.id ? `
          <button class="ib press" id="open-fp-profile" aria-label="Открыть профиль" style="width:34px; height:34px">
            <svg style="width:18px; height:18px" viewBox="0 0 24 24"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3"/></svg>
          </button>
        ` : ''}
      </div>

      <div style="margin-top: 16px">
        <div style="display:flex; justify-content:space-between; align-items:baseline">
          <div>
            <div style="font-size: 34px; font-weight: 800; letter-spacing: -.05em; line-height: 1">
              ${rubTotal}
            </div>
            ${rubAvail ? `<div style="font-size: 13px; opacity: .85; margin-top: 4px">Доступно: ${rubAvail}</div>` : ''}
          </div>
          <div style="text-align: right; font-size: 13px; font-weight: 600; opacity: .9">
            <div>${usdTotal}</div>
            <div style="margin-top:2px">${eurTotal}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Сетка статистики -->
    <div class="stat-grid rv in">
      <div class="stat-card">
        <div class="val">${acc.active_sales != null ? acc.active_sales : '—'}</div>
        <div class="lbl">${t('active_sales')}</div>
      </div>

      <div class="stat-card">
        <div class="val">${acc.active_purchases != null ? acc.active_purchases : '—'}</div>
        <div class="lbl">${t('active_purchases')}</div>
      </div>

      <div class="stat-card">
        <div class="val" id="raise-timer-val">—</div>
        <div class="lbl">${t('next_raise')}</div>
      </div>

      <div class="stat-card">
        <div class="val">${uptime}</div>
        <div class="lbl">${t('uptime')}</div>
      </div>
    </div>

    <!-- Индикатор реального времени (SSE Live Indicator) -->
    <div class="rv in" style="display:flex; align-items:center; gap:8px; margin: 20px 4px 6px; font-size:12px; font-weight:600; color:var(--muted)">
      <i style="width:8px; height:8px; border-radius:50%; background:var(--ok); display:inline-block; box-shadow:0 0 8px var(--ok)"></i>
      <span>Живой поток событий активен</span>
    </div>

    <!-- Панель автоматизации -->
    <h3 class="k rv in" style="margin-top: 12px">${t('automation')}</h3>
    <div class="panel rv in">
      ${renderSwitchRow(t('autoraise'), 'autoRaise', tog.autoRaise)}
      ${renderSwitchRow(t('autoresponse'), 'autoResponse', tog.autoResponse)}
      ${renderSwitchRow(t('autodelivery'), 'autoDelivery', tog.autoDelivery)}
      ${renderSwitchRow(t('multidelivery'), 'multiDelivery', tog.multiDelivery)}
      ${renderSwitchRow(t('autorestore'), 'autoRestore', tog.autoRestore)}
      ${renderSwitchRow(t('autodisable'), 'autoDisable', tog.autoDisable)}
      ${renderSwitchRow(t('old_mode'), 'oldMsgGetMode', tog.oldMsgGetMode)}
      ${renderSwitchRow(t('keep_unread'), 'keepSentMessagesUnread', tog.keepSentMessagesUnread)}
    </div>

    <!-- Футер инфо -->
    <div class="rv in" style="text-align: center; margin-top: 24px; font-size: 13px; color: var(--muted)">
      FunPay Cardinal v${d.version || '0.1.17.15'} · Carnaval Mini App
    </div>
  `;
}

function renderSwitchRow(label, key, checked) {
  return `
    <div class="row">
      <span>${label}</span>
      <button class="sw" role="switch" aria-checked="${Boolean(checked)}" data-key="${key}" aria-label="${label}">
        <i></i>
      </button>
    </div>
  `;
}

function initRaiseTimer(root, raiseTime) {
  const el = root.querySelector('#raise-timer-val');
  if (!el) return;

  if (!raiseTime || raiseTime <= 0) {
    el.textContent = '—';
    return;
  }

  function update() {
    const now = Math.floor(Date.now() / 1000);
    const diff = raiseTime - now;
    if (diff <= 0) {
      el.textContent = 'скоро';
      return;
    }
    const m = Math.floor(diff / 60);
    const s = diff % 60;
    el.textContent = `${m}м ${s < 10 ? '0' : ''}${s}с`;
  }

  update();
  _raiseTimer = setInterval(update, 1000);
}

function handleLiveEvent(ev, root) {
  // Глобальные toast-уведомления обрабатываются централизованно в app.js
  if (ev.type === 'lots.raised') {
    const timerVal = root.querySelector('#raise-timer-val');
    if (timerVal) timerVal.textContent = 'только что';
  }
}

function formatCurrency(n) {
  return Number(n).toLocaleString('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

function formatUptime(sec) {
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (d > 0) return `${d}д ${h}ч`;
  if (h > 0) return `${h}ч ${m}м`;
  return `${m}м`;
}

function renderSkeleton() {
  return `
    <div class="nav glass rv in" style="height:56px"></div>
    <div style="padding-top:68px">
      <div style="height:140px; border-radius:28px; background:var(--track); margin-bottom:12px; animation:pulse 1.4s ease infinite"></div>
      <div class="stat-grid">
        ${[1, 2, 3, 4].map(() => `
          <div style="height:80px; border-radius:24px; background:var(--track); animation:pulse 1.4s ease infinite"></div>
        `).join('')}
      </div>
      <div style="height:280px; border-radius:32px; background:var(--track); margin-top:24px; animation:pulse 1.4s ease infinite"></div>
    </div>
    <style>@keyframes pulse{0%,100%{opacity:.5}50%{opacity:1}}</style>
  `;
}

function renderError(msg) {
  return `
    <div class="nav glass rv in"><b>Carnaval</b></div>
    <div class="empty" style="padding-top: 140px">
      <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8v4M12 16h.01"/></svg>
      <p>Не удалось загрузить данные<br><small style="color:var(--err)">${msg}</small></p>
      <button class="btn press" onclick="location.reload()" style="margin-top:16px; max-width:180px">Повторить</button>
    </div>
  `;
}

/**
 * app.js — точка входа Carnaval Mini App.
 * Vanilla ES-модули, без внешних фреймворков и сборщиков.
 */

import { auth } from './api.js';
import { tg } from './tg.js';
import { router } from './router.js';
import { initLocale, t } from './i18n.js';
import { hideSplash } from './ui/splash.js';
import { initGlassEffect } from './ui/glass.js';
import { initQualityTier } from './ui/tier.js';
import { initSheet } from './ui/sheet.js';
import { startSSE, onEvent, onConnectionStatus } from './sse.js';
import { showToast } from './ui/toast.js';
import { renderOnboarding, openPanelUnlockModal } from './ui/onboarding.js';

document.documentElement.classList.add('js');

// 1. Инициализация локали и темы Telegram
initLocale();
document.documentElement.setAttribute('data-theme', tg.colorScheme);
tg.onThemeChange(() => {
  document.documentElement.setAttribute('data-theme', tg.colorScheme);
});

async function main() {
  // Защитный таймер: сплеш гарантированно скроется максимум через 3.5 секунды
  setTimeout(hideSplash, 3500);

  // 2. Telegram WebApp готовность
  tg.ready();

  // 3. Проверка запуска вне Telegram
  const hasInitData = Boolean(tg.initData && tg.initData.trim());
  const isDev = Boolean(typeof window !== 'undefined' && window.__CARNAVAL_DEV);

  // Инициализация глобальных UI компонентов (профиль качества, стекло, шторка)
  initQualityTier();
  initGlassEffect();
  initSheet();

  if (!hasInitData && !isDev) {
    // Открыто в обычном браузере без Telegram WebApp
    hideSplash();
    renderUnauthorizedScreen(true);
    return;
  }

  // 4. Авторизация по initData
  let authResult;
  try {
    authResult = await auth(tg.initData);
  } catch (err) {
    authResult = { ok: false, error: err };
  }

  if (!authResult || authResult.ok === false) {
    hideSplash();
    const err = authResult?.error;
    if (err && (err.status >= 500 || err.status === 0 || !err.status)) {
      renderBackendUnavailableScreen(err);
    } else {
      renderUnauthorizedScreen(false);
    }
    return;
  }

  // Слушатель блокировки панели (403 panel_locked)
  window.addEventListener('carnaval:panel_locked', () => {
    openPanelUnlockModal(() => {
      router.reload();
    });
  });

  // Проверка первоначальной настройки (onboarding)
  if (authResult.system_state === 'UNINITIALIZED' || authResult.system_state === 'OWNER_CLAIM') {
    hideSplash();
    const appEl = document.getElementById('app');
    if (appEl) {
      renderOnboarding(appEl, async () => {
        await startAppDashboard();
      });
    }
    return;
  }

  await startAppDashboard();
}

async function startAppDashboard() {
  // 5. Инициализация SPA роутера (рендерит дашборд)
  await router.init();

  // 6. Deep link проверка (start_param из Telegram или ?startapp=...)
  const urlParams = new URLSearchParams(window.location.search);
  const startParam = tg.initDataUnsafe?.start_param || urlParams.get('startapp') || '';
  if (startParam.startsWith('order_')) {
    const orderId = startParam.replace('order_', '');
    router.navigate('orders');
    setTimeout(() => {
      window.dispatchEvent(new CustomEvent('open_order_detail', { detail: { orderId } }));
    }, 400);
  } else if (startParam.startsWith('chat_')) {
    const chatId = startParam.replace('chat_', '');
    router.navigate('chats');
    setTimeout(() => {
      window.dispatchEvent(new CustomEvent('open_chat_history', { detail: { chatId } }));
    }, 400);
  }

  // 7. Скрыть splash-экран
  hideSplash();

  // 8. Запуск SSE потока событий
  startSSE();

  onConnectionStatus((status) => {
    const offlineIndicator = document.getElementById('offline-badge');
    if (offlineIndicator) {
      offlineIndicator.style.display = status === 'connected' ? 'none' : 'inline-flex';
    }
  });

  onEvent((ev) => {
    if (ev.type === 'order.new') {
      const buyer = ev.data?.buyer_username || ev.data?.username || 'покупателя';
      showToast(`📦 Новый заказ #${ev.data?.order_id || ''} от ${buyer}`, 'ok');
      tg.haptic.notification('success');
    } else if (ev.type === 'message.new') {
      const sender = ev.data?.chat_name || ev.data?.author || 'Чат';
      showToast(`💬 ${sender}: ${ev.data?.text || ''}`.slice(0, 60), 'info');
      tg.haptic.impact('light');
    } else if (ev.type === 'lots.raised') {
      showToast('🚀 Лоты успешно подняты!', 'ok');
      tg.haptic.notification('success');
    } else if (ev.type === 'delivery.done') {
      showToast(`📦 Товар выдан: ${ev.data?.product || ''}`, 'ok');
      tg.haptic.notification('success');
    }
  });
}

/**
 * Экран для неавторизованных пользователей или запуска вне Telegram.
 */
function renderUnauthorizedScreen(isOutsideTelegram = false) {
  const app = document.getElementById('app');
  if (!app) return;

  if (isOutsideTelegram) {
    app.innerHTML = `
      <div class="page" style="min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px">
        <div class="panel rv in" style="max-width: 420px; width: 100%; text-align: center; padding: 36px 24px">
          <div style="width: 64px; height: 64px; margin: 0 auto 16px; border-radius: 50%; background: var(--p-c); color: var(--primary); display: grid; place-items: center">
            <svg style="width: 32px; height: 32px" viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          </div>
          <h2 style="margin: 0 0 12px; font-size: 22px">Откройте из Telegram</h2>
          <p class="tx" style="margin: 0 auto 24px; font-size: 14px; line-height: 1.5">
            Carnaval — это Telegram Mini App для управления ботом FunPay Cardinal.<br>
            Для безопасного доступа запустите приложение через кнопку меню в вашем Telegram-боте.
          </p>
        </div>
      </div>
    `;
    return;
  }

  // Если открыто в Telegram, но нет в authorized_users
  app.innerHTML = `
    <div class="page" style="min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px">
      <div class="panel rv in" style="max-width: 420px; width: 100%; text-align: center; padding: 36px 24px">
        <div style="width: 64px; height: 64px; margin: 0 auto 16px; border-radius: 50%; background: var(--err-c); color: var(--err); display: grid; place-items: center">
          <svg style="width: 32px; height: 32px" viewBox="0 0 24 24"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
        </div>
        <h2 style="margin: 0 0 12px; font-size: 22px">Доступ ограничен</h2>
        <p class="tx" style="margin: 0 auto 24px; font-size: 14px; line-height: 1.5">
          Ваш Telegram ID отсутствует в списке администраторов бота.<br>
          Отправьте боту секретный пароль в чат, чтобы получить доступ к панели.
        </p>
        <button class="btn press" id="open-bot-btn" style="width: 100%; background: var(--primary); color: var(--on-primary)">
          Вернуться в чат с ботом
        </button>
      </div>
    </div>
  `;

  document.getElementById('open-bot-btn')?.addEventListener('click', () => {
    tg.haptic.impact('medium');
    tg.close();
  });
}

/**
 * Экран ожидания запуска или недоступности бэкенда (HTTP 502/503/504 / Network).
 */
function renderBackendUnavailableScreen(err) {
  const app = document.getElementById('app');
  if (!app) return;

  const statusMsg = err?.status ? `(HTTP ${err.status})` : '';

  app.innerHTML = `
    <div class="page" style="min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px">
      <div class="panel rv in" style="max-width: 420px; width: 100%; text-align: center; padding: 36px 24px">
        <div style="width: 64px; height: 64px; margin: 0 auto 16px; border-radius: 50%; background: var(--warn-c, #fff3cd); color: var(--warn, #b7791f); display: grid; place-items: center">
          <svg style="width: 32px; height: 32px" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <line x1="12" y1="8" x2="12" y2="12"/>
            <line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
        </div>
        <h2 style="margin: 0 0 12px; font-size: 22px">Бэкенд подключается</h2>
        <p class="tx" style="margin: 0 auto 24px; font-size: 14px; line-height: 1.5">
          Сервер бэкенда на Infrlo запускается или временно недоступен ${statusMsg}.<br>
          Если контейнер перезапускается, подождите несколько секунд и обновите.
        </p>
        <button class="btn press" id="retry-connect-btn" style="width: 100%; background: var(--primary); color: var(--on-primary); margin-bottom: 12px">
          🔄 Повторить попытку
        </button>
        <button class="btn press" id="open-bot-btn-err" style="width: 100%; background: transparent; border: 1px solid var(--border); color: var(--fg)">
          Вернуться в чат с ботом
        </button>
      </div>
    </div>
  `;

  document.getElementById('retry-connect-btn')?.addEventListener('click', () => {
    tg.haptic.impact('medium');
    window.location.reload();
  });

  document.getElementById('open-bot-btn-err')?.addEventListener('click', () => {
    tg.haptic.impact('light');
    tg.close();
  });
}

main().catch((err) => {
  console.error('[Carnaval] fatal error', err);
  hideSplash();
  const app = document.getElementById('app');
  if (app) {
    app.innerHTML = `
      <div class="empty" style="padding-top: 140px">
        <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8v4M12 16h.01"/></svg>
        <p>Ошибка запуска приложения<br><small style="color:var(--err)">${err?.message || ''}</small></p>
      </div>
    `;
  }
});

/**
 * ui/onboarding.js — интерфейс первичной настройки (onboarding) и окно ввода пароля (panel unlock).
 */

import * as api from '../api.js';
import { tg, haptic } from '../tg.js';
import { openSheet, closeSheet } from './sheet.js';
import { showToast } from './toast.js';
import { escapeHtml } from './sanitize.js';

/**
 * Рендерит пошаговый мастер первичной настройки системы (7 шагов, Section 10 & 56).
 */
export async function renderOnboarding(container, onComplete) {
  let step = 1;
  let status = {};

  try {
    status = await api.getSetupStatus();
    if (status.state === 'OWNER_CLAIM') {
      step = 2;
    }
  } catch (e) {
    console.warn('[Onboarding] Ошибка получения статуса:', e);
  }

  function renderStep() {
    container.innerHTML = `
      <div class="page" style="min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px">
        <div class="panel rv in" style="max-width: 440px; width: 100%; padding: 28px 20px; box-sizing: border-box; text-align: center">
          
          <div style="display: flex; justify-content: center; gap: 6px; margin-bottom: 24px">
            ${[1, 2, 3, 4, 5, 6, 7].map(s => `
              <span style="width: 16px; height: 5px; border-radius: 3px; background: ${step >= s ? 'var(--p)' : 'var(--sep)'}"></span>
            `).join('')}
          </div>

          <div id="onboarding-step-body"></div>
        </div>
      </div>
    `;

    const body = container.querySelector('#onboarding-step-body');
    if (!body) return;

    if (step === 1) {
      const user = tg.initDataUnsafe?.user || {};
      body.innerHTML = `
        <div style="width: 60px; height: 60px; margin: 0 auto 16px; border-radius: 50%; background: var(--p-c); color: var(--primary); display: grid; place-items: center">
          <svg style="width: 30px; height: 30px" viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
        </div>
        <h2 style="margin: 0 0 8px; font-size: 20px">Добро пожаловать в Carnaval</h2>
        <p class="tx" style="margin: 0 auto 20px; font-size: 13px; line-height: 1.5; opacity: .7">
          Это первый запуск бота. Зарегистрируйте текущий аккаунт Telegram как владельца системы.
        </p>
        <div class="card glass" style="padding: 12px; margin-bottom: 20px; text-align: left; font-size: 13px">
          <div>Пользователь: <b>${escapeHtml(user.first_name || 'Администратор')}</b></div>
          ${user.username ? `<div style="opacity:.6">@${escapeHtml(user.username)}</div>` : ''}
          <div style="opacity:.5; font-size: 11px; margin-top: 4px">ID: ${escapeHtml(user.id || '—')}</div>
        </div>
        <button id="step1-claim-btn" class="btn press" style="width: 100%; background: var(--p); color: #fff; padding: 12px; font-weight: 600; border-radius: 14px">
          Подтвердить владение
        </button>
      `;

      body.querySelector('#step1-claim-btn')?.addEventListener('click', async () => {
        haptic('impact', 'medium');
        try {
          await api.claimSetup();
          showToast('Владелец успешно зарегистрирован', 'success');
          step = 2;
          renderStep();
        } catch (err) {
          showToast(err.message || 'Ошибка регистрации', 'error');
        }
      });
    } else if (step === 2) {
      body.innerHTML = `
        <div style="width: 60px; height: 60px; margin: 0 auto 16px; border-radius: 50%; background: var(--p-c); color: var(--primary); display: grid; place-items: center">
          <svg style="width: 30px; height: 30px" viewBox="0 0 24 24"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
        </div>
        <h2 style="margin: 0 0 8px; font-size: 20px">Мастер-пароль панели</h2>
        <p class="tx" style="margin: 0 auto 20px; font-size: 13px; line-height: 1.5; opacity: .7">
          Задайте пароль для доступа к панели управления и чувствительным настройкам (хешируется с Argon2id).
        </p>
        <div style="display: flex; flex-direction: column; gap: 10px; margin-bottom: 20px; text-align: left">
          <input id="ob-pwd" type="password" class="inp" placeholder="Пароль (минимум 6 символов)"
            style="width: 100%; background: var(--bg2); border: 1.5px solid var(--sep); border-radius: 12px; padding: 10px 14px; color: var(--tx); font-size: 14px; box-sizing: border-box">
          <input id="ob-pwd-conf" type="password" class="inp" placeholder="Повторите пароль"
            style="width: 100%; background: var(--bg2); border: 1.5px solid var(--sep); border-radius: 12px; padding: 10px 14px; color: var(--tx); font-size: 14px; box-sizing: border-box">
        </div>
        <button id="step2-pwd-btn" class="btn press" style="width: 100%; background: var(--p); color: #fff; padding: 12px; font-weight: 600; border-radius: 14px">
          Сохранить пароль
        </button>
      `;

      body.querySelector('#step2-pwd-btn')?.addEventListener('click', async () => {
        const pwd = document.getElementById('ob-pwd')?.value || '';
        const conf = document.getElementById('ob-pwd-conf')?.value || '';
        if (pwd.length < 6) { showToast('Пароль должен быть не короче 6 символов', 'error'); return; }
        if (pwd !== conf) { showToast('Пароли не совпадают', 'error'); return; }

        haptic('impact', 'medium');
        try {
          await api.setupPassword(pwd);
          showToast('Пароль панели сохранён', 'success');
          step = 3;
          renderStep();
        } catch (err) {
          showToast(err.message || 'Ошибка установки пароля', 'error');
        }
      });
    } else if (step === 3) {
      body.innerHTML = `
        <div style="width: 60px; height: 60px; margin: 0 auto 16px; border-radius: 50%; background: var(--warn-c, #fff3e0); color: var(--warn, #ff9800); display: grid; place-items: center">
          <svg style="width: 30px; height: 30px" viewBox="0 0 24 24"><path d="M21 2l-2 2m-2-2l2 2m0 0l-4 4m2-2l-2-2m-4 8a6 6 0 1 1-6-6c1.7 0 3.2.7 4.2 1.8L19 2"/></svg>
        </div>
        <h2 style="margin: 0 0 8px; font-size: 20px">Golden Key FunPay</h2>
        <p class="tx" style="margin: 0 auto 16px; font-size: 13px; line-height: 1.5; opacity: .7">
          Ключ сессии FunPay (32 hex-символа). Он шифруется AES-256-GCM и сохраняется в защищённом хранилище.
        </p>
        <input id="ob-gk" type="text" class="inp" placeholder="32 символа golden_key" maxlength="32"
          style="width: 100%; background: var(--bg2); border: 1.5px solid var(--sep); border-radius: 12px; padding: 10px 14px; color: var(--tx); font-size: 13px; box-sizing: border-box; margin-bottom: 16px; font-family: monospace">
        <button id="step3-gk-btn" class="btn press" style="width: 100%; background: var(--p); color: #fff; padding: 12px; font-weight: 600; border-radius: 14px; margin-bottom: 10px">
          Сохранить Golden Key
        </button>
        <button id="step3-skip-btn" class="btn press" style="width: 100%; background: transparent; border: 1.5px solid var(--sep); color: var(--tx); padding: 10px; font-size: 13px; border-radius: 14px">
          Пропустить (настроить позже)
        </button>
      `;

      body.querySelector('#step3-gk-btn')?.addEventListener('click', async () => {
        const key = document.getElementById('ob-gk')?.value?.trim() || '';
        if (key.length !== 32) {
          showToast('Golden Key должен содержать ровно 32 символа', 'error');
          return;
        }
        const btn = document.getElementById('step3-gk-btn');
        const origText = btn ? btn.textContent : '';
        if (btn) {
          btn.disabled = true;
          btn.textContent = 'Подключение к FunPay…';
        }
        haptic('impact', 'medium');
        try {
          await api.setupGoldenKey(key);
          showToast('Аккаунт FunPay успешно верифицирован и подключен!', 'success');
          step = 4;
          renderStep();
        } catch (err) {
          showToast(err.message || 'Не удалось подключить аккаунт FunPay', 'error');
        } finally {
          if (btn) {
            btn.disabled = false;
            btn.textContent = origText || 'Сохранить и продолжить';
          }
        }
      });

      body.querySelector('#step3-skip-btn')?.addEventListener('click', () => {
        haptic('selection');
        step = 4;
        renderStep();
      });
    } else if (step === 4) {
      body.innerHTML = `
        <div style="width: 60px; height: 60px; margin: 0 auto 16px; border-radius: 50%; background: var(--p-c); color: var(--primary); display: grid; place-items: center">
          <svg style="width: 30px; height: 30px" viewBox="0 0 24 24"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
        </div>
        <h2 style="margin: 0 0 8px; font-size: 20px">FunPay Аккаунт</h2>
        <p class="tx" style="margin: 0 auto 16px; font-size: 13px; line-height: 1.5; opacity: .7">
          Логин и пароль от учетной записи FunPay (пароль хранится в зашифрованном виде).
        </p>
        <div style="display: flex; flex-direction: column; gap: 10px; margin-bottom: 16px; text-align: left">
          <input id="ob-fp-login" type="text" class="inp" placeholder="Логин FunPay"
            style="width: 100%; background: var(--bg2); border: 1.5px solid var(--sep); border-radius: 12px; padding: 10px 14px; color: var(--tx); font-size: 14px; box-sizing: border-box">
          <input id="ob-fp-pwd" type="password" class="inp" placeholder="Пароль FunPay"
            style="width: 100%; background: var(--bg2); border: 1.5px solid var(--sep); border-radius: 12px; padding: 10px 14px; color: var(--tx); font-size: 14px; box-sizing: border-box">
        </div>
        <div style="display: flex; gap: 8px; margin-bottom: 10px">
          <button id="step4-test-btn" class="btn press" style="flex: 1; background: var(--bg2); border: 1.5px solid var(--sep); color: var(--tx); padding: 10px; font-size: 13px; border-radius: 14px">
            Проверить
          </button>
          <button id="step4-save-btn" class="btn press" style="flex: 2; background: var(--p); color: #fff; padding: 10px; font-weight: 600; font-size: 13px; border-radius: 14px">
            Сохранить
          </button>
        </div>
        <button id="step4-skip-btn" class="btn press" style="width: 100%; background: transparent; border: 1.5px solid var(--sep); color: var(--tx); padding: 10px; font-size: 13px; border-radius: 14px">
          Пропустить
        </button>
      `;

      body.querySelector('#step4-test-btn')?.addEventListener('click', async () => {
        const login = document.getElementById('ob-fp-login')?.value?.trim() || '';
        const pwd = document.getElementById('ob-fp-pwd')?.value || '';
        if (!login || !pwd) { showToast('Заполните логин и пароль', 'error'); return; }
        haptic('selection');
        try {
          const res = await api.testFunPay(login, pwd);
          showToast(res.message || 'Подключение проверено', 'success');
        } catch (e) {
          showToast(e.message || 'Ошибка проверки', 'error');
        }
      });

      body.querySelector('#step4-save-btn')?.addEventListener('click', async () => {
        const login = document.getElementById('ob-fp-login')?.value?.trim() || '';
        const pwd = document.getElementById('ob-fp-pwd')?.value || '';
        if (!login || !pwd) { showToast('Заполните логин и пароль', 'error'); return; }
        haptic('impact', 'medium');
        try {
          await api.setupFunPay(login, pwd);
          showToast('FunPay учетные данные зашифрованы', 'success');
          step = 5;
          renderStep();
        } catch (e) {
          showToast(e.message || 'Ошибка сохранения', 'error');
        }
      });

      body.querySelector('#step4-skip-btn')?.addEventListener('click', () => {
        haptic('selection');
        step = 5;
        renderStep();
      });
    } else if (step === 5) {
      body.innerHTML = `
        <div style="width: 60px; height: 60px; margin: 0 auto 16px; border-radius: 50%; background: var(--p-c); color: var(--primary); display: grid; place-items: center">
          <svg style="width: 30px; height: 30px" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
        </div>
        <h2 style="margin: 0 0 8px; font-size: 20px">Настройка Прокси</h2>
        <p class="tx" style="margin: 0 auto 16px; font-size: 13px; line-height: 1.5; opacity: .7">
          Использование прокси для работы с FunPay (поддержка HTTP/SOCKS5).
        </p>
        <div style="display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; text-align: left">
          <div style="display: flex; gap: 8px">
            <input id="ob-prx-host" type="text" class="inp" placeholder="Хост / IP"
              style="flex: 2; background: var(--bg2); border: 1.5px solid var(--sep); border-radius: 12px; padding: 10px 14px; color: var(--tx); font-size: 14px; box-sizing: border-box">
            <input id="ob-prx-port" type="number" class="inp" placeholder="Порт"
              style="flex: 1; background: var(--bg2); border: 1.5px solid var(--sep); border-radius: 12px; padding: 10px 14px; color: var(--tx); font-size: 14px; box-sizing: border-box">
          </div>
          <input id="ob-prx-user" type="text" class="inp" placeholder="Логин (опционально)"
            style="width: 100%; background: var(--bg2); border: 1.5px solid var(--sep); border-radius: 12px; padding: 10px 14px; color: var(--tx); font-size: 14px; box-sizing: border-box">
          <input id="ob-prx-pwd" type="password" class="inp" placeholder="Пароль (опционально)"
            style="width: 100%; background: var(--bg2); border: 1.5px solid var(--sep); border-radius: 12px; padding: 10px 14px; color: var(--tx); font-size: 14px; box-sizing: border-box">
        </div>
        <div style="display: flex; gap: 8px; margin-bottom: 10px">
          <button id="step5-test-btn" class="btn press" style="flex: 1; background: var(--bg2); border: 1.5px solid var(--sep); color: var(--tx); padding: 10px; font-size: 13px; border-radius: 14px">
            Проверить
          </button>
          <button id="step5-save-btn" class="btn press" style="flex: 2; background: var(--p); color: #fff; padding: 10px; font-weight: 600; font-size: 13px; border-radius: 14px">
            Сохранить
          </button>
        </div>
        <button id="step5-skip-btn" class="btn press" style="width: 100%; background: transparent; border: 1.5px solid var(--sep); color: var(--tx); padding: 10px; font-size: 13px; border-radius: 14px">
          Пропустить (прямое подключение)
        </button>
      `;

      body.querySelector('#step5-test-btn')?.addEventListener('click', async () => {
        const host = document.getElementById('ob-prx-host')?.value?.trim() || '';
        const port = document.getElementById('ob-prx-port')?.value?.trim() || '';
        const user = document.getElementById('ob-prx-user')?.value?.trim() || '';
        const pwd = document.getElementById('ob-prx-pwd')?.value || '';
        if (!host || !port) { showToast('Укажите хост и порт прокси', 'error'); return; }
        haptic('selection');
        try {
          const res = await api.testProxy(host, port, user, pwd);
          showToast(res.message || 'Прокси доступен', 'success');
        } catch (e) {
          showToast(e.message || 'Ошибка проверки', 'error');
        }
      });

      body.querySelector('#step5-save-btn')?.addEventListener('click', async () => {
        const host = document.getElementById('ob-prx-host')?.value?.trim() || '';
        const port = document.getElementById('ob-prx-port')?.value?.trim() || '';
        const user = document.getElementById('ob-prx-user')?.value?.trim() || '';
        const pwd = document.getElementById('ob-prx-pwd')?.value || '';
        if (!host || !port) { showToast('Укажите хост и порт прокси', 'error'); return; }
        haptic('impact', 'medium');
        try {
          await api.setupProxy(host, port, user, pwd);
          showToast('Настройки прокси сохранены', 'success');
          step = 6;
          renderStep();
        } catch (e) {
          showToast(e.message || 'Ошибка сохранения', 'error');
        }
      });

      body.querySelector('#step5-skip-btn')?.addEventListener('click', () => {
        haptic('selection');
        step = 6;
        renderStep();
      });
    } else if (step === 6) {
      body.innerHTML = `
        <div style="width: 60px; height: 60px; margin: 0 auto 16px; border-radius: 50%; background: var(--ok-c, #e8f5e9); color: var(--ok, #4caf50); display: grid; place-items: center">
          <svg style="width: 30px; height: 30px" viewBox="0 0 24 24"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
        </div>
        <h2 style="margin: 0 0 8px; font-size: 20px">Проверка системы</h2>
        <p class="tx" style="margin: 0 auto 16px; font-size: 13px; line-height: 1.5; opacity: .7">
          Проверка ключевых сервисов перед запуском:
        </p>
        <div id="check-list" class="card glass" style="padding: 14px; margin-bottom: 20px; text-align: left; font-size: 13px; line-height: 2">
          <div>Проверка компонентов...</div>
        </div>
        <button id="step6-next-btn" class="btn press" style="width: 100%; background: var(--p); color: #fff; padding: 12px; font-weight: 600; border-radius: 14px">
          Продолжить
        </button>
      `;

      // Асинхронно обновляем чек-лист
      (async () => {
        try {
          const s = await api.getSetupStatus();
          const checkEl = body.querySelector('#check-list');
          if (checkEl) {
            checkEl.innerHTML = `
              <div>${s.has_owner ? '✅' : '❌'} Владелец: ${s.has_owner ? 'Зарегистрирован' : 'Не найден'}</div>
              <div>${s.has_password ? '✅' : '❌'} Мастер-пароль (Argon2id): ${s.has_password ? 'Активен' : 'Не задан'}</div>
              <div>${s.has_golden_key ? '✅' : '⚪'} Golden Key: ${s.has_golden_key ? 'Зашифрован' : 'Пропущен'}</div>
              <div>${s.has_funpay ? '✅' : '⚪'} FunPay аккаунт: ${s.has_funpay ? 'Настроен' : 'Пропущен'}</div>
              <div>${s.has_proxy ? '✅' : '⚪'} Прокси: ${s.has_proxy ? 'Настроен' : 'Прямое подключение'}</div>
              <div>🔒 Хранилище: AES-256-GCM в защищённом томе</div>
            `;
          }
        } catch {}
      })();

      body.querySelector('#step6-next-btn')?.addEventListener('click', () => {
        haptic('selection');
        step = 7;
        renderStep();
      });
    } else if (step === 7) {
      body.innerHTML = `
        <div style="width: 60px; height: 60px; margin: 0 auto 16px; border-radius: 50%; background: var(--ok-c, #e8f5e9); color: var(--ok, #4caf50); display: grid; place-items: center">
          <svg style="width: 30px; height: 30px" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>
        </div>
        <h2 style="margin: 0 0 8px; font-size: 20px">Всё готово к работе!</h2>
        <p class="tx" style="margin: 0 auto 20px; font-size: 13px; line-height: 1.5; opacity: .7">
          Первоначальная настройка завершена. Нажмите кнопку ниже для финализации и входа в панель управления.
        </p>
        <button id="step7-fin-btn" class="btn press" style="width: 100%; background: var(--p); color: #fff; padding: 12px; font-weight: 600; border-radius: 14px">
          Завершить настройку и войти
        </button>
      `;

      body.querySelector('#step7-fin-btn')?.addEventListener('click', async () => {
        haptic('notification', 'success');
        try {
          await api.finalizeSetup();
          showToast('Система активирована!', 'success');
          onComplete?.();
        } catch (err) {
          showToast(err.message || 'Ошибка финализации', 'error');
        }
      });
    }
  }

  renderStep();
}

/**
 * Модальное окно разблокировки панели паролем при событии carnaval:panel_locked.
 */
let _isUnlockSheetOpen = false;

export function openPanelUnlockModal(onUnlocked) {
  if (_isUnlockSheetOpen) return;
  _isUnlockSheetOpen = true;

  openSheet({
    title: '🔒 Разблокировка панели',
    content: `
      <p class="tx" style="font-size: 13px; opacity: .7; margin-bottom: 14px">
        Для выполнения этой операции введите мастер-пароль панели управления:
      </p>
      <input id="modal-unlock-pwd" type="password" class="inp" placeholder="Пароль панели"
        style="width: 100%; background: var(--bg2); border: 1.5px solid var(--sep); border-radius: 12px; padding: 10px 14px; color: var(--tx); font-size: 14px; box-sizing: border-box; margin-bottom: 12px">
      <div id="unlock-err-msg" style="color: var(--danger, #ff4d4f); font-size: 12px; display: none; margin-bottom: 10px"></div>
    `,
    actions: [
      {
        label: 'Отмена',
        style: 'secondary',
        onClick: () => {
          _isUnlockSheetOpen = false;
          closeSheet();
        },
      },
      {
        label: 'Разблокировать',
        style: 'primary',
        onClick: async () => {
          const pwd = document.getElementById('modal-unlock-pwd')?.value || '';
          const errEl = document.getElementById('unlock-err-msg');
          if (!pwd) {
            if (errEl) {
              errEl.textContent = 'Введите пароль';
              errEl.style.display = 'block';
            }
            return;
          }

          try {
            await api.panelUnlock(pwd);
            _isUnlockSheetOpen = false;
            closeSheet();
            showToast('Панель успешно разблокирована', 'success');
            onUnlocked?.();
          } catch (err) {
            if (errEl) {
              errEl.textContent = err.message || 'Неверный пароль';
              errEl.style.display = 'block';
            }
          }
        },
      },
    ],
    onClose: () => {
      _isUnlockSheetOpen = false;
    },
  });
}

/**
 * ui/sheet.js — модальная нижняя шторка (iOS Liquid Glass Presentation Sheet).
 * Реализовано в точности по mattering.html:
 *   - Фон #app уменьшается до scale(0.93), translateY(12px), filter(brightness(0.82))
 *   - Шторка следует за пальцем при перетаскивании за шапку (.hd)
 *   - Прерывание и пружинный возврат при отпускании
 */

import { tg } from '../tg.js';

let _sheetEl = null;
let _scrimEl = null;
let _titleEl = null;
let _contentEl = null;
let _onCloseCallback = null;

let _drag = 0;
let _y0 = 0;
let _t0 = 0;
let _dy = 0;

export function initSheet() {
  _sheetEl = document.getElementById('sheet');
  _scrimEl = document.getElementById('scrim');
  _titleEl = document.getElementById('sheet-title');
  _contentEl = document.getElementById('sheet-content');
  const hd = document.getElementById('hd');
  const app = document.getElementById('app');

  if (!_sheetEl || !hd) return;

  _scrimEl?.addEventListener('click', () => closeSheet());

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && document.body.classList.contains('open')) {
      closeSheet();
    }
  });

  // Жест перетаскивания шторки вниз за заголовок
  hd.addEventListener('pointerdown', (e) => {
    _drag = 1;
    _y0 = e.clientY;
    _t0 = e.timeStamp;
    _dy = 0;
    _sheetEl.style.transition = 'none';
    if (app) app.style.transition = 'none';
    hd.setPointerCapture(e.pointerId);
  });

  hd.addEventListener('pointermove', (e) => {
    if (!_drag) return;
    _dy = e.clientY - _y0;
    const p = Math.max(0, Math.min(1, _dy / (_sheetEl.offsetHeight || 300)));
    _sheetEl.style.transform = `translate(-50%, ${_dy < 0 ? _dy * 0.12 : _dy}px)`;
    if (app) {
      app.style.transform = `scale(${0.93 + 0.07 * p}) translateY(${12 * (1 - p)}px)`;
      app.style.filter = `brightness(${0.82 + 0.18 * p})`;
    }
  });

  const endDrag = (e) => {
    if (!_drag) return;
    _drag = 0;
    const v = _dy / Math.max(1, e.timeStamp - _t0);
    _sheetEl.style.transition = '';
    if (app) {
      app.style.transition = '';
      app.style.transform = '';
      app.style.filter = '';
    }
    _sheetEl.style.transform = '';
    if (_dy > 110 || v > 0.6) {
      closeSheet();
    }
  };

  hd.addEventListener('pointerup', endDrag);
  hd.addEventListener('pointercancel', endDrag);
}

/**
 * Открыть шторку с заголовком и HTML содержимым (поддерживает и объект с actions, и (title, html)).
 */
export function openSheet(titleOrOptions, maybeContentHTML = '', onClose = null) {
  if (!_sheetEl) initSheet();

  let title = '';
  let contentHTML = '';
  let actions = null;
  let cb = onClose;

  if (typeof titleOrOptions === 'object' && titleOrOptions !== null) {
    title = titleOrOptions.title || '';
    contentHTML = titleOrOptions.content || '';
    actions = titleOrOptions.actions || null;
    cb = titleOrOptions.onClose || onClose;
  } else {
    title = String(titleOrOptions || '');
    contentHTML = String(maybeContentHTML || '');
  }

  if (actions && Array.isArray(actions)) {
    const actBtns = actions.map((a, i) => {
      const cls = a.style === 'danger' ? 'btn err press' : a.style === 'secondary' ? 'btn tn press' : 'btn ok press';
      return `<button class="${cls}" data-act-idx="${i}" style="flex:1">${a.label}</button>`;
    }).join('');
    contentHTML += `<div class="btns" style="display:flex;gap:10px;margin-top:20px">${actBtns}</div>`;
  }

  if (_titleEl) _titleEl.textContent = title;
  if (_contentEl) {
    _contentEl.innerHTML = contentHTML;
    if (actions && Array.isArray(actions)) {
      _contentEl.querySelectorAll('[data-act-idx]').forEach(btn => {
        const idx = Number(btn.dataset.actIdx);
        btn.addEventListener('click', (e) => actions[idx]?.onClick?.(e));
      });
    }
  }
  _onCloseCallback = cb;

  document.body.classList.add('open');
  const app = document.getElementById('app');
  if (app) app.inert = true;
  tg.haptic.impact('light');
}

/**
 * Закрыть шторку.
 */
export function closeSheet() {
  document.body.classList.remove('open');
  const app = document.getElementById('app');
  if (app) app.inert = false;
  tg.haptic.selection();
  if (_onCloseCallback) {
    const cb = _onCloseCallback;
    _onCloseCallback = null;
    cb();
  }
}

/**
 * Открыть диалог подтверждения (Confirm Sheet) для опасных действий.
 * Поддерживает как openConfirmSheet('Текст', onConfirm), так и openConfirmSheet({ ... }).
 */
export function openConfirmSheet(optionsOrMessage, maybeOnConfirm) {
  let title = 'Подтверждение';
  let message = '';
  let confirmText = 'Подтвердить';
  let danger = true;
  let onConfirm = null;

  if (typeof optionsOrMessage === 'string') {
    message = optionsOrMessage;
    onConfirm = maybeOnConfirm;
  } else if (optionsOrMessage && typeof optionsOrMessage === 'object') {
    title = optionsOrMessage.title || title;
    message = optionsOrMessage.message || '';
    confirmText = optionsOrMessage.confirmText || confirmText;
    danger = optionsOrMessage.danger !== false;
    onConfirm = optionsOrMessage.onConfirm;
  }

  const content = `
    <p class="tx" style="margin-bottom: 20px">${message}</p>
    <div class="btns" style="display:flex;gap:10px">
      <button class="btn ${danger ? 'err' : 'ok'} press" id="confirm-action-btn" style="flex:1">${confirmText}</button>
      <button class="btn tn press" id="cancel-action-btn" style="flex:1">Отмена</button>
    </div>
  `;

  openSheet(title, content);

  document.getElementById('confirm-action-btn')?.addEventListener('click', () => {
    closeSheet();
    onConfirm?.();
  });

  document.getElementById('cancel-action-btn')?.addEventListener('click', () => {
    closeSheet();
  });
}

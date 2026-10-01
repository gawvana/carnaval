/**
 * ui/dock.js — нижний плавающий элемент управления: FAB + Dock с линзой.
 * Из mattering.html: .chrome > .fab + .dock.glass > .lens + .tab*5
 */

import { tg } from '../tg.js';
import { openSheet, closeSheet } from './sheet.js';
import { t } from '../i18n.js';

export function renderDock(tabs, onSelect) {
  const chrome = document.createElement('div');
  chrome.className = 'chrome';
  chrome.id = 'chrome';

  // ── FAB (Floating Action Button) ──
  const fab = document.createElement('button');
  fab.className = 'fab press';
  fab.id = 'fab';
  fab.setAttribute('aria-label', t('create_action'));
  fab.innerHTML = `<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>`;
  fab.addEventListener('click', () => {
    tg.haptic.impact('medium');
    openCreateSheet();
  });
  chrome.appendChild(fab);

  // ── Dock ──
  const dock = document.createElement('nav');
  dock.className = 'dock glass';
  dock.setAttribute('aria-label', 'Разделы');

  const lens = document.createElement('i');
  lens.className = 'lens';
  dock.appendChild(lens);

  const tabEls = tabs.map((t) => {
    const btn = document.createElement('button');
    btn.className = 'tab';
    btn.dataset.id = t.id;
    btn.innerHTML = `${t.icon}<span>${t.label}</span>`;
    dock.appendChild(btn);
    return btn;
  });

  chrome.appendChild(dock);

  let current = 0;

  function setActive(id) {
    const idx = tabs.findIndex(t => t.id === id);
    if (idx < 0) return;
    current = idx;
    dock.style.setProperty('--i', String(idx));
    tabEls.forEach((b, j) => b.classList.toggle('on', j === idx));
  }

  // ── Drag-select (функция pick() из mattering.html) ──
  let dragging = false;
  function atIdx(e) {
    const r = dock.getBoundingClientRect();
    const pad = 8;
    const n = tabs.length;
    return Math.max(0, Math.min(n - 1,
      Math.floor((e.clientX - r.left - pad) / ((r.width - 2 * pad) / n))
    ));
  }

  dock.addEventListener('pointerdown', (e) => {
    dragging = true;
    dock.classList.add('lift');
    dock.setPointerCapture(e.pointerId);
    const i = atIdx(e);
    tg.haptic.selection();
    onSelect(tabs[i].id);
  });

  dock.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    const i = atIdx(e);
    if (i !== current) {
      tg.haptic.selection();
      onSelect(tabs[i].id);
    }
  });

  const endDrag = () => {
    dragging = false;
    dock.classList.remove('lift');
  };

  dock.addEventListener('pointerup', endDrag);
  dock.addEventListener('pointercancel', endDrag);

  // Click fallback
  tabEls.forEach((btn, i) => {
    btn.addEventListener('click', (e) => {
      tg.haptic.impact('light');
      onSelect(tabs[i].id);
    });
  });

  return { el: chrome, setActive, fab };
}

function openCreateSheet() {
  const content = `
    <button class="opt press" id="action-create-lot">
      <em style="background:var(--ok-c);color:var(--on-ok-c)">
        <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
      </em>
      <div>
        <b>Автовыдачу</b>
        <span class="tx" style="font-size:12px;margin:0;display:block">Привязать товар или текст к лоту</span>
      </div>
    </button>
    <button class="opt press" id="action-create-file">
      <em style="background:var(--p);color:var(--on-p)">
        <svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M12 18v-6M9 15h6"/></svg>
      </em>
      <div>
        <b>${t('action_product_file')}</b>
        <span class="tx" style="font-size:12px;margin:0;display:block">Файл со списком товаров</span>
      </div>
    </button>
    <button class="opt press" id="action-create-cmd">
      <em style="background:var(--t);color:var(--on-t)">
        <svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
      </em>
      <div>
        <b>${t('action_auto_response')}</b>
        <span class="tx" style="font-size:12px;margin:0;display:block">Ответ на ключевые слова</span>
      </div>
    </button>
    <button class="opt press" id="action-create-tmplt">
      <em style="background:var(--s);color:var(--on-s)">
        <svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 9h8M8 13h6"/></svg>
      </em>
      <div>
        <b>${t('action_template')}</b>
        <span class="tx" style="font-size:12px;margin:0;display:block">Заготовка для ручных ответов</span>
      </div>
    </button>
  `;

  openSheet(t('create_action'), content);

  const goToAuto = () => {
    closeSheet();
    location.hash = 'automation';
  };

  document.getElementById('action-create-lot')?.addEventListener('click', goToAuto);
  document.getElementById('action-create-file')?.addEventListener('click', goToAuto);
  document.getElementById('action-create-cmd')?.addEventListener('click', goToAuto);
  document.getElementById('action-create-tmplt')?.addEventListener('click', goToAuto);
}

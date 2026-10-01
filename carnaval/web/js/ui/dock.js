/**
 * ui/dock.js — нижний плавающий элемент управления: Dock с линзой.
 * Структура: .chrome > .dock.glass > .lens + .tab*5
 */

import { tg } from '../tg.js';
import { getIcon } from './icons.js';

export function renderDock(tabs, onSelect) {
  const chrome = document.createElement('div');
  chrome.className = 'chrome';
  chrome.id = 'chrome';

  // ── Dock ──
  const dock = document.createElement('nav');
  dock.className = 'dock glass';
  dock.setAttribute('aria-label', 'Разделы');

  const lens = document.createElement('i');
  lens.className = 'lens';
  dock.appendChild(lens);

  const tabEls = tabs.map((tab) => {
    const btn = document.createElement('button');
    btn.className = 'tab';
    btn.dataset.id = tab.id;
    
    // Гарантируем семантические SVG-иконки без эмодзи
    let iconHtml = tab.icon;
    if (!iconHtml || !iconHtml.trim().startsWith('<svg')) {
      const iconKey = tab.id === 'dashboard' ? 'home' : tab.id;
      iconHtml = getIcon(iconKey);
    }
    
    btn.innerHTML = `${iconHtml}<span>${tab.label}</span>`;
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
    btn.addEventListener('click', () => {
      tg.haptic.impact('light');
      onSelect(tabs[i].id);
    });
  });

  return { el: chrome, setActive };
}

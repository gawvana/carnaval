/**
 * ui/header.js — прилипающая стеклянная шапка (Sticky Glass Header).
 * Включает логотип/заголовок, аватар/ник продавца, переключатель темы.
 */

import { tg } from '../tg.js';

const MOON_ICON = `<svg viewBox="0 0 24 24"><path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/></svg>`;
const SUN_ICON = `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6L7 7M17 17l1.4 1.4M18.4 5.6L17 7M7 17l-1.4 1.4"/></svg>`;

export function renderHeader({ title = 'Carnaval', subtitle = '', showThemeToggle = true, onThemeToggle = null }) {
  const header = document.createElement('header');
  header.className = 'nav glass rv in';

  const left = document.createElement('b');
  left.innerHTML = `
    <svg style="width:20px;height:20px;color:var(--primary)" viewBox="0 0 24 24" fill="none" stroke="currentColor">
      <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
    </svg>
    <span>${title}</span>
  `;

  header.appendChild(left);

  const right = document.createElement('div');
  right.style.display = 'flex';
  right.style.alignItems = 'center';
  right.style.gap = '8px';

  if (subtitle) {
    const sub = document.createElement('span');
    sub.style.fontSize = '13px';
    sub.style.fontWeight = '600';
    sub.style.color = 'var(--muted)';
    sub.textContent = subtitle;
    right.appendChild(sub);
  }

  if (showThemeToggle) {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark'
      || window.matchMedia('(prefers-color-scheme: dark)').matches;

    const themeBtn = document.createElement('button');
    themeBtn.className = 'ib press';
    themeBtn.setAttribute('aria-label', 'Сменить тему');
    themeBtn.innerHTML = isDark ? SUN_ICON : MOON_ICON;

    themeBtn.addEventListener('click', () => {
      tg.haptic.selection();
      const current = document.documentElement.getAttribute('data-theme') || (isDark ? 'dark' : 'light');
      const next = current === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      themeBtn.innerHTML = next === 'dark' ? SUN_ICON : MOON_ICON;
      onThemeToggle?.(next);
    });

    right.appendChild(themeBtn);
  }

  header.appendChild(right);
  return header;
}

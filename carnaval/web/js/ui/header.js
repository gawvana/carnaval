/**
 * ui/header.js — прилипающая стеклянная шапка (Sticky Glass Header).
 * Включает логотип/заголовок, аватар/ник продавца, переключатель темы и интерактивную кнопку профиля.
 */

import { tg } from '../tg.js';
import { getIcon } from './icons.js';

export function renderHeader({ title = 'Carnaval', subtitle = '', showThemeToggle = true, onThemeToggle = null, showProfile = true }) {
  const header = document.createElement('header');
  header.className = 'nav glass rv in';

  const left = document.createElement('b');
  left.style.display = 'flex';
  left.style.alignItems = 'center';
  left.style.gap = '8px';
  left.style.cursor = 'pointer';
  left.innerHTML = `
    <span style="display:inline-flex;color:var(--primary)">
      ${getIcon('funpay')}
    </span>
    <span>${title}</span>
  `;
  left.addEventListener('click', () => {
    tg.haptic.selection();
    location.hash = 'dashboard';
  });

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
    themeBtn.innerHTML = isDark ? getIcon('sun') : getIcon('moon');

    themeBtn.addEventListener('click', () => {
      tg.haptic.selection();
      const current = document.documentElement.getAttribute('data-theme') || (isDark ? 'dark' : 'light');
      const next = current === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      themeBtn.innerHTML = next === 'dark' ? getIcon('sun') : getIcon('moon');
      onThemeToggle?.(next);
    });

    right.appendChild(themeBtn);
  }

  if (showProfile) {
    const profileBtn = document.createElement('button');
    profileBtn.className = 'ib press';
    profileBtn.id = 'header-profile-btn';
    profileBtn.setAttribute('aria-label', 'Профиль');
    profileBtn.style.position = 'relative';

    const photoUrl = tg.user?.photo_url;
    if (photoUrl) {
      profileBtn.innerHTML = `<img src="${photoUrl}" alt="Avatar" style="width:28px;height:28px;border-radius:50%;object-fit:cover;border:1.5px solid var(--primary);display:block">`;
    } else {
      profileBtn.innerHTML = getIcon('profile');
    }

    profileBtn.addEventListener('click', () => {
      tg.haptic.impact('light');
      location.hash = 'profile';
    });

    right.appendChild(profileBtn);
  }

  header.appendChild(right);
  return header;
}

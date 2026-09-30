/**
 * router.js — хэш-роутер для SPA.
 * Маршруты: #dashboard (default), #orders, #chats, #automation, #more
 */

import { renderDashboard } from './pages/dashboard.js';
import { renderOrders } from './pages/orders.js';
import { renderChats } from './pages/chats.js';
import { renderAutomation } from './pages/automation.js';
import { renderMore } from './pages/more.js';
import { renderDock } from './ui/dock.js';

const ROUTES = {
  dashboard: renderDashboard,
  orders:    renderOrders,
  chats:     renderChats,
  automation:renderAutomation,
  more:      renderMore,
};

const DEFAULT_ROUTE = 'dashboard';

const TABS = [
  { id: 'dashboard',  label: 'Главная',       icon: homeIcon() },
  { id: 'orders',     label: 'Заказы',        icon: ordersIcon() },
  { id: 'chats',      label: 'Чаты',          icon: chatsIcon() },
  { id: 'automation', label: 'Авто',          icon: autoIcon() },
  { id: 'more',       label: 'Ещё',           icon: moreIcon() },
];

class Router {
  constructor() {
    this._current = null;
    this._dock = null;
  }

  async init() {
    const app = document.getElementById('app');

    // Структура приложения
    app.innerHTML = `
      <div class="page">
        <div class="aur" id="aur">
          <i class="b" style="--c:var(--p);--k:-.12;left:-160px;top:40px"></i>
          <i class="b" style="--c:var(--t);--k:-.2;right:-200px;top:22%"></i>
          <i class="b" style="--c:var(--primary);--k:-.08;left:-200px;top:48%;opacity:.35"></i>
          <i class="b" style="--c:var(--t);--k:-.15;right:-160px;top:74%"></i>
        </div>
        <div class="wrap" id="main-wrap"></div>
      </div>
    `;

    // Dock
    this._dock = renderDock(TABS, (id) => this.navigate(id));
    document.body.appendChild(this._dock.el);

    // Toast контейнер
    const tc = document.createElement('div');
    tc.className = 'toast-container';
    tc.id = 'toasts';
    document.body.appendChild(tc);

    // Scroll → collapse dock
    app.addEventListener('scroll', () => {
      const y = app.scrollTop;
      app.classList.toggle('sc', y > 30);
      document.getElementById('aur')?.style.setProperty('--sy', String(y));
      const ch = document.getElementById('chrome');
      if (ch) ch.classList.toggle('min', y > 120);
    }, { passive: true });

    // Начальный маршрут
    const hash = location.hash.replace('#', '') || DEFAULT_ROUTE;
    await this.navigate(hash in ROUTES ? hash : DEFAULT_ROUTE);

    window.addEventListener('hashchange', async () => {
      const id = location.hash.replace('#', '') || DEFAULT_ROUTE;
      await this.navigate(id in ROUTES ? id : DEFAULT_ROUTE);
    });
  }

  async navigate(id) {
    if (id === this._current) return;
    this._current = id;
    location.hash = id;
    this._dock?.setActive(id);

    const wrap = document.getElementById('main-wrap');
    if (!wrap) return;
    wrap.innerHTML = '';

    try {
      await ROUTES[id](wrap);
    } catch (e) {
      console.error('[router] render error', e);
      wrap.innerHTML = `<p class="tx" style="padding:32px">Ошибка загрузки</p>`;
    }

    // Scroll-reveal
    const io = new IntersectionObserver((es) => {
      es.forEach(e => { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } });
    }, { root: document.getElementById('app'), threshold: .1 });
    wrap.querySelectorAll('.rv').forEach(n => io.observe(n));
  }

  getCurrentRoute() {
    return this._current || DEFAULT_ROUTE;
  }

  async reload() {
    const id = this.getCurrentRoute();
    const wrap = document.getElementById('main-wrap');
    if (!wrap || !ROUTES[id]) return;
    try {
      wrap.innerHTML = '';
      await ROUTES[id](wrap);
    } catch (e) {
      console.error('[router] reload error', e);
    }
  }
}

export const router = new Router();

// ── SVG иконки ──────────────────────────────────────────────────
function homeIcon() {
  return `<svg viewBox="0 0 24 24"><path d="M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z"/></svg>`;
}
function ordersIcon() {
  return `<svg viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="15" rx="3.5"/><path d="M8 3v4M16 3v4M4 10h16"/></svg>`;
}
function chatsIcon() {
  return `<svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`;
}
function autoIcon() {
  return `<svg viewBox="0 0 24 24"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>`;
}
function moreIcon() {
  return `<svg viewBox="0 0 24 24"><circle cx="12" cy="5" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="12" cy="19" r="1"/></svg>`;
}

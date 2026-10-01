/**
 * router.js — хэш-роутер для SPA.
 * Маршруты: #dashboard (default), #orders, #chats, #automation, #more, #profile
 */

import { renderDashboard } from './pages/dashboard.js';
import { renderOrders } from './pages/orders.js';
import { renderChats } from './pages/chats.js';
import { renderAutomation } from './pages/automation.js';
import { renderMore } from './pages/more.js';
import { renderProfile } from './pages/profile.js';
import { renderDock } from './ui/dock.js';
import { getIcon } from './ui/icons.js';

const ROUTES = {
  dashboard:  renderDashboard,
  orders:     renderOrders,
  chats:      renderChats,
  automation: renderAutomation,
  more:       renderMore,
  profile:    renderProfile,
  '/profile': renderProfile,
};

const DEFAULT_ROUTE = 'dashboard';

const TABS = [
  { id: 'dashboard',  label: 'Главная',       icon: getIcon('home') },
  { id: 'orders',     label: 'Заказы',        icon: getIcon('orders') },
  { id: 'chats',      label: 'Чаты',          icon: getIcon('chats') },
  { id: 'automation', label: 'Авто',          icon: getIcon('automation') },
  { id: 'more',       label: 'Ещё',           icon: getIcon('more') },
];

function resolveRoute(hash) {
  const clean = (hash || '').replace(/^#\/?/, '').trim();
  if (clean === 'profile' || clean === '/profile') return 'profile';
  return clean in ROUTES ? clean : DEFAULT_ROUTE;
}

class Router {
  constructor() {
    this._current = null;
    this._dock = null;
    this._abortController = null;
    this._unmountCurrent = null;
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
    const initialRoute = resolveRoute(location.hash);
    await this.navigate(initialRoute);

    window.addEventListener('hashchange', async () => {
      const targetRoute = resolveRoute(location.hash);
      await this.navigate(targetRoute);
    });
  }

  async navigate(id) {
    const routeId = resolveRoute(id);
    if (routeId === this._current) return;

    if (this._abortController) {
      try {
        this._abortController.abort('Navigation');
      } catch (e) {}
    }
    this._abortController = new AbortController();

    if (typeof this._unmountCurrent === 'function') {
      try {
        this._unmountCurrent();
      } catch (e) {}
      this._unmountCurrent = null;
    }

    this._current = routeId;
    location.hash = routeId;
    this._dock?.setActive(routeId);

    const wrap = document.getElementById('main-wrap');
    if (!wrap) return;
    wrap.innerHTML = '';

    try {
      const routeHandler = ROUTES[routeId] || ROUTES[DEFAULT_ROUTE];
      const cleanup = await routeHandler(wrap, { signal: this._abortController.signal });
      if (typeof cleanup === 'function') {
        this._unmountCurrent = cleanup;
      }
    } catch (e) {
      if (e?.name === 'AbortError' || e?.message === 'Navigation') return;
      console.error('[router] render error', e);
      wrap.innerHTML = `<p class="tx" style="padding:32px">Ошибка загрузки</p>`;
    }

    this._observeReveal(wrap);
  }

  _observeReveal(wrap) {
    if (!wrap) return;
    const io = new IntersectionObserver((es) => {
      es.forEach(e => {
        if (e.isIntersecting) {
          e.target.classList.add('in');
          io.unobserve(e.target);
        }
      });
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
      this._observeReveal(wrap);
    } catch (e) {
      console.error('[router] reload error', e);
    }
  }
}

export const router = new Router();

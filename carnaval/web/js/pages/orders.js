/**
 * pages/orders.js — Экран заказов продавца.
 * Фильтрация по статусам (Все / Оплачены / Закрыты / Возврат),
 * просмотр деталей в Liquid Glass Sheet, возврат средств с Confirm-шторкой,
 * ответы на отзывы.
 */

import { getOrders, getOrderDetails, refundOrder } from '../api.js';
import { tg } from '../tg.js';
import { renderHeader } from '../ui/header.js';
import { openSheet, closeSheet, openConfirmSheet } from '../ui/sheet.js';
import { showToast } from '../ui/toast.js';
import { escapeHtml } from '../ui/sanitize.js';

let _currentStatus = null;
let _nextOrderId = null;
let _ordersList = [];

export async function renderOrders(wrap) {
  wrap.innerHTML = '';

  const header = renderHeader({
    title: 'Заказы',
    subtitle: 'Управление продажами',
  });
  wrap.appendChild(header);

  const container = document.createElement('div');
  container.style.paddingTop = '68px';
  container.innerHTML = `
    <!-- Фильтр-сегмент (Mattering .seg) -->
    <div class="seg rv in" id="orders-filter" style="--seg-cols: 4; margin-bottom: 16px">
      <i></i>
      <button class="on" data-status="">Все</button>
      <button data-status="paid">Оплачен</button>
      <button data-status="closed">Закрыт</button>
      <button data-status="refunded">Возврат</button>
    </div>

    <!-- Список заказов -->
    <div id="orders-list-content">
      ${renderOrdersSkeleton()}
    </div>

    <!-- Кнопка пагинации -->
    <div id="orders-load-more" style="display:none; margin-top:16px; text-align:center">
      <button class="btn tn press" id="load-more-btn" style="width:100%; max-width:320px; margin:0 auto">Загрузить ещё</button>
    </div>
  `;
  wrap.appendChild(container);

  // Инициализация сегментного переключателя
  initOrdersFilter(container);

  // Загрузка первой страницы
  await loadOrders(true);
}

function initOrdersFilter(root) {
  const seg = root.querySelector('#orders-filter');
  if (!seg) return;
  const buttons = seg.querySelectorAll('button');

  buttons.forEach((btn, idx) => {
    btn.addEventListener('click', async () => {
      tg.haptic.selection();
      buttons.forEach((b) => b.classList.remove('on'));
      btn.classList.add('on');
      seg.style.setProperty('--k', String(idx));

      _currentStatus = btn.dataset.status || null;
      _nextOrderId = null;
      await loadOrders(true);
    });
  });
}

async function loadOrders(isRefresh = false) {
  const content = document.getElementById('orders-list-content');
  const loadMore = document.getElementById('orders-load-more');
  if (!content) return;

  if (isRefresh) {
    content.innerHTML = renderOrdersSkeleton();
    _ordersList = [];
  }

  try {
    const res = await getOrders(_currentStatus, _nextOrderId, 20);

    if (res.ok === false || res.error_code) {
      const isNotInit = res.error_code === 'FUNPAY_ACCOUNT_NOT_INITIALIZED';
      const title = isNotInit ? 'Аккаунт FunPay не подключен' : 'Ошибка загрузки заказов';
      const msg = res.message || (isNotInit ? 'Требуется подключить Golden Key в настройках.' : 'Не удалось связаться с сервером FunPay.');

      content.innerHTML = `
        <div class="card rv in" style="padding:24px 18px; text-align:center; margin-top:16px; border:1px solid color-mix(in srgb, var(--err) 30%, transparent); background:color-mix(in srgb, var(--err) 8%, var(--surface))">
          <div style="width:52px; height:52px; border-radius:50%; background:var(--err-c); color:var(--on-err-c); display:grid; place-items:center; margin:0 auto 12px">
            <svg viewBox="0 0 24 24" style="width:26px;height:26px;stroke-width:2;stroke:currentColor;fill:none"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          </div>
          <b style="font-size:17px; display:block; margin-bottom:6px">${escapeHtml(title)}</b>
          <p style="font-size:13px; color:var(--muted); margin:0 auto 16px; max-width:320px">${escapeHtml(msg)}</p>
          
          <div style="display:flex; justify-content:center; gap:10px; flex-wrap:wrap">
            ${isNotInit ? `
              <button class="btn press" id="go-setup-key-orders-btn" style="height:40px; padding:0 18px; font-size:13px">Настроить аккаунт</button>
            ` : ''}
            <button class="btn tn press" id="retry-orders-btn" style="height:40px; padding:0 18px; font-size:13px">Повторить попытку</button>
          </div>
        </div>
      `;

      content.querySelector('#go-setup-key-orders-btn')?.addEventListener('click', () => {
        location.hash = 'more';
      });

      content.querySelector('#retry-orders-btn')?.addEventListener('click', () => {
        loadOrders(true);
      });

      if (loadMore) loadMore.style.display = 'none';
      return;
    }

    _nextOrderId = res.next_order_id;

    if (isRefresh) {
      _ordersList = res.orders || [];
    } else {
      _ordersList.push(...(res.orders || []));
    }

    if (_ordersList.length === 0) {
      content.innerHTML = `
        <div class="empty rv in">
          <svg viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="15" rx="3.5"/><path d="M8 3v4M16 3v4M4 10h16"/></svg>
          <p>Заказов не найдено</p>
        </div>
      `;
      if (loadMore) loadMore.style.display = 'none';
      return;
    }

    content.innerHTML = `
      <div style="display:grid; gap:10px">
        ${_ordersList.map(renderOrderCardHTML).join('')}
      </div>
    `;

    // Привязка кликов для открытия деталей
    content.querySelectorAll('.order-card-btn').forEach((card) => {
      card.addEventListener('click', () => {
        const orderId = card.dataset.id;
        openOrderDetailsModal(orderId);
      });
    });

    if (loadMore) {
      loadMore.style.display = _nextOrderId ? 'block' : 'none';
      const btn = loadMore.querySelector('#load-more-btn');
      if (btn) {
        btn.onclick = () => loadOrders(false);
      }
    }
  } catch (err) {
    content.innerHTML = `
      <div class="empty rv in">
        <p style="color:var(--err)">Ошибка загрузки заказов<br><small>${err.message}</small></p>
        <button id="orders-retry-btn" class="btn press" style="margin-top:12px; max-width:160px">Повторить</button>
      </div>
    `;
    content.querySelector('#orders-retry-btn')?.addEventListener('click', () => loadOrders(true));
  }
}

function renderOrderCardHTML(o) {
  const statusInfo = getStatusDisplay(o.status);
  const safeId = escapeHtml(o.id);
  const safePrice = escapeHtml(o.price);
  const safeCurrency = escapeHtml(o.currency);
  const safeDesc = escapeHtml(o.description || 'Без описания');
  const safeBuyer = escapeHtml(o.buyer_username);
  const safeSubcat = escapeHtml(o.subcategory_name || '');
  return `
    <button class="card n press order-card-btn rv in" data-id="${safeId}" style="height:auto; min-height:100px; padding:16px; text-align:left; width:100%">
      <div style="display:flex; justify-content:space-between; align-items:flex-start; width:100%">
        <div>
          <span style="display:inline-block; padding:3px 8px; border-radius:8px; font-size:11px; font-weight:700; background:${statusInfo.bg}; color:${statusInfo.color}">
            ${statusInfo.label}
          </span>
          <b style="font-size:15px; margin-left:6px">#${safeId}</b>
        </div>
        <div style="font-size:16px; font-weight:800; color:var(--primary)">
          ${safePrice} ${safeCurrency}
        </div>
      </div>

      <div style="margin: 8px 0; font-size:13px; font-weight:600; color:var(--on); overflow:hidden; text-overflow:ellipsis; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical">
        ${safeDesc}
      </div>

      <div style="display:flex; justify-content:space-between; font-size:12px; color:var(--muted)">
        <span>Покупатель: <b>${safeBuyer}</b></span>
        <span>${safeSubcat}</span>
      </div>
    </button>
  `;
}

async function openOrderDetailsModal(orderId) {
  tg.haptic.impact('medium');
  openSheet(`Заказ #${orderId}`, `
    <div style="text-align:center; padding:32px 0">
      <div style="width:36px; height:36px; border-radius:50%; border:3px solid var(--track); border-top-color:var(--primary); animation:spin 1s linear infinite; margin:0 auto"></div>
    </div>
    <style>@keyframes spin{to{transform:rotate(360deg)}}</style>
  `);

  try {
    const o = await getOrderDetails(orderId);
    if (!o) throw new Error('Заказ не найден');

    const statusInfo = getStatusDisplay(o.status);
    const safeSum = escapeHtml(o.sum);
    const safeCurrency = escapeHtml(o.currency);
    const safeBuyer = escapeHtml(o.buyer_username);
    const safeAmount = escapeHtml(o.amount);
    const safeSubcategory = escapeHtml(o.subcategory || '');

    const sheetContent = `
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px">
        <span style="padding:4px 10px; border-radius:10px; font-size:12px; font-weight:700; background:${statusInfo.bg}; color:${statusInfo.color}">
          ${statusInfo.label}
        </span>
        <b style="font-size:22px; color:var(--primary)">${safeSum} ${safeCurrency}</b>
      </div>

      <div class="panel" style="padding:14px; margin-bottom:14px">
        <div class="row"><span>Покупатель</span><b>${safeBuyer}</b></div>
        <div class="row"><span>Количество</span><b>${safeAmount} шт.</b></div>
        ${safeSubcategory ? `<div class="row"><span>Категория</span><b>${safeSubcategory}</b></div>` : ''}
      </div>

      <!-- Поля заказа -->
      ${Object.keys(o.fields || {}).length > 0 ? `
        <h4 style="font-size:13px; color:var(--muted); margin:12px 4px 6px">Параметры лота</h4>
        <div class="panel" style="padding:14px; margin-bottom:14px; font-size:13px">
          ${Object.values(o.fields).map(f => `
            <div style="margin-bottom:6px">
              <span style="color:var(--muted)">${escapeHtml(f.name)}:</span>
              <b>${escapeHtml(f.value)}</b>
            </div>
          `).join('')}
        </div>
      ` : ''}

      <!-- Товары автовыдачи -->
      ${(o.order_secrets || []).length > 0 ? `
        <h4 style="font-size:13px; color:var(--muted); margin:12px 4px 6px">Выданный товар</h4>
        <div class="panel" style="padding:14px; margin-bottom:14px; background:var(--s); color:var(--on-s); font-family:monospace; font-size:12px; white-space:pre-wrap; word-break:break-all">
          ${escapeHtml(o.order_secrets.join('\n'))}
        </div>
      ` : ''}

      <!-- Отзыв -->
      ${o.review ? `
        <h4 style="font-size:13px; color:var(--muted); margin:12px 4px 6px">Отзыв покупателя</h4>
        <div class="panel" style="padding:14px; margin-bottom:14px">
          <div style="display:flex; gap:3px; color:var(--warn, #f5a623); align-items:center">${Array.from({ length: Math.min(5, Math.max(1, o.review.stars || 5)) }).map(() => '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" stroke="currentColor" stroke-width="1" aria-hidden="true"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>').join('')}</div>
          <div style="font-size:13px; margin:4px 0">${escapeHtml(o.review.text || 'Без текста')}</div>
          ${o.review.reply ? `
            <div style="margin-top:8px; padding-top:8px; border-top:1px solid var(--track); font-size:12px">
              <b style="color:var(--muted)">Ваш ответ:</b>
              <p>${escapeHtml(o.review.reply)}</p>
            </div>
          ` : ''}
        </div>
      ` : ''}

      <!-- Кнопки действий -->
      <div style="display:flex; flex-direction:column; gap:8px; margin-top:16px">
        ${o.chat_id ? `
          <button class="btn press" id="open-chat-from-order" style="width:100%">
            Открыть переписку
          </button>
        ` : ''}

        ${o.status === 'PAID' || o.status === 'paid' ? `
          <button class="btn err press" id="refund-order-btn" style="width:100%">
            Вернуть деньги
          </button>
        ` : ''}
      </div>
    `;

    openSheet(`Заказ #${orderId}`, sheetContent);

    // Обработчик перехода в чат
    document.getElementById('open-chat-from-order')?.addEventListener('click', () => {
      closeSheet();
      location.hash = `chats`;
    });

    // Обработчик возврата денег (с Confirm-шторкой)
    document.getElementById('refund-order-btn')?.addEventListener('click', () => {
      openConfirmSheet({
        title: 'Возврат средств',
        message: `Вы действительно хотите вернуть покупателю ${o.sum} ${o.currency} за заказ #${orderId}? Это действие необратимо.`,
        confirmText: 'Вернуть деньги',
        danger: true,
        onConfirm: async () => {
          try {
            await refundOrder(orderId, true);
            showToast(`Возврат по заказу #${orderId} оформлен`, 'ok');
            loadOrders(true);
          } catch (e) {
            showToast(e.message || 'Ошибка возврата', 'err');
          }
        },
      });
    });
  } catch (err) {
    openSheet(`Ошибка`, `<p class="tx" style="color:var(--err)">${err.message}</p>`);
  }
}

function getStatusDisplay(status) {
  const s = String(status).toUpperCase();
  if (s === 'PAID') return { label: 'Оплачен', bg: 'var(--ok-c)', color: 'var(--on-ok-c)' };
  if (s === 'CLOSED') return { label: 'Закрыт', bg: 'var(--p)', color: 'var(--on-p)' };
  if (s === 'REFUNDED') return { label: 'Возврат', bg: 'var(--err-c)', color: 'var(--on-err-c)' };
  return { label: s, bg: 'var(--n)', color: 'var(--on-n)' };
}

function renderOrdersSkeleton() {
  return `
    <div style="display:grid; gap:10px">
      ${[1, 2, 3].map(() => `
        <div style="height:100px; border-radius:24px; background:var(--track); animation:pulse 1.4s ease infinite"></div>
      `).join('')}
    </div>
  `;
}

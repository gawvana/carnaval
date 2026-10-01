/**
 * pages/chats.js — Экран чатов и переписок FunPay.
 * Двухуровневый мобильный UX: список диалогов -> открытие полноэкранного чата.
 * Шапка с кнопкой назад и аватаром, поток сообщений с автопрокруткой,
 * адаптивный мобильный composer с поддержкой Safe Area и клавиатуры,
 * скрытие нижнего дока в треде, шаблоны быстрых ответов,
 * мгновенное добавление сообщений через SSE и статус 'Покупатель смотрит'.
 */

import {
  getChats,
  getChatHistory,
  sendChatMessage,
  sendChatImage,
  getBuyerViewing,
  openEventStream,
  getTemplates,
} from '../api.js';
import { tg } from '../tg.js';
import { renderHeader } from '../ui/header.js';
import { showToast } from '../ui/toast.js';
import { escapeHtml } from '../ui/sanitize.js';
import { openSheet, closeSheet } from '../ui/sheet.js';

let _activeChatId = null;
let _activeChatName = null;
let _stopChatEvents = null;
let _cleanupViewport = null;

export async function renderChats(wrap) {
  wrap.innerHTML = '';
  _closeActiveThread();

  const header = renderHeader({
    title: 'Чаты',
    subtitle: 'Переписки FunPay',
  });
  wrap.appendChild(header);

  const container = document.createElement('div');
  container.id = 'chats-root';
  container.style.paddingTop = '68px';
  container.innerHTML = `
    <div id="chats-list-view">
      ${renderChatsSkeleton()}
    </div>
    <div id="chat-thread-view" class="mobile-chat-thread" style="display:none"></div>
  `;
  wrap.appendChild(container);

  await loadChatsList();

  // Очистка при смене вкладки в роутере
  return () => {
    _closeActiveThread();
  };
}

function _closeActiveThread() {
  _activeChatId = null;
  _activeChatName = null;
  if (_stopChatEvents) {
    try { _stopChatEvents(); } catch (_) {}
    _stopChatEvents = null;
  }
  if (_cleanupViewport) {
    try { _cleanupViewport(); } catch (_) {}
    _cleanupViewport = null;
  }
  document.body.classList.remove('in-chat-thread');
  try { tg.backButton.hide(); } catch (_) {}

  const threadView = document.getElementById('chat-thread-view');
  if (threadView) {
    threadView.style.display = 'none';
    threadView.innerHTML = '';
  }
  const listView = document.getElementById('chats-list-view');
  if (listView) {
    listView.style.display = 'block';
  }
}

async function loadChatsList() {
  const listView = document.getElementById('chats-list-view');
  if (!listView) return;

  try {
    const res = await getChats();

    // 1. Ошибка подключения FunPay или сети
    if (res.ok === false || res.error_code) {
      renderChatsErrorState(listView, res);
      return;
    }

    const chats = res.chats || [];

    // 2. Успешный ответ при 0 чатов
    if (chats.length === 0) {
      listView.innerHTML = `
        <div class="empty rv in" style="padding:48px 16px; text-align:center">
          <svg viewBox="0 0 24 24" style="width:48px;height:48px;color:var(--muted);margin-bottom:12px;opacity:.7"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          <b style="font-size:17px;display:block;margin-bottom:6px">Диалогов пока нет</b>
          <p style="font-size:14px;color:var(--muted);max-width:280px;margin:0 auto 16px">Здесь появятся ваши сообщения с покупателями на FunPay</p>
          <button class="btn press" id="refresh-chats-btn" style="height:38px;padding:0 20px;font-size:13px;margin:0 auto">Обновить</button>
        </div>
      `;
      listView.querySelector('#refresh-chats-btn')?.addEventListener('click', () => {
        listView.innerHTML = renderChatsSkeleton();
        loadChatsList();
      });
      return;
    }

    // 3. Список чатов
    listView.innerHTML = `
      <div style="display:grid; gap:8px">
        ${chats.map(renderChatCardHTML).join('')}
      </div>
    `;

    listView.querySelectorAll('.chat-card-btn').forEach((card) => {
      card.addEventListener('click', () => {
        const chatId = card.dataset.id;
        const chatName = card.dataset.name;
        openChatThread(chatId, chatName);
      });
    });
  } catch (err) {
    renderChatsErrorState(listView, { error_code: 'CLIENT_ERROR', message: err.message });
  }
}

function renderChatsErrorState(container, errData) {
  const isNotInit = errData.error_code === 'FUNPAY_ACCOUNT_NOT_INITIALIZED';
  const title = isNotInit ? 'Аккаунт FunPay не подключен' : 'Ошибка загрузки диалогов';
  const msg = errData.message || (isNotInit ? 'Требуется подключить Golden Key в настройках.' : 'Не удалось связаться с сервером FunPay.');

  container.innerHTML = `
    <div class="card rv in" style="padding:24px 18px; text-align:center; margin-top:16px; border:1px solid color-mix(in srgb, var(--err) 30%, transparent); background:color-mix(in srgb, var(--err) 8%, var(--surface))">
      <div style="width:52px; height:52px; border-radius:50%; background:var(--err-c); color:var(--on-err-c); display:grid; place-items:center; margin:0 auto 12px">
        <svg viewBox="0 0 24 24" style="width:26px;height:26px;stroke-width:2;stroke:currentColor;fill:none"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
      </div>
      <b style="font-size:17px; display:block; margin-bottom:6px">${escapeHtml(title)}</b>
      <p style="font-size:13px; color:var(--muted); margin:0 auto 16px; max-width:320px">${escapeHtml(msg)}</p>
      
      <div style="display:flex; justify-content:center; gap:10px; flex-wrap:wrap">
        ${isNotInit ? `
          <button class="btn press" id="go-setup-key-btn" style="height:40px; padding:0 18px; font-size:13px">Настроить аккаунт</button>
        ` : ''}
        <button class="btn tn press" id="retry-chats-btn" style="height:40px; padding:0 18px; font-size:13px">Повторить попытку</button>
      </div>
    </div>
  `;

  container.querySelector('#go-setup-key-btn')?.addEventListener('click', () => {
    location.hash = 'more';
  });

  container.querySelector('#retry-chats-btn')?.addEventListener('click', () => {
    container.innerHTML = renderChatsSkeleton();
    loadChatsList();
  });
}

function renderChatCardHTML(c) {
  const initials = escapeHtml((c.name || 'U')[0].toUpperCase());
  const safeId = escapeHtml(c.id);
  const safeName = escapeHtml(c.name);
  const safeMsg = escapeHtml(c.last_message_text || 'Нет сообщений');
  return `
    <button class="card n press chat-card-btn rv in" data-id="${safeId}" data-name="${safeName}" style="height:auto; min-height:76px; padding:14px; text-align:left; width:100%; display:flex; align-items:center; gap:12px">
      <div style="width:44px; height:44px; border-radius:50%; background:var(--p); color:var(--on-p); display:grid; place-items:center; font-weight:800; font-size:16px; flex:none; position:relative">
        ${initials}
        ${c.unread ? `<i style="position:absolute; top:0; right:0; width:12px; height:12px; border-radius:50%; background:var(--err); border:2px solid var(--n)"></i>` : ''}
      </div>

      <div style="flex:1; min-width:0">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:2px">
          <b style="font-size:15px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap">${safeName}</b>
          ${c.unread ? `<span style="font-size:11px; font-weight:700; color:var(--err); background:var(--err-c); padding:2px 6px; border-radius:6px">Новое</span>` : ''}
        </div>
        <div style="font-size:13px; color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap">
          ${safeMsg}
        </div>
      </div>
    </button>
  `;
}

async function openChatThread(chatId, chatName) {
  _activeChatId = chatId;
  _activeChatName = chatName;

  const listView = document.getElementById('chats-list-view');
  const threadView = document.getElementById('chat-thread-view');
  if (!listView || !threadView) return;

  // Активируем полноэкранный режим треда и скрытие нижнего дока
  document.body.classList.add('in-chat-thread');
  listView.style.display = 'none';
  threadView.style.display = 'flex';

  const initials = escapeHtml((chatName || 'U')[0].toUpperCase());
  const safeName = escapeHtml(chatName);

  threadView.innerHTML = `
    <!-- Мобильная шапка чата -->
    <header class="mobile-chat-header">
      <button class="ib press" id="back-to-chats-btn" aria-label="Назад" style="flex:none; width:38px; height:38px">
        <svg viewBox="0 0 24 24" style="width:22px;height:22px;stroke-width:2.2"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
      </button>

      <div class="mobile-chat-avatar">
        ${initials}
      </div>

      <div style="flex:1; min-width:0">
        <b style="font-size:16px; font-weight:700; display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap">${safeName}</b>
        <span id="buyer-viewing-label" style="font-size:11px; color:var(--muted); display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap">FunPay диалог #${escapeHtml(chatId)}</span>
      </div>
    </header>

    <!-- Поток сообщений -->
    <div id="messages-container" class="mobile-chat-messages">
      <div style="text-align:center; padding:48px 0">
        <div style="width:32px; height:32px; border-radius:50%; border:3px solid var(--track); border-top-color:var(--primary); animation:spin 1s linear infinite; margin:0 auto"></div>
      </div>
    </div>

    <!-- Мобильный Composer (поле ввода) -->
    <div class="mobile-chat-composer" id="chat-composer">
      <div class="mobile-chat-composer-inner">
        <!-- Прикрепление картинки -->
        <label class="ib press" style="flex:none; width:36px; height:36px; cursor:pointer" title="Прикрепить изображение">
          <input type="file" id="chat-file-input" accept="image/*" style="display:none">
          <svg viewBox="0 0 24 24" style="width:20px;height:20px"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>
        </label>

        <!-- Быстрые шаблоны ответов -->
        <button class="ib press" id="chat-templates-btn" type="button" style="flex:none; width:36px; height:36px" title="Шаблоны ответов">
          <svg viewBox="0 0 24 24" style="width:20px;height:20px"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
        </button>

        <!-- Текстовое поле -->
        <input type="text" id="chat-msg-input" placeholder="Сообщение..." autocomplete="off">

        <!-- Кнопка отправки -->
        <button class="ib press" id="chat-send-btn" type="button" style="color:var(--primary); flex:none; width:36px; height:36px" aria-label="Отправить">
          <svg viewBox="0 0 24 24" style="width:20px;height:20px;transform:translateX(1px)"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>
        </button>
      </div>
    </div>
  `;

  // Обработчик закрытия ветки чата
  const handleBack = () => {
    _closeActiveThread();
    loadChatsList();
  };

  document.getElementById('back-to-chats-btn')?.addEventListener('click', handleBack);
  tg.backButton.show(handleBack);

  // Адаптация под виртуальную клавиатуру мобильных устройств
  const composerEl = document.getElementById('chat-composer');
  const msgsEl = document.getElementById('messages-container');

  const onViewportResize = () => {
    if (!window.visualViewport || !composerEl) return;
    const keyboardHeight = Math.max(0, window.innerHeight - window.visualViewport.height - window.visualViewport.offsetTop);
    if (keyboardHeight > 0) {
      composerEl.style.paddingBottom = `calc(${keyboardHeight}px + 8px)`;
    } else {
      composerEl.style.paddingBottom = 'calc(8px + env(safe-area-inset-bottom, 0px))';
    }
    if (msgsEl) {
      msgsEl.scrollTop = msgsEl.scrollHeight;
    }
  };

  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', onViewportResize);
    window.visualViewport.addEventListener('scroll', onViewportResize);
    _cleanupViewport = () => {
      window.visualViewport.removeEventListener('resize', onViewportResize);
      window.visualViewport.removeEventListener('scroll', onViewportResize);
    };
  }

  // Загрузка сообщений и статуса "Покупатель смотрит"
  await loadMessages(chatId);
  loadBuyerViewingInfo(chatId);

  // Обработчики ввода и отправки
  const msgInput = document.getElementById('chat-msg-input');
  const sendBtn = document.getElementById('chat-send-btn');
  const fileInput = document.getElementById('chat-file-input');
  const tmplBtn = document.getElementById('chat-templates-btn');

  msgInput?.addEventListener('focus', () => {
    setTimeout(() => {
      if (msgsEl) msgsEl.scrollTop = msgsEl.scrollHeight;
    }, 250);
  });

  async function handleSend() {
    const text = msgInput.value.trim();
    if (!text) return;
    msgInput.value = '';
    tg.haptic.impact('light');

    appendMessageHTML({
      id: Date.now(),
      text,
      author: 'Вы',
      isMe: true,
    });

    try {
      await sendChatMessage(chatId, text, chatName);
    } catch (e) {
      showToast(e.message || 'Ошибка отправки', 'err');
    }
  }

  sendBtn?.addEventListener('click', handleSend);
  msgInput?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') handleSend();
  });

  // Отправка картинки
  fileInput?.addEventListener('change', async () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    showToast('Загрузка изображения...', '');
    try {
      await sendChatImage(chatId, file, chatName);
      showToast('Изображение отправлено', 'ok');
      await loadMessages(chatId);
    } catch (e) {
      showToast(e.message || 'Ошибка загрузки изображения', 'err');
    }
  });

  // Шаблоны ответов
  tmplBtn?.addEventListener('click', () => {
    openTemplatesSheet(chatId, chatName, msgInput);
  });

  // SSE слушатель новых сообщений в открытом чате
  if (_stopChatEvents) _stopChatEvents();
  _stopChatEvents = openEventStream((ev) => {
    if (ev.type === 'message.new' && String(ev.data?.chat_id) === String(_activeChatId)) {
      appendMessageHTML({
        id: ev.data.id || Date.now(),
        text: ev.data.text,
        author: ev.data.author || chatName,
        isMe: false,
        image_link: ev.data.image_link,
      });
      tg.haptic.notification('success');
    }
  });
}

async function loadMessages(chatId) {
  const container = document.getElementById('messages-container');
  if (!container) return;

  try {
    const res = await getChatHistory(chatId);

    if (res.ok === false || res.error_code) {
      container.innerHTML = `
        <div class="empty" style="padding:48px 16px; text-align:center">
          <p style="color:var(--err); margin-bottom:12px">${escapeHtml(res.message || 'Ошибка загрузки сообщений')}</p>
          <button class="btn tn press" id="retry-history-btn" style="height:36px; padding:0 16px; font-size:13px; margin:0 auto">Повторить</button>
        </div>
      `;
      container.querySelector('#retry-history-btn')?.addEventListener('click', () => {
        container.innerHTML = `<div style="text-align:center; padding:48px 0"><div style="width:32px; height:32px; border-radius:50%; border:3px solid var(--track); border-top-color:var(--primary); animation:spin 1s linear infinite; margin:0 auto"></div></div>`;
        loadMessages(chatId);
      });
      return;
    }

    const msgs = res.messages || [];

    if (msgs.length === 0) {
      container.innerHTML = `<div class="empty" style="padding:48px 0"><p>История переписки пуста</p></div>`;
      return;
    }

    container.innerHTML = '';
    msgs.forEach((m) => {
      appendMessageHTML(m, false);
    });
    container.scrollTop = container.scrollHeight;
  } catch (err) {
    container.innerHTML = `
      <div class="empty" style="padding:48px 16px; text-align:center">
        <p style="color:var(--err); margin-bottom:12px">Ошибка загрузки сообщений<br><small>${escapeHtml(err.message)}</small></p>
        <button class="btn tn press" id="retry-history-btn" style="height:36px; padding:0 16px; font-size:13px; margin:0 auto">Повторить</button>
      </div>
    `;
    container.querySelector('#retry-history-btn')?.addEventListener('click', () => {
      container.innerHTML = `<div style="text-align:center; padding:48px 0"><div style="width:32px; height:32px; border-radius:50%; border:3px solid var(--track); border-top-color:var(--primary); animation:spin 1s linear infinite; margin:0 auto"></div></div>`;
      loadMessages(chatId);
    });
  }
}

function appendMessageHTML(m, scroll = true) {
  const container = document.getElementById('messages-container');
  if (!container) return;

  const isMe = m.isMe || m.author === 'Вы';
  const el = document.createElement('div');
  el.style.display = 'flex';
  el.style.flexDirection = 'column';
  el.style.alignItems = isMe ? 'flex-end' : 'flex-start';
  el.style.margin = '4px 0';

  const safeImg = m.image_link && /^https?:\/\//i.test(m.image_link) ? escapeHtml(m.image_link) : '';
  const safeText = escapeHtml(m.text || '');

  el.innerHTML = `
    <div style="max-width:82%; padding:10px 14px; border-radius:${isMe ? '18px 18px 4px 18px' : '18px 18px 18px 4px'}; background:${isMe ? 'var(--primary)' : 'var(--n)'}; color:${isMe ? 'var(--on-primary)' : 'var(--on-n)'}; font-size:14px; word-break:break-word; box-shadow:0 2px 8px rgba(0,0,0,.08)">
      ${safeImg ? `<img src="${safeImg}" style="max-width:100%; border-radius:12px; margin-bottom:6px; display:block">` : ''}
      <div style="white-space:pre-wrap">${safeText}</div>
    </div>
  `;

  container.appendChild(el);
  if (scroll) container.scrollTop = container.scrollHeight;
}

async function loadBuyerViewingInfo(chatId) {
  const label = document.getElementById('buyer-viewing-label');
  if (!label) return;

  try {
    const res = await getBuyerViewing(chatId, parseInt(chatId, 10));
    if (res.viewing?.text) {
      label.textContent = `Смотрит: ${res.viewing.text}`;
    }
  } catch (_) {}
}

async function openTemplatesSheet(chatId, chatName, inputEl) {
  try {
    const res = await getTemplates();
    const tmpls = res.templates || [];
    if (tmpls.length === 0) {
      showToast('Нет сохраненных шаблонов', '');
      return;
    }

    const content = `
      <div style="display:flex; flex-direction:column; gap:8px; max-height:60vh; overflow-y:auto; padding-bottom:12px">
        ${tmpls.map((t, idx) => `
          <button class="card n press template-select-item" data-idx="${t.index ?? idx}" style="padding:12px 14px; text-align:left; width:100%; border-radius:18px; border:1px solid var(--edge)">
            <b style="font-size:14px; display:block; margin-bottom:4px; color:var(--primary)">Шаблон #${(t.index ?? idx) + 1}</b>
            <div style="font-size:13px; color:var(--on-n); white-space:pre-wrap; word-break:break-word; max-height:60px; overflow:hidden; text-overflow:ellipsis">${escapeHtml(t.text || '')}</div>
          </button>
        `).join('')}
      </div>
    `;

    openSheet('Шаблоны быстрых ответов', content);

    document.querySelectorAll('.template-select-item').forEach((item) => {
      item.addEventListener('click', async () => {
        const idx = Number(item.dataset.idx);
        const tmpl = tmpls.find(t => (t.index ?? 0) === idx) || tmpls[idx];
        closeSheet();
        if (inputEl && tmpl?.text) {
          inputEl.value = tmpl.text;
          inputEl.focus();
        }
      });
    });
  } catch (err) {
    showToast('Не удалось загрузить шаблоны', 'err');
  }
}

function renderChatsSkeleton() {
  return `
    <div style="display:grid; gap:8px">
      ${[1, 2, 3, 4].map(() => `
        <div style="height:76px; border-radius:24px; background:var(--track); animation:pulse 1.4s ease infinite"></div>
      `).join('')}
    </div>
  `;
}

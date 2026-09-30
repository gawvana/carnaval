/**
 * pages/chats.js — Экран чатов и переписок FunPay.
 * Список диалогов с индикацией непрочитанных, живой диалог,
 * отправка текста и изображений, статус 'Покупатель смотрит',
 * мгновенное добавление сообщений через SSE.
 */

import { getChats, getChatHistory, sendChatMessage, sendChatImage, getBuyerViewing, openEventStream } from '../api.js';
import { tg } from '../tg.js';
import { renderHeader } from '../ui/header.js';
import { showToast } from '../ui/toast.js';

let _activeChatId = null;
let _activeChatName = null;
let _stopChatEvents = null;

export async function renderChats(wrap) {
  wrap.innerHTML = '';
  _activeChatId = null;

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
    <div id="chat-thread-view" style="display:none"></div>
  `;
  wrap.appendChild(container);

  await loadChatsList();
}

async function loadChatsList() {
  const listView = document.getElementById('chats-list-view');
  if (!listView) return;

  try {
    const res = await getChats();
    const chats = res.chats || [];

    if (chats.length === 0) {
      listView.innerHTML = `
        <div class="empty rv in">
          <svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          <p>Диалогов пока нет</p>
        </div>
      `;
      return;
    }

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
    listView.innerHTML = `
      <div class="empty rv in">
        <p style="color:var(--err)">Не удалось загрузить чаты<br><small>${err.message}</small></p>
      </div>
    `;
  }
}

function renderChatCardHTML(c) {
  const initials = (c.name || 'U')[0].toUpperCase();
  return `
    <button class="card n press chat-card-btn rv in" data-id="${c.id}" data-name="${c.name}" style="height:auto; min-height:76px; padding:14px; text-align:left; width:100%; display:flex; align-items:center; gap:12px">
      <div style="width:44px; height:44px; border-radius:50%; background:var(--p); color:var(--on-p); display:grid; place-items:center; font-weight:800; font-size:16px; flex:none; position:relative">
        ${initials}
        ${c.unread ? `<i style="position:absolute; top:0; right:0; width:12px; height:12px; border-radius:50%; background:var(--err); border:2px solid var(--n)"></i>` : ''}
      </div>

      <div style="flex:1; min-width:0">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:2px">
          <b style="font-size:15px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap">${c.name}</b>
          ${c.unread ? `<span style="font-size:11px; font-weight:700; color:var(--err); background:var(--err-c); padding:2px 6px; border-radius:6px">Новое</span>` : ''}
        </div>
        <div style="font-size:13px; color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap">
          ${c.last_message_text || 'Нет сообщений'}
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

  listView.style.display = 'none';
  threadView.style.display = 'block';

  threadView.innerHTML = `
    <!-- Шапка чата -->
    <div style="display:flex; align-items:center; gap:10px; margin-bottom:12px">
      <button class="ib press" id="back-to-chats-btn" aria-label="Назад">
        <svg viewBox="0 0 24 24"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
      </button>
      <div>
        <b style="font-size:16px; display:block">${chatName}</b>
        <span id="buyer-viewing-label" style="font-size:11px; color:var(--muted)"></span>
      </div>
    </div>

    <!-- Поток сообщений -->
    <div id="messages-container" style="display:flex; flex-direction:column; gap:8px; min-height:360px; max-height:55vh; overflow-y:auto; padding:8px 4px; scrollbar-width:none">
      <div style="text-align:center; padding:32px 0"><div style="width:28px; height:28px; border-radius:50%; border:3px solid var(--track); border-top-color:var(--primary); animation:spin 1s linear infinite; margin:0 auto"></div></div>
    </div>

    <!-- Поле ввода и отправки (Composer) -->
    <div class="panel glass" style="padding:10px; border-radius:24px; margin-top:12px; display:flex; gap:8px; align-items:center">
      <label class="ib press" style="flex:none; cursor:pointer" title="Прикрепить изображение">
        <input type="file" id="chat-file-input" accept="image/*" style="display:none">
        <svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>
      </label>

      <input type="text" id="chat-msg-input" placeholder="Написать сообщение..." style="flex:1; border:none; background:none; font:inherit; color:inherit; outline:none; font-size:14px">

      <button class="ib press" id="chat-send-btn" style="color:var(--primary); flex:none" aria-label="Отправить">
        <svg viewBox="0 0 24 24" style="transform:translateX(1px)"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>
      </button>
    </div>
  `;

  // Кнопка возврата
  document.getElementById('back-to-chats-btn')?.addEventListener('click', () => {
    _activeChatId = null;
    threadView.style.display = 'none';
    listView.style.display = 'block';
    loadChatsList();
  });

  // Загрузка сообщений
  await loadMessages(chatId);

  // Подгрузка информации "Покупатель смотрит"
  loadBuyerViewingInfo(chatId);

  // Обработчик отправки сообщения
  const msgInput = document.getElementById('chat-msg-input');
  const sendBtn = document.getElementById('chat-send-btn');
  const fileInput = document.getElementById('chat-file-input');

  async function handleSend() {
    const text = msgInput.value.trim();
    if (!text) return;
    msgInput.value = '';
    tg.haptic.impact('light');

    // Локально отображаем оптимистичное сообщение
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
    container.innerHTML = `<div class="empty"><p style="color:var(--err)">Ошибка загрузки сообщений</p></div>`;
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

  el.innerHTML = `
    <div style="max-width:80%; padding:10px 14px; border-radius:${isMe ? '18px 18px 4px 18px' : '18px 18px 18px 4px'}; background:${isMe ? 'var(--primary)' : 'var(--n)'}; color:${isMe ? 'var(--on-primary)' : 'var(--on-n)'}; font-size:14px; word-break:break-word">
      ${m.image_link ? `<img src="${m.image_link}" style="max-width:100%; border-radius:12px; margin-bottom:6px; display:block">` : ''}
      <div>${m.text || ''}</div>
    </div>
  `;

  container.appendChild(el);
  if (scroll) container.scrollTop = container.scrollHeight;
}

async function loadBuyerViewingInfo(chatId) {
  const label = document.getElementById('buyer-viewing-label');
  if (!label) return;

  try {
    // В FunPay chat_id в личных переписках совпадает с buyer_id
    const res = await getBuyerViewing(chatId, parseInt(chatId, 10));
    if (res.viewing?.text) {
      label.textContent = `Смотрит: ${res.viewing.text}`;
    }
  } catch (_) {}
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

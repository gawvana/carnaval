/**
 * sse.js — надёжный SSE-клиент на основе fetch + ReadableStream.
 *
 * Особенности:
 * - Заголовок Authorization: Bearer <token> (токен не передаётся в URL).
 * - Разбор SSE потока (id, event, data, :ping).
 * - Last-Event-ID для досылки пропущенных сообщений при переподключении.
 * - Экспоненциальный backoff (1с -> 30с) с джиттером при разрыве связи.
 * - Индикатор соединения (updateConnectionStatus).
 * - Автоматический фолбэк на поллинг /api/dashboard каждые 20 сек, если стрим недоступен.
 */

import { apiUrl } from './config.js';
import { getToken } from './api.js';

let lastEventId = 0;
let isConnected = false;
let shouldRun = false;
let retryCount = 0;
let abortController = null;
let pollingInterval = null;

// Слушатели событий
const eventListeners = new Set();
// Слушатели статуса подключения (online / offline / reconnecting)
const statusListeners = new Set();

export function onEvent(listener) {
  eventListeners.add(listener);
  return () => eventListeners.delete(listener);
}

export function onConnectionStatus(listener) {
  statusListeners.add(listener);
  listener(isConnected ? 'connected' : 'disconnected');
  return () => statusListeners.delete(listener);
}

function notifyStatus(status) {
  for (const fn of statusListeners) {
    try { fn(status); } catch (e) { console.error('SSE status listener error:', e); }
  }
}

function notifyEvent(event) {
  for (const fn of eventListeners) {
    try { fn(event); } catch (e) { console.error('SSE event listener error:', e); }
  }
}

/** Запускает фолбэк-поллинг /api/dashboard при отсутствии стрима. */
function startFallbackPolling() {
  if (pollingInterval) return;
  console.warn('[SSE] Запущен фолбэк-поллинг дашборда (каждые 20 сек)');
  pollingInterval = setInterval(async () => {
    if (isConnected) {
      stopFallbackPolling();
      return;
    }
    try {
      const tok = getToken();
      if (!tok) return;
      const res = await fetch(apiUrl('/api/dashboard'), {
        headers: { Authorization: `Bearer ${tok}` },
      });
      if (res.ok) {
        const data = await res.json();
        notifyEvent({ type: 'dashboard.poll', ts: Date.now(), data });
      }
    } catch (e) {
      // игнорируем ошибку поллинга
    }
  }, 20000);
}

function stopFallbackPolling() {
  if (pollingInterval) {
    clearInterval(pollingInterval);
    pollingInterval = null;
  }
}

/** Вычисляет задержку переподключения (1 -> 30 с) с джиттером. */
function getRetryDelay() {
  const base = Math.min(30000, 1000 * Math.pow(1.5, retryCount));
  const jitter = base * 0.2 * (Math.random() - 0.5);
  return Math.round(base + jitter);
}

/** Основной цикл подключения SSE. */
async function connect() {
  if (!shouldRun) return;

  const tok = getToken();
  if (!tok) {
    // Ждём появления токена
    setTimeout(connect, 1000);
    return;
  }

  abortController = new AbortController();
  notifyStatus(retryCount === 0 ? 'connecting' : 'reconnecting');

  const headers = {
    Authorization: `Bearer ${tok}`,
    Accept: 'text/event-stream',
  };
  if (lastEventId > 0) {
    headers['Last-Event-ID'] = String(lastEventId);
  }

  try {
    const url = apiUrl(`/api/events${lastEventId ? `?last_event_id=${lastEventId}` : ''}`);
    const response = await fetch(url, {
      headers,
      signal: abortController.signal,
    });

    if (!response.ok) {
      if (response.status === 401) {
        try {
          const { tg } = await import('./tg.js');
          const { auth } = await import('./api.js');
          if (tg && tg.initData) {
            const reauth = await auth(tg.initData);
            if (reauth && reauth.ok !== false && (reauth.token || reauth.csrf_token)) {
              console.log('[SSE] Сессия успешно обновлена после 401, переподключение...');
              setTimeout(connect, 400);
              return;
            }
          }
        } catch (_) {}
      }
      throw new Error(`SSE HTTP ${response.status}`);
    }

    if (!response.body) {
      throw new Error('ReadableStream not supported');
    }

    // Соединение успешно установлено
    isConnected = true;
    retryCount = 0;
    notifyStatus('connected');
    stopFallbackPolling();

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (shouldRun) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n\n');
      buffer = lines.pop() || '';

      for (const block of lines) {
        parseEventBlock(block);
      }
    }
  } catch (err) {
    if (err.name === 'AbortError') return;
    console.warn('[SSE] Ошибка соединения:', err.message);
  } finally {
    isConnected = false;
    notifyStatus('disconnected');
    startFallbackPolling();

    if (shouldRun) {
      retryCount++;
      const delay = getRetryDelay();
      console.log(`[SSE] Переподключение через ${Math.round(delay / 1000)} сек...`);
      setTimeout(connect, delay);
    }
  }
}

/** Разбор отдельного SSE-блока сообщений. */
function parseEventBlock(block) {
  if (!block.trim()) return;

  let eventType = 'message';
  let eventData = '';
  let id = null;

  for (const rawLine of block.split('\n')) {
    const line = rawLine.trim();
    if (line.startsWith(':')) {
      // Keepalive ping (: ping)
      continue;
    }
    if (line.startsWith('id:')) {
      id = parseInt(line.slice(3).trim(), 10);
      if (!isNaN(id)) lastEventId = id;
    } else if (line.startsWith('event:')) {
      eventType = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      eventData = line.slice(5).trim();
    }
  }

  if (eventData) {
    try {
      const parsed = JSON.parse(eventData);
      notifyEvent({
        id,
        type: parsed.type || eventType,
        ts: parsed.ts || Date.now(),
        data: parsed.data || parsed,
      });
    } catch {
      notifyEvent({ id, type: eventType, ts: Date.now(), data: eventData });
    }
  }
}

export function startSSE() {
  if (shouldRun) return;
  shouldRun = true;
  connect();
}

export function stopSSE() {
  shouldRun = false;
  isConnected = false;
  if (abortController) {
    abortController.abort();
    abortController = null;
  }
  stopFallbackPolling();
  notifyStatus('disconnected');
}

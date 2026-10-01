/**
 * api.js — единый API-клиент Carnaval.
 *
 * Архитектура:
 * - Все запросы проходят через request(method, path, options).
 * - Единая подстановка Authorization: Bearer <token>.
 * - Автоповтор GET-запросов при сетевых сбоях.
 * - Однократный авто-релогин при 401 Unauthorized через tg.initData.
 * - Парсинг ошибок {error, message} в ApiError.
 */

import { apiUrl } from './config.js';
import { tg } from './tg.js';

const TOKEN_KEY = 'crn_token';

export class ApiError extends Error {
  constructor(status, code, message, data = null) {
    super(message || code || `HTTP ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.data = data;
  }
}

export function getToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY) ?? '';
  } catch {
    return '';
  }
}

export function setToken(t) {
  try {
    if (t) sessionStorage.setItem(TOKEN_KEY, t);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    // Ignore storage errors in restricted contexts
  }
}

let isRelogging = false;

/**
 * Единая функция выполнения HTTP-запросов к бэкенду.
 *
 * @param {'GET'|'POST'|'PATCH'|'DELETE'} method
 * @param {string} path — путь относительно корня API (напр. '/api/dashboard')
 * @param {object} [options]
 * @param {object} [options.json] — тело в формате JSON
 * @param {FormData} [options.form] — тело в формате FormData (для файлов)
 * @param {number} [options.timeout=15000] — таймаут в миллисекундах
 * @param {boolean} [options.allowRelogin=true] — пытаться ли обновить токен при 401
 * @param {number} [options.retries=1] — количество повторов при сетевых сбоях (только для GET)
 */
export async function request(method, path, options = {}) {
  const {
    json,
    form,
    timeout = 15000,
    allowRelogin = true,
    retries = method === 'GET' ? 1 : 0,
    signal: userSignal,
  } = options;

  const url = apiUrl(path);
  const headers = {};

  const token = getToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
    if (['POST', 'PATCH', 'PUT', 'DELETE'].includes(method.toUpperCase())) {
      headers['X-CSRF-Token'] = token;
    }
  }

  let body = undefined;
  if (json !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(json);
  } else if (form !== undefined) {
    body = form;
    // Content-Type выставляется браузером с boundary автоматически
  }

  // Контроллер таймаута
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new Error('Request timeout')), timeout);

  // Слияние сигналов прерывания
  if (userSignal) {
    userSignal.addEventListener('abort', () => controller.abort(userSignal.reason));
  }

  try {
    const res = await fetch(url, {
      method,
      headers,
      body,
      credentials: 'same-origin',
      signal: controller.signal,
    });
    clearTimeout(timer);

    // 1. Проверка на 401 Unauthorized и попытка авто-релогина
    if (res.status === 401 && allowRelogin && !isRelogging && tg && tg.initData && !path.startsWith('/api/auth')) {
      isRelogging = true;
      try {
        console.warn('[API] 401 получен — попытка авто-релогина...');
        const reAuthOk = await auth(tg.initData);
        if (reAuthOk && reAuthOk.ok !== false && (reAuthOk.token || reAuthOk.csrf_token)) {
          isRelogging = false;
          // Повторяем исходный запрос с новым токеном без повторного релогина
          return await request(method, path, { ...options, allowRelogin: false });
        }
      } catch (authErr) {
        console.error('[API] Авто-релогин не удался:', authErr);
      } finally {
        isRelogging = false;
      }
    }

    // 2. Обработка ошибок (res.ok === false)
    if (!res.ok) {
      let errCode = `http_${res.status}`;
      let errMessage = res.statusText;
      let errData = null;

      try {
        const ct = res.headers.get('content-type') || '';
        if (ct.includes('application/json')) {
          errData = await res.json();
          errCode = errData.error || errData.detail?.error || errCode;
          errMessage = errData.message || errData.detail?.message || errData.detail || errMessage;
        } else {
          errMessage = await res.text();
        }
      } catch {}

      if (res.status === 403 && (errCode === 'panel_locked' || (typeof errMessage === 'string' && errMessage.includes('пароль')))) {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('carnaval:panel_locked'));
        }
      }

      throw new ApiError(res.status, errCode, errMessage, errData);
    }

    // 3. Успешный ответ
    const contentType = res.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      return await res.json();
    }
    if (contentType.includes('text/plain')) {
      return await res.text();
    }
    return res;
  } catch (err) {
    clearTimeout(timer);

    // Не повторяем, если запрос был отменен
    if (err.name === 'AbortError') {
      throw err;
    }

    // Авто-повтор GET запросов при сетевых ошибках
    if (retries > 0 && err.name !== 'ApiError') {
      console.warn(`[API] Сетевой сбой на ${method} ${path}, повтор через 500мс...`);
      await new Promise(r => setTimeout(r, 500));
      return await request(method, path, { ...options, retries: retries - 1 });
    }

    throw err;
  }
}

// ─────────────────────────────────────────────────────────────
// Авторизация и статус
// ─────────────────────────────────────────────────────────────

export async function auth(initData) {
  try {
    const data = await request('POST', '/api/auth/telegram', {
      json: { init_data: initData || '' },
      allowRelogin: false,
    });
    if (data && (data.token || data.csrf_token)) {
      setToken(data.token || data.csrf_token);
      return data;
    }
    return false;
  } catch (e) {
    console.error('[API] Ошибка auth:', e);
    return { ok: false, error: e };
  }
}

export async function panelUnlock(password) {
  return await request('POST', '/api/auth/panel-unlock', {
    json: { password },
  });
}

export async function getAuthMe() {
  return await request('GET', '/api/auth/me');
}

export async function logout() {
  try {
    await request('POST', '/api/auth/logout');
  } finally {
    setToken('');
  }
}

export async function logoutAll() {
  try {
    return await request('POST', '/api/auth/logout-all');
  } finally {
    setToken('');
  }
}

export async function getActiveSessions() {
  return await request('GET', '/api/auth/sessions');
}

export async function changePassword(old_password, new_password) {
  return await request('POST', '/api/auth/change-password', {
    json: { old_password, new_password },
  });
}

export async function getSetupStatus() {
  return await request('GET', '/api/setup/status');
}

export async function claimSetup() {
  return await request('POST', '/api/setup/claim');
}

export async function setupPassword(password) {
  return await request('POST', '/api/setup/password', {
    json: { password },
  });
}

export async function setupGoldenKey(golden_key) {
  return await request('POST', '/api/setup/golden-key', {
    json: { golden_key },
  });
}

export async function setupFunPay(login, password) {
  return await request('POST', '/api/setup/funpay', {
    json: { login, password },
  });
}

export async function testFunPay(login, password) {
  return await request('POST', '/api/setup/funpay/test', {
    json: { login, password },
  });
}

export async function setupProxy(host, port, username = '', password = '') {
  return await request('POST', '/api/setup/proxy', {
    json: { host, port: Number(port), username, password },
  });
}

export async function testProxy(host, port, username = '', password = '') {
  return await request('POST', '/api/setup/proxy/test', {
    json: { host, port: Number(port), username, password },
  });
}

export async function getSecretStatus(name) {
  return await request('GET', `/api/secrets/${name}`);
}

export async function finalizeSetup() {
  return await request('POST', '/api/setup/finalize');
}

export async function getMe() {
  return await request('GET', '/api/me');
}

export async function getDashboard() {
  return await request('GET', '/api/dashboard');
}

export async function getHealth() {
  return await request('GET', '/api/health');
}

export async function getSettings() {
  return await request('GET', '/api/settings');
}

export async function patchSetting(section, key, value, confirm = false) {
  return await request('PATCH', `/api/settings/${encodeURIComponent(section)}/${encodeURIComponent(key)}`, {
    json: { value: String(value), confirm: Boolean(confirm) },
  });
}

// ─────────────────────────────────────────────────────────────
// Заказы
// ─────────────────────────────────────────────────────────────

export async function getOrders(status = null, offset = null, limit = 25) {
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  if (offset) params.set('offset', offset);
  if (limit) params.set('limit', String(limit));
  const qs = params.toString();
  return await request('GET', `/api/orders${qs ? '?' + qs : ''}`);
}

export async function getOrder(orderId) {
  return await request('GET', `/api/orders/${encodeURIComponent(orderId)}`);
}

export async function refundOrder(orderId, confirm = true) {
  return await request('POST', `/api/orders/${encodeURIComponent(orderId)}/refund`, {
    json: { confirm: Boolean(confirm) },
  });
}

export async function sendReviewReply(orderId, text, rating = 5) {
  return await request('POST', `/api/orders/${encodeURIComponent(orderId)}/review-reply`, {
    json: { text, rating },
  });
}

export async function deleteReviewReply(orderId) {
  return await request('DELETE', `/api/orders/${encodeURIComponent(orderId)}/review-reply`);
}

// ─────────────────────────────────────────────────────────────
// Чаты
// ─────────────────────────────────────────────────────────────

export async function getChats(update = false) {
  return await request('GET', `/api/chats${update ? '?update=true' : ''}`);
}

export async function getChatHistory(chatId, before = null) {
  const qs = before ? `?before=${before}` : '';
  return await request('GET', `/api/chats/${encodeURIComponent(chatId)}/history${qs}`);
}

export async function sendMessage(chatId, text, chatName = null) {
  return await request('POST', `/api/chats/${encodeURIComponent(chatId)}/messages`, {
    json: { text, chat_name: chatName },
  });
}

export async function sendImage(chatId, file, chatName = null) {
  const fd = new FormData();
  fd.append('file', file);
  const qs = chatName ? `?chat_name=${encodeURIComponent(chatName)}` : '';
  return await request('POST', `/api/chats/${encodeURIComponent(chatId)}/images${qs}`, {
    form: fd,
  });
}

export async function getBuyerViewing(chatId, buyerId) {
  return await request('GET', `/api/chats/${encodeURIComponent(chatId)}/viewing?buyer_id=${encodeURIComponent(buyerId)}`);
}

// ─────────────────────────────────────────────────────────────
// Автоматизация (Склад, Лоты, Автоответчик, Шаблоны)
// ─────────────────────────────────────────────────────────────

export async function getDeliveryLots() {
  return await request('GET', '/api/delivery/lots');
}

export async function getDeliveryLot(i) {
  return await request('GET', `/api/delivery/lots/${encodeURIComponent(i)}`);
}

export async function createDeliveryLot(data) {
  return await request('POST', '/api/delivery/lots', { json: data });
}

export async function updateDeliveryLot(i, data) {
  return await request('PATCH', `/api/delivery/lots/${encodeURIComponent(i)}`, { json: data });
}

export async function deleteDeliveryLot(i, confirm = true) {
  return await request('DELETE', `/api/delivery/lots/${encodeURIComponent(i)}?confirm=${Boolean(confirm)}`);
}

export async function testDeliveryLot(i) {
  return await request('POST', `/api/delivery/lots/${encodeURIComponent(i)}/test`);
}

export async function getProductsFiles() {
  return await request('GET', '/api/delivery/files');
}

export async function getProductsFile(name) {
  return await request('GET', `/api/delivery/files/${encodeURIComponent(name)}`);
}

export async function uploadProductsFile(file, name = null) {
  const fd = new FormData();
  if (file) fd.append('file', file);
  const qs = name ? `?name=${encodeURIComponent(name)}` : '';
  return await request('POST', `/api/delivery/files${qs}`, { form: fd });
}

export async function addGoodsToFile(name, goods, atZeroPosition = false) {
  return await request('POST', `/api/delivery/files/${encodeURIComponent(name)}/goods`, {
    json: { goods, at_zero_position: atZeroPosition },
  });
}

export async function deleteProductsFile(name, confirm = true) {
  return await request('DELETE', `/api/delivery/files/${encodeURIComponent(name)}?confirm=${Boolean(confirm)}`);
}

export async function getAutoResponseCommands() {
  return await request('GET', '/api/autoresponse/commands');
}

export async function createAutoResponseCommand(data) {
  return await request('POST', '/api/autoresponse/commands', { json: data });
}

export async function updateAutoResponseCommand(i, data) {
  return await request('PATCH', `/api/autoresponse/commands/${encodeURIComponent(i)}`, { json: data });
}

export async function deleteAutoResponseCommand(i, confirm = true) {
  return await request('DELETE', `/api/autoresponse/commands/${encodeURIComponent(i)}?confirm=${Boolean(confirm)}`);
}

export async function getTemplates() {
  return await request('GET', '/api/templates');
}

export async function createTemplate(text) {
  return await request('POST', '/api/templates', { json: { text } });
}

export async function updateTemplate(i, text) {
  return await request('PATCH', `/api/templates/${encodeURIComponent(i)}`, { json: { text } });
}

export async function deleteTemplate(i, confirm = true) {
  return await request('DELETE', `/api/templates/${encodeURIComponent(i)}?confirm=${Boolean(confirm)}`);
}

export async function getFunPayLots(refresh = false) {
  return await request('GET', `/api/funpay/lots${refresh ? '?refresh=true' : ''}`);
}

// ─────────────────────────────────────────────────────────────
// Вкладка «Ещё»
// ─────────────────────────────────────────────────────────────

export async function getNotifications() {
  return await request('GET', '/api/more/notifications');
}

export async function updateNotification(section, key, enabled) {
  return await request('PATCH', '/api/more/notifications', { json: { section, key, enabled } });
}

export async function getGreetings() {
  return await request('GET', '/api/more/greetings');
}

export async function updateGreeting(section, key, value) {
  return await request('PATCH', '/api/more/greetings', { json: { section, key, value } });
}

export async function getBlacklist() {
  return await request('GET', '/api/more/blacklist');
}

export async function addToBlacklist(username) {
  return await request('POST', '/api/more/blacklist', { json: { username } });
}

export async function removeFromBlacklist(username) {
  return await request('DELETE', `/api/more/blacklist/${encodeURIComponent(username)}`);
}

export async function getPlugins() {
  return await request('GET', '/api/more/plugins');
}

export async function togglePlugin(uuid) {
  return await request('POST', `/api/more/plugins/${encodeURIComponent(uuid)}/toggle`);
}

export async function uploadPlugin(file, confirm = false) {
  const fd = new FormData();
  fd.append('file', file);
  fd.append('confirm', String(confirm));
  return await request('POST', '/api/more/plugins/upload', { form: fd });
}

export async function deletePlugin(uuid, confirm = true) {
  return await request('DELETE', `/api/more/plugins/${encodeURIComponent(uuid)}?confirm=${Boolean(confirm)}`);
}

export async function getProxy() {
  return await request('GET', '/api/more/proxy');
}

export async function addProxy(proxy) {
  return await request('POST', '/api/more/proxy', { json: { proxy } });
}

export async function deleteProxy(proxy_id) {
  return await request('DELETE', `/api/more/proxy/${encodeURIComponent(proxy_id)}`);
}

export async function activateProxy(proxy_id) {
  return await request('POST', `/api/more/proxy/${encodeURIComponent(proxy_id)}/activate`);
}

export async function setProxyEnabled(enabled) {
  return await request('PATCH', '/api/more/proxy/enabled', { json: { enabled } });
}

export async function getAuthorizedUsers() {
  return await request('GET', '/api/more/authorized-users');
}

export async function removeAuthorizedUser(user_id, confirm = true) {
  return await request('DELETE', `/api/more/authorized-users/${encodeURIComponent(user_id)}?confirm=${Boolean(confirm)}`);
}

export async function getAccountInfo() {
  return await request('GET', '/api/more/account');
}

export async function changeGoldenKey(new_key, confirm = false) {
  return await request('POST', '/api/more/account/golden-key', { json: { new_key, confirm } });
}

export async function deleteGoldenKey(confirm = true) {
  return await request('DELETE', `/api/more/account/golden-key?confirm=${Boolean(confirm)}`);
}

export async function reconnectAccount(force = true) {
  return await request('POST', `/api/more/account/reconnect?force=${Boolean(force)}`);
}

export async function lockPanel() {
  return await request('POST', '/api/auth/panel-lock');
}

export async function getAuditLogs(limit = 100) {
  return await request('GET', `/api/more/audit-logs?limit=${encodeURIComponent(limit)}`);
}

export async function getLogs(n = 150) {
  return await request('GET', `/api/more/logs?n=${encodeURIComponent(n)}`);
}

export async function clearLogs(confirm = true) {
  return await request('DELETE', `/api/more/logs?confirm=${Boolean(confirm)}`);
}

export function getBackupUrl() {
  return apiUrl('/api/more/backup');
}

export async function restoreBackup(file, confirm = false) {
  const fd = new FormData();
  fd.append('file', file);
  fd.append('confirm', String(confirm));
  return await request('POST', '/api/more/backup/restore', { form: fd });
}

export async function restartCardinal(confirm = false) {
  return await request('POST', '/api/more/system/restart', { json: { confirm } });
}

export async function shutdownCardinal(confirm = false) {
  return await request('POST', '/api/more/system/shutdown', { json: { confirm } });
}

export async function getMeta() {
  return await request('GET', '/api/meta', { allowRelogin: false });
}

// ── Алиасы и совместимость страниц ───────────────────────────
export { onEvent as openEventStream } from './sse.js';
export const updateSetting = patchSetting;
export const getOrderDetails = getOrder;
export const sendChatMessage = sendMessage;
export const sendChatImage = sendImage;
export const createDeliveryTest = testDeliveryLot;

export async function createProductsFile(name, goods = []) {
  return await request('POST', '/api/delivery/files', {
    json: { name, goods },
  });
}

// ── Bot Parity Функции ───────────────────────────────────────

export async function getWatermark() {
  return await request('GET', '/api/more/watermark');
}

export async function updateWatermark(watermark) {
  return await request('PATCH', '/api/more/watermark', { json: { watermark } });
}

export async function getGreetingsText() {
  return await request('GET', '/api/more/greetings/text');
}

export async function updateGreetingsText(text) {
  return await request('PATCH', '/api/more/greetings/text', { json: { text } });
}

export async function getGreetingsCooldown() {
  return await request('GET', '/api/more/greetings/cooldown');
}

export async function updateGreetingsCooldown(cooldown) {
  return await request('PATCH', '/api/more/greetings/cooldown', { json: { cooldown: Number(cooldown) } });
}

export async function getOrderConfirmSettings() {
  return await request('GET', '/api/more/order-confirm');
}

export async function getOrderConfirmReplyText() {
  return await request('GET', '/api/more/order-confirm/reply-text');
}

export async function updateOrderConfirmReplyText(text) {
  return await request('PATCH', '/api/more/order-confirm/reply-text', { json: { text } });
}

export async function getReviewReplySettings() {
  return await request('GET', '/api/more/review-reply');
}

export async function getReviewReplyStar(stars) {
  return await request('GET', `/api/more/review-reply/${encodeURIComponent(stars)}`);
}

export async function updateReviewReplyStar(stars, data) {
  return await request('PATCH', `/api/more/review-reply/${encodeURIComponent(stars)}`, { json: data });
}

export async function banUser(username, reason = null) {
  return await request('POST', '/api/more/blacklist/ban', { json: { username, reason } });
}

export async function unbanUser(username, reason = null) {
  return await request('POST', '/api/more/blacklist/unban', { json: { username, reason } });
}

export async function testProxyConnection(proxy_id) {
  return await request('POST', `/api/more/proxy/${encodeURIComponent(proxy_id)}/test`);
}

export async function setProxyCheckEnabled(check) {
  return await request('PATCH', '/api/more/proxy/check', { json: { check: Boolean(check) } });
}

export async function selectProxy(proxy_id) {
  return await request('POST', '/api/more/proxy/select', { json: { proxy_id: Number(proxy_id) } });
}

export async function getAuthorizedUser(target_user_id) {
  return await request('GET', `/api/more/authorized-users/${encodeURIComponent(target_user_id)}`);
}

export async function pinPlugin(uuid) {
  return await request('POST', `/api/more/plugins/${encodeURIComponent(uuid)}/pin`);
}

export async function getPluginCommands(uuid) {
  return await request('GET', `/api/more/plugins/${encodeURIComponent(uuid)}/commands`);
}

export async function getConfigsList() {
  return await request('GET', '/api/more/configs');
}

export function downloadConfigUrl(config_type) {
  return apiUrl(`/api/more/configs/${encodeURIComponent(config_type)}/download`);
}

export async function uploadConfig(config_type, contentOrFile, confirm = false) {
  if (contentOrFile instanceof File) {
    const fd = new FormData();
    fd.append('file', contentOrFile);
    fd.append('confirm', String(confirm));
    return await request('POST', `/api/more/configs/${encodeURIComponent(config_type)}`, { form: fd });
  } else {
    return await request('POST', `/api/more/configs/${encodeURIComponent(config_type)}`, {
      json: { content: String(contentOrFile), confirm: Boolean(confirm) },
    });
  }
}

export async function requestOrderRefund(order_id) {
  return await request('POST', `/api/orders/${encodeURIComponent(order_id)}/refund/request`);
}

export async function confirmOrderRefund(order_id) {
  return await request('POST', `/api/orders/${encodeURIComponent(order_id)}/refund/confirm`);
}

export async function cancelOrderRefund(order_id) {
  return await request('POST', `/api/orders/${encodeURIComponent(order_id)}/refund/cancel`);
}

export async function getTemplatesAnswerMode(username = null) {
  const qs = username ? `?username=${encodeURIComponent(username)}` : '';
  return await request('GET', `/api/templates/answer-mode${qs}`);
}

export async function renderTemplate(i, username = null) {
  return await request('POST', `/api/templates/${encodeURIComponent(i)}/render`, {
    json: { username },
  });
}

export async function sendTemplate(i, chat_id, username = null) {
  return await request('POST', `/api/templates/${encodeURIComponent(i)}/send`, {
    json: { chat_id: Number(chat_id), username },
  });
}

export async function sendChatTemplate(chat_id, template_index, username = null) {
  return await request('POST', `/api/chats/${encodeURIComponent(chat_id)}/templates`, {
    json: { template_index: Number(template_index), username },
  });
}



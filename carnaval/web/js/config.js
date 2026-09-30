/**
 * config.js — runtime конфигурация Carnaval Mini App.
 *
 * При деплое на Vercel: API-запросы идут через Vercel proxy (/api/*),
 * что означает тот же origin — относительные URL работают без изменений.
 *
 * При прямом подключении к Cardinal (без Vercel):
 * тоже относительные URL — Cardinal сам отдаёт статику.
 *
 * При работе в стороннем окружении (нестандартный деплой):
 * задайте window.__CARNAVAL_API в index.html или через серверный шаблонизатор:
 *   <script>window.__CARNAVAL_API = 'https://myserver.example.com';</script>
 */

/**
 * Возвращает базовый URL для API-запросов.
 *
 * Порядок приоритета:
 *  1. window.__CARNAVAL_API  — явно задан в HTML
 *  2. ''                      — относительные URL (Vercel proxy или прямой Cardinal)
 */
export function getApiBase() {
  return (typeof window !== 'undefined' && window.__CARNAVAL_API) || '';
}

/**
 * Строит полный URL для API-запроса.
 * @param {string} path — путь, напр. '/api/dashboard'
 */
export function apiUrl(path) {
  const base = getApiBase();
  // Убираем дублирование слешей
  if (base.endsWith('/') && path.startsWith('/')) {
    return base.slice(0, -1) + path;
  }
  return base + path;
}

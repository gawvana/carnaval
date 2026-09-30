# Carnaval — Telegram Mini App для FunPay Cardinal

**Carnaval** — полнофункциональная панель управления FunPay Cardinal в формате Telegram Mini App (Mattering Design System v2, Apple Liquid Glass, пружинные анимации, нативный haptic feedback).

---

## 🏛 Архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                    Telegram Messenger Client                    │
│    (Mini App WebView / WebApp Button / MenuButtonWebApp)        │
└────────────────┬───────────────────────────────┬────────────────┘
                 │ 1. Загрузка статики (HTML/JS)  │ 2. Прямые API & SSE запросы
                 ▼                               │    (Authorization: Bearer)
┌────────────────────────────────┐               │
│        Vercel Edge CDN         │               │
│    (Статический фронтенд)      │               │
│   • carnaval/web (HTML/CSS/JS) │               │
│   • runtime-config.js (API URL)│               │
└────────────────────────────────┘               ▼
                                 ┌────────────────────────────────┐
                                 │   Infrlo Cloud / VPS Server    │
                                 │  (Cardinal Бот + Carnaval API) │
                                 │   • Fast-API Daemon Thread     │
                                 │   • SSE Bridge (Last-Event-ID) │
                                 │   • Persistent Volume (configs)│
                                 │   • Strict CORS (Vercel Domain)│
                                 └───────────────┬────────────────┘
                                                 │ FunPay API (Requests)
                                                 ▼
                                 ┌────────────────────────────────┐
                                 │          FunPay.com            │
                                 └────────────────────────────────┘
```

---

## 🔒 Безопасность

1. **Криптографическая проверка `initData`**: HMAC-SHA256 валидация с использованием токена Telegram-бота.
2. **Сессионные токены**: HMAC-SHA256 с TTL 4 часа. Токены передаются **только** в заголовке `Authorization: Bearer <token>`, никогда в строке запроса (URL).
3. **Проверка отзыва доступа на каждом запросе**: Зависимость `require_user` при каждом обращении к API проверяет, что `user_id` находится в списке `authorized_users` Telegram-бота. При отзыве доступа пользователь немедленно блокируется.
4. **Строгий CORS**: Значение `*` в продакшене запрещено. Разрешены только явные домены фронтенда на Vercel.
5. **Подтверждение опасных действий (`confirm: true`)**: Возврат средств, смена `golden_key`, загрузка и удаление плагинов, удаление товаров, шаблонов и команд, очистка логов, перезапуск и выключение требуют подтверждения и логируются в аудит-лог.
6. **Безопасность транспорта**: `Content-Security-Policy: frame-ancestors 'none'` для ответов API, `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`.

---

## 🚀 Пошаговое развёртывание

### 1. Бэкенд (Infrlo или VPS)
Подробная инструкция в [docs/infrlo.md](docs/infrlo.md).

Задайте переменные окружения:
- `FUNPAY_GOLDEN_KEY` — ключ FunPay
- `TG_BOT_TOKEN` — токен бота из @BotFather
- `TG_PANEL_PASSWORD` — пароль для входа в бота
- `CARNAVAL_ENABLED=1`
- `CARNAVAL_ALLOWED_ORIGINS=https://your-app.vercel.app`
- `CARNAVAL_PUBLIC_URL=https://your-app.vercel.app`
- `CARNAVAL_TRUST_PROXY=1`

### 2. Фронтенд (Vercel)
1. **Import Git Repository**: `gawvana/carnaval`
2. **Framework Preset**: Other
3. **Build Command**: `node scripts/gen-config.mjs`
4. **Output Directory**: `carnaval/web`
5. **Environment Variables**:
   - `CARNAVAL_API_URL` = `https://your-backend.infrlo.app` (без слэша на конце)
6. Нажмите **Deploy**.

### 3. Настройка Telegram (@BotFather)
1. Откройте `@BotFather` -> `/mybots` -> выберите вашего бота.
2. **Bot Settings** -> **Menu Button** -> **Configure menu button**:
   - URL: `https://your-app.vercel.app`
   - Text: `Carnaval`
3. Бот автоматически подключит Mini App меню и кнопку запуска.

---

## 🧪 Тестирование и запуск в dev-режиме

```bash
# Запуск dev-сервера с мок-данными (браузер + эмуляция):
python dev_server.py
# Откройте: http://127.0.0.1:8765

# Запуск полного набора тестов:
pytest -q
```

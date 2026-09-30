# Carnaval — Telegram Mini App для FunPay Cardinal

**Carnaval** — полнофункциональная панель управления FunPay Cardinal в формате Telegram Mini App (Mattering Design System v2, Apple Liquid Glass, пружинные анимации, нативный haptic feedback).

---

## 🏛 Архитектура (Vercel Frontend + Infrlo Backend)

Проект работает по модели раздельного развёртывания со сквозным Same-Origin проксированием через Vercel Rewrites:

```text
                    TELEGRAM MESSENGER
                            │
                            ▼
                    MINI APP FRONTEND
                 https://<vercel-domain>/
                            │
                    /api/* external rewrite
                            │
                            ▼
                    INFRLO BACKEND RUNTIME
                 https://<infrlo-backend>/
                            │
             ┌──────────────┴──────────────┐
             │                             │
          FastAPI                   Telegram Bot Worker
       • REST API                    • WebApp Menu Button
       • SSE Stream (/api/events)    • Admin Management
       • Rate Limits & CSRF          • Notifications
             │                             │
             └──────────────┬──────────────┘
                            │
                            ▼
                     Cardinal Engine
               (FunPay Polling & Automation)
                            │
             ┌──────────────┴──────────────┐
             │                             │
       SQLite Database               Encrypted Secrets
       (/data/app.db)             (/data/secrets/master.key)
```

- **Vercel** хостит статический фронтенд (`carnaval/web/`). Vercel прозрачно проксирует `/api/*` на бэкенд Infrlo через external rewrite в `vercel.json`. В браузере и WebView это один origin — куки `HttpOnly; SameSite=Lax`, CSRF и сессии работают без проблем.
- **Infrlo** выполняет контейнер бэкенда: FastAPI, Telegram-бот, автоматизация Cardinal, персистентный диск `/data` с базой SQLite и AES-256-GCM шифрованием.

---

## 🚀 Минимальный быстрый запуск (Section 76)

Вся настройка занимает несколько минут и не требует ручного создания множества `.env` файлов:

1. **Создайте или перевыпустите Telegram-бота**:
   - В `@BotFather` получите новый токен бота: `TG_BOT_TOKEN`.
2. **Разверните бэкенд на Infrlo**:
   - Подключите репозиторий `gawvana/carnaval`.
   - Примонтируйте **Persistent Volume** в папку `/data`.
   - Задайте **единственную обязательную переменную окружения**:
     ```env
     TG_BOT_TOKEN=ваш_токен_бота
     ```
   - Настройте Healthcheck: `/health` (порт `8000`).
   - Получите публичный адрес бэкенда: `https://<ваш-бэкенд>.infrlo.app`.
3. **Разверните фронтенд на Vercel**:
   - Импортируйте репозиторий `gawvana/carnaval` в Vercel.
   - Build Command: `node scripts/build-vercel.mjs`
   - Output Directory: `carnaval/web`
   - Environment Variables:
     ```env
     BACKEND_PUBLIC_ORIGIN=https://<ваш-бэкенд>.infrlo.app
     ```
   - Получите публичный адрес фронтенда: `https://<ваш-проект>.vercel.app`.
4. **Настройте кнопку Menu Button в Telegram**:
   - В `@BotFather`: `/mybots` -> выберите бота -> **Bot Settings** -> **Menu Button** -> **Configure menu button**:
     - URL: `https://<ваш-проект>.vercel.app`
     - Текст: `Открыть панель`
5. **Откройте Telegram-бота и запустите Mini App**:
   - Отправьте боту команду `/start` и нажмите «Открыть панель».
6. **Пройдите первичный мастер Onboarding**:
   - Подтверждение владельца (Claim Ownership).
   - Создание мастер-пароля панели (Argon2id).
   - Ввод Golden Key FunPay (сохраняется в AES-256-GCM зашифрованном виде).
   - Настройка учетных данных FunPay и Прокси (опционально).
   - Финализация.

---

## 🔒 Безопасность

1. **Принцип единственного секрета (One Secret Principle)**:
   - Контейнеру на Infrlo для старта нужен только `TG_BOT_TOKEN`.
   - Никаких секретов в коде, Git или Vercel бандле.
   - Секреты `golden_key`, `funpay_password`, `proxy_password` вводятся внутри Mini App и шифруются **AES-256-GCM** с мастер-ключом в `/data/secrets/master.key` (права 0600).
2. **Двухуровневая аутентификация**:
   - **Слой 1**: HMAC-SHA256 верификация `Telegram.WebApp.initData` с защитой от Replay-атак (`auth_date` $\le$ 1 час).
   - **Слой 2**: Разблокировка панели мастер-паролем (Argon2id) с блокировкой на 15 минут после 5 неверных попыток.
3. **Сессии и Same-Origin безопасность**:
   - Серверные сессии в SQLite (токены хешируются алгоритмом SHA-256).
   - Куки: `HttpOnly; Secure; SameSite=Lax`.
   - `X-CSRF-Token` проверяется на всех мутирующих запросах (`POST`, `PUT`, `PATCH`, `DELETE`).
4. **Фильтрация и санитизация**:
   - Контекстное экранирование HTML на фронтенде (`sanitize.js`) предотвращает XSS.
   - Централизованный лог-фильтр маскирует токены ботов, Golden Key и куки.
   - Защита от Zip Slip (../) и Zip Bomb при работе с бэкапами и плагинами.
   - SSRF защита при валидации прокси и вебхуков (блокировка loopback, приватных сетей и cloud metadata).

---

## 🧪 Тестирование

Полный набор unit- и security-тестов (63 теста, 100% passing):

```bash
pytest -v
```

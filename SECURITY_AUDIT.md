# SECURITY AUDIT — Carnaval / Cardinal

**Проект:** Carnaval / FunPay Cardinal Telegram Mini App & Automation Bot  
**Версия:** 1.0.0 Production  
**Дата аудита:** 30 сентября 2026 г.  
**Архитектура:** Hybrid Decoupled (Vercel Frontend + External Rewrite -> Infrlo Backend)  
**Статус автоматизированных тестов:** 63/63 passed (100%)

---

## 1. Architecture

Система построена на разделении ответственности между статическим фронтендом на Vercel и полнофункциональным защищенным runtime бэкендом на Infrlo:

```text
                     TELEGRAM MESSENGER
                             │
                             ▼ (WebApp / MenuButton)
                     MINI APP FRONTEND
                  https://<vercel-domain>/
                             │
                     /api/* external rewrite
                             │
                             ▼
                     INFRLO BACKEND RUNTIME
                  https://<infrlo-backend>/
                             │
            ┌────────────────┴────────────────┐
            │                                 │
     FastAPI Service                   Telegram Bot Worker
      • Same-Origin API                 • Menu Button WebApp
      • SSE Streams (/api/events)       • Admin Chat Management
      • Rate Limiting & CSRF            • Notifications
            │                                 │
            └────────────────┬────────────────┘
                             │
                             ▼
                      Cardinal Engine
                (FunPay Polling & Automation)
                             │
            ┌────────────────┴────────────────┐
            │                                 │
      SQLite Persistent               AES-256-GCM Encrypted
      Storage (/data/app.db)          Secrets (/data/secrets/)
```

1. **Vercel Frontend**:
   - Обслуживает статические HTML/CSS/JS файлы Mini App (`carnaval/web/`).
   - Не выполняет Python-логику, не хранит базу данных SQLite, не имеет доступа к секретам.
   - Прозрачно перенаправляет запросы `/api/*` на бэкенд Infrlo через external rewrite в `vercel.json` и Build Output API v3 (`.vercel/output/config.json`).
   - Для браузера Mini App и API находятся на одном origin (`https://<vercel-domain>/`), что обеспечивает бесшовную работу SameSite cookies, CSRF токенов и fetch-запросов.
2. **Infrlo Backend**:
   - Контейнеризированный сервис (Docker), работающий от пользователя `app` (UID 1000).
   - Запускает FastAPI сервер, Telegram-бота (telebot) и автоматизацию Cardinal в едином надежном супервизоре.
   - Монтирует персистентный том в `/data` для надежного сохранения базы данных, конфигураций, плагинов и зашифрованных ключей.
3. **Cardinal & FunPay Integration**:
   - Осуществляет мониторинг заказов, автовыдачу товаров, автоподнятие лотов и пересылку чатов с FunPay.
   - Запускается динамически: даже если при старте контейнера Golden Key отсутствует, сервер стартует в режиме ожидания первичной настройки без сбоев.

---

## 2. Authentication

Аутентификация построена по принципу нулевого доверия (Zero Trust) и разделена на два строгих независимых слоя:

1. **Слой 1 — Криптографическая идентификация Telegram (HMAC-SHA256)**:
   - Вход в систему происходит через передачу `Telegram.WebApp.initData` на эндпоинт `POST /api/auth/telegram`.
   - Backend проверяет HMAC-SHA256 подпись данных Telegram с использованием ключа `HMAC-SHA256(b"WebAppData", TG_BOT_TOKEN)`.
   - `initDataUnsafe` на клиенте используется исключительно для отображения имени в UI и категорически отвергается как доказательство авторизации на бэкенде.
   - **Защита от Replay-атак**: Проверяется временная метка `auth_date`. Запросы старше 1 часа (3600 секунд) отклоняются.
2. **Слой 2 — Разблокировка панели управления (Panel Unlock)**:
   - Аутентификация в Telegram подтверждает личность пользователя, но оставляет панель в заблокированном состоянии (`panel_unlocked = false`).
   - Для доступа к критическим функциям (настройки, заказы, секреты, бэкапы, плагины) требуется ввод мастер-пароля панели (`POST /api/auth/panel-unlock`).
   - Пароль проверяется с защитой от перебора (см. раздел Authorization).

---

## 3. Authorization

Система разграничения прав доступа гарантирует изоляцию управления инстансом:

1. **Ролевая модель**:
   - `owner` (Владелец) — полный доступ к системе, смене паролей, управлению Golden Key и шифрованным хранилищем.
   - `admin` (Авторизованный пользователь) — доступ к операционной работе (заказы, чаты).
   - Неавторизованные пользователи Telegram получают отказ в доступе (403 Forbidden).
2. **Машина состояний первого владельца (Owner Claim State Machine)**:
   - Состояния: `UNINITIALIZED` $\rightarrow$ `OWNER_CLAIM` $\rightarrow$ `INITIALIZED`.
   - Перевод в статус владельца защищен эксклюзивной атомарной транзакцией SQLite (`BEGIN IMMEDIATE`).
   - Первый администратор бота, открывший Mini App, заявляет владение. Повторные запросы или попытки параллельного захвата отклоняются с `409 Conflict`.
3. **Немедленный отзыв доступа (Real-time Revocation)**:
   - Зависимость `require_telegram_auth` на каждом запросе проверяет актуальность прав пользователя в списке `authorized_users` Telegram-бота.
   - При удалении администратора из бота его доступ к Mini App аннулируется мгновенно.

---

## 4. Session Security

1. **Серверные сессии в SQLite**:
   - Токен сессии генерируется криптографически стойким генератором: `<user_id>.<urlsafe_token_entropy>` (более 192 бит энтропии).
   - В базе данных SQLite (`sessions`) сохраняется **исключительно SHA-256 хеш токена** (`session_id_hash`). Сырые токены сессий в базе не хранятся.
2. **Транспорт сессионных токенов**:
   - При успешном входе бэкенд выставляет куку:
     `Set-Cookie: carnaval_session=...; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=14400`
   - Поддерживается также передача в заголовке `Authorization: Bearer <token>`. Токены никогда не передаются через параметры URL (query string).
3. **Таймауты и завершение**:
   - Абсолютное время жизни сессии (Absolute TTL): 4 часа.
   - Таймаут неактивности (Idle Timeout): 30 минут (`last_seen_at`).
   - Реализованы эндпоинты `POST /api/auth/logout` (завершение текущей сессии) и `POST /api/auth/logout-all` (отзыв всех активных сессий на всех устройствах пользователя).

---

## 5. Secret Management

1. **Централизованный SecretManager**:
   - Все конфиденциальные параметры (`golden_key`, `funpay_password`, `proxy_password`, `session_secret`) управляются исключительно через класс `SecretManager`.
2. **Симметричное шифрование AES-256-GCM**:
   - Шифрование Authenticated Encryption with Associated Data (AEAD).
   - Мастер-ключ шифрования (256 бит) создается при первом старте и хранится в защищенном файле `/data/secrets/master.key` с правами доступа `0600`.
   - Для каждого шифрования генерируется уникальный криптографический 96-битный nonce (`os.urandom(12)`).
   - В таблице `secrets` хранятся только зашифрованный `ciphertext` и `nonce`.
3. **Принцип единственного переменного окружения (Single Secret Principle)**:
   - Единственная обязательная переменная окружения для запуска контейнера: `TG_BOT_TOKEN`.
   - Никаких обязательных `.env` переменных для `GOLDEN_KEY`, `FUNPAY_PASSWORD`, `PROXY_PASSWORD` не требуется. Они настраиваются через зашифрованный интерфейс Mini App.
4. **Автоматическая миграция (Secret Migration)**:
   - Метод `SecretManager.migrate_legacy_env_secrets()` при старте приложения автоматически обнаруживает переменные окружения из старых версий, шифрует их в базу данных и удаляет из `os.environ`.
5. **Запрет выдачи секретов (Zero Secret Leakage)**:
   - Эндпоинты API (например, `GET /api/secrets/golden-key` или `GET /api/more/account`) возвращают **только статус наличия**: `{"configured": true}` или маскированное значение `••••••••••••••••`. Сырое значение секрета клиенту не передается ни при каких обстоятельствах.

---

## 6. Telegram Security

1. **Валидация launch-параметров**:
   - Валидация алгоритмом HMAC-SHA256 с токеном бота.
   - Валидация строго по спецификации Telegram Core: сортировка параметров, конкатенация строк через `\n`, вычисление промежуточного ключа `HMAC-SHA256(b"WebAppData", bot_token)`.
2. **Защита Menu Button**:
   - Кнопка меню настраивается через метод `set_chat_menu_button` и указывает исключительно на доверенный HTTPS URL фронтенда на Vercel (`https://<vercel-domain>/`).
3. **Интерактивные команды бота**:
   - Команда `/start` возвращает приветствие и WebApp-кнопку «Открыть панель». Прямой доступ к управлению через незащищенные чаты заблокирован.

---

## 7. Frontend Security

1. **Защита от XSS (Cross-Site Scripting)**:
   - Библиотека `carnaval/web/js/ui/sanitize.js` содержит строгое экранирование (`escapeHtml`).
   - Все динамические данные (имена покупателей, сообщения чатов, параметры товаров, отзывы, заголовки лотов) проходят обязательное экранирование перед вставкой в DOM.
   - Запрещено использование `eval` и `new Function`.
2. **Контекст браузера**:
   - `localStorage` и `sessionStorage` не используются для хранения мастер-ключей или паролей.
   - Для выполнения API запросов используется централизованный клиент `web/js/api.js` с относительными путями (`/api/...`) и `credentials: 'same-origin'`.

---

## 8. API Security

1. **CSRF Защита**:
   - Защита базируется на SameSite куках и валидации токена `X-CSRF-Token` на всех мутирующих методах (`POST`, `PUT`, `PATCH`, `DELETE`).
   - Если запрос отправлен с сессионной кукой, заголовок `X-CSRF-Token` должен совпадать с токеном сессии, иначе возвращается 403 Forbidden.
2. **CORS (Cross-Origin Resource Sharing)**:
   - В продакшене `allow_origins=["*"]` запрещено.
   - Разрешаются только явные домены Vercel (`CARNAVAL_ALLOWED_ORIGINS`).
3. **Защита от подбора паролей (Brute-Force & Lockout Rate Limiting)**:
   - Максимум 5 неудачных попыток ввода пароля панели.
   - После 5 ошибок наступает временная блокировка на 15 минут (900 секунд).
   - Общий рейт-лимит на мутирующие запросы API: 60 запросов в минуту на IP.
4. **Защитные заголовки HTTP (Security Headers)**:
   - `Cache-Control: no-store, no-cache, must-revalidate` (для приватных API)
   - `Content-Security-Policy: frame-ancestors 'none'` (для API)
   - `Content-Security-Policy: ... frame-ancestors https://web.telegram.org https://*.telegram.org telegram:;` (для UI)
   - `X-Content-Type-Options: nosniff`
   - `Referrer-Policy: strict-origin-when-cross-origin`
   - `Permissions-Policy: geolocation=(), microphone=(), camera=()`

---

## 9. File Security

1. **Лимиты загрузки файлов**:
   - Ограничение размера файлов загрузки: до 50 МБ.
   - Обработка входящих файлов без загрузки гигантских объектов в оперативную память.
2. **Защита от Zip Slip (Path Traversal)**:
   - Функция `validate_zip_archive()` проверяет каждый элемент архива: использование `os.path.commonpath([dest, target]) == dest`. Любые пути, содержащие `../` или абсолютные пути, вызывают `ZipValidationError` и немедленно отклоняются.
3. **Защита от Zip Bomb (Архивных бомб)**:
   - Ограничение максимального количества файлов в архиве: не более 500 файлов.
   - Ограничение суммарного распакованного размера: не более 50 МБ.
   - Запрет символических и жестких ссылок (проверка Unix permission bits `0o120000`).

---

## 10. Plugin Security

1. **Проверка манифестов и метаданных**:
   - Загрузка плагинов проходит строгую валидацию путей, структуры и имени файла.
   - Плагины не имеют доступа к чтению каталога `/data/secrets/` или прямому изменению таблиц авторизации.
2. **Изоляция исполнения**:
   - Контейнер Docker выполняется от непривилегированного пользователя `app`, что исключает возможность модификации системных файлов хоста через плагин.

---

## 11. Docker Security

1. **Непривилегированный пользователь (Non-root Execution)**:
   - В `Dockerfile` создан пользователь `app` с фиксированным UID 1000:
     ```dockerfile
     RUN groupadd -g 1000 app && useradd -u 1000 -g app -s /bin/bash app
     USER app
     ```
2. **Исключение секретов из образа (.dockerignore)**:
   - `.dockerignore` гарантирует, что локальные файлы `.env*`, `data/`, `*.db`, `master.key`, `carnaval_secret.key`, логи и бэкапы никогда не попадут в скомпилированный Docker образ.
3. **Healthcheck**:
   - Интегрирована автоматическая проверка работоспособности контейнера:
     `HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:8000/health || exit 1`

---

## 12. Vercel Security

1. **Чистый статический бандл**:
   - Vercel фронтенд не содержит секретных переменных окружения (`TG_BOT_TOKEN`, `GOLDEN_KEY` и т.д.).
   - Скрипт сборки `scripts/build-vercel.mjs` проверяет переменные окружения и принудительно удаляет любые случайно попавшие приватные ключи.
2. **External Rewrites**:
   - В `vercel.json` настроен прозрачный реверс-прокси:
     ```json
     {
       "source": "/api/:path*",
       "destination": "https://<infrlo-backend>/api/:path*"
     }
     ```
   - Заголовок `Cache-Control: no-store, no-cache, must-revalidate` исключает кэширование динамических ответов API на Edge CDN Vercel.

---

## 13. Infrlo Security

1. **Persistent Volume**:
   - Каталог `/data` монтируется как постоянный том (Persistent Volume), сохраняющий данные при перезапусках контейнера.
2. **Сетевая изоляция и переменные окружения**:
   - Переменная `PORT` считывается из окружения (по умолчанию 8000).
   - Единственная передаваемая переменная — `TG_BOT_TOKEN`.

---

## 14. Backup Security

1. **Белый список содержимого (Whitelist Approach)**:
   - Функция `create_backup()` архивирует только пользовательские конфигурации (`configs`), шаблоны (`storage`) и плагины (`plugins`).
2. **Гарантированное исключение секретов**:
   - Файлы ключей `master.key`, `carnaval_secret.key`, `*.db`, `*.sqlite`, `.env*`, а также кэши сессий **напрямую исключены** из формирования резервной копии.
   - Тест `test_backup_excludes_secrets` проверяет каждый сформированный архив на отсутствие ключевых файлов.

---

## 15. Tests

Автоматизированный тестовый набор состоит из **63 тестов** (прохождение 100%):
- `tests/test_carnaval_phase1.py` (6 тестов) — базовая функциональность
- `tests/test_carnaval_phase2.py` (3 теста) — API заказов и чатов
- `tests/test_carnaval_phase3.py` (4 теста) — автовыдача и автоответчик
- `tests/test_carnaval_phase4.py` (3 теста) — статистика и аналитика
- `tests/test_carnaval_phase5.py` (6 тестов) — управление плагинами и прокси
- `tests/test_carnaval_phase6.py` (4 теста) — Vercel external rewrites, config.js, CORS
- `tests/test_carnaval_phase7.py` (12 тестов) — интеграционные сценарии
- `tests/test_carnaval_security_master.py` (25 тестов):
  - `test_valid_telegram_init_data` — проверка валидного initData (HMAC-SHA256)
  - `test_invalid_telegram_init_data` — отклонение невалидных токенов и данных
  - `test_expired_telegram_init_data` — отклонение просроченного initData (>1ч)
  - `test_first_owner_claim` — захват владения первым администратором
  - `test_second_owner_rejected` — отклонение повторных попыток захвата
  - `test_owner_claim_race` — атомарность и защита от состояния гонки
  - `test_panel_password` — Argon2id хеширование мастер-пароля
  - `test_password_rate_limit` — блокировка после 5 неудачных попыток
  - `test_session_creation` — создание серверной сессии с SHA-256 хешем
  - `test_session_expiration` — истечение срока неактивности сессии
  - `test_session_revocation` — аннулирование сессии
  - `test_logout_all` — отзыв всех сессий пользователя
  - `test_secret_encryption` — шифрование секретов AES-256-GCM
  - `test_secret_not_returned` — запрет раскрытия сырых секретов в API
  - `test_secret_not_logged` — санитизация логов и фильтрация токенов
  - `test_backup_excludes_secrets` — исключение master.key и .env из бэкапов
  - `test_restore_traversal` — блокировка Zip Slip (../../)
  - `test_zip_bomb` — блокировка архивов, превышающих лимиты
  - `test_upload_limit` — ограничение размера загружаемых файлов
  - `test_xss` — экранирование HTML и защита от XSS
  - `test_ssrf` — защита от SSRF (блокировка loopback, приватных сетей, metadata)
  - `test_cors` — проверка заголовков CORS
  - `test_csrf` — проверка обязательности X-CSRF-Token для мутирующих запросов
  - `test_security_headers` — валидация CSP, nosniff, frame-ancestors
  - `test_startup_with_only_bot_token` — запуск с единственной переменной TG_BOT_TOKEN

---

## 16. Deployment Verification

Процедура проверки сквозного функционирования (End-to-End Checklist):
1. **Frontend (Vercel)**:
   - Проект разворачивается из репозитория `gawvana/carnaval`.
   - Запрос `GET /` отдает HTML/JS интерфейс Mini App.
   - Запрос `GET /api/health` перенаправляется на Infrlo и возвращает `{"status": "ok"}`.
2. **Backend (Infrlo)**:
   - Docker контейнер запускается с переменной `TG_BOT_TOKEN`.
   - Healthcheck на `http://localhost:8000/health` сообщает о статусе `200 OK`.
   - Персистентный диск `/data` содержит базу данных `app.db` и мастер-ключ `secrets/master.key`.
3. **Telegram Mini App Flow**:
   - Открытие Mini App передает `initData` в `POST /api/auth/telegram`.
   - При первом запуске отображается 7-шаговый мастер настройки Onboarding.
   - Владелец сохраняет мастер-пароль панели и Golden Key.
   - Воркеры Cardinal автоматически начинают опрос FunPay и выполнение задач.

---

## 17. Known Limitations

1. **Внешние платформенные токены деплоя**:
   - Автоматическая публикация на production-кластеры Vercel и Infrlo требует наличия соответствующих CLI-токенов (`VERCEL_TOKEN`, Infrlo API credentials). При их отсутствии в локальном окружении деплой осуществляется через подключение Git-репозитория в веб-панелях сервисов.
2. **Ограничения времени жизни соединений на Vercel Free**:
   - Vercel Edge proxy имеет лимит времени жизни HTTP-соединений для Server-Sent Events (SSE). Для обеспечения непрерывной работы в Mini App реализован автоматический fallback: при разрыве SSE-потока клиент прозрачно переключается на периодический поллинг (`startFallbackPolling`), не прерывая работу интерфейса.

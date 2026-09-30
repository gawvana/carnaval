# Carnaval — Telegram Mini App для FunPay Cardinal

**Carnaval** — полнофункциональная панель управления FunPay Cardinal в формате Telegram Mini App (Mattering Design System v2, Apple Liquid Glass, пружинные анимации, нативный haptic feedback).

---

## 🏛 Архитектура (Single-Origin)

Проект работает по **Single-Origin** архитектуре. Никаких внешних фронтенд-хостингов (Vercel и т.д.) не требуется. FastAPI бэкенд на Infrlo раздаёт как статический Mini App (`/`), так и REST API / SSE потоки (`/api/*`):

```
┌─────────────────────────────────────────────────────────────────┐
│                    Telegram Messenger Client                    │
│    (Mini App WebView / WebApp Button / MenuButtonWebApp)        │
└────────────────────────────────┬────────────────────────────────┘
                                 │ HTTPS (same-origin)
                                 │ Cookies / Bearer / CSRF
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Infrlo Cloud / Docker Host                     │
│                  https://<app>.infrlo.app                       │
│                                                                 │
│  FastAPI Application (Port 8000):                               │
│  ├── Static Mini App Files  →  GET /                            │
│  ├── REST API Endpoints     →  /api/*                           │
│  ├── Real-time SSE Streams  →  /api/stream                      │
│  ├── Healthcheck            →  /health                          │
│                                                                 │
│  FunPay Cardinal Engine:                                        │
│  ├── Telegram Bot Worker (aiogram)                              │
│  └── FunPay Polling & Automation Loop                           │
│                                                                 │
│  Encrypted Persistent Storage (/data):                          │
│  ├── SQLite DB (app.db) - AES-256-GCM encrypted secrets        │
│  ├── Master Key (secrets/master.key - 0600)                    │
│  └── Configs, Logs, Backups, Storage                            │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼ FunPay API (Requests)
┌─────────────────────────────────────────────────────────────────┐
│                          FunPay.com                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔒 Безопасность

1. **Единственная обязательная переменная окружения**:
   Для запуска контейнера требуется только:
   ```env
   TG_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
   ```
   Все остальные секреты (`golden_key`, `panel_password`, `master.key`) настраиваются и хранятся внутри через защищённый мастер-интерфейс в Mini App.

2. **Двухуровневая аутентификация**:
   - **Уровень 1 (Telegram Identity)**: Криптографическая валидация `initData` через HMAC-SHA256 с токеном бота, проверка срока давности (replay protection) и прав администратора.
   - **Уровень 2 (Argon2id Panel Unlock)**: Пароль панели хешируется с использованием Argon2id (память: 64 МБ, итерации: 3, параллелизм: 4). Доступ к конфиденциальным операциям требует ввода пароля панели.

3. **Защита от перебора (Brute-Force Protection)**:
   - До 5 попыток ввода пароля панели.
   - При 5 неудачных попытках — временная блокировка на 15 минут с логированием в `audit_logs`.

4. **Шифрование секретов (AES-256-GCM)**:
   - `golden_key` и пароли учетных записей шифруются с использованием ключа `master.key` (хранится в защищенном каталоге `/data/secrets/master.key` с правами 0600).
   - Секреты никогда не попадают в логи, трассировки ошибок или экспортируемые бэкапы.

5. **XSS и CSRF защита**:
   - Контекстное экранирование HTML на фронтенде (`carnaval/web/js/ui/sanitize.js`) для всех динамических данных (имена покупателей, чаты, описания лотов, отзывы).
   - CSRF токены на всех мутирующих запросах (POST, PUT, PATCH, DELETE) с `SameSite=Lax` / `SameSite=Strict`.

6. **Защита бэкапов и файлов**:
   - Архиватор предотвращает атаки Zip Slip (проверка `path.resolve`) и Zip Bomb (ограничение распакованного размера и коэффициента сжатия).
   - Секреты (`*.key`, `*.db`, `master.key`, `.env*`) исключены из бэкапов.

7. **SSRF защита вебхуков**:
   - Валидация URL вебхуков с резолвингом DNS и запретом приватных, локальных и loopback диапазонов IP (`127.0.0.0/8`, `10.0.0.0/8`, `192.168.0.0/16`, `172.16.0.0/12`, `169.254.0.0/16`, `::1`).

---

## 🚀 Развёртывание на Infrlo

Подробное руководство находится в [docs/infrlo.md](docs/infrlo.md).

### Краткий чек-лист:
1. Создайте проект на [Infrlo](https://infrlo.app) с репозиторием `gawvana/carnaval`.
2. Подключите **Persistent Volume** с точкой монтирования `/data`.
3. Укажите единственную переменную окружения:
   ```env
   TG_BOT_TOKEN=ваш_токен_бота
   ```
4. Включите Healthcheck:
   - Путь: `/health`
   - Порт: `8000`
5. В Telegram у `@BotFather` настройте кнопку Web App:
   - `/mybots` -> выберите бота -> **Bot Settings** -> **Menu Button**
   - URL: `https://<ваш-проект>.infrlo.app`
   - Текст: `Carnaval`

---

## 📲 Первичная настройка (Onboarding Wizard)

1. Откройте Telegram-бота и запустите Mini App (по кнопке меню или команде `/start`).
2. При первом запуске откроется **Мастер первичной настройки**:
   - **Шаг 1. Закрепление владельца**: Первый администратор, запустивший Mini App, заявляет права владельца инстанса.
   - **Шаг 2. Пароль панели**: Установите мастер-пароль панели (Argon2id).
   - **Шаг 3. Golden Key FunPay**: Введите ваш Golden Key от FunPay (можно пропустить и ввести позже в настройках).
3. После завершения мастера система готова к работе. Если Golden Key был указан, бот автоматически начнёт опрос FunPay и выполнение сценариев автовыдачи.

---

## 🧪 Тестирование и разработка

```bash
# Запуск полного набора unit- и security-тестов:
pytest -v

# Запуск dev-сервера локально:
python dev_server.py
# Интерфейс доступен по адресу: http://127.0.0.1:8765
```

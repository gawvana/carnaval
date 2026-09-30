# Развёртывание Carnaval + Cardinal на Infrlo (Single-Origin Architecture)

Документ описывает запуск self-hosted экземпляра Carnaval (Telegram Bot + Mini App + FunPay Cardinal) на платформе Infrlo.

---

## 1. Архитектура Single-Origin

- **Без стороннего хостинга (Vercel удален):** Бэкенд FastAPI и фронтенд Telegram Mini App обслуживаются в рамках единого происхождения (Single-Origin) на домене `https://<app>.infrlo.app`.
  - Статический фронтенд: `GET /`
  - REST API & SSE: `GET/POST /api/*`
- **Единый секрет на старте:** Для запуска сервиса требуется **только одна** переменная окружения: `TG_BOT_TOKEN`.
- **Onboarding и настройка из интерфейса:** Golden Key, мастер-пароль панели управления и прокси настраиваются через графический интерфейс Mini App после первого запуска.
- **Шифрование данных:** Все секреты шифруются ключом AES-256-GCM, хранящимся локально в защищенном томе `/data/secrets/master.key`.

---

## 2. Параметры создания сервиса в Infrlo

1. **Dashboard** -> **New Service** -> **Deploy from GitHub repository**:
   - Repository: `gawvana/carnaval` (или ваш форк)
   - Branch: `main`
   - Build Type: `Dockerfile`
   - Service Type: **Web Service (Always On)**

2. **Environment Variables**:
   ```env
   TG_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
   CARNAVAL_TRUST_PROXY=1
   ```
   > 💡 Никаких `FUNPAY_GOLDEN_KEY`, `PANEL_PASSWORD` или `VERCEL` указывать не нужно!

3. **Persistent Volume (Диск)**:
   - Mount Path: `/data`
   - Размер: 2–5 GB
   > В томе `/data` сохраняются: `master.key`, база данных SQLite (`app.db`), конфигурационные файлы, товары автовыдачи и логи.

4. **Health Check**:
   - Path: `/health`
   - Port: `8765` (или `${PORT}`)
   - Protocol: `HTTP`

5. **Networking**:
   - Public HTTPS: Включено (публичный домен вида `https://<app-name>.infrlo.app`)

---

## 3. Первый запуск и привязка к Telegram

1. После деплоя скопируйте публичный URL вашего сервиса (например, `https://my-carnaval.infrlo.app`).
2. В Telegram откройте `@BotFather`:
   - Выберите команду `/mybots` -> выберите вашего бота.
   - Перейдите в **Bot Settings** -> **Menu Button** -> **Configure menu button**.
   - Отправьте ссылку: `https://my-carnaval.infrlo.app`.
   - Введите текст кнопки: `⚡ Carnaval`.
3. Откройте диалог со своим ботом в Telegram и нажмите кнопку меню `⚡ Carnaval`:
   - Шаг 1: Нажмите **«Захватить владение»** (первый клик регистрирует ваш Telegram ID как единственного владельца).
   - Шаг 2: Установите **мастер-пароль панели** (хешируется с Argon2id).
   - Шаг 3: Введите **Golden Key FunPay** (шифруется AES-256-GCM).
   - Шаг 4: Нажмите **«Завершить настройку и войти»**.
4. Готово! Все службы (Cardinal, автовыдача, автоответчик, панель управления) работают в штатном защищенном режиме.

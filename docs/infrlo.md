# Развёртывание бэкенда Carnaval + Cardinal на Infrlo

Документ описывает запуск production-бэкенда Carnaval (FastAPI + Telegram Bot + FunPay Cardinal + SQLite Storage) на облачной платформе Infrlo.

---

## 1. Роль сервиса в архитектуре

```text
Telegram Mini App (Vercel)
         │
         ▼  /api/* external rewrite
Infrlo Backend (FastAPI + Cardinal)
         │
    Persistent Volume (/data)
```

- **Runtime Logic:** FastAPI, фоновый Telegram-бот и автоматизация Cardinal выполняются в контейнере Infrlo.
- **Единый секрет на старте:** Для запуска сервиса требуется **только одна** переменная окружения: `TG_BOT_TOKEN`.
- **Onboarding и настройка из интерфейса:** Golden Key, мастер-пароль панели управления и прокси настраиваются через графический интерфейс Mini App после первого запуска.
- **Шифрование данных:** Все секреты шифруются ключом AES-256-GCM, хранящимся локально в защищенном томе `/data/secrets/master.key`.
- **Vercel External Rewrite:** Vercel фронтенд прозрачно перенаправляет запросы `/api/*` на адрес бэкенда Infrlo. Браузер и Mini App считают происхождение единым (Same-Origin).

---

## 2. Параметры создания сервиса в Infrlo

1. **Dashboard** -> **New Service** -> **Deploy from GitHub repository**:
   - Repository: `gawvana/carnaval` (или ваш форк)
   - Branch: `main`
   - Build Type: `Dockerfile`
   - Service Type: **Web Service (Always On)**

2. **Environment Variables**:
   ```env
   TG_BOT_TOKEN=ваш_токен_бота_из_BotFather
   CARNAVAL_TRUST_PROXY=1
   CARNAVAL_ALLOWED_ORIGINS=https://your-project.vercel.app
   ```
   > 💡 Никаких `FUNPAY_GOLDEN_KEY`, `PANEL_PASSWORD` или других секретов вручную указывать не нужно!

3. **Persistent Volume (Диск)**:
   - Mount Path: `/data`
   - Размер: 2–5 GB
   > В томе `/data` сохраняются: `master.key`, база данных SQLite (`app.db`), конфигурационные файлы, товары автовыдачи и логи.

4. **Health Check**:
   - Path: `/health`
   - Port: `8000` (или `${PORT}`)
   - Protocol: `HTTP`

5. **Networking**:
   - Public HTTPS: Включено (публичный домен вида `https://<app-name>.infrlo.com`)

---

## 3. Подключение Vercel Фронтенда

1. Скопируйте публичный HTTPS URL созданного сервиса Infrlo (например: `https://carnavalqmjw.infrlo.com`).
2. В проекте на **Vercel**:
   - В разделе **Settings** -> **Environment Variables** укажите:
     ```env
     BACKEND_PUBLIC_ORIGIN=https://carnavalqmjw.infrlo.com
     ```
   - Запустите деплой (`node scripts/build-vercel.mjs` выполнится автоматически).
3. В Telegram у `@BotFather`:
   - Настройте кнопку меню на полученный адрес Vercel (`https://your-project.vercel.app`).
4. При открытии Mini App открывается мастер Onboarding, сохраняет мастер-пароль панели и Golden Key в зашифрованном виде.

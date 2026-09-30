# Развёртывание бэкенда Cardinal + Carnaval API на Infrlo

Документ составлен на основе архитектурных требований FunPay Cardinal и платформы Infrlo.

---

## 4.0 Разведка платформы Infrlo

| Вопрос | Ответ и требования | Источник / Обоснование |
|---|---|---|
| **Постоянный процесс** (Continuous process) | **Критично**: Cardinal — бот на циклах `while True`, опрашивающий FunPay раз в секунду. Scale-to-zero (засыпание без входящих HTTP-запросов) **недопустимо**, иначе автовыдача и поднятие лотов прекращаются. Требуется тип сервиса: **Background Worker** или **Web Service (Always On)**. | Архитектура Cardinal (`cardinal.py`, `FunPayAPI.updater`) |
| **Постоянный диск (Persistent Volume)** | **Критично**: Папки `configs/`, `storage/`, `logs/`, `plugins/` содержат `_main.cfg`, товары автовыдачи (`storage/products/`), токены сессии и логи. При перезапуске контейнера без Volume данные будут утеряны. | Точки монтирования `VOLUME` в `Dockerfile` |
| **Способ сборки** | Сборка из GitHub репозитория по `Dockerfile` (Python 3.11). Переменная порта: `$PORT` (передаётся платформой и автоматически подхватывается `bootstrap_env.py` и `server.py`). | `Dockerfile`, `bootstrap_env.py` |
| **HTTPS и SSE** | Платформа предоставляет автоматический бесплатный SSL/TLS сертификат на публичный домен `*.infrlo.app` (или привязанный кастомный домен). Поддержка HTTP/1.1 и HTTP/2 со стримингом SSE без принудительной буферизации (заголовок `X-Accel-Buffering: no`). | `carnaval/routers/events.py` |
| **Лимиты ресурсов** | Cardinal потребляет ~50–150 МБ RAM. Минимального тарифа Infrlo (256–512 МБ RAM) более чем достаточно. | Профиль потребления памяти Cardinal |
| **Доступ к сети** | Требуется беспрепятственный исходящий доступ к `api.telegram.org` и `funpay.com`. Если FunPay блокирует датацентровые IP (Cloudflare Bot Management), в конфиге настраивается резидентский прокси через `FUNPAY_PROXY`. | `configs/_main.cfg` `[Proxy]` |

> ⚠️ **Альтернатива (если Infrlo недоступен или не даёт постоянный процесс/volume):**
> Любой VPS (Ubuntu 22.04 / 24.04, Docker + Docker Compose, Timeweb, Hetzner, Aeza). `docker run -d --name cardinal -v ./configs:/app/configs -v ./storage:/app/storage --env-file .env <image>`

---

## 4.1 Параметры создания сервиса в Infrlo

1. **Dashboard** -> **New Service** -> **Deploy from GitHub repository**:
   - Repository: `gawvana/carnaval`
   - Branch: `main`
   - Build Type: `Dockerfile`
2. **Environment Variables**:
   ```env
   FUNPAY_GOLDEN_KEY=ваш_32_значный_golden_key
   TG_BOT_TOKEN=токен_бота_из_BotFather
   TG_PANEL_PASSWORD=секретный_пароль_для_входа_в_бота
   CARNAVAL_ENABLED=1
   CARNAVAL_HOST=0.0.0.0
   CARNAVAL_ALLOWED_ORIGINS=https://your-carnaval.vercel.app
   CARNAVAL_PUBLIC_URL=https://your-carnaval.vercel.app
   CARNAVAL_TRUST_PROXY=1
   ```
3. **Persistent Disks (Volumes)**:
   - Volume 1: `/app/configs` (размер 1 GB)
   - Volume 2: `/app/storage` (размер 2 GB)
   - Volume 3: `/app/plugins` (размер 1 GB)
4. **Health Check**:
   - Path: `/api/meta`
   - Port: `${PORT}`
   - Protocol: `HTTP`
5. **Networking**:
   - Public HTTPS: Включено (публичный домен вида `https://<app-name>.infrlo.app`)

---

## 4.2 Проверка после деплоя

```bash
# 1. Проверка публичного мета-эндпоинта (без CORS-origins в ответе):
curl https://<your-backend>.infrlo.app/api/meta
# Ожидается: {"app":"Carnaval","version":"0.1.17.15"}

# 2. Проверка healthcheck:
curl https://<your-backend>.infrlo.app/api/health
# Ожидается: {"status":"ok","app":"Carnaval",...}
```

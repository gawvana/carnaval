# Forensic Bug Reproduction: Carnaval Final Remediation

> **Дата составления:** 2026-10-01  
> **Окружение:** Google Antigravity 2.0 / Windows / Python 3.12 / FastAPI / Telegram Mini App  
> **Принцип:** Никаких правок в коде до фиксации точного воспроизведения, ожидаемого и фактического поведения.

---

## Таблица верифицированных дефектов

| ID | Область | Критичность | Корневой файл | Статус воспроизведения |
| :--- | :--- | :---: | :--- | :---: |
| **BUG-01** | Update Engine | **P0** | `carnaval/services/update.py` | **REPRODUCED** |
| **BUG-02** | Update API Contract | **P0** | `carnaval/routers/update.py`, `updates.js` | **REPRODUCED** |
| **BUG-03** | Update & System Auth | **P0** | `carnaval/routers/update.py` | **REPRODUCED** |
| **BUG-04** | Plugin Lab Route Mismatch | **P0** | `carnaval/web/js/pages/plugins_lab.js` | **REPRODUCED** |
| **BUG-05** | Fake Plugins Fallback | **P1** | `carnaval/web/js/pages/plugins_lab.js` | **REPRODUCED** |
| **BUG-06** | Command Palette Broken Routes | **P1** | `command_palette.js`, `error_center.js`, `updates.js` | **REPRODUCED** |
| **BUG-07** | Health Map False Positives | **P1** | `carnaval/web/js/ui/health_map.js` | **REPRODUCED** |
| **BUG-08** | Weak Health Account Rule | **P1** | `carnaval/services/live.py` | **REPRODUCED** |
| **BUG-09** | Live Timeline Fake Events | **P1** | `carnaval/web/js/ui/timeline.js` | **REPRODUCED** |
| **BUG-10** | Automation Simulator Fake Results | **P1** | `carnaval/web/js/pages/automation_lab.js` | **REPRODUCED** |
| **BUG-11** | Automation Builder Scaffold | **P1** | `carnaval/web/js/pages/automation_lab.js` | **REPRODUCED** |
| **BUG-12** | Missing Add Authorized User | **P1** | `routers/more.py`, `api.js`, `more.js` | **REPRODUCED** |
| **BUG-13** | UI Emoji Residuals | **P2** | `app.js`, `dashboard.js`, `onboarding.js`, `automation_lab.js` | **REPRODUCED** |

---

## Подробное описание каждого дефекта

### BUG-01: Update System Simulated Installation & Missing Artifact Pipeline
- **BUG:** Движок обновлений `install_update()` не выполняет распаковку и атомарную установку файлов из артефакта, а лишь перезаписывает строковые метаданные версий в SQLite (`system_state`).
- **EXPECTED:** Реальный цикл обновления: валидация манифеста -> проверка хеша SHA-256 и размера артефакта -> pre-update бэкап -> атомарное стадирование файлов во временную директорию -> миграции схемы SQLite -> атомарная замена -> health check -> откат при сбое.
- **ACTUAL:** В `carnaval/services/update.py` (строки 528-530) происходит только:
  ```python
  set_state(STATE_APP_VERSION_KEY, target_ver)
  set_state(STATE_BACKEND_VERSION_KEY, target_ver)
  ```
- **REPRODUCTION:** Вызов `install_update()` с валидным zip-архивом оставляет файлы приложения нетронутыми, меняя только строковое значение в БД.
- **ROOT CAUSE:** Отсутствие модуля атомарного распаковщика и стадирования файлов артефакта.
- **STATUS:** **REPRODUCED**

---

### BUG-02: Update API Contract & Manifest Schema Mismatch
- **BUG:** Несовместимость контракта между фронтендом `updates.js` и бэкендом `routers/update.py`.
- **EXPECTED:** Унифицированный ответ проверки обновлений:
  ```json
  {
    "ok": true,
    "current_version": "2.1.0",
    "latest_version": "2.2.0",
    "update_available": true,
    "channel": "stable",
    "manifest": { ... },
    "status": "idle",
    "progress": 100,
    "error_code": null
  }
  ```
  И эндпоинт установки `POST /api/updates/install { manifest_id, version }`, где бэкенд сам берет валидированный артефакт.
- **ACTUAL:** Бэкенд возвращал `{ update_available, current_version, latest_version, manifest }`, а фронтенд в `updates.js` (строка 191) считывал `res.version`, получая `undefined`. При установке фронтенд отправлял `{ version }`, тогда как бэкенд ожидал `manifest` и `artifact_bytes_b64`.
- **REPRODUCTION:** Нажатие кнопки «Проверить» в Центре обновлений показывает уведомление `Найдено обновление: vundefined`. Нажатие «Установить» отправляет `{ version: undefined }` и падает.
- **ROOT CAUSE:** Асинхронная разработка моделей запроса/ответа без общего контракта.
- **STATUS:** **REPRODUCED**

---

### BUG-03: Update & System Modes Endpoints Lack Authorization (Security Critical)
- **BUG:** Деструктивные эндпоинты обновления и переключения системных режимов не имеют проверки авторизации.
- **EXPECTED:** Эндпоинты:
  - `POST /api/updates/install`
  - `POST /api/updates/rollback`
  - `POST /api/system/maintenance`
  - `POST /api/system/safe-mode`
  должны требовать `require_panel_unlocked` (или `require_owner`), предотвращая несанкционированные перезагрузки и отключения автовыдачи.
- **ACTUAL:** В `carnaval/routers/update.py` функции принимают только `request: Request` без `Depends(...)`. Любой анонимный сетевой запрос может перевести систему в Maintenance Mode.
- **REPRODUCTION:** Вызов `curl -X POST http://localhost:5000/api/system/maintenance -H "Content-Type: application/json" -d '{"enabled": true}'` возвращает HTTP 200 без токена.
- **ROOT CAUSE:** Пропущены зависимости внедрения безопасности в `carnaval/routers/update.py`.
- **STATUS:** **REPRODUCED**

---

### BUG-04: Plugin Lab Endpoint Path Mismatches
- **BUG:** Фронтенд Лаборатории плагинов обращается к несуществующим путям `/api/plugins/...`.
- **EXPECTED:** Вызовы списка, переключения, закрепления и перезагрузки плагинов должны соответствовать реальным роутам бэкенда.
- **ACTUAL:** `carnaval/web/js/pages/plugins_lab.js` вызывает:
  - `GET /api/plugins` (в бэкенде: `GET /api/more/plugins`)
  - `POST /api/plugins/{uuid}/toggle` (в бэкенде: `POST /api/more/plugins/{uuid}/toggle`)
  - `POST /api/plugins/{uuid}/pin` (в бэкенде: отсутствует / `more/plugins`)
  - `POST /api/plugins/{uuid}/reload` (в бэкенде: `POST /api/more/plugins/{uuid}/reload`)
  - `POST /api/plugins/reload-all` (в бэкенде: `POST /api/more/plugins/reload-all`)
- **REPRODUCTION:** Переход на страницу `#/plugins-lab` отправляет `GET /api/plugins` и получает HTTP 404 Not Found.
- **ROOT CAUSE:** Несоответствие префикса пути `/api/plugins` vs `/api/more/plugins`.
- **STATUS:** **REPRODUCED**

---

### BUG-05: Fake Plugins Fallback in Plugin Lab
- **BUG:** При недоступности бэкенда страница плагинов генерирует вымышленные плагины.
- **EXPECTED:** При ошибке сети отображается честное состояние ошибки "Не удалось загрузить плагины" с кнопкой повтора.
- **ACTUAL:** В `carnaval/web/js/pages/plugins_lab.js` (строки 49-50) блок `catch` подставляет:
  ```javascript
  { uuid: 'p1', name: 'AutoDeliver Plus', version: '1.2.0', author: 'Carnaval Team', ... },
  { uuid: 'p2', name: 'Review Bot', version: '1.0.4', author: 'Community', ... }
  ```
- **REPRODUCTION:** Отключить сеть или вызвать сбой плагинов; интерфейс отобразит активные "AutoDeliver Plus" и "Review Bot".
- **ROOT CAUSE:** Захардкоженный fallback-массив в `plugins_lab.js`.
- **STATUS:** **REPRODUCED**

---

### BUG-06: Command Palette Broken Action Routes
- **BUG:** Командная строка (`Ctrl+K`) вызывает несуществующие эндпоинты для реконнекта и бэкапа.
- **EXPECTED:** Единые авторитетные роуты:
  - Реконнект FunPay: `POST /api/setup/reconnect`
  - Создание бэкапа: `POST /api/more/backup` (скачивание) или `POST /api/more/backup/create`
- **ACTUAL:** В `carnaval/web/js/ui/command_palette.js` (строки 207, 217):
  - `POST /api/account/reconnect` -> 404 Not Found
  - `POST /api/backup` -> 404 Not Found
  То же самое в `error_center.js` (строка 20) и `updates.js` (строка 167).
- **REPRODUCTION:** Вызов команды "Переподключить FunPay" или "Создать бэкап" из палитры команд завершается HTTP 404.
- **ROOT CAUSE:** Использование устаревших путей вместо авторитетных роутов модуля `more`.
- **STATUS:** **REPRODUCED**

---

### BUG-07: Health Map False Positives on API Failure
- **BUG:** При ошибке бэкенда карта здоровья сервисов показывает все узлы как работающие без сбоев (`healthy`).
- **EXPECTED:** При сбое сети или ошибке узлы топологии должны переходить в статус `UNKNOWN` или `UNAVAILABLE`.
- **ACTUAL:** В `carnaval/web/js/ui/health_map.js` (строки 24-32) блок `catch` возвращает 5 узлов с `status: 'healthy'`:
  - `Telegram Bot: healthy (Бот активен)`
  - `FastAPI Backend: healthy (Порт 5000)`
  - `Cardinal Core: healthy (Ядро работает)`
  - `FunPay Runner: healthy (Цикл активен)`
  - `FunPay API: healthy (Соединение установлено)`
- **REPRODUCTION:** Отключить соединение с бэкендом; экран Topology DAG рисует полностью зеленые пульсирующие узлы.
- **ROOT CAUSE:** Фальшивый дефолтный список в обработчике исключений.
- **STATUS:** **REPRODUCED**

---

### BUG-08: Weak Health Account Rule in Live Telemetry
- **BUG:** Проверка готовности аккаунта в `carnaval/services/live.py` не требует завершенной инициализации.
- **EXPECTED:** Статус FunPay `ready` выставляется ТОЛЬКО если:
  `account exists AND is_initiated is True AND valid account.id (int > 0) AND authenticated runtime state`.
- **ACTUAL:** Строка 344 `carnaval/services/live.py`:
  ```python
  if acc and (getattr(acc, "is_initiated", False) or getattr(acc, "id", None)):
  ```
  Если `is_initiated` ложно, но `account.id` присутствует, статус помечается как `ready`.
- **REPRODUCTION:** Создать мок аккаунта с `id = 123` и `is_initiated = False`; телеметрия сообщает `fp_connection_state = "ready"`.
- **ROOT CAUSE:** Дизъюнкция `or` вместо строгой конъюнкции `and`.
- **STATUS:** **REPRODUCED**

---

### BUG-09: Live Timeline Fake Events
- **BUG:** Блок `catch` таймлайна событий генерирует ложные события инициализации системы.
- **EXPECTED:** При ошибке загрузки таймлайна отображается надпись «Таймлайн временно недоступен» с кнопкой повтора.
- **ACTUAL:** В `carnaval/web/js/ui/timeline.js` (строки 26-27):
  ```javascript
  { id: '1', title: 'Система запущена', desc: 'Cardinal и Carnaval успешно инициализированы' },
  { id: '2', title: 'FunPay подключен', desc: 'Авторизация по Golden Key подтверждена' }
  ```
- **REPRODUCTION:** Заблокировать эндпоинт `/api/live/timeline`; отображаются фальшивые события.
- **ROOT CAUSE:** Хардкод моков в блоке `catch`.
- **STATUS:** **REPRODUCED**

---

### BUG-10: Automation Simulator Fake Results
- **BUG:** При сбое эндпоинта симуляции фронтенд выводит сфабрикованный успешный результат выдачи товара.
- **EXPECTED:** Отображение реальной ошибки симуляции без фальсификации выдачи ключа.
- **ACTUAL:** В `carnaval/web/js/pages/automation_lab.js` (строки 109-120):
  ```javascript
  matched_rule: 'AutoDelivery_Default_Rule',
  actions_preview: ['Выдача товара: KEY-TEST-992-817', 'Отправка автоответа: "Спасибо за покупку!"']
  ```
- **REPRODUCTION:** Прервать запрос к `/api/automation/simulate`; на экране появляется выданный ключ `KEY-TEST-992-817`.
- **ROOT CAUSE:** Фабрикация демонстрационных данных при ошибке.
- **STATUS:** **REPRODUCED**

---

### BUG-11: Automation Lab Scaffold Missing Interactive Builder Functionality
- **BUG:** Лаборатория автоматизации содержит только статический просмотр шагов без возможности редактирования, сохранения и настройки цепочек.
- **EXPECTED:** Полнофункциональный визуальный конструктор правил Cardinal:
  - Добавление / Удаление / Редактирование шагов (Триггер, Условие, Действие, Уведомление)
  - Выбор реальных событий (`order_created`, `message_received`, `command_received`)
  - Выбор реальных действий (`deliver_product`, `send_response`, `send_notification`, `raise_lots`)
  - Валидация цепочки, сохранение в Cardinal config, дублирование, включение / отключение, запуск теста
- **ACTUAL:** В `carnaval/web/js/pages/automation_lab.js` только статичные плашки `WHEN`, `IF`, `THEN`, `NOTIFY`.
- **REPRODUCTION:** Открыть `#/automation-lab`; кнопки добавления или изменения условий отсутствуют.
- **ROOT CAUSE:** Незавершенный UI-scaffold.
- **STATUS:** **REPRODUCED**

---

### BUG-12: Missing `POST /more/authorized-users` & `addAuthorizedUser()` in API and Mini App UI
- **BUG:** Невозможно добавить нового доверенного пользователя через Telegram Mini App.
- **EXPECTED:** Полный CRUD: просмотр, добавление по Telegram ID, удаление, просмотр детальной карточки.
- **ACTUAL:** В `carnaval/services/more.py` метод `add_authorized_user()` реализован, но:
  1. В `carnaval/routers/more.py` отсутствует эндпоинт `POST /more/authorized-users`.
  2. В `carnaval/web/js/api.js` отсутствует функция `addAuthorizedUser(userId)`.
  3. В интерфейсе `pages/more.js` отсутствует модальное окно или форма ввода ID нового пользователя.
- **REPRODUCTION:** Попытка добавить пользователя через Mini App невозможна из-за отсутствия элементов UI и API роута.
- **ROOT CAUSE:** Неполная интеграция сервисного слоя с роутером и фронтендом.
- **STATUS:** **REPRODUCED**

---

### BUG-13: UI Emoji Residuals in Interface Elements
- **BUG:** В интерфейсных сообщениях и модальных окнах сохраняются текстовые эмодзи вместо системных SVG-иконок.
- **EXPECTED:** 0% эмодзи в интерфейсе управления; 100% отображение через векторный реестр `getIcon(...)`.
- **ACTUAL:**
  - `carnaval/web/js/app.js` (строки 128, 132, 135, 138, 219): `📦`, `💬`, `🚀`, `📦`, `🔄`
  - `carnaval/web/js/pages/dashboard.js` (строка 100): `🟢 онлайн`, `🔴 офлайн`
  - `carnaval/web/js/ui/onboarding.js` (строки 321-326, 377): `✅`, `❌`, `⚪`, `🔒`
  - `carnaval/web/js/pages/automation_lab.js` (строка 136): `✓`, `✗`
  - `carnaval/web/js/pages/automation.js` (строка 635): `✕`
- **REPRODUCTION:** Скрипт поиска юникод-символов выявляет 17 вхождений в `.js` файлах.
- **ROOT CAUSE:** Пропущенные строки в старых шаблонах интерфейса.
- **STATUS:** **REPRODUCED**

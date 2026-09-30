/**
 * i18n.js — интернационализация Carnaval Mini App (ru / en / uk).
 * Включает описания подстановочных переменных Cardinal (v_*).
 */

const STORAGE_KEY = 'crn_lang';

export const LOCALES = {
  ru: {
    name: 'Русский',
    flag: '🇷🇺',
    app_title: 'Carnaval',
    tab_dashboard: 'Главная',
    tab_orders: 'Заказы',
    tab_chats: 'Чаты',
    tab_automation: 'Авто',
    tab_more: 'Ещё',
    balance_rub: 'Баланс ₽',
    balance_usd_eur: '$ / €',
    active_sales: 'Продажи',
    active_purchases: 'Покупки',
    uptime: 'Аптайм',
    status_running: 'работает',
    status_stopped: 'остановлен',
    automation: 'Автоматизация',
    autoraise: 'Автоподнятие лотов',
    autoresponse: 'Автоответчик',
    autodelivery: 'Авто-выдача',
    multidelivery: 'Мульти-выдача',
    autorestore: 'Восстановление лотов',
    autodisable: 'Деактивация лотов',
    old_mode: 'Старый режим сообщений',
    keep_unread: 'Оставлять непрочитанным',
    next_raise: 'Следующее поднятие',
    next_raise_soon: 'скоро',
    no_active_lots: 'нет активных лотов',
    create_action: 'Создать',
    action_product_file: 'Товарный файл',
    action_auto_response: 'Команду автоответа',
    action_template: 'Шаблон ответа',
    saved: 'Сохранено',
    error_save: 'Ошибка сохранения',
    unauthorized: 'Нет доступа',
    auth_help: 'Отправьте боту секретный пароль в чате Telegram для авторизации.',
    open_bot_chat: 'Открыть чат с ботом',
    theme_light: 'Светлая',
    theme_dark: 'Тёмная',
    theme_auto: 'Системная',
    confirm_title: 'Подтверждение',
    confirm_btn: 'Подтвердить',
    cancel_btn: 'Отмена',
    vars_title: 'Переменные для шаблонов',
  },
  en: {
    name: 'English',
    flag: '🇺🇸',
    app_title: 'Carnaval',
    tab_dashboard: 'Home',
    tab_orders: 'Orders',
    tab_chats: 'Chats',
    tab_automation: 'Auto',
    tab_more: 'More',
    balance_rub: 'Balance ₽',
    balance_usd_eur: '$ / €',
    active_sales: 'Sales',
    active_purchases: 'Purchases',
    uptime: 'Uptime',
    status_running: 'running',
    status_stopped: 'stopped',
    automation: 'Automation',
    autoraise: 'Auto-raise lots',
    autoresponse: 'Auto-response',
    autodelivery: 'Auto-delivery',
    multidelivery: 'Multi-delivery',
    autorestore: 'Auto-restore lots',
    autodisable: 'Auto-disable lots',
    old_mode: 'Old message mode',
    keep_unread: 'Keep unread on reply',
    next_raise: 'Next raise',
    next_raise_soon: 'soon',
    no_active_lots: 'no active lots',
    create_action: 'Create',
    action_product_file: 'Goods file',
    action_auto_response: 'Auto-response rule',
    action_template: 'Reply template',
    saved: 'Saved',
    error_save: 'Failed to save',
    unauthorized: 'Access Denied',
    auth_help: 'Please send the secret password to the Telegram bot to get access.',
    open_bot_chat: 'Open Bot Chat',
    theme_light: 'Light',
    theme_dark: 'Dark',
    theme_auto: 'System',
    confirm_title: 'Confirmation',
    confirm_btn: 'Confirm',
    cancel_btn: 'Cancel',
    vars_title: 'Template Variables',
  },
  uk: {
    name: 'Українська',
    flag: '🇺🇦',
    app_title: 'Carnaval',
    tab_dashboard: 'Головна',
    tab_orders: 'Замовлення',
    tab_chats: 'Чати',
    tab_automation: 'Авто',
    tab_more: 'Більше',
    balance_rub: 'Баланс ₽',
    balance_usd_eur: '$ / €',
    active_sales: 'Продажі',
    active_purchases: 'Купівлі',
    uptime: 'Аптайм',
    status_running: 'працює',
    status_stopped: 'зупинено',
    automation: 'Автоматизація',
    autoraise: 'Автопідняття лотів',
    autoresponse: 'Автовідповідач',
    autodelivery: 'Авто-видача',
    multidelivery: 'Мульти-видача',
    autorestore: 'Відновлення лотів',
    autodisable: 'Деактивація лотів',
    old_mode: 'Старий режим повідомлень',
    keep_unread: 'Залишати непрочитаним',
    next_raise: 'Наступне підняття',
    next_raise_soon: 'незабаром',
    no_active_lots: 'немає активних лотів',
    create_action: 'Створити',
    action_product_file: 'Файл товарів',
    action_auto_response: 'Команду автовідповідача',
    action_template: 'Шаблон відповіді',
    saved: 'Збережено',
    error_save: 'Помилка збереження',
    unauthorized: 'Немає доступу',
    auth_help: 'Надішліть боту секретний пароль у чаті Telegram для авторизації.',
    open_bot_chat: 'Відкрити чат з ботом',
    theme_light: 'Світла',
    theme_dark: 'Темна',
    theme_auto: 'Системна',
    confirm_title: 'Підтвердження',
    confirm_btn: 'Підтвердити',
    cancel_btn: 'Скасувати',
    vars_title: 'Змінні для шаблонів',
  }
};

/**
 * Подстановочные переменные Cardinal (из locales/ru.py).
 */
export const TEMPLATE_VARIABLES = [
  { name: '$username', desc: 'Никнейм покупателя' },
  { name: '$chat_id', desc: 'ID чата' },
  { name: '$chat_name', desc: 'Название чата' },
  { name: '$message_text', desc: 'Текст входящего сообщения' },
  { name: '$order_id', desc: 'ID заказа (без #)' },
  { name: '$order_link', desc: 'Ссылка на заказ' },
  { name: '$order_title', desc: 'Название товара' },
  { name: '$order_params', desc: 'Параметры лота' },
  { name: '$game', desc: 'Название игры' },
  { name: '$category', desc: 'Категория лота' },
  { name: '$product', desc: 'Товар(-ы), выданный(-е) автовыдачей' },
  { name: '$date', desc: 'Текущая дата (дд.мм.гг)' },
  { name: '$time', desc: 'Текущее время (чч:мм)' },
  { name: '$full_time', desc: 'Время с секундами (чч:мм:сс)' },
  { name: '$photo=[PHOTO ID]', desc: 'Отправка изображения по ID' },
  { name: '$sleep=[TIME]', desc: 'Пауза в секундах перед следующим действием' },
];

let _currentLocale = 'ru';

export function initLocale(savedLocale) {
  if (savedLocale && savedLocale in LOCALES) {
    _currentLocale = savedLocale;
    return;
  }
  const fromStorage = localStorage.getItem(STORAGE_KEY);
  if (fromStorage && fromStorage in LOCALES) {
    _currentLocale = fromStorage;
    return;
  }
  const tgLang = window.Telegram?.WebApp?.initDataUnsafe?.user?.language_code;
  if (tgLang && tgLang in LOCALES) {
    _currentLocale = tgLang;
  } else {
    _currentLocale = 'ru';
  }
}

export function setLocale(lang) {
  if (lang in LOCALES) {
    _currentLocale = lang;
    localStorage.setItem(STORAGE_KEY, lang);
  }
}

export function getLocale() {
  return _currentLocale;
}

export function t(key, fallback = '') {
  return LOCALES[_currentLocale]?.[key] ?? LOCALES.ru[key] ?? fallback ?? key;
}

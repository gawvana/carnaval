/**
 * ui/theme.js — синхронизация темы с Telegram.WebApp.colorScheme.
 *
 * Telegram передаёт colorScheme ('light' | 'dark') и themeParams.
 * Мы применяем data-theme на <html> и переопределяем CSS-переменные
 * если Telegram задал свою цветовую схему.
 */

export function applyTelegramTheme() {
  const twa = window.Telegram?.WebApp;
  if (!twa) return;

  const scheme = twa.colorScheme ?? 'light';
  document.documentElement.setAttribute('data-theme', scheme);

  // Подписаться на смену темы
  twa.onEvent?.('themeChanged', () => {
    const s = twa.colorScheme ?? 'light';
    document.documentElement.setAttribute('data-theme', s);
  });
}

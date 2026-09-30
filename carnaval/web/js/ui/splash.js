/**
 * ui/splash.js — скрытие сплеш-скрина.
 */

export function hideSplash() {
  const el = document.getElementById('splash');
  if (!el) return;
  el.classList.add('hidden');
  el.style.opacity = '0';
  el.style.pointerEvents = 'none';
  // Удалить из DOM после завершения анимации перехода (с тайм-аут фоллбэком)
  el.addEventListener('transitionend', () => el.remove(), { once: true });
  setTimeout(() => {
    if (el.parentNode) el.remove();
  }, 500);
}

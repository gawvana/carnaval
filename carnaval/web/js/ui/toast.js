/**
 * ui/toast.js — всплывающие уведомления.
 * Типы: '' (нейтральный), 'ok', 'err', 'warn'
 */

export function showToast(msg, type = '') {
  const container = document.getElementById('toasts');
  if (!container) return;

  const el = document.createElement('div');
  el.className = `toast${type ? ` ${type}` : ''}`;
  el.textContent = msg;

  // Цвет по типу
  if (type === 'ok')   { el.style.background = 'var(--ok)';   el.style.color = 'var(--on-ok)'; }
  if (type === 'err')  { el.style.background = 'var(--err)';  el.style.color = 'var(--on-err)'; }
  if (type === 'warn') { el.style.background = 'var(--warn)'; el.style.color = 'var(--on-warn)'; }

  container.appendChild(el);
  setTimeout(() => {
    el.classList.add('out');
    el.addEventListener('animationend', () => el.remove(), { once: true });
  }, 2800);
}

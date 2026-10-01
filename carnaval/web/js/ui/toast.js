/**
 * ui/toast.js — всплывающие уведомления.
 * Типы: '' (нейтральный), 'ok', 'err', 'warn'
 */

export function showToast(msg, type = '') {
  const container = document.getElementById('toasts');
  if (!container) return;

  // Normalize type aliases
  const typeMap = { 'error': 'err', 'success': 'ok', 'warning': 'warn' };
  const normalizedType = typeMap[type] || type;

  const el = document.createElement('div');
  el.className = `toast${normalizedType ? ` ${normalizedType}` : ''}`;
  el.setAttribute('role', 'status');
  el.setAttribute('aria-live', 'polite');
  el.textContent = msg;

  if (normalizedType === 'ok')   { el.style.background = 'var(--ok)';   el.style.color = 'var(--on-ok)'; }
  if (normalizedType === 'err')  { el.style.background = 'var(--err)';  el.style.color = 'var(--on-err)'; }
  if (normalizedType === 'warn') { el.style.background = 'var(--warn)'; el.style.color = 'var(--on-warn)'; }

  container.appendChild(el);
  setTimeout(() => {
    el.classList.add('out');
    el.addEventListener('animationend', () => el.remove(), { once: true });
  }, 2800);
}

/**
 * pages/placeholder.js — заглушка для будущих страниц.
 */

export function renderPlaceholder(id, title, _icon) {
  return (wrap) => {
    wrap.innerHTML = `
    <header class="nav glass rv">
      <b>${title}</b>
    </header>
    <div class="empty rv" style="padding-top:120px">
      <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8v4M12 16h.01"/></svg>
      <p>Скоро</p>
      <small style="color:var(--muted);font-size:13px">Реализуется в следующих этапах</small>
    </div>`;
  };
}

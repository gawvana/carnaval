/**
 * ui/glass.js — эффект стекла (specular rim + hover glow).
 * Из mattering.html: pointermove → --ang (specular rim угол) + --mx/--my (glow позиция).
 */

export function initGlassEffect() {
  document.addEventListener('pointermove', (e) => {
    const ang = 135
      + (e.clientX / innerWidth - 0.5) * 70
      + (e.clientY / innerHeight - 0.5) * 40;
    document.documentElement.style.setProperty('--ang', `${ang}deg`);

    const g = e.target?.closest?.('.glass');
    if (g) {
      const r = g.getBoundingClientRect();
      g.style.setProperty('--mx', `${e.clientX - r.left}px`);
      g.style.setProperty('--my', `${e.clientY - r.top}px`);
    }
  });
}

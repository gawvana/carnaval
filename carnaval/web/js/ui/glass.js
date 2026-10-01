/**
 * ui/glass.js — Высокопроизводительный эффект стекла.
 * Устраняет Layout Thrashing, синхронные reflow и фризы скролла.
 * Применяет WeakMap кэширование геометрии, single-ticket RAF и Scroll Guard.
 */

import { getQualityTier } from './tier.js';

let rafId = null;
let isScrolling = false;
let scrollTimeout = null;

// Кэш координат элементов (предотвращает повторные getBoundingClientRect)
const rectCache = new WeakMap();

// Текущие координаты указателя
let currentX = -1;
let currentY = -1;
let activeElement = null;
let isHovering = false;

// Определение сенсорного экрана без мыши
const isCoarsePointer = typeof window !== 'undefined' && window.matchMedia?.('(pointer: coarse)')?.matches;

export function initGlassEffect() {
  const tier = getQualityTier();
  if (tier === 'SAVER' || isCoarsePointer) {
    // В режиме энергосбережения или на тачскринах динамический hover выключен
    return;
  }

  const app = document.getElementById('app') || window;

  // 1. Пассивный слушатель скролла для блокировки эффекта во время прокрутки
  window.addEventListener('scroll', handleScroll, { passive: true });
  if (app !== window) {
    app.addEventListener('scroll', handleScroll, { passive: true });
  }

  // 2. Пассивные слушатели движения указателя
  document.addEventListener('pointermove', handlePointerMove, { passive: true });
  document.addEventListener('pointerleave', handlePointerLeave, { passive: true });
}

function handleScroll() {
  isScrolling = true;
  if (scrollTimeout) clearTimeout(scrollTimeout);
  scrollTimeout = setTimeout(() => {
    isScrolling = false;
  }, 150);
}

function handlePointerMove(e) {
  if (isScrolling) return;

  currentX = e.clientX;
  currentY = e.clientY;

  const target = e.target?.closest?.('.glass');
  if (target !== activeElement) {
    if (activeElement) {
      activeElement.classList.remove('glass-active');
    }
    activeElement = target;
    if (activeElement) {
      activeElement.classList.add('glass-active');
      if (!rectCache.has(activeElement)) {
        rectCache.set(activeElement, activeElement.getBoundingClientRect());
      }
    }
  }

  isHovering = Boolean(activeElement);

  // Планируем отрисовку в следующем RAF кадре
  if (!rafId && isHovering) {
    rafId = requestAnimationFrame(updateGlassFrame);
  }
}

function handlePointerLeave() {
  if (activeElement) {
    activeElement.classList.remove('glass-active');
    activeElement = null;
  }
  isHovering = false;
  if (rafId) {
    cancelAnimationFrame(rafId);
    rafId = null;
  }
}

function updateGlassFrame() {
  rafId = null;

  if (!isHovering || !activeElement || isScrolling) {
    return;
  }

  // Получаем кэшированный Rect
  let rect = rectCache.get(activeElement);
  if (!rect) {
    rect = activeElement.getBoundingClientRect();
    rectCache.set(activeElement, rect);
  }

  // Расчет угла для конкретной карточки (локально, не для :root!)
  const localX = currentX - rect.left;
  const localY = currentY - rect.top;
  const normX = (currentX / window.innerWidth) - 0.5;
  const normY = (currentY / window.innerHeight) - 0.5;
  const ang = 135 + (normX * 50) + (normY * 30);

  // Применяем переменные ТОЛЬКО к активному элементу
  activeElement.style.setProperty('--ang', `${ang.toFixed(1)}deg`);
  activeElement.style.setProperty('--mx', `${localX.toFixed(1)}px`);
  activeElement.style.setProperty('--my', `${localY.toFixed(1)}px`);
}

/**
 * Очистка кэша геометрии при ресайзе окна или смене страницы
 */
export function invalidateGlassCache() {
  if (activeElement) {
    rectCache.delete(activeElement);
  }
}

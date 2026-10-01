/**
 * ui/tier.js — Менеджер графических профилей устройства (Quality Tiers).
 * Поддерживает режимы: HIGH, BALANCED, SAVER.
 */

export const QUALITY_TIERS = {
  HIGH: 'HIGH',
  BALANCED: 'BALANCED',
  SAVER: 'SAVER',
};

const STORAGE_KEY = 'crn_quality_tier';

let currentTier = null;
const listeners = new Set();

export function initQualityTier() {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved && QUALITY_TIERS[saved]) {
    setQualityTier(saved, false);
    return;
  }

  // Автоматическое определение по возможностям железа
  const detected = detectDeviceTier();
  setQualityTier(detected, false);
}

function detectDeviceTier() {
  const nav = navigator;

  // 1. Явные требования экономии ресурсов
  if (nav.connection?.saveData) return QUALITY_TIERS.SAVER;
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches) return QUALITY_TIERS.SAVER;

  // 2. Анализ памяти и ядер процессора
  const ram = nav.deviceMemory || 4; // GB (Chrome/Edge API)
  const cores = nav.hardwareConcurrency || 4;

  if (ram < 3 || cores < 4) {
    return QUALITY_TIERS.SAVER;
  }

  if (ram <= 4 || cores <= 6) {
    return QUALITY_TIERS.BALANCED;
  }

  return QUALITY_TIERS.HIGH;
}

export function getQualityTier() {
  return currentTier || QUALITY_TIERS.BALANCED;
}

export function setQualityTier(tier, saveToStorage = true) {
  if (!QUALITY_TIERS[tier]) return;
  currentTier = tier;

  if (saveToStorage) {
    localStorage.setItem(STORAGE_KEY, tier);
  }

  const root = document.documentElement;
  root.setAttribute('data-tier', tier.toLowerCase());

  // Применяем CSS-переменные профиля
  if (tier === QUALITY_TIERS.HIGH) {
    root.style.setProperty('--glass-blur', '22px');
    root.style.setProperty('--glass-sat', '180%');
    root.style.setProperty('--aurora-display', 'block');
    root.style.setProperty('--aurora-anim', 'running');
    root.style.setProperty('--rv-filter-enabled', '1');
  } else if (tier === QUALITY_TIERS.BALANCED) {
    root.style.setProperty('--glass-blur', '10px');
    root.style.setProperty('--glass-sat', '140%');
    root.style.setProperty('--aurora-display', 'block');
    root.style.setProperty('--aurora-anim', 'paused');
    root.style.setProperty('--rv-filter-enabled', '0');
  } else if (tier === QUALITY_TIERS.SAVER) {
    root.style.setProperty('--glass-blur', '0px');
    root.style.setProperty('--glass-sat', '100%');
    root.style.setProperty('--aurora-display', 'none');
    root.style.setProperty('--aurora-anim', 'paused');
    root.style.setProperty('--rv-filter-enabled', '0');
  }

  listeners.forEach((fn) => {
    try {
      fn(tier);
    } catch (e) {
      console.warn('Error in tier listener:', e);
    }
  });
}

export function onTierChange(callback) {
  listeners.add(callback);
  return () => listeners.delete(callback);
}

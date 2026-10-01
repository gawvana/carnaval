/**
 * tg.js — чистая и безопасная обёртка над Telegram WebApp SDK.
 * Обрабатывает как окружение внутри Telegram, так и браузерный fallback (standalone / dev).
 */

const twa = typeof window !== 'undefined' ? window.Telegram?.WebApp : null;

export const tg = {
  isAvailable: Boolean(twa),
  raw: twa,

  ready() {
    try {
      twa?.ready();
      twa?.expand();
      twa?.enableClosingConfirmation?.();
    } catch (_) {}
  },

  close() {
    try {
      twa?.close();
    } catch (_) {}
  },

  get initData() {
    return twa?.initData ?? '';
  },

  get initDataUnsafe() {
    return twa?.initDataUnsafe ?? {};
  },

  get startParam() {
    return twa?.initDataUnsafe?.start_param ?? null;
  },

  get user() {
    return twa?.initDataUnsafe?.user ?? null;
  },

  get colorScheme() {
    return twa?.colorScheme ?? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  },

  get themeParams() {
    return twa?.themeParams ?? {};
  },

  onThemeChange(fn) {
    if (twa?.onEvent) {
      twa.onEvent('themeChanged', fn);
    }
  },

  onViewportChange(fn) {
    if (twa?.onEvent) {
      twa.onEvent('viewportChanged', fn);
    }
  },

  // ── Haptic feedback ──
  haptic: {
    impact(style = 'light') {
      try {
        if (twa?.HapticFeedback) {
          twa.HapticFeedback.impactOccurred(style);
        } else if (navigator.vibrate) {
          navigator.vibrate(6);
        }
      } catch (_) {}
    },
    notification(type = 'success') {
      try {
        if (twa?.HapticFeedback) {
          twa.HapticFeedback.notificationOccurred(type);
        } else if (navigator.vibrate) {
          navigator.vibrate(type === 'error' ? [10, 50, 10] : 10);
        }
      } catch (_) {}
    },
    selection() {
      try {
        if (twa?.HapticFeedback) {
          twa.HapticFeedback.selectionChanged();
        } else if (navigator.vibrate) {
          navigator.vibrate(4);
        }
      } catch (_) {}
    },
  },

  // ── MainButton ──
  mainButton: {
    show(text, onClick) {
      if (!twa?.MainButton) return;
      twa.MainButton.setText(text);
      twa.MainButton.show();
      if (onClick) {
        twa.MainButton.offClick?.();
        twa.MainButton.onClick(onClick);
      }
    },
    hide() {
      twa?.MainButton?.hide();
    },
    showProgress(leaveActive = false) {
      twa?.MainButton?.showProgress(leaveActive);
    },
    hideProgress() {
      twa?.MainButton?.hideProgress();
    },
  },

  // ── BackButton ──
  backButton: {
    show(onClick) {
      if (!twa?.BackButton) return;
      twa.BackButton.show();
      if (onClick) {
        twa.BackButton.offClick?.();
        twa.BackButton.onClick(onClick);
      }
    },
    hide() {
      twa?.BackButton?.hide();
    },
  },

  // ── Links & Modals ──
  openLink(url) {
    if (twa?.openLink) {
      twa.openLink(url);
    } else {
      window.open(url, '_blank', 'noopener,noreferrer');
    }
  },

  openTelegramLink(url) {
    if (twa?.openTelegramLink) {
      twa.openTelegramLink(url);
    } else {
      window.open(url, '_blank');
    }
  },

  showAlert(message) {
    return new Promise((resolve) => {
      if (twa?.showAlert) {
        twa.showAlert(message, () => resolve());
      } else {
        alert(message);
        resolve();
      }
    });
  },

  showConfirm(message) {
    return new Promise((resolve) => {
      if (twa?.showConfirm) {
        twa.showConfirm(message, (ok) => resolve(Boolean(ok)));
      } else {
        resolve(confirm(message));
      }
    });
  },
};

/**
 * Хелпер тактильного отклика: haptic('selection'), haptic('impact', 'medium'), etc.
 */
export function haptic(type = 'selection', style = 'light') {
  if (type === 'selection') {
    tg.haptic.selection();
  } else if (type === 'impact') {
    tg.haptic.impact(style);
  } else if (type === 'notification') {
    tg.haptic.notification(style);
  } else {
    tg.haptic.selection();
  }
}

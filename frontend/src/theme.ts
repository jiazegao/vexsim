// Light, dark, or as the system says; remembered in this browser.

export type Theme = "system" | "light" | "dark";
const KEY = "vexsim.theme";
const listeners = new Set<() => void>();

export function loadTheme(): Theme {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  if (theme === "system") delete root.dataset.theme;
  else root.dataset.theme = theme;
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // not remembered
  }
  listeners.forEach((listener) => listener());
}

export function nextTheme(theme: Theme): Theme {
  return theme === "system" ? "light" : theme === "light" ? "dark" : "system";
}

/** Call `listener` when the colors change: the toggle, or the system's setting. */
export function onThemeChange(listener: () => void): () => void {
  listeners.add(listener);
  const media = window.matchMedia?.("(prefers-color-scheme: dark)");
  media?.addEventListener?.("change", listener);
  return () => {
    listeners.delete(listener);
    media?.removeEventListener?.("change", listener);
  };
}

import { defineStore } from "pinia";

export type ThemeMode = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "auto-oncall-theme";

function readStoredMode(): ThemeMode {
  try {
    const stored = typeof localStorage === "undefined" ? null : localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") return stored;
  } catch {
    // 隐私模式等场景下 localStorage 可能不可用，回退到跟随系统。
  }
  return "system";
}

function persistMode(mode: ThemeMode): void {
  try {
    if (typeof localStorage !== "undefined") localStorage.setItem(THEME_STORAGE_KEY, mode);
  } catch {
    // 持久化失败不影响当前会话主题。
  }
}

function systemPrefersDark(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function resolveTheme(mode: ThemeMode, systemDark: boolean): ResolvedTheme {
  if (mode === "system") return systemDark ? "dark" : "light";
  return mode;
}

export function applyTheme(theme: ResolvedTheme): void {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.theme = theme;
}

/** 在创建 Vue 应用之前同步一次主题，避免刷新时先闪一帧默认配色。 */
export function applyInitialTheme(): void {
  applyTheme(resolveTheme(readStoredMode(), systemPrefersDark()));
}

export const useThemeStore = defineStore("theme", {
  state: () => ({
    mode: readStoredMode() as ThemeMode,
    systemDark: systemPrefersDark(),
    initialized: false
  }),
  getters: {
    resolved(state): ResolvedTheme {
      return resolveTheme(state.mode, state.systemDark);
    }
  },
  actions: {
    initialize(): void {
      if (this.initialized) return;
      this.initialized = true;
      this.systemDark = systemPrefersDark();
      this.apply();
      if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
      const store = this;
      window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (event) => {
        store.handleSystemChange(event.matches);
      });
    },
    apply(): void {
      applyTheme(this.resolved);
    },
    set(mode: ThemeMode): void {
      this.mode = mode;
      persistMode(mode);
      this.apply();
    },
    toggle(): void {
      this.set(this.resolved === "dark" ? "light" : "dark");
    },
    handleSystemChange(dark: boolean): void {
      this.systemDark = dark;
      if (this.mode === "system") this.apply();
    }
  }
});

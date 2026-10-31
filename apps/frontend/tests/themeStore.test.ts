// @vitest-environment jsdom

import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  applyInitialTheme,
  resolveTheme,
  THEME_STORAGE_KEY,
  useThemeStore
} from "../src/stores/theme";

interface MediaStub {
  readonly matches: boolean;
  dispatch(dark: boolean): void;
}

function stubMatchMedia(matches: boolean): MediaStub {
  const listeners: Array<(event: { matches: boolean }) => void> = [];
  vi.stubGlobal("matchMedia", vi.fn(() => ({
    matches,
    media: "(prefers-color-scheme: dark)",
    addEventListener: (_type: string, listener: (event: { matches: boolean }) => void) => {
      listeners.push(listener);
    },
    removeEventListener: vi.fn()
  })));
  return {
    matches,
    dispatch(dark: boolean): void {
      for (const listener of listeners) listener({ matches: dark });
    }
  };
}

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
  setActivePinia(createPinia());
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

describe("theme store", () => {
  it("resolves light or dark from an explicit mode", () => {
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
  });

  it("defaults to the system preference and writes data-theme", () => {
    stubMatchMedia(false);
    const theme = useThemeStore();

    expect(theme.mode).toBe("system");
    expect(theme.resolved).toBe("light");

    theme.initialize();
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("follows a dark system preference", () => {
    stubMatchMedia(true);
    const theme = useThemeStore();

    theme.initialize();
    expect(theme.resolved).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("toggles between light and dark and persists the choice", () => {
    stubMatchMedia(false);
    const theme = useThemeStore();
    theme.initialize();

    theme.toggle();
    expect(theme.mode).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");

    theme.toggle();
    expect(theme.mode).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
  });

  it("reacts to system changes only while following the system", () => {
    const media = stubMatchMedia(false);
    const theme = useThemeStore();
    theme.initialize();

    media.dispatch(true);
    expect(theme.resolved).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");

    theme.set("light");
    media.dispatch(true);
    expect(theme.resolved).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("restores a stored preference before the app mounts", () => {
    stubMatchMedia(false);
    localStorage.setItem(THEME_STORAGE_KEY, "dark");

    applyInitialTheme();
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});

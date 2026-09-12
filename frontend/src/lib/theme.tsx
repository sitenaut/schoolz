import { createContext, useCallback, useContext, useEffect, useState } from "react";

type Theme = "light" | "dark" | "system";
const KEY = "schoolz_theme";

function apply(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
}

function readStored(): Theme {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

type Ctx = { theme: Theme; setTheme: (t: Theme) => void; cycle: () => void };
const ThemeContext = createContext<Ctx | null>(null);

/** Explicit light/dark toggle, layered over the CSS's own
 * prefers-color-scheme default - "system" (the default) removes any
 * override and follows the OS/browser; "light"/"dark" stamp
 * data-theme on <html>, which the stylesheet's tokens key off to win in
 * either direction. Persisted per device (localStorage), same pattern
 * as the school picker - no account needed for a preference this small. */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(readStored);

  useEffect(() => {
    apply(theme);
  }, [theme]);

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
    try {
      if (t === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, t);
    } catch {
      /* private mode etc - just won't persist */
    }
  }, []);

  // system -> light -> dark -> system - one button cycles all three.
  const cycle = useCallback(() => {
    setTheme(theme === "system" ? "light" : theme === "light" ? "dark" : "system");
  }, [theme, setTheme]);

  return <ThemeContext.Provider value={{ theme, setTheme, cycle }}>{children}</ThemeContext.Provider>;
}

export function useTheme(): Ctx {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside ThemeProvider");
  return ctx;
}

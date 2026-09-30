import i18n from "i18next";
import { initReactI18next } from "react-i18next";

/** English is the source language and lives at the site's original,
 * unprefixed URLs. Every other language lives under `/<code>/...`, so adding
 * one never touches an English route. The router's `basename` is the prefix,
 * which is what makes every existing <Link>/navigate() carry it for free.
 *
 * Strings use their English text as the key (`t("Add a child")`), so English
 * needs no resource file at all and an untranslated string simply renders in
 * English. Only the non-English JSON is shipped, and only to those visitors.
 * Plurals: pick the key yourself (`n === 1 ? "1 child" : "{{count}} children"`)
 * - i18next's own count suffixes would need an English resource too. */
export type Lang = "en" | "es" | "zh" | "ko" | "hi";

export const DEFAULT_LANG: Lang = "en";

export const LANGUAGES: { code: Lang; native: string; locale: string }[] = [
  { code: "en", native: "English", locale: "en-US" },
  { code: "es", native: "Español", locale: "es-US" },
  { code: "zh", native: "中文", locale: "zh-CN" },
  { code: "ko", native: "한국어", locale: "ko-KR" },
  { code: "hi", native: "हिन्दी", locale: "hi-IN" },
];

const PREFIXED: Lang[] = ["es", "zh", "ko", "hi"];
export const LANG_STORAGE_KEY = "schoolz_lang";

export function langFromPath(pathname: string): Lang {
  for (const code of PREFIXED) {
    if (pathname === `/${code}` || pathname.startsWith(`/${code}/`)) return code;
  }
  return DEFAULT_LANG;
}

/** Fixed for the life of the page: switching language is a full navigation
 * to the other prefix, never an in-place swap. */
export const CURRENT_LANG: Lang = typeof window === "undefined" ? DEFAULT_LANG : langFromPath(window.location.pathname);

export const ROUTER_BASENAME = CURRENT_LANG === DEFAULT_LANG ? "" : `/${CURRENT_LANG}`;

/** BCP-47 tag for Intl / toLocale*String. */
export const LOCALE: string = LANGUAGES.find((l) => l.code === CURRENT_LANG)?.locale ?? "en-US";

/** Pages whose Spanish version is real. Untranslated pages still open under
 * /es (nav works everywhere) but SeoHead points them at the English URL, so
 * search never indexes an English page as its own "Spanish" duplicate.
 * Mirror any change in backend/routers/seo.py. */
export function isTranslatedPath(routerPath: string): boolean {
  const p = routerPath.split(/[?#]/)[0];
  if (["/", "/schools", "/lunch", "/directory", "/calendar"].includes(p)) return true;
  return /^\/schools\/[^/]+$/.test(p);
}

/** A router-relative path ("/schools/x?y=1") as a real URL path in `lang`. */
export function localizedPath(routerPath: string, lang: Lang): string {
  const path = routerPath.startsWith("/") ? routerPath : `/${routerPath}`;
  if (lang === DEFAULT_LANG) return path;
  return path === "/" ? `/${lang}` : `/${lang}${path}`;
}

/** Strip any language prefix from a full pathname. */
export function stripLangPrefix(pathname: string): string {
  const lang = langFromPath(pathname);
  if (lang === DEFAULT_LANG) return pathname;
  return pathname.slice(lang.length + 1) || "/";
}

export function getStoredLang(): Lang | null {
  try {
    const v = localStorage.getItem(LANG_STORAGE_KEY);
    return LANGUAGES.some((l) => l.code === v) ? (v as Lang) : null;
  } catch {
    return null;
  }
}

export function storeLang(lang: Lang): void {
  try {
    localStorage.setItem(LANG_STORAGE_KEY, lang);
  } catch {
    /* private mode / blocked storage: the URL prefix still carries the choice */
  }
}

/** Where the same page lives in `lang`, keeping query and hash. */
export function urlForLang(lang: Lang, loc: Pick<Location, "pathname" | "search" | "hash"> = window.location): string {
  return localizedPath(stripLangPrefix(loc.pathname), lang) + loc.search + loc.hash;
}

export function switchLanguage(lang: Lang): void {
  storeLang(lang);
  window.location.assign(urlForLang(lang));
}

/** The visitor's browser asks for a language we have but the page isn't in it. */
export function browserPrefersOtherLang(): Lang | null {
  if (typeof navigator === "undefined") return null;
  for (const tag of navigator.languages ?? [navigator.language]) {
    const lower = (tag || "").toLowerCase();
    // Only Simplified is offered: a Traditional-script browser (zh-TW/HK/MO,
    // zh-Hant) would be handed the wrong script.
    if (/^zh-(tw|hk|mo|hant)/.test(lower)) continue;
    const base = lower.split("-")[0];
    const match = LANGUAGES.find((l) => l.code === base);
    if (match) return match.code === CURRENT_LANG ? null : match.code;
  }
  return null;
}

/** A stored non-default choice wins over the URL the visitor happened to
 * arrive on (a shared English link, a bookmark). Never applied under
 * automation - the prerender crawl must see the URL it asked for - and never
 * for an explicit "en", so a Spanish URL someone sends you still opens. */
export function redirectToStoredLang(): boolean {
  if (typeof window === "undefined" || navigator.webdriver) return false;
  const stored = getStoredLang();
  if (!stored || stored === DEFAULT_LANG || stored === CURRENT_LANG || CURRENT_LANG !== DEFAULT_LANG) return false;
  window.location.replace(urlForLang(stored));
  return true;
}

export async function initI18n(): Promise<void> {
  const resources: Record<string, { translation: Record<string, string> }> = {};
  if (CURRENT_LANG !== DEFAULT_LANG) {
    const mod = await import(`../locales/${CURRENT_LANG}.ts`);
    resources[CURRENT_LANG] = { translation: mod.default };
  }
  await i18n.use(initReactI18next).init({
    resources,
    lng: CURRENT_LANG,
    fallbackLng: false,
    keySeparator: false,
    nsSeparator: false,
    interpolation: { escapeValue: false },
    returnNull: false,
    react: { useSuspense: false },
  });
  if (typeof document !== "undefined") document.documentElement.lang = CURRENT_LANG;
}

export { i18n };

/** Lower-case and strip accents, so "reunion" finds "Reunión" and "nino"
 * finds "niño". For client-side search boxes; the server folds its own. */
export function foldAccents(text: string): string {
  return text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

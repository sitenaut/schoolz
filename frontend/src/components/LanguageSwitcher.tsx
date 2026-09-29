import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { CURRENT_LANG, LANGUAGES, Lang, browserPrefersOtherLang, getStoredLang, localizedPath, storeLang, urlForLang } from "../lib/i18n";
import { saveAccountLanguage } from "../lib/account";
import { useAuth } from "../context/AuthContext";

function useLangHref() {
  const { pathname, search, hash } = useLocation();
  return (lang: Lang) => localizedPath(pathname, lang) + search + hash;
}

/** Plain anchors, not buttons: the alternate-language URL is real and
 * crawlable, and the switch is a full page load anyway (the router's
 * basename is fixed per load). The choice is remembered on the device, and on
 * the account when signed in, so it follows them to another phone. */
export function LanguageSwitcher() {
  const hrefFor = useLangHref();
  const { user } = useAuth();
  return (
    <span className="lang-switch" role="group" aria-label="Language">
      {LANGUAGES.map((l) => (
        <a
          key={l.code}
          href={hrefFor(l.code)}
          hrefLang={l.code}
          lang={l.code}
          aria-current={l.code === CURRENT_LANG ? "true" : undefined}
          onClick={() => {
            storeLang(l.code);
            if (user) void saveAccountLanguage(l.code);
          }}
        >
          {l.native}
        </a>
      ))}
    </span>
  );
}

const OFFER_TEXT: Record<Exclude<Lang, "en">, { ask: string; label: string; no: string }> = {
  es: { ask: "¿Prefiere ver schoolz en español?", label: "Español", no: "No, gracias" },
  zh: { ask: "您想用中文查看 schoolz 吗？", label: "中文", no: "不用了" },
};

const DISMISS_KEY = "schoolz_lang_offer_dismissed";

/** A first-time visitor whose browser is set to Spanish is offered the Spanish
 * page once - never redirected, so a shared English link still opens as sent
 * and crawlers (which send no language) are unaffected. Written in the
 * language it offers, since the visitor can't read the current one yet. */
export function LanguageOffer() {
  const hrefFor = useLangHref();
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem(DISMISS_KEY) === "1";
    } catch {
      return false;
    }
  });
  const other = browserPrefersOtherLang();
  if (dismissed || !other || getStoredLang() || navigator.webdriver) return null;
  if (other === "en") return null;
  const text = OFFER_TEXT[other];
  const close = () => {
    try {
      localStorage.setItem(DISMISS_KEY, "1");
    } catch {
      /* ignore */
    }
    setDismissed(true);
  };
  return (
    <div className="lang-offer" role="region" aria-label="Language / 语言 / Idioma" lang={other}>
      <span>{text.ask}</span>
      <a className="btn" href={hrefFor(other)} onClick={() => storeLang(other)}>
        {text.label}
      </a>
      <button className="ghost" onClick={close} aria-label={text.no}>
        {text.no}
      </button>
    </div>
  );
}

/** Account <-> device. A device with no explicit choice adopts the account's
 * (moving to that language once); a device that has one pushes it to an
 * account that has none. An explicit choice on this device always wins. */
export function useAccountLanguageSync() {
  const { user } = useAuth();
  useEffect(() => {
    if (!user || navigator.webdriver) return;
    const stored = getStoredLang();
    const saved = user.preferred_language as Lang | null | undefined;
    if (!stored && saved && LANGUAGES.some((l) => l.code === saved)) {
      storeLang(saved);
      if (saved !== CURRENT_LANG) window.location.replace(urlForLang(saved));
    } else if (stored && !saved) {
      void saveAccountLanguage(stored);
    }
  }, [user]);
}

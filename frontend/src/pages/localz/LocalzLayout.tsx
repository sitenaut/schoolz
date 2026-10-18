import { useEffect } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { IconExit, IconMessage, IconPhone } from "../../components/icons";
import { HELP_NOW, helpLineHref, quickExit } from "../../lib/localz";

/** Wraps every Localz page: the "Need help right now?" lines stay on screen,
 * every number visible (they wrap, never scroll out of sight), and Quick
 * exit (or Esc) swaps the page for a neutral one without leaving it in
 * Back. Inside AppShell, which switches its nav to Localz's.
 *
 * Not on the provider pages: they're for people running a program, and Esc
 * there would throw away a half-filled form. */
export function LocalzLayout() {
  const { t } = useTranslation();
  const forProviders = useLocation().pathname.startsWith("/localz/providers");

  useEffect(() => {
    if (forProviders) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      // Esc already means "close" in a dialog and "clear" in a text box.
      if (document.querySelector("[role='dialog']")) return;
      const el = document.activeElement;
      if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) return;
      quickExit();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [forProviders]);

  return (
    <div className="localz">
      {!forProviders && (
        <section className="localz-helpnow" aria-label={t("Need help right now?")}>
          <div className="localz-helpnow-head">
            <span className="localz-helpnow-title">{t("Need help right now?")}</span>
            <button className="btn localz-exit" onClick={quickExit} title={t("Leave this site quickly (Esc)")}>
              <IconExit />
              {t("Quick exit")}
            </button>
          </div>
          <div className="localz-helpnow-lines">
            {HELP_NOW.map((line) => (
              <a key={helpLineHref(line)} className="localz-helpnow-line" href={helpLineHref(line)}>
                {line.sms ? <IconMessage /> : <IconPhone />}
                <strong>{line.number}</strong>
                <span>{t(line.label)}</span>
              </a>
            ))}
          </div>
        </section>
      )}
      <Outlet />
    </div>
  );
}

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { IconArrowUp } from "./icons";

// Shown once the page has scrolled a screen and a half - long lists
// (Calendar, which also auto-scrolls far down to today, Local events,
// Localz listings) otherwise leave a long swipe back to the filters.
const SHOW_AFTER_SCREENS = 1.5;

/** A floating "back to top" button above the chat button, on every page. */
export function BackToTop() {
  const { t } = useTranslation();
  const [shown, setShown] = useState(false);

  useEffect(() => {
    let frame = 0;
    const check = () => {
      frame = 0;
      setShown(window.scrollY > window.innerHeight * SHOW_AFTER_SCREENS);
    };
    const onScroll = () => {
      if (!frame) frame = window.requestAnimationFrame(check);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, []);

  if (!shown) return null;
  const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  return (
    <button
      className="back-to-top"
      onClick={() => window.scrollTo({ top: 0, behavior: reduceMotion ? "auto" : "smooth" })}
      aria-label={t("Back to top")}
      title={t("Back to top")}
    >
      <IconArrowUp />
    </button>
  );
}

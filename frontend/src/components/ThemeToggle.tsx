import { useTheme } from "../lib/theme";
import { IconAuto, IconMoon, IconSun } from "./icons";
import { useTranslation } from "react-i18next";

/** One button, cycles system -> light -> dark -> system. The icon shown
 * is always the *current* state (what you'll see), not the action the
 * click performs - "Auto" shows a half-toned circle so it reads as
 * distinct from a plain sun/moon. */
export function ThemeToggle() {
  const { t } = useTranslation();
  const { theme, cycle } = useTheme();
  const label = theme === "light" ? t("Light") : theme === "dark" ? t("Dark") : t("Auto");
  const Icon = theme === "light" ? IconSun : theme === "dark" ? IconMoon : IconAuto;
  return (
    <button className="ghost themeToggle" onClick={cycle} title={t("Theme: {{label}} (tap to change)", { label })} aria-label={t("Theme: {{label}}. Tap to change.", { label })}>
      <Icon />
    </button>
  );
}

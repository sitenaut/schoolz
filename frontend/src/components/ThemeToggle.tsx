import { useTheme } from "../lib/theme";
import { IconAuto, IconMoon, IconSun } from "./icons";

const LABELS = { system: "Auto", light: "Light", dark: "Dark" } as const;

/** One button, cycles system -> light -> dark -> system. The icon shown
 * is always the *current* state (what you'll see), not the action the
 * click performs - "Auto" shows a half-toned circle so it reads as
 * distinct from a plain sun/moon. */
export function ThemeToggle() {
  const { theme, cycle } = useTheme();
  const Icon = theme === "light" ? IconSun : theme === "dark" ? IconMoon : IconAuto;
  return (
    <button className="ghost themeToggle" onClick={cycle} title={`Theme: ${LABELS[theme]} (tap to change)`} aria-label={`Theme: ${LABELS[theme]}. Tap to change.`}>
      <Icon />
    </button>
  );
}

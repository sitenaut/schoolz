import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { LOCALE } from "../../lib/i18n";
import type { ResourceSummary } from "../../lib/localz";

const isoToday = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

const day = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString(LOCALE, { weekday: "short", month: "short", day: "numeric" });

/** "Online" / "In person or online", when a provider said so. */
export function deliveryLabel(delivery: ResourceSummary["delivery"]): string | null {
  return delivery === "online" ? "Online" : delivery === "both" ? "In person or online" : null;
}

/** How a program takes people right now. A closed one with a date in the
 * past may well be open: say to call rather than "closed". */
export function signupText(signup: ResourceSummary["signup"], t: TFunction): string | null {
  if (!signup) return null;
  switch (signup.status) {
    case "drop_in":
      return t("No sign-up needed - just come");
    case "open":
      return t("Sign-ups are open");
    case "waitlist":
      return t("Waiting list - call to join");
    case "closed":
      if (!signup.opens_on) return t("Sign-ups are closed for now");
      return signup.opens_on > isoToday() ? t("Sign-ups open {{date}}", { date: day(signup.opens_on) }) : t("Sign-ups may be open - call to check");
    default:
      return null;
  }
}

/** The next days a monthly, every-other-week or seasonal program meets,
 * plus how to join: what a plain list of weekdays can't say. */
export function ProgramNotes({ r, detail = false }: { r: ResourceSummary; detail?: boolean }) {
  const { t } = useTranslation();
  const next = r.next_open ?? [];
  const joining = signupText(r.signup, t);
  if (!next.length && !joining) return null;
  return (
    <div className="localz-program-notes">
      {next.length > 0 && (
        <p>
          <strong>{t("Next:")}</strong> {next.map((n) => `${day(n.on)}, ${n.times}`).join(" · ")}
        </p>
      )}
      {joining && (
        <p>
          <strong>{joining}</strong>
          {detail && r.signup?.how ? ` · ${r.signup.how}` : ""}
        </p>
      )}
    </div>
  );
}

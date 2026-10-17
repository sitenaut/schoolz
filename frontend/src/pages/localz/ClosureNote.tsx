import { useTranslation } from "react-i18next";
import { IconAlert } from "../../components/icons";
import { LOCALE } from "../../lib/i18n";

type Closure = { starts_on: string; ends_on: string; note: string | null };

const isoToday = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

const day = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString(LOCALE, { weekday: "short", month: "short", day: "numeric" });

/** A provider's posted closure on a card or a listing page. The server only
 * sends one that hasn't ended. */
export function ClosureNote({ closure }: { closure: Closure }) {
  const { t } = useTranslation();
  const today = isoToday();
  const text =
    closure.starts_on <= today
      ? closure.ends_on === today
        ? t("Closed today")
        : t("Closed until {{date}}", { date: day(closure.ends_on) })
      : closure.starts_on === closure.ends_on
        ? t("Closed {{date}}", { date: day(closure.starts_on) })
        : t("Closed {{from}} to {{to}}", { from: day(closure.starts_on), to: day(closure.ends_on) });
  return (
    <p className="localz-alert" role="note">
      <IconAlert />
      <span>
        <strong>{text}</strong>
        {closure.note ? ` · ${closure.note}` : ""}
      </span>
    </p>
  );
}

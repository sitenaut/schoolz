import { useTranslation } from "react-i18next";
import type { School } from "../types";
import { telHref } from "../lib/calendar";
import { IconMail, IconPhone } from "./icons";
import { trackEvent } from "../lib/track";

/** Adapts to whatever method the school's own materials specify - some
 * schools want a phone call, others want email to named staff, East wants
 * the Genesis portal (confirmed real - see CLAUDE.md). Renders only a real
 * action; when no direct link can be built it renders nothing, and the raw
 * instructions go in <AbsenceNote> where there's room for a paragraph (this
 * button sits in pill rows, one of them sticky). */
export function AbsenceButton({ school, className = "action primary" }: { school: School; className?: string }) {
  const { t } = useTranslation();
  const track = (method: string) => trackEvent("action", { action: "absence", method, school_slug: school.slug });
  if (school.absence_method === "email" && school.absence_emails.length > 0) {
    const subject = encodeURIComponent(`${school.name}: Student absence`);
    const body = encodeURIComponent("My child will be absent today.\n\nStudent name:\nTeacher:\nReason:\n");
    return (
      <a
        className={className}
        href={`mailto:${school.absence_emails.join(",")}?subject=${subject}&body=${body}`}
        onClick={() => track("mailto")}
      >
        <IconMail />
        {t("Report absence")}
      </a>
    );
  }
  if (school.absence_method === "phone" && school.absence_phone) {
    return (
      <a className={className} href={telHref(school.absence_phone)} onClick={() => track("tel")}>
        <IconPhone />
        {t("Report absence")}
      </a>
    );
  }
  if (school.absence_method === "portal" && school.absence_portal_url) {
    return (
      <a
        className={className}
        href={school.absence_portal_url}
        target="_blank"
        rel="noreferrer"
        onClick={() => track("portal")}
      >
        {t("Report absence in {{portal}}", { portal: school.absence_portal_name || t("the portal") })}
      </a>
    );
  }
  return null;
}

/** True when AbsenceButton has an action to show. */
export function hasAbsenceAction(school: School): boolean {
  return (
    (school.absence_method === "email" && school.absence_emails.length > 0) ||
    (school.absence_method === "phone" && !!school.absence_phone) ||
    (school.absence_method === "portal" && !!school.absence_portal_url)
  );
}

/** The school's own absence instructions, for schools with no direct action
 * (e.g. "send a note when your child returns"). */
export function AbsenceNote({ school, style }: { school: School; style?: React.CSSProperties }) {
  if (hasAbsenceAction(school) || !school.absence_instructions) return null;
  return (
    <p className="note" style={style}>
      {school.absence_instructions}
    </p>
  );
}

import type { School } from "../types";
import { telHref } from "../lib/calendar";
import { IconMail, IconPhone } from "./icons";
import { trackEvent } from "../lib/track";

/** Adapts to whatever method the school's own materials specify - some
 * schools want a phone call, others want email to named staff, East wants
 * the Genesis portal (confirmed real - see CLAUDE.md). Falls back to the
 * raw extracted instructions only when no direct link can be built. */
export function AbsenceButton({ school, className = "action primary" }: { school: School; className?: string }) {
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
        Report absence
      </a>
    );
  }
  if (school.absence_method === "phone" && school.absence_phone) {
    return (
      <a className={className} href={telHref(school.absence_phone)} onClick={() => track("tel")}>
        <IconPhone />
        Report absence
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
        Report absence in {school.absence_portal_name || "the portal"}
      </a>
    );
  }
  if (school.absence_instructions) {
    return <span className="note">{school.absence_instructions}</span>;
  }
  return null;
}

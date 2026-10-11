import { describe, expect, it } from "vitest";
import { hasAbsenceAction } from "../components/AbsenceButton";
import type { School } from "../types";

const school = (over: Partial<School>) =>
  ({ absence_method: null, absence_emails: [], absence_phone: null, absence_portal_url: null, ...over }) as School;

describe("hasAbsenceAction", () => {
  it("is false for a note-only school, so no paragraph lands in the pill row", () => {
    expect(hasAbsenceAction(school({ absence_method: "other", absence_instructions: "Send a note" }))).toBe(false);
  });
  it("needs the contact detail its method names", () => {
    expect(hasAbsenceAction(school({ absence_method: "phone" }))).toBe(false);
    expect(hasAbsenceAction(school({ absence_method: "phone", absence_phone: "(856) 555-0100" }))).toBe(true);
    expect(hasAbsenceAction(school({ absence_method: "email", absence_emails: ["a@b.org"] }))).toBe(true);
    expect(hasAbsenceAction(school({ absence_method: "portal", absence_portal_url: "https://x" }))).toBe(true);
  });
});

import { describe, expect, it } from "vitest";
import { type Criteria, type FitAnswers, describe as describeCriteria, fitFor, sortByFit } from "./localzFit";

const base: Criteria = {
  open_to_all: false,
  vague: false,
  age_min: null,
  age_max: null,
  child_age_min: null,
  child_age_max: null,
  requires: [],
  focus: [],
  either: false,
  asks_immigration_status: false,
  other: null,
};
const c = (over: Partial<Criteria>): Criteria => ({ ...base, ...over });
const a = (over: Partial<FitAnswers>): FitAnswers => ({ ages: [], has: [], focus: [], noStatusFirst: false, ...over });

describe("matching a listing against the visitor's answers", () => {
  it("says nothing until there's something to match", () => {
    expect(fitFor(c({ age_min: 60 }), null)).toBeNull();
    expect(fitFor(c({ age_min: 60 }), a({}))).toBeNull();
    expect(fitFor(null, a({ ages: ["60+"] }))).toBeNull();
  });

  it("a veteran sees veterans' programs as for them; others see them lower, not hidden", () => {
    const vets = c({ requires: ["veteran_military"] });
    expect(fitFor(vets, a({ has: ["veteran_military"] }))?.level).toBe("yes");
    expect(fitFor(vets, a({ ages: ["18-59"] }))?.level).toBe("no");
  });

  it("matches anyone in the household by age, and children for family programs", () => {
    const seniors = c({ age_min: 60 });
    expect(fitFor(seniors, a({ ages: ["18-59", "60+"] }))?.level).toBe("yes");
    expect(fitFor(seniors, a({ ages: ["18-59"] }))?.level).toBe("no");
    const littleKids = c({ child_age_max: 4 });
    expect(fitFor(littleKids, a({ ages: ["18-59", "1-4"] }))?.level).toBe("yes");
    expect(fitFor(littleKids, a({ ages: ["18-59", "13-17"] }))?.level).toBe("no");
    expect(fitFor(littleKids, a({ has: ["disability"] }))?.level).toBe("check"); // no ages given
  });

  it("'either' is enough with one of the groups", () => {
    const seniorsOrDisabled = c({ age_min: 60, requires: ["disability"], either: true });
    expect(fitFor(seniorsOrDisabled, a({ ages: ["18-59"], has: ["disability"] }))?.level).toBe("yes");
    expect(fitFor(seniorsOrDisabled, a({ ages: ["18-59"] }))?.level).toBe("no");
    // The right age alone is only worth a "check" when there are other groups.
    expect(fitFor(seniorsOrDisabled, a({ ages: ["60+"] }))?.level).toBe("check");
    const vetsSeniorsDisabled = c({ age_min: 60, requires: ["disability", "veteran_military"], either: true });
    expect(fitFor(vetsSeniorsDisabled, a({ ages: ["18-59"], has: ["veteran_military"] }))?.level).toBe("yes");
  });

  it("income and unusual requirements can't be checked, so they're 'check', never 'yes'", () => {
    expect(fitFor(c({ age_min: 60, requires: ["low_income"] }), a({ ages: ["60+"] }))?.level).toBe("check");
    expect(fitFor(c({ other: "court referral" }), a({ ages: ["18-59"] }))?.level).toBe("check");
    expect(fitFor(c({ vague: true }), a({ ages: ["18-59"] }))?.level).toBe("check");
  });

  it("who a service focuses on only ever adds a match - not choosing one rules nothing out", () => {
    const women = c({ focus: ["women"], age_min: 18 });
    expect(fitFor(women, a({ ages: ["18-59"], focus: ["women"] }))?.level).toBe("yes");
    expect(fitFor(women, a({ ages: ["18-59"] }))?.level).toBe("check");
    expect(fitFor(women, a({ ages: ["18-59"], focus: ["lgbtq"] }))?.level).toBe("check");
  });

  it("open to everyone is its own good news", () => {
    expect(fitFor(c({ open_to_all: true }), a({ has: ["job_loss"] }))?.level).toBe("open");
  });

  it("sorts best fits first and keeps the server's order otherwise", () => {
    const items = [
      { id: "seniors", eligibility: c({ age_min: 60 }) },
      { id: "unread", eligibility: null },
      { id: "open", eligibility: c({ open_to_all: true }) },
      { id: "vets", eligibility: c({ requires: ["veteran_military"] }) },
      { id: "status", eligibility: c({ open_to_all: true, asks_immigration_status: true }) },
      { id: "open2", eligibility: c({ open_to_all: true }) },
    ];
    const answers = a({ has: ["veteran_military"], ages: ["18-59"], noStatusFirst: true });
    expect(sortByFit(items, answers).map((i) => i.id)).toEqual(["vets", "open", "open2", "status", "unread", "seniors"]);
    expect(sortByFit(items, null)).toBe(items);
  });

  it("describes who a listing is for in plain words", () => {
    expect(describeCriteria(c({ age_min: 60, requires: ["low_income"], other: "DDD referral" })).map((l) => l.text)).toEqual([
      "Ages {{min}} and up",
      "Income limits",
      "DDD referral",
    ]);
  });
});

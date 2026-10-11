// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { StatusPill } from "./today";

afterEach(cleanup);

const pill = (status: "weekend" | "open" | "closed" | "early_dismissal" | "delayed", label: string | null, hours: string | null) =>
  render(<StatusPill status={status as never} label={label} hours={hours} />).container.firstElementChild!;

describe("StatusPill", () => {
  it("never wraps a bare label, so a long school name cannot squeeze it into two lines", () => {
    expect(pill("weekend", null, null).classList.contains("short")).toBe(true);
    expect(pill("open", null, null).classList.contains("short")).toBe(true);
    expect(pill("closed", null, null).classList.contains("short")).toBe(true);
    expect(pill("early_dismissal", null, null).classList.contains("short")).toBe(true);
  });

  it("lets a label with hours or a reason wrap, since that one can be long", () => {
    expect(pill("open", null, "8:35 AM-3:00 PM").classList.contains("short")).toBe(false);
    expect(pill("closed", "Columbus Day", null).classList.contains("short")).toBe(false);
    expect(pill("early_dismissal", null, "12:45 PM").classList.contains("short")).toBe(false);
  });
});

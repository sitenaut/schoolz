import { describe, expect, it } from "vitest";
import { formatPhone, mainDigits, nextPhoneValue } from "./phone";

describe("formatPhone", () => {
  it.each([
    ["8", "(8"],
    ["856", "(856"],
    ["8565", "(856) 5"],
    ["8565550", "(856) 555-0"],
    ["8565550101", "(856) 555-0101"],
    ["85655501011", "(856) 555-0101, 1"],
    ["856555010123", "(856) 555-0101, 23"],
    ["(856) 555-0101,", "(856) 555-0101, "],
    ["(856) 555-0101 x12", "(856) 555-0101, 12"],
    ["856-555-0101 ext. 7", "(856) 555-0101, 7"],
    ["+1 856 555 0101", "(856) 555-0101"],
    ["1", ""],
    ["", ""],
  ])("%s -> %s", (raw, out) => expect(formatPhone(raw)).toBe(out));
});

describe("nextPhoneValue", () => {
  it("formats while typing", () => {
    let v = "";
    for (const ch of "8565550101,12") v = nextPhoneValue(v, v + ch);
    expect(v).toBe("(856) 555-0101, 12");
  });
  it("a backspace over punctuation removes the digit before it", () => {
    expect(nextPhoneValue("(856) 5", "(856) ")).toBe("(856");
    expect(nextPhoneValue("(856) 555-0", "(856) 555-")).toBe("(856) 555");
    expect(nextPhoneValue("(856", "(85")).toBe("(85");
  });
  it("a backspace after the comma removes the comma", () => {
    expect(nextPhoneValue("(856) 555-0101, ", "(856) 555-0101,")).toBe("(856) 555-0101");
  });
});

describe("mainDigits", () => {
  it("leaves the extension out", () => {
    expect(mainDigits("(856) 555-0101, 12")).toBe("8565550101");
    expect(mainDigits("1-856-555-0101 x9")).toBe("8565550101");
  });
});

import { describe, expect, it } from "vitest";
import { initials } from "./format";

describe("initials", () => {
  it("takes two letters from a class's name", () => {
    expect(initials("World History")).toBe("WH");
    expect(initials("Geometry")).toBe("Ge");
    expect(initials("PE / Health")).toBe("PH");
  });

  it("skips a number, which says less than the name it follows", () => {
    expect(initials("English 10")).toBe("En");
    expect(initials("Spanish 2")).toBe("Sp");
    expect(initials("210")).toBe("21");
    expect(initials("")).toBe("?");
  });
});

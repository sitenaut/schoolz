import { describe, expect, it } from "vitest";
import { districtLabel } from "./districtLabel";

describe("districtLabel", () => {
  it("leaves a New Jersey district's name alone", () => {
    expect(districtLabel({ name: "Woodbury City Public School District", state: "NJ" })).toBe("Woodbury City Public School District");
    expect(districtLabel({ name: "Older API response" })).toBe("Older API response");
  });
  it("names the state of any other, since the same name exists in several", () => {
    expect(districtLabel({ name: "Washington Township School District", state: "PA" })).toBe("Washington Township School District (PA)");
  });
});

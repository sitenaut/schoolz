import { describe, expect, it } from "vitest";
import { friendlyAuthError } from "./authErrors";

describe("friendlyAuthError", () => {
  it("replaces an unreadable body with the fallback", () => {
    for (const message of ["{}", "", "  ", "[]", "null", undefined]) {
      expect(friendlyAuthError({ message }, "try later")).toBe("try later");
    }
  });
  it("passes real messages through untouched", () => {
    expect(friendlyAuthError({ message: "Invalid login credentials" }, "try later")).toBe("Invalid login credentials");
  });
});

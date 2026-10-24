import { describe, expect, it } from "vitest";
import { errorDetail } from "./errorDetail";

describe("errorDetail", () => {
  it("passes a message through", () => {
    expect(errorDetail({ detail: "Invite expired" }, "fallback")).toBe("Invite expired");
  });

  it("turns FastAPI's 422 list into its messages, never an object", () => {
    const body = {
      detail: [{ loc: ["body", "invitee_email"], msg: "value is not a valid email address", type: "value_error" }],
    };
    expect(errorDetail(body, "Could not create invite")).toBe("value is not a valid email address");
  });

  it("falls back when there's nothing usable", () => {
    for (const body of [null, {}, { detail: null }, { detail: [{}] }, { detail: { x: 1 } }, "oops"]) {
      expect(errorDetail(body, "fallback")).toBe("fallback");
    }
  });
});

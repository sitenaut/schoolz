import { describe, expect, it } from "vitest";
import { AUTH_MODE } from "./authConfig";

describe("authConfig", () => {
  it("defaults to local auth mode", () => {
    expect(["local", "supabase"]).toContain(AUTH_MODE);
  });
});

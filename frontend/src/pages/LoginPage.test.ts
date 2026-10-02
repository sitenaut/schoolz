import { describe, expect, it } from "vitest";
import { safeNext } from "./LoginPage";

describe("safeNext", () => {
  it("keeps valid same-site paths", () => {
    expect(safeNext("/invites/123")).toBe("/invites/123");
    expect(safeNext("/start?welcome=1")).toBe("/start?welcome=1");
    expect(safeNext("/schools/cherry-hill-east")).toBe("/schools/cherry-hill-east");
  });

  it("falls back to root for null or empty string", () => {
    expect(safeNext(null)).toBe("/");
    expect(safeNext("")).toBe("/");
  });

  it("blocks external protocol-relative URLs", () => {
    expect(safeNext("//evil.com")).toBe("/");
    expect(safeNext("//evil.com/path")).toBe("/");
    expect(safeNext("/\\evil.com")).toBe("/");
  });

  it("blocks non-slash relative or absolute schemes", () => {
    expect(safeNext("https://evil.com")).toBe("/");
    expect(safeNext("javascript:alert(1)")).toBe("/");
    expect(safeNext("evil.com")).toBe("/");
  });
});

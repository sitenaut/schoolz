import { describe, expect, it } from "vitest";
import { isOutsideApp, returnToFor, safeNext } from "./safeNext";

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

describe("a next outside the app (Focus)", () => {
  it("is told apart from app paths", () => {
    expect(isOutsideApp("/focus/")).toBe(true);
    expect(isOutsideApp("/focus/?student=abc")).toBe(true);
    expect(isOutsideApp("/focus")).toBe(true);
    expect(isOutsideApp("/focused-reading")).toBe(false);
    expect(isOutsideApp("/family")).toBe(false);
  });

  it("comes back from Google through /login, which does the page load", () => {
    expect(returnToFor("/focus/")).toBe("/login?next=%2Ffocus%2F");
    expect(returnToFor("/family")).toBe("/family");
    expect(returnToFor("/")).toBeUndefined();
  });

  it("can't leave the site", () => {
    expect(safeNext("//evil.com/focus/")).toBe("/");
    expect(isOutsideApp(safeNext("https://evil.com/focus/"))).toBe(false);
  });
});

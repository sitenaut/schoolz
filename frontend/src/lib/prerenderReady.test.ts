import { describe, expect, it } from "vitest";
import { isPrerenderLoad } from "./prerenderReady";

const person = {
  search: "",
  userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/27.0 Mobile/15E148 Safari/604.1",
  brands: [],
  webdriver: false,
};

describe("isPrerenderLoad", () => {
  it("is false for an ordinary visitor, including one flagged internal", () => {
    expect(isPrerenderLoad(person)).toBe(false);
    expect(isPrerenderLoad({ ...person, search: "?internal=1" })).toBe(false);
  });

  it("is true for prerender.py's own ?prerender=1", () => {
    expect(isPrerenderLoad({ ...person, search: "?internal=1&prerender=1" })).toBe(true);
  });

  it("catches the droplet's stealth Chromium, which hides webdriver and fakes a desktop UA", () => {
    const stealth = {
      search: "",
      userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
      brands: ["HeadlessChrome", "Not=A?Brand", "Chromium"],
      webdriver: false,
    };
    expect(isPrerenderLoad(stealth)).toBe(true);
    expect(isPrerenderLoad({ ...person, webdriver: true })).toBe(true);
  });
});

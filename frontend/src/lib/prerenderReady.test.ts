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

  it("catches crawlers that run JavaScript in an ordinary-looking Chrome", () => {
    for (const userAgent of [
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36 (compatible; meta-externalagent/1.1 (+https://developers.facebook.com/docs/sharing/webmasters/crawler))",
      "Mozilla/5.0 (compatible; ExaSearchBot/1.0; +https://crawler.exa.ai/)",
      "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Mobile Safari/537.36 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    ]) {
      expect(isPrerenderLoad({ ...person, userAgent })).toBe(true);
    }
  });

  it("leaves real browsers alone, in-app ones included", () => {
    for (const userAgent of [
      "Mozilla/5.0 (iPhone; CPU iPhone OS 26_6_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/155.0.8059.37 Mobile/15E148 Safari/604.1",
      "Mozilla/5.0 (iPhone; CPU iPhone OS 27_0_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/24A446 Safari/604.1 [FBAN/FBIOS;FBAV/583.0.0.61.69;FBBV/1]",
      "Mozilla/5.0 (Linux; Android 10; CUBOT X30) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Mobile Safari/537.36 EdgA/155.0.0.0",
      "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/27.0 Mobile/15E148 Safari/604.1 Ddg/27.0",
    ]) {
      expect(isPrerenderLoad({ ...person, userAgent })).toBe(false);
    }
  });
});

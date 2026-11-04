import { describe, expect, it } from "vitest";
import { isCrawlerLoad, isOwnRender, isPrerenderLoad, isStaleLinuxChrome } from "./prerenderReady";

const NOV_4_2026 = Date.UTC(2026, 10, 4, 12);

const person = {
  search: "",
  userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/27.0 Mobile/15E148 Safari/604.1",
  brands: [],
  webdriver: false,
  platform: "",
  now: NOV_4_2026,
};

const linuxChrome = (major: number) =>
  `Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${major}.0.0.0 Safari/537.36`;

describe("isStaleLinuxChrome", () => {
  it("catches the Nov 3-4 crawler: desktop Linux Chrome 145 and 147 while stable was 156", () => {
    expect(isStaleLinuxChrome(linuxChrome(145), "Linux", NOV_4_2026)).toBe(true);
    expect(isStaleLinuxChrome(linuxChrome(147), "Linux", NOV_4_2026)).toBe(true);
    expect(isCrawlerLoad({ ...person, userAgent: linuxChrome(145), brands: ["Not:A-Brand", "Chromium"], platform: "Linux" })).toBe(true);
  });

  it("leaves an up-to-date or slightly behind Linux Chrome alone", () => {
    expect(isStaleLinuxChrome(linuxChrome(156), "Linux", NOV_4_2026)).toBe(false);
    expect(isStaleLinuxChrome(linuxChrome(151), "Linux", NOV_4_2026)).toBe(false);
  });

  it("leaves an old Android tablet in desktop mode alone: same UA, but its platform says Android", () => {
    expect(isStaleLinuxChrome(linuxChrome(138), "Android", NOV_4_2026)).toBe(false);
  });

  it("needs the platform to confirm Linux, so a browser without userAgentData is never caught by it", () => {
    expect(isStaleLinuxChrome(linuxChrome(145), "", NOV_4_2026)).toBe(false);
  });

  it("leaves Chromebooks, Windows and Android phones alone, however old", () => {
    for (const userAgent of [
      "Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
      "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
      "Mozilla/5.0 (Linux; Android 9; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36",
    ]) {
      expect(isStaleLinuxChrome(userAgent, "Linux", NOV_4_2026)).toBe(false);
    }
  });

  it("estimates the stable version conservatively as time passes", () => {
    // A year on, real stable is ~169; the estimate (one major per five weeks)
    // is 166, so only a Linux Chrome at 160 or older is caught.
    const nov2027 = Date.UTC(2027, 10, 4, 12);
    expect(isStaleLinuxChrome(linuxChrome(160), "Linux", nov2027)).toBe(true);
    expect(isStaleLinuxChrome(linuxChrome(161), "Linux", nov2027)).toBe(false);
  });
});

describe("isPrerenderLoad", () => {
  it("is false for an ordinary visitor, including one flagged internal", () => {
    expect(isPrerenderLoad(person)).toBe(false);
    expect(isPrerenderLoad({ ...person, search: "?internal=1" })).toBe(false);
  });

  it("is true for prerender.py's own ?prerender=1", () => {
    expect(isPrerenderLoad({ ...person, search: "?internal=1&prerender=1" })).toBe(true);
  });

  it("tells our own render apart from a crawler loading the page itself", () => {
    expect(isOwnRender("?internal=1&prerender=1")).toBe(true);
    expect(isCrawlerLoad({ ...person, search: "?internal=1&prerender=1" })).toBe(false);
    expect(isOwnRender("")).toBe(false);
    expect(isCrawlerLoad({ ...person, webdriver: true })).toBe(true);
  });

  it("catches the droplet's stealth Chromium, which hides webdriver and fakes a desktop UA", () => {
    const stealth = {
      ...person,
      userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
      brands: ["HeadlessChrome", "Not=A?Brand", "Chromium"],
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

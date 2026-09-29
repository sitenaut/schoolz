import { describe, expect, it } from "vitest";
import { localizedPath, stripLangPrefix, langFromPath, foldAccents } from "./i18n";
import es from "../locales/es";

describe("language paths", () => {
  it("leaves English URLs untouched", () => {
    expect(localizedPath("/schools/x", "en")).toBe("/schools/x");
    expect(localizedPath("/", "en")).toBe("/");
    expect(langFromPath("/schools/x")).toBe("en");
  });
  it("prefixes other languages", () => {
    expect(localizedPath("/schools/x", "es")).toBe("/es/schools/x");
    expect(localizedPath("/", "es")).toBe("/es");
  });
  it("round-trips and does not mistake look-alike segments for a prefix", () => {
    expect(stripLangPrefix("/es/schools/x")).toBe("/schools/x");
    expect(stripLangPrefix("/es")).toBe("/");
    expect(langFromPath("/essex")).toBe("en");
    expect(langFromPath("/es/lunch")).toBe("es");
  });
});

describe("es translations", () => {
  const placeholders = (s: string) => [...s.matchAll(/{{\s*\w+\s*}}/g)].map((m) => m[0].replace(/\s/g, "")).sort();
  it("has no empty values and keeps every {{placeholder}}", () => {
    for (const [k, v] of Object.entries(es)) {
      expect(v.trim(), `empty translation for "${k}"`).not.toBe("");
      expect(placeholders(v), `placeholders differ for "${k}"`).toEqual(placeholders(k));
    }
  });
});

describe("foldAccents", () => {
  it("makes search ignore accents and case", () => {
    expect(foldAccents("Reunión")).toBe("reunion");
    expect(foldAccents("ESPAÑOL")).toBe("espanol");
    expect(foldAccents("Niño")).toBe(foldAccents("nino"));
  });
});

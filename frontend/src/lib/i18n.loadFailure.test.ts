// @vitest-environment jsdom
// @vitest-environment-options { "url": "http://localhost/es/schools/maple" }
// A failed language download used to reject initI18n, and main.tsx never
// rendered: /es, /zh, /ko and /hi went blank with no way to recover.
import { expect, it, vi } from "vitest";

vi.mock("../locales/es.ts", () => {
  throw new Error("Failed to fetch dynamically imported module");
});

import { CURRENT_LANG, i18n, initI18n } from "./i18n";

it("falls back to English strings when the language file fails to load", async () => {
  expect(CURRENT_LANG).toBe("es");
  await expect(initI18n()).resolves.toBeUndefined();
  expect(i18n.t("Try again")).toBe("Try again");
});

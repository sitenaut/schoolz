import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { AVATAR_KEYS, EMOJIS, HELP_CODES, TERMS_VERSION } from "./shared";

// The server refuses any avatar or emoji outside its own fixed sets
// (backend/bills/catalog.py), so the two lists must never drift.
const py = readFileSync(fileURLToPath(new URL("../../../../../backend/bills/catalog.py", import.meta.url)), "utf8");

function quoted(block: string): string[] {
  return [...block.matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
}

describe("Neighborz catalog", () => {
  it("ships one avatar for every key the server accepts", () => {
    const block = py.match(/AVATARS: tuple\[str, \.\.\.\] = \(([\s\S]*?)\n\)/)![1];
    expect(AVATAR_KEYS).toEqual(quoted(block).sort());
    expect(AVATAR_KEYS.length).toBe(24);
  });

  it("offers exactly the server's emojis", () => {
    const block = py.match(/EMOJIS: dict\[str, str\] = \{([\s\S]*?)\n\}/)![1];
    const keys = [...block.matchAll(/^\s+"([a-z_]+)":/gm)].map((m) => m[1]);
    expect(Object.keys(EMOJIS)).toEqual(keys);
  });

  it("agrees to the terms version the server asks for", () => {
    expect(py).toContain(`TERMS_VERSION = "${TERMS_VERSION}"`);
  });

  it("asks Localz for the server's other-help codes", () => {
    const block = py.match(/HELP_CODES: tuple\[str, \.\.\.\] = \(([\s\S]*?)\n\)/)![1];
    expect(HELP_CODES).toEqual([...block.matchAll(/"([A-Z0-9.-]+)"/g)].map((m) => m[1]));
  });
});

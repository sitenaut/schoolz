import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { ACTION_LABELS, actionLabel } from "./AuditLogPage";

describe("audit log labels", () => {
  it("has words for every action the backend records", () => {
    const py = readFileSync(fileURLToPath(new URL("../../../backend/services/audit.py", import.meta.url)), "utf8");
    // AUDITED values (`): "role.create",`) and the actions note() is given in this file.
    const recorded = new Set([...py.matchAll(/\):\s*"([a-z_]+\.[a-z_]+)"/g), ...py.matchAll(/"(auth\.[a-z_]+)"/g)].map((m) => m[1]));
    for (const router of ["admin_api_keys", "admin_secret_requests", "gmail"]) {
      const src = readFileSync(fileURLToPath(new URL(`../../../backend/routers/${router}.py`, import.meta.url)), "utf8");
      for (const m of src.matchAll(/audit\.note\(request, "([a-z_.]+)"/g)) recorded.add(m[1]);
    }
    expect(recorded.size).toBeGreaterThan(20);
    const unlabeled = [...recorded].filter((a) => !a.startsWith("resources.") && !ACTION_LABELS[a]);
    expect(unlabeled).toEqual([]);
  });

  it("falls back to readable text", () => {
    expect(actionLabel("resources.onboarding_approve")).toBe("Localz: onboarding approve");
    expect(actionLabel("something.new")).toBe("something.new");
  });
});

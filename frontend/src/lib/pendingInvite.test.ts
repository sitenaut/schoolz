import { beforeEach, describe, expect, it, vi } from "vitest";
import { clearPendingInvite, invitePath, loadPendingInvite, markPendingInviteRefused, savePendingInvite } from "./pendingInvite";

function memoryStorage(): Storage {
  const m = new Map<string, string>();
  return {
    get length() {
      return m.size;
    },
    clear: () => m.clear(),
    getItem: (k) => m.get(k) ?? null,
    key: (i) => [...m.keys()][i] ?? null,
    removeItem: (k) => void m.delete(k),
    setItem: (k, v) => void m.set(k, String(v)),
  };
}

describe("pendingInvite", () => {
  beforeEach(() => vi.stubGlobal("localStorage", memoryStorage()));

  it("round-trips a saved invite", () => {
    savePendingInvite({ kind: "student", token: "abc" });
    expect(loadPendingInvite()).toEqual({ kind: "student", token: "abc" });
    clearPendingInvite();
    expect(loadPendingInvite()).toBeNull();
  });

  it("ignores junk in storage", () => {
    localStorage.setItem("schoolz.pendingInvite", '{"kind":"nope","token":"x"}');
    expect(loadPendingInvite()).toBeNull();
    localStorage.setItem("schoolz.pendingInvite", "not json");
    expect(loadPendingInvite()).toBeNull();
  });

  it("maps each kind to its route", () => {
    expect(invitePath({ kind: "guardian", token: "t" })).toBe("/invites/t");
    expect(invitePath({ kind: "student", token: "t" })).toBe("/student-invites/t");
  });
});

describe("markPendingInviteRefused", () => {
  beforeEach(() => vi.stubGlobal("localStorage", memoryStorage()));

  it("remembers which account an invite was refused for, until the link is opened again", () => {
    clearPendingInvite();
    savePendingInvite({ kind: "student", token: "t1" });
    markPendingInviteRefused("parent-1");
    expect(loadPendingInvite()).toEqual({ kind: "student", token: "t1", refusedFor: "parent-1" });
    savePendingInvite({ kind: "student", token: "t1" });
    expect(loadPendingInvite()).toEqual({ kind: "student", token: "t1" });
    clearPendingInvite();
    markPendingInviteRefused("parent-1");
    expect(loadPendingInvite()).toBeNull();
  });
});

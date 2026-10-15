import { describe, expect, it, vi } from "vitest";
import { hasStoredSession, recoverSession } from "./sessionRecovery";

function storage(keys: string[]) {
  return { length: keys.length, key: (i: number) => keys[i] ?? null };
}

const noSleep = () => Promise.resolve();
const retryable = { name: "AuthRetryableFetchError", status: 0 };

describe("hasStoredSession", () => {
  it("finds a supabase session key", () => {
    expect(hasStoredSession(storage(["theme", "sb-abc123-auth-token"]))).toBe(true);
  });
  it("ignores other keys and missing storage", () => {
    expect(hasStoredSession(storage(["sb-abc123-auth-token-code-verifier-x", "theme"]))).toBe(false);
    expect(hasStoredSession(undefined)).toBe(false);
  });
  it("treats storage that throws as empty", () => {
    const broken = { get length(): number { throw new Error("blocked"); }, key: () => null };
    expect(hasStoredSession(broken)).toBe(false);
  });
});

describe("recoverSession", () => {
  it("retries a network failure and recovers", async () => {
    const refresh = vi
      .fn()
      .mockResolvedValueOnce({ data: { session: null }, error: retryable })
      .mockResolvedValueOnce({ data: { session: { access_token: "t" } }, error: null });
    expect(await recoverSession(refresh, [0, 1, 1], noSleep)).toBe("recovered");
    expect(refresh).toHaveBeenCalledTimes(2);
  });

  it("stops at a real refusal", async () => {
    const refresh = vi.fn().mockResolvedValue({ data: { session: null }, error: { name: "AuthApiError", status: 400 } });
    expect(await recoverSession(refresh, [0, 1, 1], noSleep)).toBe("gone");
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("gives up after the last try", async () => {
    const refresh = vi.fn().mockRejectedValue(new TypeError("Load failed"));
    expect(await recoverSession(refresh, [0, 1, 1], noSleep)).toBe("gone");
    expect(refresh).toHaveBeenCalledTimes(3);
  });
});

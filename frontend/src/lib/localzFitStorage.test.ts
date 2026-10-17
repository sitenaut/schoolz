import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  AGE_BANDS,
  DEVICE_KEY,
  DEVICE_TTL_MS,
  FIT_FOCUS,
  FIT_NEEDS,
  type FitAnswers,
  forgetDevice,
  readFit,
  SESSION_KEY,
  saveFit,
} from "./localzFit";
import { quickExit } from "./localz";

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

const answers: FitAnswers = { ages: ["18-59", "1-4"], has: ["disability"], focus: ["survivors"], noStatusFirst: true };
const NOW = Date.UTC(2026, 9, 17, 12);

describe("answers kept on the device", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", memoryStorage());
    vi.stubGlobal("sessionStorage", memoryStorage());
    vi.stubGlobal("window", new EventTarget());
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("uses neutral key names that say nothing about what's stored", () => {
    saveFit(answers, true);
    saveFit(answers, false);
    for (const key of [DEVICE_KEY, SESSION_KEY]) expect(key).not.toMatch(/servic|help|eligib|localz|fit|need/i);
  });

  it("keeps a session answer for the visit, and a remembered one on the device", () => {
    saveFit(answers);
    expect(readFit()).toEqual({ answers, remember: false });
    expect(localStorage.getItem(DEVICE_KEY)).toBeNull();
    saveFit(answers, true);
    expect(sessionStorage.getItem(SESSION_KEY)).toBeNull();
    expect(readFit()).toEqual({ answers, remember: true });
  });

  it("forgets a remembered answer after 90 days, and removes it", () => {
    saveFit(answers, true);
    vi.setSystemTime(NOW + DEVICE_TTL_MS - 1000);
    expect(readFit()?.remember).toBe(true);
    vi.setSystemTime(NOW + DEVICE_TTL_MS + 1);
    expect(readFit()).toBeNull();
    expect(localStorage.getItem(DEVICE_KEY)).toBeNull();
  });

  it("treats a save dated in the future, or unreadable, as gone", () => {
    localStorage.setItem(DEVICE_KEY, JSON.stringify({ a: answers, t: NOW + 24 * 3600 * 1000 }));
    expect(readFit()).toBeNull();
    expect(localStorage.getItem(DEVICE_KEY)).toBeNull();
    localStorage.setItem(DEVICE_KEY, "{not json");
    expect(readFit()).toBeNull();
    expect(localStorage.getItem(DEVICE_KEY)).toBeNull();
  });

  it("'Forget this device' clears remembered and session answers alike", () => {
    saveFit(answers, true);
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(answers));
    forgetDevice();
    expect(localStorage.getItem(DEVICE_KEY)).toBeNull();
    expect(sessionStorage.getItem(SESSION_KEY)).toBeNull();
    expect(readFit()).toBeNull();
  });

  it("moves answers from the old descriptive key to the neutral one", () => {
    localStorage.setItem("localz_fit", JSON.stringify(answers));
    expect(readFit()).toEqual({ answers, remember: true });
    expect(localStorage.getItem("localz_fit")).toBeNull();
    expect(JSON.parse(localStorage.getItem(DEVICE_KEY) as string).t).toBe(NOW);
  });

  it("Quick exit takes remembered answers with it", () => {
    saveFit(answers, true);
    const replace = vi.fn();
    const win = Object.assign(new EventTarget(), { location: { replace } });
    vi.stubGlobal("window", win);
    vi.stubGlobal("document", { title: "", body: { replaceChildren: vi.fn() } });
    quickExit();
    expect(replace).toHaveBeenCalled();
    expect(localStorage.getItem(DEVICE_KEY)).toBeNull();
    expect(readFit()).toBeNull();
  });

  it("survives storage that throws", () => {
    const blocked = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
      removeItem: () => {
        throw new Error("blocked");
      },
    };
    vi.stubGlobal("localStorage", blocked);
    vi.stubGlobal("sessionStorage", blocked);
    saveFit(answers);
    expect(readFit()).toEqual({ answers, remember: false });
    forgetDevice();
    expect(readFit()).toBeNull();
  });
});

describe("the saved profile's vocabulary", () => {
  it("is exactly the sheet's, on the server too", () => {
    const py = readFileSync(fileURLToPath(new URL("../../../backend/resources/saved_profile.py", import.meta.url)), "utf8");
    const tuple = (name: string) => {
      const m = py.match(new RegExp(`^${name} = \\(([^)]*)\\)`, "m"));
      return m ? [...m[1].matchAll(/"([^"]+)"/g)].map((x) => x[1]) : null;
    };
    expect(tuple("AGE_BANDS")).toEqual([...AGE_BANDS]);
    expect(tuple("NEEDS")).toEqual([...FIT_NEEDS]);
    expect(tuple("FOCUS")).toEqual([...FIT_FOCUS]);
  });
});

import { afterEach, describe, expect, it, vi } from "vitest";
import { AWAY_MS, buildWatcher, entryScript, newBuildLive } from "./freshBuild";

const INDEX = (entry: string) =>
  `<!doctype html><html><head><script type="module" crossorigin src="/assets/${entry}"></script>` +
  `<link rel="modulepreload" crossorigin href="/assets/vendor-DXjDNoeS.js"></head><body><div id="root"></div></body></html>`;

describe("entryScript", () => {
  it("finds the built entry, not the vendor preload", () => {
    expect(entryScript(INDEX("index-Y_oJzIAV.js"))).toBe("/assets/index-Y_oJzIAV.js");
  });

  it("is null for a page that isn't the built app", () => {
    expect(entryScript(`<script type="module" src="/src/main.tsx"></script>`)).toBeNull();
    expect(entryScript("<html><body>Sign in to the Wi-Fi</body></html>")).toBeNull();
  });
});

describe("newBuildLive", () => {
  afterEach(() => vi.unstubAllGlobals());

  const serve = (body: string, ok = true) => vi.stubGlobal("fetch", vi.fn(async () => ({ ok, text: async () => body })));

  it("is true when the site serves another entry", async () => {
    serve(INDEX("index-NEW.js"));
    expect(await newBuildLive("/assets/index-OLD.js")).toBe(true);
  });

  it("is false for the same build, a failed answer, or no answer", async () => {
    serve(INDEX("index-OLD.js"));
    expect(await newBuildLive("/assets/index-OLD.js")).toBe(false);
    serve(INDEX("index-NEW.js"), false);
    expect(await newBuildLive("/assets/index-OLD.js")).toBe(false);
    serve("<html>captive portal</html>");
    expect(await newBuildLive("/assets/index-OLD.js")).toBe(false);
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("offline"))));
    expect(await newBuildLive("/assets/index-OLD.js")).toBe(false);
  });

  it("doesn't ask when the running page has no built entry (the dev server)", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    expect(await newBuildLive(null)).toBe(false);
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("buildWatcher", () => {
  function setup({ live = true, busy = false } = {}) {
    let clock = 0;
    const check = vi.fn(async () => live);
    const reload = vi.fn();
    const w = buildWatcher({ check, reload, busy: () => busy, now: () => clock });
    const away = async (ms: number) => {
      w.hidden();
      clock += ms;
      await w.visible();
    };
    return { w, check, reload, away };
  }

  it("reloads when the visitor comes back after a while to a newer build", async () => {
    const { check, reload, away } = setup();
    await away(AWAY_MS);
    expect(check).toHaveBeenCalledOnce();
    expect(reload).toHaveBeenCalledOnce();
  });

  it("doesn't even ask after a short look away", async () => {
    const { check, reload, away } = setup();
    await away(AWAY_MS - 1);
    expect(check).not.toHaveBeenCalled();
    expect(reload).not.toHaveBeenCalled();
  });

  it("doesn't ask on a first visible with no hidden before it", async () => {
    const { w, check } = setup();
    await w.visible();
    expect(check).not.toHaveBeenCalled();
  });

  it("leaves the page alone when the live build is the running one", async () => {
    const { w, reload, away } = setup({ live: false });
    await away(AWAY_MS);
    w.navigated();
    expect(reload).not.toHaveBeenCalled();
  });

  it("waits for the next page when this one has typing or a dialog open", async () => {
    const { w, reload, away } = setup({ busy: true });
    await away(AWAY_MS);
    expect(reload).not.toHaveBeenCalled();
    w.navigated();
    expect(reload).toHaveBeenCalledOnce();
  });

  it("asks once per stale tab, however often the visitor comes back", async () => {
    const { check, away } = setup({ busy: true });
    await away(AWAY_MS);
    await away(AWAY_MS);
    expect(check).toHaveBeenCalledOnce();
  });
});

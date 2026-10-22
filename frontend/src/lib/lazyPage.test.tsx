// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { claimReload, lazyPage } from "./lazyPage";

afterEach(() => {
  cleanup();
  sessionStorage.clear();
  vi.restoreAllMocks();
});

function memoryStore() {
  const data = new Map<string, string>();
  return { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v) };
}

describe("claimReload", () => {
  it("allows one reload, then refuses until the gap has passed", () => {
    const store = memoryStore();
    expect(claimReload(store, 1_000_000)).toBe(true);
    expect(claimReload(store, 1_010_000)).toBe(false);
    expect(claimReload(store, 1_031_000)).toBe(true);
  });

  it("never reloads without storage to remember it by", () => {
    expect(claimReload(null, 1_000_000)).toBe(false);
    const throwing = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {},
    };
    expect(claimReload(throwing, 1_000_000)).toBe(false);
  });
});

describe("lazyPage", () => {
  it("renders the page with its props once the chunk arrives", async () => {
    const Page = lazyPage(async () => ({ kind }: { kind: string }) => <p>page {kind}</p>);
    render(<Page kind="guardian" />);
    expect(await screen.findByText("page guardian")).toBeTruthy();
  });

  it("reloads once when a chunk fails to load (an old build after a deploy)", async () => {
    const reload = vi.fn();
    vi.spyOn(window, "location", "get").mockReturnValue({ ...window.location, reload });
    const Page = lazyPage(() => Promise.reject(new TypeError("Failed to fetch dynamically imported module")));
    render(<Page />);
    await vi.waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
    expect(screen.queryByText("This page didn't load.")).toBeNull();
  });

  it("shows a Reload button instead of looping when it fails again right after", async () => {
    vi.spyOn(window, "location", "get").mockReturnValue({ ...window.location, reload: vi.fn() });
    vi.spyOn(console, "error").mockImplementation(() => {}); // React logs the caught error
    sessionStorage.setItem("schoolz_chunk_reload_at", String(Date.now()));
    const Page = lazyPage(() => Promise.reject(new TypeError("Failed to fetch dynamically imported module")));
    render(<Page />);
    expect(await screen.findByText("This page didn't load.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reload" })).toBeTruthy();
    expect(window.location.reload).not.toHaveBeenCalled();
  });
});

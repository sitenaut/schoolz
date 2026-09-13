import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "./api";

function jsonResponse(status: number): Response {
  return new Response(JSON.stringify({}), { status });
}

beforeEach(() => {
  // apiFetch's authHeader() reads localStorage in local auth mode - not
  // present in vitest's default node environment, so it's stubbed rather
  // than switching the whole suite to jsdom for one function.
  vi.stubGlobal("localStorage", {
    getItem: () => null,
    setItem: () => undefined,
    removeItem: () => undefined,
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("apiFetch retry", () => {
  it("retries a GET once after a connection failure, and returns the retry's result", async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(jsonResponse(200));
    vi.stubGlobal("fetch", fetchMock);

    // Awaited only after the timer advances - apiFetch's retry is parked
    // behind a real setTimeout, so nothing resolves until fake time moves.
    const pending = apiFetch("/schools");
    await vi.advanceTimersByTimeAsync(2000);
    const res = await pending;

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(res.status).toBe(200);
  });

  it("retries a GET once on a 503, and returns the retry's result", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(503)).mockResolvedValueOnce(jsonResponse(200));
    vi.stubGlobal("fetch", fetchMock);

    const pending = apiFetch("/schools");
    await vi.advanceTimersByTimeAsync(2000);
    const res = await pending;

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(res.status).toBe(200);
  });

  it("does not retry a second time if the retry also fails", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);

    // The assertion attaches its rejection handler immediately, before
    // fake time advances - attaching it after would race the rejection
    // and vitest would report a false "unhandled rejection".
    const assertion = expect(apiFetch("/schools")).rejects.toThrow();
    await vi.advanceTimersByTimeAsync(2000);
    await assertion;
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("never retries a non-GET request, even on failure", async () => {
    // A survey submission or a PATCH saving a school's hours must not be
    // silently resent - a network failure or 502/503/504 gives no
    // reliable signal about whether the first attempt was processed.
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiFetch("/survey", { method: "POST", body: "{}" })).rejects.toThrow();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not retry a normal successful GET", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(200));
    vi.stubGlobal("fetch", fetchMock);

    const res = await apiFetch("/schools");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(res.status).toBe(200);
  });

  it("does not retry an ordinary 404", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(404));
    vi.stubGlobal("fetch", fetchMock);

    const res = await apiFetch("/schools/does-not-exist");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(res.status).toBe(404);
  });
});

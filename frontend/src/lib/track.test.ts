import { beforeEach, describe, expect, it, vi } from "vitest";

const pushEvent = vi.fn();
const gaEvent = vi.fn();
vi.mock("./telemetry", () => ({ getFaro: () => ({ api: { pushEvent } }) }));
vi.mock("./analytics", () => ({ gaEvent }));

describe("trackEvent routing", () => {
  beforeEach(() => {
    pushEvent.mockClear();
    gaEvent.mockClear();
  });

  it("sends dashboard-queried events to Faro", async () => {
    const { trackEvent } = await import("./track");
    trackEvent("cta_click", { cta: "x" });
    trackEvent("auth_timeout", { after_ms: 1 });
    expect(pushEvent).toHaveBeenCalledTimes(2);
  });

  it("keeps product events GA4-only", async () => {
    const { trackEvent } = await import("./track");
    trackEvent("action", { action: "absence", method: "tel" });
    trackEvent("calendar_search", { result_count: 3 });
    expect(pushEvent).not.toHaveBeenCalled();
    expect(gaEvent).toHaveBeenCalledWith("action_absence", expect.anything());
    expect(gaEvent).toHaveBeenCalledWith("calendar_search", expect.anything());
  });

  it("does not forward page_view or auth_timeout to GA", async () => {
    const { trackEvent } = await import("./track");
    trackEvent("page_view", { route: "/" });
    expect(pushEvent).toHaveBeenCalledTimes(1);
    expect(gaEvent).not.toHaveBeenCalled();
  });
});

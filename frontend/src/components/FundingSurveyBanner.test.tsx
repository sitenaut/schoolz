// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (s: string, o?: Record<string, string>) => s.replace(/{{(\w+)}}/g, (_, k) => o?.[k] ?? "") }),
}));

import { FundingSurveyBanner, SURVEY_URL } from "./FundingSurveyBanner";

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.useRealTimers();
});

const banner = () => screen.queryByRole("region", { name: "School funding survey" });

describe("FundingSurveyBanner", () => {
  it("links to the form itself, in a new tab", () => {
    render(<FundingSurveyBanner today="2026-11-05" lastDay="2026-12-01" />);
    const link = screen.getByRole("link");
    expect(link.getAttribute("href")).toBe(SURVEY_URL);
    expect(link.getAttribute("target")).toBe("_blank");
    expect(SURVEY_URL).not.toContain("fbclid");
  });

  it("shows through its last day and not after", () => {
    render(<FundingSurveyBanner today="2026-12-01" lastDay="2026-12-01" />);
    expect(banner()).not.toBeNull();
    cleanup();
    render(<FundingSurveyBanner today="2026-12-02" lastDay="2026-12-01" />);
    expect(banner()).toBeNull();
  });

  it("names the last day only once it's confirmed", () => {
    render(<FundingSurveyBanner today="2026-11-05" lastDay="2026-12-01" showLastDay={false} />);
    expect(screen.queryByText(/Open until/)).toBeNull();
    cleanup();
    render(<FundingSurveyBanner today="2026-11-05" lastDay="2026-12-01" showLastDay />);
    expect(screen.getByText(/Open until December 1/)).not.toBeNull();
  });

  it("stays closed on this device once closed", () => {
    render(<FundingSurveyBanner today="2026-11-05" lastDay="2026-12-01" />);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(banner()).toBeNull();
    cleanup();
    render(<FundingSurveyBanner today="2026-11-05" lastDay="2026-12-01" />);
    expect(banner()).toBeNull();
  });

  it("goes once the survey is opened, but not before the link is followed", () => {
    vi.useFakeTimers();
    render(<FundingSurveyBanner today="2026-11-05" lastDay="2026-12-01" />);
    fireEvent.click(screen.getByRole("link"));
    expect(screen.queryByRole("link")).not.toBeNull();
    act(() => {
      vi.runAllTimers();
    });
    expect(banner()).toBeNull();
    expect(localStorage.getItem("schoolz_funding_survey_done")).toBe("1");
  });

  it("never renders in the prerender's browser", () => {
    // jsdom has no navigator.webdriver; a browser under automation says true.
    Object.defineProperty(navigator, "webdriver", { value: true, configurable: true });
    try {
      render(<FundingSurveyBanner today="2026-11-05" lastDay="2026-12-01" />);
      expect(banner()).toBeNull();
    } finally {
      Reflect.deleteProperty(navigator, "webdriver");
    }
  });
});

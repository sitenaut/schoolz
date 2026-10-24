// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

let auth: { user: { id: string } | null; loading: boolean } = { user: null, loading: false };
vi.mock("../context/AuthContext", () => ({ useAuth: () => auth }));
vi.mock("../lib/track", () => ({ trackEvent: () => {} }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (s: string) => s }) }));

let replyTo: (body: unknown) => void = () => {};
vi.mock("../api", () => ({
  apiFetch: () =>
    new Promise((resolve) => {
      replyTo = (body) => resolve({ ok: true, status: 200, json: async () => body });
    }),
}));

import { ChatWidget } from "./ChatWidget";

// jsdom has no layout, so no scrolling.
Element.prototype.scrollTo = () => {};

afterEach(() => {
  cleanup();
  sessionStorage.clear();
});

async function ask(text: string) {
  fireEvent.change(screen.getByRole("textbox"), { target: { value: text } });
  fireEvent.click(screen.getByLabelText("Send"));
}

describe("ChatWidget", () => {
  it("drops a reply that arrives after the account signed out", async () => {
    auth = { user: { id: "mom" }, loading: false };
    const { rerender } = render(<ChatWidget />);
    fireEvent.click(screen.getByLabelText("Ask schoolz"));
    await ask("What is Zoe missing?");
    expect(screen.getByText("What is Zoe missing?")).toBeTruthy();

    // Signed out on a shared computer while the answer was still coming.
    auth = { user: null, loading: false };
    rerender(<ChatWidget />);
    await act(async () => replyTo({ reply: "Zoe is missing the lab report.", history: [{ role: "user", content: "x" }], escalated: false }));

    expect(screen.queryByText("What is Zoe missing?")).toBeNull();
    expect(screen.queryByText("Zoe is missing the lab report.")).toBeNull();
    expect(sessionStorage.getItem("schoolz_chat_v1")).toBeNull();
  });

  it("still shows a reply for the same account", async () => {
    auth = { user: { id: "mom" }, loading: false };
    render(<ChatWidget />);
    fireEvent.click(screen.getByLabelText("Ask schoolz"));
    await ask("Bell times?");
    await act(async () => replyTo({ reply: "School starts at 8:15.", history: [], escalated: false }));
    expect(screen.getByText("School starts at 8:15.")).toBeTruthy();
  });
});

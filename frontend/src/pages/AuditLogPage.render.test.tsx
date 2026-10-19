// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const apiFetch = vi.fn();
vi.mock("../api", () => ({ apiFetch: (...args: unknown[]) => apiFetch(...args) }));

import { AuditLogPage } from "./AuditLogPage";

afterEach(() => {
  cleanup();
  apiFetch.mockReset();
});

const json = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body });
const event = (id: number, action: string, extra: object = {}) => ({
  id, ts: "2026-10-18T22:00:00Z", action, outcome: "success", status: 200, actor_user_id: "u1", actor: "boss@example.com",
  credential: "session", api_key_id: null, method: "POST", route: "/x", target: null, request_id: "r", ...extra,
});

describe("AuditLogPage", () => {
  it("shows events in words, filters by kind, and pages back", async () => {
    apiFetch
      .mockResolvedValueOnce(json({ events: [event(9, "role.create", { target: { role_id: "abc" } })], next_before_id: 9 }))
      .mockResolvedValueOnce(json({ events: [event(3, "auth.sign_in", { credential: "api_key", actor: null, actor_user_id: null, outcome: "denied", status: 403 })], next_before_id: null }))
      .mockResolvedValueOnce(json({ events: [], next_before_id: null }));

    render(<AuditLogPage />);
    expect(await screen.findByText("Created role")).toBeTruthy();
    expect(screen.getByText("role id: abc")).toBeTruthy();
    expect(apiFetch).toHaveBeenLastCalledWith("/admin/audit-log?limit=50");

    fireEvent.click(screen.getByText("Load older"));
    expect(await screen.findByText("Signed in")).toBeTruthy();
    expect(screen.getByText("Refused (403)")).toBeTruthy();
    expect(screen.getByText("Not signed in")).toBeTruthy();
    expect(apiFetch).toHaveBeenLastCalledWith("/admin/audit-log?limit=50&before_id=9");
    expect(screen.queryByText("Load older")).toBeNull();

    fireEvent.click(screen.getByText("API keys"));
    await waitFor(() => expect(apiFetch).toHaveBeenLastCalledWith("/admin/audit-log?limit=50&action=api_key."));
    expect(await screen.findByText("Nothing recorded yet for this filter.")).toBeTruthy();
  });

  it("says so when the reader isn't a super admin", async () => {
    apiFetch.mockResolvedValueOnce(json({ detail: "no" }, 403));
    render(<AuditLogPage />);
    expect(await screen.findByText("Only super admins can read the audit log.")).toBeTruthy();
  });
});

// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const auth = {
  user: { mfa_required: true, mfa_passed: false, mfa_enforced: true } as Record<string, boolean>,
  refresh: async () => {},
};
vi.mock("../context/AuthContext", () => ({ useAuth: () => auth }));
const verifiedTotpFactorId = vi.fn();
vi.mock("../lib/mfa", () => ({
  verifiedTotpFactorId: () => verifiedTotpFactorId(),
  verifyCode: async () => {},
}));

import { MfaGate } from "./MfaGate";

afterEach(() => {
  cleanup();
  verifiedTotpFactorId.mockReset();
});

const gate = () =>
  render(
    <MemoryRouter>
      <MfaGate>
        <p>Admin page</p>
      </MfaGate>
    </MemoryRouter>,
  );

describe("MfaGate with two-step sign-in enforced", () => {
  it("offers a retry when the factor check fails, not 'Set up two-step sign-in'", async () => {
    verifiedTotpFactorId.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    gate();
    expect(await screen.findByText("Couldn't check your two-step sign-in")).toBeTruthy();
    expect(screen.queryByText("Set up two-step sign-in")).toBeNull();

    verifiedTotpFactorId.mockResolvedValueOnce("factor-1");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Enter your code")).toBeTruthy();
  });

  it("asks an admin with no factor to set one up", async () => {
    verifiedTotpFactorId.mockResolvedValueOnce(null);
    gate();
    expect(await screen.findByText("Set up two-step sign-in")).toBeTruthy();
  });
});

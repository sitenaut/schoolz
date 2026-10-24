// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";

let auth: { user: { id: string } | null; loading: boolean } = { user: null, loading: true };
vi.mock("../context/AuthContext", () => ({ useAuth: () => auth }));

import { useViewerEpoch, withoutViewerLayer } from "./viewer";
import type { SchoolToday } from "../types";

describe("useViewerEpoch", () => {
  it("moves only when the person changes after auth has settled", () => {
    auth = { user: null, loading: true };
    const { result, rerender } = renderHook(() => useViewerEpoch());
    expect(result.current).toBe(0);
    // Settling on load is not a change: those requests carried the token.
    auth = { user: { id: "mom" }, loading: false };
    rerender();
    expect(result.current).toBe(0);
    auth = { user: { id: "mom" }, loading: false }; // a refreshed user object, same person
    rerender();
    expect(result.current).toBe(0);
    auth = { user: null, loading: false }; // signed out on a shared device
    rerender();
    expect(result.current).toBe(1);
    auth = { user: { id: "dad" }, loading: false };
    rerender();
    expect(result.current).toBe(2);
  });
});

describe("withoutViewerLayer", () => {
  it("keeps the school's day and drops the child layer", () => {
    const card = { status: "open", my_specials: [{ first_name: "Zoe" }], my_current_classes: [{ first_name: "Zoe" }] } as unknown as SchoolToday;
    const bare = withoutViewerLayer(card);
    expect(bare.status).toBe("open");
    expect(bare.my_specials).toEqual([]);
    expect(bare.my_current_classes).toEqual([]);
  });
});

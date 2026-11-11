// @vitest-environment jsdom
// Old addresses of a child's schoolwork (the Kidz page, the Focus app) and a
// router navigation to Gradez all end in a page load of a /gradez address:
// Gradez's document starts no analytics, so it is never rendered in one that has.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const auth = {
  user: { id: "u1", student_profile_id: null as string | null },
  loading: false,
  authTimedOut: false,
};
vi.mock("./context/AuthContext", () => ({ useAuth: () => auth, AuthProvider: ({ children }: { children: unknown }) => children }));

// The shell only says where it is: the main app's pages aren't under test.
vi.mock("./components/AppShell", async () => {
  const { useLocation } = await import("react-router-dom");
  return {
    AppShell: function Shell() {
      return <p>In the app at {useLocation().pathname}</p>;
    },
  };
});

import { Routed } from "./App";

const replace = vi.fn();

function at(url: string) {
  vi.stubGlobal("location", { ...window.location, replace });
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routed />
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  replace.mockReset();
  vi.unstubAllGlobals();
  auth.user = { id: "u1", student_profile_id: null };
});

describe("old addresses of a child's schoolwork", () => {
  it("take a Kidz tab to the same tab in Gradez", () => {
    at("/kids/kid-1?tab=grades");
    expect(replace).toHaveBeenCalledWith("/gradez?student=kid-1&tab=grades");
  });

  it("take the Kidz audit to About this data", () => {
    at("/kids/kid-1?tab=audit");
    expect(replace).toHaveBeenCalledWith("/gradez?student=kid-1&sheet=data");
  });

  it("take the Kidz page with no tab to To do", () => {
    at("/kids/kid-1");
    expect(replace).toHaveBeenCalledWith("/gradez?student=kid-1");
  });

  it("take the Focus app to Gradez, keeping the child", () => {
    at("/focus/?student=kid-1");
    expect(replace).toHaveBeenCalledWith("/gradez?student=kid-1");
  });

  it("take a guardian's old list of children to My family, without a page load", async () => {
    at("/kids");
    expect(await screen.findByText("In the app at /family")).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
  });
});

describe("Gradez reached by a router navigation", () => {
  it("loads the address again, as a document of its own", () => {
    at("/gradez?student=kid-1&tab=grades");
    expect(replace).toHaveBeenCalledWith("/gradez?student=kid-1&tab=grades");
  });
});

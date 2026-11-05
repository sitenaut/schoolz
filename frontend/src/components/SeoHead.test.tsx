// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, waitFor } from "@testing-library/react";
import { HelmetProvider } from "react-helmet-async";
import { SeoHead } from "./SeoHead";

const robots = () => document.head.querySelector('meta[name="robots"]')?.getAttribute("content") ?? null;

afterEach(cleanup);

describe("SeoHead", () => {
  it("asks search engines to leave out a page marked noindex", async () => {
    render(
      <HelmetProvider>
        <SeoHead title="A home daycare · Localz" description="Hours" path="/localz/r/abc" noindex />
      </HelmetProvider>,
    );
    await waitFor(() => expect(document.title).toBe("A home daycare · Localz"));
    expect(robots()).toBe("noindex");
  });

  it("leaves every other page indexable", async () => {
    render(
      <HelmetProvider>
        <SeoHead title="A food pantry · Localz" description="Hours" path="/localz/r/def" />
      </HelmetProvider>,
    );
    await waitFor(() => expect(document.title).toBe("A food pantry · Localz"));
    expect(robots()).toBeNull();
  });
});

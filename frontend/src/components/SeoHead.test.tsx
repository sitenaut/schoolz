// @vitest-environment jsdom
import { readFileSync } from "node:fs";
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

  it("replaces index.html's generic description instead of adding a second one", async () => {
    // vitest runs from frontend/ (jsdom's import.meta.url isn't a file URL).
    const html = readFileSync("index.html", "utf8");
    const tag = html.match(/<meta name="description"[^>]*>/)![0];
    document.head.insertAdjacentHTML("beforeend", tag);
    render(
      <HelmetProvider>
        <SeoHead title="Bells Elementary School · schoolz" description="Bells in Washington Township" path="/schools/bells" />
      </HelmetProvider>,
    );
    await waitFor(() => expect(document.title).toBe("Bells Elementary School · schoolz"));
    const descriptions = [...document.head.querySelectorAll('meta[name="description"]')].map((m) => m.getAttribute("content"));
    expect(descriptions).toEqual(["Bells in Washington Township"]);
  });
});

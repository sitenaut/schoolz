// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { SeasonalAttraction } from "../lib/seasonal";
import { SeasonalAttractions } from "./SeasonalAttractions";

afterEach(cleanup);

function volunteer(name: string, resource_id: string | null, latitude: number | null = 39.94): SeasonalAttraction {
  return {
    id: name,
    season: "winter",
    kind: "volunteer",
    name,
    venue: null,
    address: "1 Main St, Camden, NJ 08102",
    town: "Camden",
    latitude,
    longitude: latitude === null ? null : -75.12,
    url: "https://example.org/volunteer",
    ticket_url: null,
    starts_on: "2026-11-13",
    ends_on: "2026-12-31",
    open_dates: null,
    schedule: null,
    price: null,
    scare_level: null,
    ages: null,
    note: null,
    verified_on: null,
    resource_id,
    open_on_day: null,
  };
}

describe("SeasonalAttractions", () => {
  it("links a volunteer place to the Localz listing for the help it gives", () => {
    const { getByText, queryAllByText } = render(
      <MemoryRouter>
        <SeasonalAttractions season="winter" attractions={[volunteer("Soup kitchen", "abc-123"), volunteer("Park cleanup", null)]} />
      </MemoryRouter>,
    );
    expect(getByText("What they provide").getAttribute("href")).toBe("/localz/r/abc-123");
    expect(queryAllByText("What they provide")).toHaveLength(1);
  });

  it("gives no directions to a drive you give to by mail or online", () => {
    const { queryAllByText } = render(
      <MemoryRouter>
        <SeasonalAttractions season="winter" attractions={[volunteer("Toy drive", null, null), volunteer("Soup kitchen", null)]} />
      </MemoryRouter>,
    );
    expect(queryAllByText("Directions ↗")).toHaveLength(1);
  });
});

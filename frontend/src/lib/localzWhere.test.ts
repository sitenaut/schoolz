import { describe, expect, it } from "vitest";
import { countiesForAreaCode, whereForPoint, whereForZip } from "./localzWhere";

describe("Set my location, worked out on the device", () => {
  it("turns a New Jersey ZIP into its county", async () => {
    expect((await whereForZip("07075"))?.county).toBe("Bergen"); // Wood-Ridge
    expect((await whereForZip("07074"))?.county).toBe("Bergen"); // Moonachie
    expect((await whereForZip(" 08034 "))?.county).toBe("Camden");
    expect(await whereForZip("10001")).toBeNull(); // Manhattan
    expect(await whereForZip("0707")).toBeNull();
  });

  it("narrows an area code to the counties it covers, and knows non-NJ codes", () => {
    expect(countiesForAreaCode("201")).toEqual(["Bergen", "Hudson"]);
    expect(countiesForAreaCode("856")).toContain("Camden");
    expect(countiesForAreaCode("212")).toBeNull();
  });

  it("places the phone at its nearest NJ ZIP's county, rounded, or nowhere outside NJ", async () => {
    const moonachie = await whereForPoint(40.84123, -74.05678);
    expect(moonachie?.county).toBe("Bergen");
    expect(moonachie?.lat).toBe(40.84);
    expect(moonachie?.lon).toBe(-74.06);
    expect(await whereForPoint(41.8781, -87.6298)).toBeNull(); // Chicago
  });
});

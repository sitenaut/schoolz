import { describe, expect, it } from "vitest";
import { GRADEZ_DOCUMENT, gradezHref, isGradezPath } from "./gradezPath";

describe("isGradezPath", () => {
  it("is Gradez and anything under it", () => {
    expect(isGradezPath("/gradez")).toBe(true);
    expect(isGradezPath("/gradez/")).toBe(true);
  });

  it("is not a page that only starts the same way", () => {
    expect(isGradezPath("/gradezilla")).toBe(false);
    expect(isGradezPath("/family")).toBe(false);
    expect(isGradezPath("/")).toBe(false);
  });

  it("says a document loaded anywhere else is not a Gradez one", () => {
    expect(GRADEZ_DOCUMENT).toBe(false);
  });
});

describe("gradezHref", () => {
  it("leaves out what the page defaults to", () => {
    expect(gradezHref()).toBe("/gradez");
    expect(gradezHref("kid-1")).toBe("/gradez?student=kid-1");
    expect(gradezHref("kid-1", "todo")).toBe("/gradez?student=kid-1");
  });

  it("names the tab and anything extra", () => {
    expect(gradezHref("kid-1", "grades")).toBe("/gradez?student=kid-1&tab=grades");
    expect(gradezHref("kid-1", "todo", { sheet: "data" })).toBe("/gradez?student=kid-1&sheet=data");
  });
});

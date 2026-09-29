// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { Modal } from "./Modal";

const dialog = (open: boolean) => (
  <Modal open={open} onClose={() => {}} title="t">
    x
  </Modal>
);

afterEach(cleanup);

describe("Modal scroll lock", () => {
  it("pins the page while open and releases it on close", () => {
    const a = render(dialog(true));
    expect(document.body.style.position).toBe("fixed");
    a.rerender(dialog(false));
    expect(document.body.style.position).toBe("");
    expect(document.body.style.overflow).toBe("");
  });

  it("releases the page when overlapping dialogs close out of order", () => {
    const a = render(dialog(true));
    const b = render(dialog(true));
    a.rerender(dialog(false));
    expect(document.body.style.position).toBe("fixed");
    b.rerender(dialog(false));
    expect(document.body.style.position).toBe("");
    expect(document.body.style.overflow).toBe("");
  });
});

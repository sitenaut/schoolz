// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { FilterSelect, filterOptions, type FilterOption } from "./FilterSelect";

const towns: FilterOption[] = ["Audubon", "Berlin", "Cherry Hill", "Haddonfield", "Lindenwold", "Maple Shade", "Mount Laurel", "Pennsauken", "Voorhees", "Woodbury"].map((t) => ({ value: t, label: t }));

afterEach(cleanup);

describe("filterOptions", () => {
  it("ANDs words across label, hint and group", () => {
    const opts: FilterOption[] = [
      { value: "a", label: "Parkview", hint: "Westville", group: "Elementary" },
      { value: "b", label: "Parkview", hint: "Stratford", group: "Elementary" },
      { value: "c", label: "East", hint: "Cherry Hill", group: "High" },
    ];
    expect(filterOptions(opts, "park west").map((o) => o.value)).toEqual(["a"]);
    expect(filterOptions(opts, "HIGH").map((o) => o.value)).toEqual(["c"]);
    expect(filterOptions(opts, "  ")).toHaveLength(3);
  });
});

describe("FilterSelect", () => {
  it("narrows the list as you type and picks with Enter", () => {
    const onChange = vi.fn();
    render(<FilterSelect value="" onChange={onChange} options={towns} placeholder="Choose your town" />);
    fireEvent.click(screen.getByRole("button", { name: "Choose your town" }));
    expect(screen.getAllByRole("option")).toHaveLength(10);
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "wood" } });
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["Woodbury"]);
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith("Woodbury");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("offers a clear row, and hides it while filtering", () => {
    const onChange = vi.fn();
    render(<FilterSelect value="Berlin" onChange={onChange} options={towns} placeholder="All towns" clearLabel="All towns" />);
    fireEvent.click(screen.getByRole("button", { name: "Berlin" }));
    expect(screen.getAllByRole("option")[0].textContent).toBe("All towns");
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "ber" } });
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["Berlin"]);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "" } });
    fireEvent.click(screen.getAllByRole("option")[0]);
    expect(onChange).toHaveBeenCalledWith("");
  });

  it("skips the filter box for a short list, and says so when nothing matches", () => {
    render(<FilterSelect value="" onChange={() => {}} options={towns.slice(0, 3)} placeholder="Pick" />);
    fireEvent.click(screen.getByRole("button", { name: "Pick" }));
    expect(screen.queryByRole("combobox")).toBeNull();
    cleanup();
    render(<FilterSelect value="" onChange={() => {}} options={towns} placeholder="Pick" />);
    fireEvent.click(screen.getByRole("button", { name: "Pick" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "zzz" } });
    expect(screen.getByText("No matches")).toBeTruthy();
  });

  it("closes on Escape without changing the value", () => {
    const onChange = vi.fn();
    render(<FilterSelect value="" onChange={onChange} options={towns} placeholder="Pick" />);
    fireEvent.click(screen.getByRole("button", { name: "Pick" }));
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
  });
});

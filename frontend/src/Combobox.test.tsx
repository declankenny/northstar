// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Combobox, type ComboOption, matchingOptions } from "./Combobox";

const OPTIONS: ComboOption[] = [
  { id: 3, label: "Test dollars", detail: "USD" }, { id: 4, label: "Test euros", detail: "EUR" }, { id: 5, label: "Test yen", detail: "JPY" },
];

/** The box as a form uses it: the chosen id lives in the parent. */
function Harness({ start = "", onChange = () => {}, onParentKey = () => {} }: { start?: string | number; onChange?: (id: string | number) => void; onParentKey?: () => void }) {
  const [value, setValue] = useState<string | number>(start);
  return (
    <div onKeyDown={onParentKey}>
      <Combobox options={OPTIONS} value={value} label="Account" onChange={(id) => { setValue(id); onChange(id); }} />
    </div>
  );
}

const box = () => screen.getByRole("combobox", { name: "Account" }) as HTMLInputElement;
const names = () => within(screen.getByRole("listbox")).getAllByRole("option").map((o) => o.textContent);

afterEach(cleanup);

describe("matching options", () => {
  it("matches the label or the detail, in any case, and lists everything when nothing is typed", () => {
    expect(matchingOptions(OPTIONS, "").map((o) => o.id)).toEqual([3, 4, 5]);
    expect(matchingOptions(OPTIONS, "  ").map((o) => o.id)).toEqual([3, 4, 5]);
    expect(matchingOptions(OPTIONS, "EURO").map((o) => o.id)).toEqual([4]);
    expect(matchingOptions(OPTIONS, "jpy").map((o) => o.id)).toEqual([5]);
    expect(matchingOptions(OPTIONS, "test").map((o) => o.id)).toEqual([3, 4, 5]);
    expect(matchingOptions(OPTIONS, "zzz")).toEqual([]);
  });
});

describe("the type-ahead", () => {
  it("is closed until it is focused, and then lists every option, with the detail beside the label", () => {
    render(<Harness />);
    expect(screen.queryByRole("listbox")).toBeNull();
    fireEvent.focus(box());
    expect(names()).toEqual(["Test dollarsUSD", "Test eurosEUR", "Test yenJPY"]);
    expect(box().getAttribute("aria-expanded")).toBe("true");
  });

  it("filters as it is typed and says when nothing matches", () => {
    render(<Harness />);
    fireEvent.focus(box());
    fireEvent.change(box(), { target: { value: "eur" } });
    expect(names()).toEqual(["Test eurosEUR"]);
    fireEvent.change(box(), { target: { value: "zzz" } });
    expect(screen.queryAllByRole("option")).toHaveLength(0);
    expect(screen.getByText("Nothing matches.")).toBeTruthy();
  });

  it("chooses with a click, returns the id and shows the choice", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    fireEvent.focus(box());
    fireEvent.mouseDown(screen.getByRole("option", { name: /Test euros/ }));
    expect(onChange).toHaveBeenCalledWith(4);
    expect(box().value).toBe("Test euros");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("chooses with the arrow keys and Enter, which is not a submit", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    fireEvent.focus(box());
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    fireEvent.keyDown(box(), { key: "ArrowUp" });
    expect(box().getAttribute("aria-activedescendant")).toBe(screen.getByRole("option", { name: /Test euros/ }).id);
    const enter = fireEvent.keyDown(box(), { key: "Enter" });
    expect(enter).toBe(false);                                       // default prevented
    expect(onChange).toHaveBeenCalledWith(4);
  });

  it("keeps the active option inside the list at both ends", () => {
    render(<Harness />);
    fireEvent.focus(box());
    fireEvent.keyDown(box(), { key: "ArrowUp" });
    expect(box().getAttribute("aria-activedescendant")).toBe(screen.getAllByRole("option")[0].id);
    for (let i = 0; i < 6; i++) fireEvent.keyDown(box(), { key: "ArrowDown" });
    expect(box().getAttribute("aria-activedescendant")).toBe(screen.getAllByRole("option")[2].id);
  });

  it("opens on the arrow key when it is closed, with the chosen option active", () => {
    render(<Harness start={4} />);
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    expect(box().getAttribute("aria-activedescendant")).toBe(screen.getByRole("option", { name: /Test euros/ }).id);
    expect(screen.getByRole("option", { name: /Test euros/ }).getAttribute("aria-selected")).toBe("true");
  });

  it("shows the chosen option when it is closed, and still lists the others when it opens again", () => {
    render(<Harness start={5} />);
    expect(box().value).toBe("Test yen");
    fireEvent.focus(box());
    expect(names()).toHaveLength(3);                                 // what is chosen does not hide the rest
  });

  it("never takes what is typed as a value: leaving without choosing shows the chosen option again", () => {
    const onChange = vi.fn();
    render(<Harness start={3} onChange={onChange} />);
    fireEvent.focus(box());
    fireEvent.change(box(), { target: { value: "eur" } });          // it matches an option, and is still only a search
    expect(box().value).toBe("eur");
    fireEvent.blur(box());
    expect(box().value).toBe("Test dollars");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("has nothing chosen to show until one is chosen", () => {
    render(<Harness />);
    expect(box().value).toBe("");
    expect(box().placeholder).toBe("Search");
  });

  it("closes the list on Escape without choosing, and keeps the Escape from the dialog around it", () => {
    const onParentKey = vi.fn();
    const onChange = vi.fn();
    render(<Harness onChange={onChange} onParentKey={onParentKey} />);
    fireEvent.focus(box());
    fireEvent.keyDown(box(), { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
    expect(onParentKey).not.toHaveBeenCalled();
    fireEvent.keyDown(box(), { key: "Escape" });                     // closed: it goes on to whatever is around
    expect(onParentKey).toHaveBeenCalledTimes(1);
  });

  it("works with ids that are text, as a declared set's values are", () => {
    const onChange = vi.fn();
    render(<Combobox options={[{ id: "Open", label: "Open" }, { id: "Closed", label: "Closed" }]} value="" label="Status" onChange={onChange} />);
    fireEvent.focus(screen.getByRole("combobox", { name: "Status" }));
    fireEvent.mouseDown(screen.getByRole("option", { name: "Closed" }));
    expect(onChange).toHaveBeenCalledWith("Closed");
  });
});

// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Choices, Condition, FieldNode, FieldTree } from "./api";
import { FilterChips } from "./FilterChips";
import { ReportFilterDrawer } from "./ReportFilterDrawer";
import { useChoiceNames } from "./useChoiceNames";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()), fetchSavedFilters: vi.fn(), saveSavedFilter: vi.fn(), changeSavedFilter: vi.fn(), deleteSavedFilter: vi.fn(),
  saveListColumns: vi.fn(), fetchListChoices: vi.fn(),
}));

import { changeSavedFilter, deleteSavedFilter, fetchListChoices, fetchSavedFilters, saveListColumns, saveSavedFilter } from "./api";

const LABELS: Record<string, string> = { is_any_of: "is one of", is_not_any_of: "is not one of" };
const ops = (...names: string[]) => names.map((name) => ({ name, label: LABELS[name] ?? name.replaceAll("_", " ") }));
const field = (over: Partial<FieldNode>): FieldNode => ({ key: "k", label: "K", path_label: "K", kind: "text", scale: null, operators: ops("equals"), choices: null, ...over });

// What a report that filters accounts might offer: a text field, a declared set, and a relation whose records have names.
const TREE: FieldTree = {
  fields: [
    field({ key: "name", label: "Name", path_label: "Name", operators: ops("contains", "equals") }),
    field({ key: "status", label: "Status", path_label: "Status", kind: "choice", operators: ops("is_any_of"), choices: "values", values: ["Open", "Closed"] }),
  ],
  relations: [field({ key: "type", label: "Account type", path_label: "Account type", kind: "choice", operators: ops("is_any_of"), choices: "records" })],
};
const NAMES: Choices = { kind: "records", values: [], more: false, options: [{ id: 3, value: "Savings", detail: null }, { id: 4, value: "Loan", detail: null }] };

const NAME: Condition = { field: "name", operator: "contains", value: "Test" };

beforeEach(() => {
  vi.mocked(fetchListChoices).mockResolvedValue(NAMES);
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const drawer = () => within(screen.getByRole("dialog"));

function show(over: Partial<Parameters<typeof ReportFilterDrawer>[0]> = {}) {
  const onApply = vi.fn(), onClose = vi.fn(), ensureChoices = vi.fn();
  render(<ReportFilterDrawer title="Test report" tree={TREE} applied={[]} choices={new Map()} ensureChoices={ensureChoices} onApply={onApply} onClose={onClose} {...over} />);
  return { onApply, onClose, ensureChoices };
}

describe("a report's filter drawer", () => {
  it("has the condition editor and nothing that belongs only to lists: no saved filters, no Columns tab, and no request for either", () => {
    show();
    const d = drawer();
    expect(screen.getByRole("dialog", { name: "Test report filters" })).toBeTruthy();
    expect(d.getByRole("heading", { name: "Test report filters" })).toBeTruthy();
    expect(d.getByRole("button", { name: "+ Add filter" })).toBeTruthy();
    expect(d.getByRole("button", { name: "Clear filters" })).toBeTruthy();
    expect(d.queryByText("Saved filter")).toBeNull();
    expect(d.queryByRole("button", { name: /^Columns/ })).toBeNull();
    expect(d.queryByRole("button", { name: /^Filters \(/ })).toBeNull();
    expect(d.queryByText(/Reset to default columns/)).toBeNull();
    for (const request of [fetchSavedFilters, saveSavedFilter, changeSavedFilter, deleteSavedFilter, saveListColumns]) expect(request).not.toHaveBeenCalled();
  });

  it("says nothing about rows, lists or currencies, because the report's population is the report's own", () => {
    show();
    const text = screen.getByRole("dialog").textContent ?? "";
    expect(text).toContain("No conditions. Nothing is filtered out.");
    expect(text).toContain("Conditions combine with AND");
    expect(text).not.toMatch(/list|row|column|currenc/i);
  });

  it("builds a condition from what the report allows, and applies it only on Apply changes", () => {
    const { onApply } = show();
    fireEvent.click(drawer().getByRole("button", { name: "+ Add filter" }));
    fireEvent.click(within(drawer().getByLabelText("Columns to filter by")).getByRole("button", { name: "Name" }));
    fireEvent.change(drawer().getByLabelText("Name"), { target: { value: "Test" } });
    expect(onApply).not.toHaveBeenCalled();
    fireEvent.click(drawer().getByRole("button", { name: "Apply changes" }));
    expect(onApply).toHaveBeenCalledWith([NAME]);
  });

  it("starts from what is applied, and Cancel and Escape throw the draft away", () => {
    const { onApply, onClose } = show({ applied: [NAME] });
    expect((drawer().getByLabelText("Name") as HTMLInputElement).value).toBe("Test");
    fireEvent.click(drawer().getByRole("button", { name: "Cancel" }));
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
    expect(onApply).not.toHaveBeenCalled();
  });

  it("clears the draft with Clear filters, which applies nothing until Apply and then applies an empty set", () => {
    const { onApply } = show({ applied: [NAME] });
    fireEvent.click(drawer().getByRole("button", { name: "Clear filters" }));
    expect(onApply).not.toHaveBeenCalled();
    expect(drawer().getByText("No conditions. Nothing is filtered out.")).toBeTruthy();
    fireEvent.click(drawer().getByRole("button", { name: "Apply changes" }));
    expect(onApply).toHaveBeenCalledWith([]);
  });

  it("refuses to apply an incomplete condition and points at it", () => {
    const { onApply } = show({ applied: [{ field: "name", operator: "contains", value: "" }] });
    fireEvent.click(drawer().getByRole("button", { name: "Apply changes" }));
    expect(onApply).not.toHaveBeenCalled();
    expect(drawer().getAllByRole("alert").length).toBeGreaterThan(0);
    expect(drawer().getByText("Type the text to look for.")).toBeTruthy();
  });

  it("says a condition on a field the report does not offer is not available, and will not apply it", () => {
    const { onApply } = show({ applied: [{ field: "opened_on", operator: "after", value: "2026-01-01" }] });
    expect(drawer().getByText("not available for this report")).toBeTruthy();
    fireEvent.click(drawer().getByRole("button", { name: "Apply changes" }));
    expect(onApply).not.toHaveBeenCalled();
    expect(drawer().getByText("Complete or remove the conditions marked below, then apply.")).toBeTruthy();
    fireEvent.click(drawer().getByRole("button", { name: "Remove the filter on opened_on" }));
    fireEvent.click(drawer().getByRole("button", { name: "Apply changes" }));
    expect(onApply).toHaveBeenCalledWith([]);
  });

  it("asks for the names of a relation's records through the function it is given, and shows them", () => {
    const ensureChoices = vi.fn();
    show({ applied: [{ field: "type", operator: "is_any_of", value: [3] }], ensureChoices, choices: new Map([["type", NAMES]]) });
    expect(ensureChoices).toHaveBeenCalledWith("type");
    expect((drawer().getByRole("checkbox", { name: "Savings" }) as HTMLInputElement).checked).toBe(true);
    expect((drawer().getByRole("checkbox", { name: "Loan" }) as HTMLInputElement).checked).toBe(false);
  });
});

describe("the applied-filter chips", () => {
  const nodes = new Map(TREE.fields.concat(TREE.relations).map((n) => [n.key, n]));

  it("say nothing when nothing is applied", () => {
    const { container } = render(<FilterChips conditions={[]} nodes={nodes} names={new Map()} onRemove={() => {}} onClear={() => {}} />);
    expect(container.textContent).toBe("");
  });

  it("describe each condition in words, named from the choices, and remove one or all", () => {
    const onRemove = vi.fn(), onClear = vi.fn();
    render(<FilterChips conditions={[NAME, { field: "type", operator: "is_any_of", value: [3, 4] }]} nodes={nodes} names={new Map([["type", NAMES]])}
      onRemove={onRemove} onClear={onClear} />);
    const chips = within(screen.getByRole("list", { name: "Filters applied" })).getAllByRole("listitem");
    expect(chips.map((c) => c.textContent)).toEqual(["Name contains Test✕", "Account type is one of Savings, Loan✕"]);
    fireEvent.click(screen.getByRole("button", { name: "Remove the filter: Account type is one of Savings, Loan" }));
    expect(onRemove).toHaveBeenCalledWith(1);
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(onClear).toHaveBeenCalled();
  });
});

describe("the names of a relation's records", () => {
  const nodes = new Map(TREE.fields.concat(TREE.relations).map((n) => [n.key, n]));
  const fetcher = vi.fn((field: string) => fetchListChoices("scope", field));

  function Probe({ scope, applied }: { scope: string; applied: Condition[] }) {
    const { named, ensureChoices } = useChoiceNames(scope, fetcher, applied, nodes);
    const [, again] = useState(0);
    return <div><span data-testid="names">{[...named.keys()].join(",")}</span><button onClick={() => { ensureChoices("type"); again((n) => n + 1); }}>ask</button></div>;
  }

  it("are asked for once per field, and at once for a condition that is already applied", async () => {
    render(<Probe scope="a" applied={[{ field: "type", operator: "is_any_of", value: [3] }]} />);
    await waitFor(() => expect(screen.getByTestId("names").textContent).toBe("type"));
    fireEvent.click(screen.getByRole("button", { name: "ask" }));
    fireEvent.click(screen.getByRole("button", { name: "ask" }));
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("are not asked for when the field is not a relation, or nothing is applied", async () => {
    render(<Probe scope="a" applied={[NAME]} />);
    await Promise.resolve();
    expect(fetcher).not.toHaveBeenCalled();
    expect(screen.getByTestId("names").textContent).toBe("");
  });

  it("start afresh for another list or report", async () => {
    const applied: Condition[] = [{ field: "type", operator: "is_any_of", value: [3] }];
    const { rerender } = render(<Probe scope="a" applied={applied} />);
    await waitFor(() => expect(screen.getByTestId("names").textContent).toBe("type"));
    rerender(<Probe scope="b" applied={applied} />);
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByTestId("names").textContent).toBe("type"));
  });

  it("ask again later when an answer failed", async () => {
    vi.mocked(fetchListChoices).mockRejectedValueOnce(new Error("down"));
    render(<Probe scope="a" applied={[]} />);
    fireEvent.click(screen.getByRole("button", { name: "ask" }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    await Promise.resolve(); await Promise.resolve();
    fireEvent.click(screen.getByRole("button", { name: "ask" }));
    await waitFor(() => expect(screen.getByTestId("names").textContent).toBe("type"));
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});

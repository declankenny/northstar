import { type KeyboardEvent, useState } from "react";
import type { Currency } from "./money";

/** The currencies whose code or name contains what was typed, in any case. Nothing typed lists them all. */
export function matchingCurrencies(catalog: Currency[], typed: string): Currency[] {
  const needle = typed.trim().toLowerCase();
  return needle ? catalog.filter((c) => c.code.toLowerCase().includes(needle) || c.name.toLowerCase().includes(needle)) : catalog;
}

/** A search box over the currency catalog, drawn in the app's own style (the browser's datalist cannot be styled, and filters by
 *  whatever is in the box, so after a choice it would show only that choice). The list filters by what the person has typed since
 *  opening it, so a chosen currency does not hide the others. `value` is the text in the box: a code after a choice. */
export function CurrencySearch({ id, catalog, value, onChange, invalid }:
  { id: string; catalog: Currency[]; value: string; onChange: (text: string) => void; invalid?: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState(false); // typed since the list opened: only then does the text filter it
  const [active, setActive] = useState(0);
  const shown = matchingCurrencies(catalog, typed ? value : "");
  const listId = `${id}-list`;

  const choose = (currency: Currency) => {
    onChange(currency.code);
    setOpen(false);
    setTyped(false);
  };
  const show = () => {
    setOpen(true);
    setActive(0);
  };

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) return show();
      setActive((index) => Math.max(0, Math.min(shown.length - 1, index + (event.key === "ArrowDown" ? 1 : -1))));
    } else if (event.key === "Enter" && open) {
      event.preventDefault(); // choosing, not submitting the form
      if (shown[active]) choose(shown[active]);
    } else if (event.key === "Escape" && open) {
      event.preventDefault();
      setOpen(false);
      setTyped(false);
    }
  };

  return (
    <div className="combo">
      <input id={id} name="currency" role="combobox" aria-expanded={open} aria-controls={listId} aria-autocomplete="list"
        aria-activedescendant={open && shown[active] ? `${id}-${shown[active].code}` : undefined}
        value={value} autoComplete="off" spellCheck={false} placeholder="Search by currency name or code"
        onChange={(event) => { onChange(event.target.value); setTyped(true); setOpen(true); setActive(0); }}
        onFocus={show} onClick={() => !open && show()} onBlur={() => { setOpen(false); setTyped(false); }} onKeyDown={onKeyDown}
        {...invalid} />
      {open && (
        <ul className="combo-list" id={listId} role="listbox" aria-label="Currencies">
          {shown.length === 0 && <li className="combo-empty" role="presentation">No currency matches.</li>}
          {shown.map((c, index) => (
            <li key={c.code} id={`${id}-${c.code}`} role="option" aria-selected={index === active} className={index === active ? "active" : undefined}
              onMouseDown={(event) => { event.preventDefault(); choose(c); }} onMouseEnter={() => setActive(index)}>
              <strong>{c.code}</strong> <span>{c.name}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

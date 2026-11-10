import { type KeyboardEvent, useId, useState } from "react";

export type ComboOption = { id: string | number; label: string; detail?: string | null };

/** The options whose label or detail contains what was typed, in any case. Nothing typed lists them all. */
export function matchingOptions(options: ComboOption[], typed: string): ComboOption[] {
  const needle = typed.trim().toLowerCase();
  return needle ? options.filter((o) => o.label.toLowerCase().includes(needle) || (o.detail ?? "").toLowerCase().includes(needle)) : options;
}

/** A type-ahead over a list of options, drawn in the app's own style (the browser's datalist cannot be styled). One option is chosen,
 *  and only from the list: what is typed searches and is never a value, so leaving the box without choosing shows the chosen option
 *  again. `value` is the chosen option's id, or "" when none is. The list filters by what has been typed since it opened, so a chosen
 *  option does not hide the others. */
export function Combobox({ options, value, onChange, label, placeholder = "Search" }:
  { options: ComboOption[]; value: string | number; onChange: (id: string | number) => void; label: string; placeholder?: string }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState<string | null>(null);   // what has been typed since the list opened; null before anything has
  const [active, setActive] = useState(0);
  const chosen = options.find((o) => o.id === value);
  const shown = matchingOptions(options, typed ?? "");
  const listId = `${id}-list`;

  const close = () => { setOpen(false); setTyped(null); };
  const choose = (option: ComboOption) => { onChange(option.id); close(); };
  const show = () => { setOpen(true); setActive(Math.max(0, shown.findIndex((o) => o.id === value))); };

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) return show();
      setActive((index) => Math.max(0, Math.min(shown.length - 1, index + (event.key === "ArrowDown" ? 1 : -1))));
    } else if (event.key === "Enter" && open) {
      event.preventDefault();                                  // choosing, not submitting anything
      if (shown[active]) choose(shown[active]);
    } else if (event.key === "Escape" && open) {
      event.preventDefault();
      event.stopPropagation();                                 // closes the list, and not the drawer around it
      close();
    }
  };

  return (
    <div className="combo">
      <input role="combobox" aria-label={label} aria-expanded={open} aria-controls={listId} aria-autocomplete="list"
        aria-activedescendant={open && shown[active] ? `${id}-${active}` : undefined}
        value={typed ?? chosen?.label ?? ""} autoComplete="off" spellCheck={false} placeholder={placeholder}
        onChange={(event) => { setTyped(event.target.value); setOpen(true); setActive(0); }}
        onFocus={show} onClick={() => !open && show()} onBlur={close} onKeyDown={onKeyDown} />
      {open && (
        <ul className="combo-list" id={listId} role="listbox" aria-label={label}>
          {shown.length === 0 && <li className="combo-empty" role="presentation">Nothing matches.</li>}
          {shown.map((option, index) => (
            <li key={option.id} id={`${id}-${index}`} role="option" aria-selected={option.id === value} className={index === active ? "active" : undefined}
              onMouseDown={(event) => { event.preventDefault(); choose(option); }} onMouseEnter={() => setActive(index)}>
              {option.label}{option.detail && <span>{option.detail}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

import { useEffect, useState } from "react";

/** One entry in a row's ⋯ menu. A note is shown in brackets after the label, which is how a greyed-out item says why. */
export type MenuItem = { label: string; onClick: () => void; danger?: boolean; disabled?: boolean; note?: string };

/** The ⋯ at the end of a table row. Rows have no inline actions: everything is in this menu. */
export function RowMenu({ label, items }: { label: string; items: MenuItem[] }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [open]);

  return (
    <>
      <button className={open ? "kebab on" : "kebab"} aria-label={label} aria-haspopup="menu" aria-expanded={open}
        onClick={(e) => { e.stopPropagation(); setOpen(!open); }}>⋯</button>
      {open && (
        <div className="menu rowmenu" role="menu">
          {items.map((item) => (
            <button key={item.label} role="menuitem" className={item.danger ? "bad" : ""} disabled={item.disabled} onClick={item.onClick}>
              {item.label}{item.note && <span className="why"> ({item.note})</span>}
            </button>
          ))}
        </div>
      )}
    </>
  );
}

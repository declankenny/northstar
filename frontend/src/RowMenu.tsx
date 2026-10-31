import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

/** One entry in a row's ⋯ menu. A note is shown in brackets after the label, which is how a greyed-out item says why. */
export type MenuItem = { label: string; onClick: () => void; danger?: boolean; disabled?: boolean; note?: string };

const GAP = 6; // between the button and the menu
const EDGE = 8; // the menu never gets closer than this to the edge of the window

/** The ⋯ at the end of a table row. Rows have no inline actions: everything is in this menu.
 *
 * The menu is drawn over the page, placed from the button's position on screen, so a panel that
 * scrolls or clips its contents can never cut it off. It opens below the button, or above it when
 * there is no room below, and its right edge lines up with the button's. */
export function RowMenu({ label, items }: { label: string; items: MenuItem[] }) {
  const [open, setOpen] = useState(false);
  const [place, setPlace] = useState<{ top: number; left: number } | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    if (!open || !button.current || !menu.current) {
      setPlace(null);
      return;
    }
    const at = button.current.getBoundingClientRect();
    const { offsetHeight: height, offsetWidth: width } = menu.current;
    const fitsBelow = window.innerHeight - at.bottom >= height + GAP + EDGE;
    setPlace({
      top: fitsBelow ? at.bottom + GAP : Math.max(EDGE, at.top - height - GAP),
      left: Math.max(EDGE, Math.min(at.right - width, window.innerWidth - width - EDGE)),
    });
  }, [open]);

  // Any click, Escape, scroll or resize closes it, so it never points at a row that has moved.
  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        button.current?.focus();
      }
    };
    document.addEventListener("click", close);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("click", close);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);

  return (
    <>
      <button ref={button} className={open ? "kebab on" : "kebab"} aria-label={label} aria-haspopup="menu" aria-expanded={open}
        onClick={(e) => { e.stopPropagation(); setOpen(!open); }}>⋯</button>
      {open && createPortal(
        <div ref={menu} className="menu rowmenu" role="menu"
          style={{ top: place?.top ?? 0, left: place?.left ?? 0, visibility: place ? "visible" : "hidden" }}>
          {items.map((item) => (
            <button key={item.label} role="menuitem" className={item.danger ? "bad" : ""} disabled={item.disabled} onClick={item.onClick}>
              {item.label}{item.note && <span className="why"> ({item.note})</span>}
            </button>
          ))}
        </div>,
        document.body,
      )}
    </>
  );
}

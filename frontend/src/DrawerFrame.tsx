import { type ReactNode, useEffect, useRef } from "react";

/** The drawer's frame: heading, an optional strip of tabs, a body, and the foot with Cancel and Apply changes. Focus starts in the
 *  drawer and Escape closes it, unless something on top of it (`escapeCloses` false) has the Escape first. `footLeft` is what the
 *  foot offers besides Cancel and Apply; `overlay` is a dialog that opens over the drawer. */
export function DrawerFrame({ label, heading, tabs, footLeft, onApply, onClose, escapeCloses = true, overlay, children }: {
  label: string; heading: string; tabs?: ReactNode; footLeft: ReactNode; onApply: () => void; onClose: () => void;
  escapeCloses?: boolean; overlay?: ReactNode; children: ReactNode;
}) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { box.current?.focus(); }, []);
  const onKey = (event: React.KeyboardEvent) => {
    if (event.key === "Escape" && escapeCloses) { event.stopPropagation(); onClose(); }
  };
  return (
    <div className="drawer" role="dialog" aria-modal="true" aria-label={label} tabIndex={-1} ref={box} onKeyDown={onKey}>
      <div className="drawer-head"><h2>{heading}</h2><button className="kebab" aria-label="Close" onClick={onClose}>✕</button></div>
      {tabs}
      <div className="drawer-body">{children}</div>
      <div className="drawer-foot">
        {footLeft}
        <span className="grow" />
        <button className="btn ghost" onClick={onClose}>Cancel</button>
        <button className="btn" onClick={onApply}>Apply changes</button>
      </div>
      {overlay}
    </div>
  );
}

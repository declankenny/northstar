import { type AnchorHTMLAttributes, type MouseEvent, useEffect, useSyncExternalStore } from "react";

// A small history router. The address bar and the page are kept in step by three things: navigate()
// changes the address without reloading, Link is an ordinary <a href> that calls navigate() on a plain
// click, and the browser's back and forward buttons are noticed through popstate. A page with unsaved
// work registers a leave guard, and every way of leaving it (a link, back, closing the tab) asks first.

const changed = new Set<() => void>();
const notify = () => changed.forEach((listener) => listener());

let leaveGuard: (() => boolean) | null = null; // returns true when it is fine to leave
let shownPath = typeof window === "undefined" ? "/" : window.location.pathname;

if (typeof window !== "undefined") {
  window.addEventListener("popstate", () => {
    if (leaveGuard && !leaveGuard()) {
      // Back and forward have already moved the address, so put it back. This adds a history entry,
      // which is the price of not being able to cancel the browser's own navigation.
      window.history.pushState(null, "", shownPath);
      return;
    }
    shownPath = window.location.pathname;
    notify();
  });
}

/** Go to another page of the app. Returns false when a leave guard refused. */
export function navigate(to: string): boolean {
  if (to === window.location.pathname + window.location.search) return true;
  if (leaveGuard && !leaveGuard()) return false;
  window.history.pushState(null, "", to);
  shownPath = window.location.pathname;
  notify();
  return true;
}

/** The current address path, re-read whenever the page changes. */
export function usePath(): string {
  return useSyncExternalStore(
    (listener) => {
      changed.add(listener);
      return () => changed.delete(listener);
    },
    () => window.location.pathname,
  );
}

/** While `active`, leaving this page (a link, back, forward, closing or reloading the tab) asks first. */
export function useLeaveGuard(active: boolean, message: string) {
  useEffect(() => {
    if (!active) return;
    leaveGuard = () => window.confirm(message);
    const beforeUnload = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", beforeUnload);
    return () => {
      leaveGuard = null;
      window.removeEventListener("beforeunload", beforeUnload);
    };
  }, [active, message]);
}

/** A link to a page of the app. A plain click changes the page without reloading. Opening it in a new
 *  tab or window, copying the address and middle-click all work, because it is a real link. */
export function Link({ to, onClick, ...rest }: { to: string } & AnchorHTMLAttributes<HTMLAnchorElement>) {
  const click = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event);
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || rest.target) return;
    event.preventDefault();
    navigate(to);
  };
  return <a {...rest} href={to} onClick={click} />;
}

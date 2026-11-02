import { type SetStateAction, useCallback, useEffect, useRef, useState } from "react";

/** One request among several for the same thing. It is `current` until a newer one starts, it is cancelled, or the component goes. */
export type Ticket = { signal: AbortSignal; current: () => boolean };

/**
 * The one rule for asking the server for something that the screen can ask again before the first answer is back:
 * only the newest request counts. `begin()` cancels the one before it (its `signal` aborts the fetch) and returns a ticket,
 * and a caller shows an answer only if `ticket.current()` still holds, which also covers an answer that lands before the
 * abort does. Leaving the screen cancels the last one.
 */
export function useLatest() {
  const last = useRef<AbortController | null>(null);
  useEffect(() => () => last.current?.abort(), []);
  return useCallback((): Ticket => {
    last.current?.abort();
    const controller = new AbortController();
    last.current = controller;
    return { signal: controller.signal, current: () => last.current === controller && !controller.signal.aborted };
  }, []);
}

type State<T> = { data: T | null; error: string | null; loading: boolean };

/**
 * Load something when the inputs in `deps` change. `data` keeps the last answer while the next loads, so changing a range does
 * not blank the screen; `reset` clears it when the inputs change, for a screen about one particular thing. `skip` waits for
 * an input that is not known yet. A cancelled request is never an error. `setData` puts in the answer to a change (the server
 * answers a write with the thing as it now is) and drops any load still on its way, so an older answer cannot undo it.
 */
export function useRequest<T>(
  load: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
  options: { skip?: boolean; reset?: boolean } = {},
) {
  const { skip = false, reset = false } = options;
  const begin = useLatest();
  const [state, setState] = useState<State<T>>({ data: null, error: null, loading: !skip });
  const [round, setRound] = useState(0);

  useEffect(() => {
    if (skip) return;
    const ticket = begin();
    setState((before) => ({ data: reset ? null : before.data, error: null, loading: true }));
    load(ticket.signal).then(
      (data) => { if (ticket.current()) setState({ data, error: null, loading: false }); },
      (e: Error) => { if (ticket.current()) setState((before) => ({ data: before.data, error: e.message, loading: false })); },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `deps` are the caller's inputs; `load` is rebuilt on every render
  }, [...deps, skip, reset, round, begin]);

  const setData = useCallback((next: SetStateAction<T | null>) => {
    begin();
    setState((before) => ({ data: typeof next === "function" ? (next as (value: T | null) => T | null)(before.data) : next, error: null, loading: false }));
  }, [begin]);
  const reload = useCallback(() => setRound((n) => n + 1), []);

  return { ...state, setData, reload };
}

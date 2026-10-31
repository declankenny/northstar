import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { fetchUpdate, RequestError, saveUpdate, type UpdatePage, type UpdateRow } from "./api";
import { dayNumber, formatDate, isoFromDay } from "./dates";
import { Modal } from "./Dialogs";
import { formatCents } from "./money";
import { baselineText, changeFromLast, isTyped, rowState, summarize, valuesForDate } from "./updateLogic";

type Banner = { kind: "ok" | "bad"; text: string };

const LEAVE = "You have amounts that are not saved. Leave this page and lose them?";

function ago(days: number | null): string {
  if (days === null) return "";
  return days === 0 ? "today" : `${days} day${days === 1 ? "" : "s"} ago`;
}

function Change({ row, text }: { row: UpdateRow; text: string }) {
  const state = rowState(row, text);
  if (state.kind === "blank" || state.kind === "invalid") return null;
  const change = changeFromLast(row, state.cents);
  if (!change) return <span className="m">first balance</span>;
  if (change.diff === 0) return <span className="m">no change</span>;
  return <span className={change.good ? "p" : "n"}>{change.diff > 0 ? "+" : "−"}{formatCents(Math.abs(change.diff))}</span>;
}

function RowNote({ row, text, error }: { row: UpdateRow; text: string; error?: string }) {
  if (error) return <div className="ub-msg n" role="alert">{error}</div>;
  const state = rowState(row, text);
  if (row.existing_cents === null) return null;
  if (state.kind === "replace") {
    return <div className="ub-msg w">will replace {formatCents(row.existing_cents)} saved on this date</div>;
  }
  return <div className="ub-msg m">saved on this date</div>;
}

export function UpdateBalances() {
  const [page, setPage] = useState<UpdatePage | null>(null);
  const [values, setValues] = useState<Record<number, string>>({});
  const [errors, setErrors] = useState<Record<number, string>>({});
  const [banner, setBanner] = useState<Banner | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null); // a date waiting for "keep or clear"
  const [saving, setSaving] = useState(false);
  const body = useRef<HTMLDivElement>(null);
  const saveButton = useRef<HTMLButtonElement>(null);
  // What is typed in the date box. A native date box reports a valid date after every keystroke
  // (typing "1" for the month already gives January), so it is acted on only when typing pauses.
  const [draft, setDraft] = useState<string | null>(null);
  const draftTimer = useRef<number | undefined>(undefined);
  const latestRequest = useRef<(date: string) => void>(() => {});

  const rows = page?.rows ?? [];
  const dirty = rows.some((row) => isTyped(row, values[row.id] ?? ""));

  /** Read a date and show it. Nothing is written. With `keep`, rows the user typed in keep their text. */
  const show = async (date: string | undefined, keep: boolean) => {
    try {
      const next = await fetchUpdate(date);
      setValues(valuesForDate(rows, values, next.rows, keep));
      setPage(next);
      setErrors({});
    } catch (e) {
      const message = (e as Error).message;
      if (page) setBanner({ kind: "bad", text: message });
      else setLoadError(message);
    }
  };

  useEffect(() => {
    void show(undefined, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- first load only
  }, []);

  // Leaving with unsaved typing asks first: closing or reloading the tab, and moving to another page.
  useEffect(() => {
    if (!dirty) return;
    const beforeUnload = (event: BeforeUnloadEvent) => event.preventDefault();
    const hashChange = () => {
      if (window.location.hash !== "#/update" && !window.confirm(LEAVE)) window.location.hash = "#/update";
    };
    window.addEventListener("beforeunload", beforeUnload);
    window.addEventListener("hashchange", hashChange);
    return () => {
      window.removeEventListener("beforeunload", beforeUnload);
      window.removeEventListener("hashchange", hashChange);
    };
  }, [dirty]);

  if (loadError) return <p className="empty">Could not load the accounts. {loadError}</p>;
  if (!page) return <p className="empty">Loading…</p>;

  const requestDate = (date: string) => {
    window.clearTimeout(draftTimer.current);
    setDraft(null);
    if (!date || date > page.today || date === page.date) return; // the date box shows page.date again
    setBanner(null);
    if (dirty) setPending(date);
    else void show(date, false);
  };
  latestRequest.current = requestDate;
  const typeDate = (value: string) => {
    setDraft(value);
    window.clearTimeout(draftTimer.current);
    if (value) draftTimer.current = window.setTimeout(() => latestRequest.current(value), 700);
  };
  const step = (days: number) => requestDate(isoFromDay(dayNumber(page.date) + days));

  const type = (id: number, text: string) => {
    setValues({ ...values, [id]: text });
    if (errors[id] !== undefined) {
      const { [id]: _gone, ...rest } = errors;
      setErrors(rest);
    }
    if (banner?.kind === "bad") setBanner(null);
  };

  const discard = () => {
    setValues(Object.fromEntries(rows.map((row) => [row.id, baselineText(row)])));
    setErrors({});
    setBanner(null);
  };

  const save = async () => {
    const amounts: Record<number, string> = {};
    for (const row of rows) if ((values[row.id] ?? "").trim() !== "") amounts[row.id] = values[row.id];
    setSaving(true);
    try {
      const saved = await saveUpdate(page.date, amounts);
      setPage(saved);
      setValues(Object.fromEntries(saved.rows.map((row) => [row.id, baselineText(row)])));
      setErrors({});
      const c = saved.saved!;
      setBanner({ kind: "ok", text: `Saved for ${formatDate(saved.date)}: ${c.added} added, ${c.updated} updated, ${c.unchanged} unchanged.` });
      body.current?.scrollTo({ top: 0 });
    } catch (e) {
      const refused = e as RequestError;
      const byRow = Object.fromEntries(Object.entries(refused.errors ?? {}).map(([id, message]) => [Number(id), message]));
      setErrors(byRow);
      setBanner({ kind: "bad", text: refused.message });
      const first = rows.find((row) => byRow[row.id] !== undefined);
      if (first) {
        const box = body.current?.querySelector<HTMLInputElement>(`input[data-id="${first.id}"]`);
        box?.focus();
        box?.scrollIntoView({ block: "center" });
      }
    } finally {
      setSaving(false);
    }
  };

  // Enter and the arrow keys move between the amount boxes, so a run of statements is typed without the mouse.
  const move = (event: KeyboardEvent<HTMLInputElement>) => {
    const keys = ["Enter", "ArrowDown", "ArrowUp"];
    if (!keys.includes(event.key)) return;
    event.preventDefault();
    const boxes = Array.from(body.current?.querySelectorAll<HTMLInputElement>("input[data-id]") ?? []);
    const at = boxes.indexOf(event.currentTarget);
    if (event.key === "ArrowUp") boxes[at - 1]?.focus();
    else if (boxes[at + 1]) boxes[at + 1].focus();
    else saveButton.current?.focus();
  };

  const summary = summarize(rows, values);
  const groups = [
    { name: "Assets", cls: "Asset", hint: "Enter the balance as the statement shows it" },
    { name: "Liabilities", cls: "Liability", hint: "Enter the amount owed as a positive number" },
  ].map((g) => ({ ...g, rows: rows.filter((r) => r.class_name === g.cls) })).filter((g) => g.rows.length > 0);

  const pendingCount = rows.filter((row) => isTyped(row, values[row.id] ?? "")).length;
  const first = rows[0]?.id;

  return (
    <div className="ub">
      <div className="top">
        <div>
          <div className="eyebrow">{formatDate(page.today).toUpperCase()}</div>
          <h1>Update balances</h1>
        </div>
        <div className="ub-date">
          <label htmlFor="ub-date">As of</label>
          <button className="ub-step" aria-label="Previous day" onClick={() => step(-1)}>‹</button>
          <input id="ub-date" type="date" value={draft ?? page.date} max={page.today}
            onChange={(e) => typeDate(e.target.value)}
            onBlur={() => { if (draft !== null) requestDate(draft); }}
            onKeyDown={(e) => { if (e.key === "Enter" && draft !== null) requestDate(draft); }} />
          <button className="ub-step" aria-label="Next day" disabled={page.date >= page.today} onClick={() => step(1)}>›</button>
          <button className="ub-step" disabled={page.date === page.today} onClick={() => requestDate(page.today)}>Today</button>
        </div>
      </div>

      {banner && <p className={`notice ${banner.kind} ub-banner`} role={banner.kind === "bad" ? "alert" : "status"}>{banner.text}</p>}

      <div className="stack" ref={body}>
        {groups.length === 0 ? (
          <div className="gcard"><p className="empty pad">No open accounts yet. Add one on the Accounts page.</p></div>
        ) : (
          groups.map((g) => (
            <div key={g.cls} className={`gcard ${g.cls.toLowerCase()}`}>
              <div className="gh"><span className="gt">{g.name}</span><span className="m">{g.hint}</span></div>
              <table className="num ub-table">
                <colgroup><col style={{ width: "26%" }} /><col style={{ width: "26%" }} /><col style={{ width: "26%" }} /><col /></colgroup>
                <thead><tr><th>Account</th><th>Last balance</th><th className="r">New balance</th><th className="r">Change</th></tr></thead>
                <tbody>
                  {g.rows.map((row) => {
                    const text = values[row.id] ?? "";
                    const cls = [isTyped(row, text) ? "typed" : "", errors[row.id] !== undefined ? "err" : ""].join(" ");
                    return (
                      <tr key={row.id} className={cls}>
                        <td><div className="ub-name">{row.name}</div><div className="m ub-sub">{row.type_name}</div></td>
                        <td>
                          {row.last_cents === null ? <span className="m">No balances yet</span> : <b>{formatCents(row.last_cents)}</b>}
                          {row.stale && <span className="badge stale">Stale</span>}
                          {row.last_date && <div className="m ub-sub">{formatDate(row.last_date)} · {ago(row.days_since)}</div>}
                        </td>
                        <td className="r">
                          <div className="ub-in">
                            <i>$</i>
                            <input data-id={row.id} className="num" inputMode="decimal" autoComplete="off"
                              aria-label={`New balance for ${row.name}`} aria-invalid={errors[row.id] !== undefined}
                              placeholder={row.class_name === "Asset" ? "balance" : "amount owed"}
                              autoFocus={row.id === first} value={text}
                              onChange={(e) => type(row.id, e.target.value)} onKeyDown={move} />
                          </div>
                          <RowNote row={row} text={text} error={errors[row.id]} />
                        </td>
                        <td className="r"><Change row={row} text={text} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ))
        )}
      </div>

      <div className="ub-foot">
        <div className="ub-status">
          {summary.entered === 0 ? (
            <>Nothing entered for {formatDate(page.date)}. Blank accounts are skipped.</>
          ) : (
            <>
              <b>{summary.entered}</b> of {rows.length} entered
              {summary.added > 0 && <> · {summary.added} new</>}
              {summary.replacing > 0 && <> · <span className="w">{summary.replacing} will replace existing</span></>}
              {summary.same > 0 && <> · {summary.same} already saved, unchanged</>}
              {summary.invalid > 0 && <> · <span className="n">{summary.invalid} not an amount</span></>}
              . Blanks are skipped.
            </>
          )}
        </div>
        {dirty && <button className="ub-discard" onClick={discard}>Discard</button>}
        <button className="btn" ref={saveButton} disabled={!dirty || saving} onClick={() => void save()}>Save balances</button>
      </div>

      {pending && (
        <Modal title="You have unsaved amounts" onClose={() => setPending(null)}>
          <p className="sub">
            You have typed {pendingCount} amount{pendingCount === 1 ? "" : "s"} that {pendingCount === 1 ? "isn't" : "aren't"} saved.
            Moving to {formatDate(pending)}: keep {pendingCount === 1 ? "it" : "them"} in the form, or clear the form and show that date's
            saved balances? Nothing is saved either way.
          </p>
          <div className="foot">
            <button className="btn ghost" onClick={() => setPending(null)}>Cancel</button>
            <button className="btn ghost" onClick={() => { const d = pending; setPending(null); void show(d, false); }}>Clear the form</button>
            <button className="btn" autoFocus onClick={() => { const d = pending; setPending(null); void show(d, true); }}>Keep my values</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

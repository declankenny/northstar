import { type FormEvent, useEffect, useRef, useState } from "react";
import { type BalancePageData, deleteBalance, editBalance, fetchBalance, RequestError } from "./api";
import { AmountReading } from "./AmountReading";
import { deleteConsequence } from "./balanceText";
import { conflictText } from "./conflicts";
import { formatDate } from "./dates";
import { ConfirmDialog, useAction } from "./Dialogs";
import { amountPlaceholder, centsToInput, formatCents } from "./money";
import { goBack, Link, useLeaveGuard } from "./router";
import { accountPath, PATHS } from "./routes";
import { useRequest } from "./useRequest";

const SAVED_FOR = 3000; // milliseconds "Saved" stays beside the buttons

/** One balance, on its own page: its amount and note are edited and the balance is deleted. The date is the balance's name and is not
 *  edited (a balance is the one of an account on a date); the rules and the wording are those of the account page's dialogs. */
export function BalancePage({ id }: { id: number }) {
  // A balance that is gone is not an error to retry: the page says so.
  const loaded = useRequest(
    async (signal) => {
      try { return await fetchBalance(id, signal); } catch (e) { if (e instanceof RequestError && e.status === 404) return "missing" as const; throw e; }
    },
    [id], { reset: true },
  );
  if (loaded.error) return <p className="empty">Could not load this balance. {loaded.error} <Link to={PATHS.balances}>Back to Balances</Link></p>;
  if (loaded.data === "missing") return <p className="empty">That balance no longer exists. <Link to={PATHS.balances}>Back to Balances</Link></p>;
  if (!loaded.data) return <p className="empty">Loading…</p>;
  return <Balance id={id} initial={loaded.data} />;
}

function Balance({ id, initial }: { id: number; initial: BalancePageData }) {
  const [data, setData] = useState(initial);                         // what the page shows beside the form; kept as the server last said
  const { account, balance, reporting } = data;
  const open = account.is_open;
  const typed = (cents: number) => centsToInput(cents, undefined, account.currency);

  // The form keeps its own baseline: the amount and note the person last saw as saved, and the version they were read at.
  const [base, setBase] = useState({ amount: typed(balance.amount_cents), note: balance.note ?? "" });
  const [amount, setAmount] = useState(base.amount);
  const [note, setNote] = useState(base.note);
  const [version, setVersion] = useState(balance.version);
  const [openedAt, setOpenedAt] = useState(balance.amount_cents);    // what the person was looking at, for a conflict message
  const [shown, setShown] = useState<string | null>(null);           // who changed the balance now on show, after Use the current value
  const [saved, setSaved] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [gone, setGone] = useState<string | null>(null);             // the balance was deleted, here or by someone else
  const { busy, error, conflict, run, clear } = useAction();
  const dirty = amount !== base.amount || note !== base.note;
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  useLeaveGuard(dirty && !gone, "You have unsaved changes to this balance. Leave without saving?");

  /** Take the balance as the server now has it. */
  const adopt = (fresh: BalancePageData) => {
    const next = { amount: typed(fresh.balance.amount_cents), note: fresh.balance.note ?? "" };
    setData(fresh); setBase(next); setAmount(next.amount); setNote(next.note); setVersion(fresh.balance.version); setOpenedAt(fresh.balance.amount_cents);
  };
  /** Show who changed it and what it is now in the details, leaving what was typed alone. A balance deleted meanwhile says so. */
  const refreshDetails = () => {
    fetchBalance(id).then(setData, (e: Error) => { if (e instanceof RequestError && e.status === 404) setGone("This balance was deleted by someone else."); });
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setShown(null);
    setSaved(false);
    run(async () => {
      await editBalance(id, { date: balance.as_of_date, amount, note }, version);
      adopt(await fetchBalance(id));
      setSaved(true);
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setSaved(false), SAVED_FOR);
    });
  };

  /** Show the balance as it is now, dropping what was typed, so the person can look at it and decide. */
  const useCurrent = () => {
    if (!conflict || conflict.amount_cents === null) return;
    const next = { amount: typed(conflict.amount_cents), note: conflict.note ?? "" };
    setBase(next); setAmount(next.amount); setNote(next.note);
    setVersion(conflict.version ?? version);
    setOpenedAt(conflict.amount_cents);
    setShown(`Showing the current value, changed by ${conflict.by ?? "someone"}${conflict.on ? ` on ${formatDate(conflict.on)}` : ""}. Your typed values were dropped.`);
    clear();
    refreshDetails();
  };
  useEffect(() => { if (conflict) refreshDetails(); }, [conflict]); // eslint-disable-line react-hooks/exhaustive-deps -- once per refusal

  const deletedBySomeoneElse = conflict?.kind === "deleted";
  const locked = !open || gone !== null || deletedBySomeoneElse;
  const date = formatDate(balance.as_of_date);
  const index = account.balances.findIndex((b) => b.id === id);
  const rate = reporting && (reporting.value === null
    ? <span className="m">No {account.currency.code} rate on or before this date</span>
    : <>{formatCents(reporting.value, { code: reporting.unit, name: reporting.unit, minor_units: reporting.scale })}{reporting.rate_date && ` (at the rate of ${formatDate(reporting.rate_date)})`}</>);

  if (gone !== null) {
    return (
      <div className="acct">
        <div className="crumb"><Link to={PATHS.balances}>Balances</Link> / {account.name} · {date}</div>
        <div className="panels" style={{ marginTop: 22 }}>
          <div className="panel"><p className="notice ok" role="status">{gone} <Link to={PATHS.balances}>Back to Balances</Link></p></div>
        </div>
      </div>
    );
  }

  return (
    <div className="acct">
      <div className="crumb"><Link to={PATHS.balances}>Balances</Link> / {account.name} · {date}</div>
      <div className="top">
        <div>
          <div className="titlerow">
            <h1><Link className="titlelink" to={accountPath(account.id)}>{account.name}</Link></h1>
            <span className="badge plain">{account.type_name} · {account.class_name}</span>
            {!open && <span className="badge plain">Closed</span>}
          </div>
          <div className="sub strong">{date}</div>
        </div>
      </div>

      <div className="panels two" style={{ marginTop: 22 }}>
        <div className="col">
          <form className="panel" onSubmit={submit}>
            <h2>Balance</h2>
            {!open && <p className="notice warn">This account is closed. Reopen it to change its balances.</p>}
            <label>Balance in {account.currency.code}
              <input inputMode="decimal" placeholder={amountPlaceholder(account.currency)} value={amount} disabled={locked}
                onChange={(e) => setAmount(e.target.value)} required />
            </label>
            <AmountReading text={amount !== base.amount ? amount : ""} currency={account.currency} />
            <label>Note (optional)
              <input value={note} maxLength={500} disabled={locked} onChange={(e) => setNote(e.target.value)} />
            </label>
            {error && <p className="notice bad" role="alert">{error}</p>}
            {conflict && (
              <p className="notice bad" role="alert"><b>Nothing was saved.</b> {conflictText(conflict, openedAt)}</p>
            )}
            {shown && !conflict && <p className="sub" role="status">{shown}</p>}
            <div className="btnrow">
              {deletedBySomeoneElse ? (
                <button type="button" className="btn" autoFocus onClick={() => goBack(PATHS.balances)}>Back</button>
              ) : conflict ? (
                <>
                  <button type="button" className="btn" autoFocus onClick={useCurrent}>Use the current value</button>
                  <button type="button" className="btn ghost" onClick={() => goBack(PATHS.balances)}>Cancel</button>
                </>
              ) : (
                <>
                  <button className="btn" disabled={locked || busy || !dirty}>Save</button>
                  <button type="button" className="btn ghost" onClick={() => goBack(PATHS.balances)}>{open ? "Cancel" : "Back"}</button>
                </>
              )}
              <span className="notice ok" role="status">{saved ? "Saved" : ""}</span>
              <span className="spacer" />
              <button type="button" className="btn ghost danger-text" disabled={locked || busy} onClick={() => setDeleting(true)}>Delete…</button>
            </div>
          </form>
        </div>

        <div className="col">
          <div className="panel">
            <h2>Details</h2>
            <dl className="facts-list">
              <dt>Currency</dt><dd>{account.currency.code}</dd>
              {reporting && <><dt>Value in {reporting.unit}</dt><dd>{rate}</dd></>}
              <dt>Entered</dt><dd>by {data.entered_by}, {formatDate(data.entered_on)}</dd>
              <dt>Last changed</dt><dd>by {data.changed_by}, {formatDate(data.changed_on)}</dd>
            </dl>
          </div>
        </div>
      </div>

      {deleting && index >= 0 && (
        <ConfirmDialog title="Delete this balance?" confirmLabel="Delete" danger onClose={() => setDeleting(false)}
          text={deleteConsequence(account.balances, index, account.currency)} onConflict={refreshDetails}
          conflict={{ lead: "Nothing was deleted.", text: (c) => conflictText(c, openedAt) }}
          onConfirm={async () => { await deleteBalance(id, version); setDeleting(false); setGone("The balance was deleted."); }} />
      )}
    </div>
  );
}

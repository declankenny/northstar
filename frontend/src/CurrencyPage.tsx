import { type FormEvent, useState } from "react";
import { addRate, changeCurrency, correctRate, type CurrencyPageData, fetchCurrency, type RateRow } from "./api";
import { dayNumber, formatDate, isoFromDay } from "./dates";
import { Modal, useAction } from "./Dialogs";
import { getLocale } from "./locale";
import { formatRate } from "./money";
import { Link } from "./router";
import { PATHS } from "./routes";
import { useRequest } from "./useRequest";

const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/** The rate's own text as the person would type it: their decimal mark, and no group marks. */
const typed = (rate: string) => rate.replace(".", getLocale().decimal_mark);

/** The admin page of one currency: its state, the date its rates start from, and its rates. Switching it on or off saves at once,
 *  and so does the start date. Adding a rate and correcting one share a dialog. */
export function CurrencyPage({ code }: { code: string }) {
  const { data, error, setData } = useRequest((signal) => fetchCurrency(code, signal), [code]);
  const [dialog, setDialog] = useState<{ rate: RateRow } | "add" | null>(null);
  const [start, setStart] = useState<string | null>(null); // what the date box shows while it is not the stored date
  const [startError, setStartError] = useState<string | null>(null);
  const action = useAction();

  const header = (name: string) => (
    <div className="top">
      <div>
        <div className="eyebrow">Admin &middot; <Link to={PATHS.currencies}>Currencies</Link></div>
        <h1>{code} &middot; {name}</h1>
      </div>
    </div>
  );
  if (error) return <>{header("")}<p className="empty">Could not load this currency. {error}</p></>;
  if (!data) return <p className="empty">Loading…</p>;

  const page: CurrencyPageData = data;
  const shownStart = start ?? page.rates_start ?? page.default_rates_start;
  const first = page.rates.length ? page.rates[page.rates.length - 1] : null;
  const gap = !page.is_system && first && page.rates_start && first.date > page.rates_start ? first : null;
  const accounts = page.open_account_count === 1 ? "1 open account" : `${page.open_account_count} open accounts`;

  const apply = (change: { is_enabled?: boolean; rates_start?: string }) =>
    action.run(async () => {
      setData(await changeCurrency(code, change));
      setStart(null);
      setStartError(null);
    });

  const flip = () => {
    if (!shownStart) return setStartError("Enter the date rates start from.");
    apply({ is_enabled: !page.is_enabled, rates_start: shownStart });
  };

  const editStart = (value: string) => {
    setStart(value);
    if (!value) return setStartError("Enter the date rates start from.");
    setStartError(null);
    if (value !== page.rates_start) apply({ rates_start: value });
  };

  return (
    <>
      {header(page.name)}
      <p className="sub">
        {page.is_system ? "The system currency." : page.is_enabled
          ? `Rates are entered here. Amounts in ${code} are converted to ${page.system_code ?? "the system currency"}.`
          : `${code} is not enabled, so it cannot be chosen for a new account.`}
      </p>

      <div className="cur-facts">
        <div className="cur-fact">
          <div className="k">Enabled</div>
          {page.is_system ? (
            <div className="v"><span className="cur-switch locked on" aria-hidden="true" /> Yes</div>
          ) : (
            <button type="button" className="cur-toggle" role="switch" aria-checked={page.is_enabled} aria-label="Enabled"
              disabled={action.busy} onClick={flip}>
              <span className={page.is_enabled ? "cur-switch on" : "cur-switch"} aria-hidden="true" />
              {page.is_enabled ? "Yes" : "No"}
            </button>
          )}
        </div>
        {!page.is_system && (
          <div className="cur-fact">
            <label className="k" htmlFor="rates-start">Rates start</label>
            <input id="rates-start" type="date" value={shownStart} max={page.today} onChange={(e) => editStart(e.target.value)} />
          </div>
        )}
        <div className="cur-fact"><div className="k">Decimals</div><div className="v">{page.minor_units}</div></div>
        <div className="cur-fact">
          <div className="k">Accounts</div>
          <div className="v">{page.account_count}{page.account_count > 0 && ` (${accounts})`}</div>
        </div>
      </div>

      {action.error && <p className="notice bad" role="alert">{action.error}</p>}
      {startError && <p className="notice bad" role="alert">{startError}</p>}

      <p className="sub">
        {page.is_system
          ? `${code} is the system currency, so it is always enabled and every total is in ${code}. It needs no rates.`
          : page.is_enabled
            ? `Accounts can be created in ${code}. An account's currency is permanent. Switching off stops new accounts using ${code}. `
              + (page.account_count > 0
                ? `The ${page.account_count} existing ${page.account_count === 1 ? "account keeps" : "accounts keep"} working and still need rates.`
                : "")
            : `Switch on to allow new accounts in ${code}. An account's currency is permanent.`}
      </p>

      {page.stale && (
        <p className="notice warn" role="status">
          Last rate was {page.stale.days} days ago ({formatDate(page.stale.last_date)}). Rates are stale after {page.stale.threshold} days.
        </p>
      )}
      {gap && (
        <p className="notice info" role="status">
          Rates start {formatDate(gap.date)}. Nothing from {formatDate(page.rates_start!)} to {formatDate(isoFromDay(dayNumber(gap.date) - 1))},
          so {code} balances before {formatDate(gap.date)} are not in net worth charts.
        </p>
      )}

      {!page.is_system && (
        <>
          <div className="cur-ratehead">
            <h2>Rates</h2>
            {page.can_add_rates && <button className="btn" onClick={() => setDialog("add")}>Add rate</button>}
          </div>
          {!page.can_add_rates ? (
            <p className="sub">Switch on {code} to add rates.</p>
          ) : page.rates.length === 0 ? (
            <p className="sub">No rates yet. Add one so accounts can use {code}.</p>
          ) : (
            <div className="panel tablepanel">
              <table>
                <thead>
                  <tr>
                    <th>Date</th><th className="r">1 {code} = {page.system_code}</th><th>Source</th><th>Last changed</th><th />
                  </tr>
                </thead>
                <tbody>
                  {page.rates.map((r) => (
                    <tr key={r.id}>
                      <td>{formatDate(r.date)}</td>
                      <td className="num r">{formatRate(r.rate)}</td>
                      <td>{capital(r.source)}</td>
                      <td>{formatDate(r.changed)}</td>
                      <td className="r"><button className="btn ghost small" onClick={() => setDialog({ rate: r })}>Correct</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {page.can_add_rates && page.rates.length > 0 && <p className="sub cur-count">A rate cannot be deleted or moved to another date.</p>}
        </>
      )}

      {dialog !== null && (
        <RateDialog page={page} rate={dialog === "add" ? null : dialog.rate} onClose={() => setDialog(null)}
          onSaved={(fresh) => { setData(fresh); setDialog(null); }} />
      )}
    </>
  );
}

/** Add a rate, or correct the one given: its date is shown and cannot change. A correction says what it changes before it is saved. */
function RateDialog(props: { page: CurrencyPageData; rate: RateRow | null; onClose: () => void; onSaved: (page: CurrencyPageData) => void }) {
  const { page, rate } = props;
  const [date, setDate] = useState(page.today);
  const [text, setText] = useState(rate ? typed(rate.rate) : "");
  const { busy, error, run } = useAction();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    run(async () => props.onSaved(rate ? await correctRate(page.code, rate.id, text) : await addRate(page.code, { date, rate: text })));
  };

  return (
    <Modal title={rate ? "Correct rate" : "Add rate"} onClose={props.onClose}>
      <form onSubmit={submit}>
        {rate ? (
          <div className="cur-fixed"><span className="k">Date</span><span>{formatDate(rate.date)}</span></div>
        ) : (
          <label>Date
            <input type="date" value={date} max={page.today} onChange={(e) => setDate(e.target.value)} required />
          </label>
        )}
        <label>Rate
          <span className="cur-rate">
            <span>1 {page.code} =</span>
            <input aria-label={`Rate: 1 ${page.code} in ${page.system_code}`} inputMode="decimal" value={text}
              placeholder={`1${getLocale().decimal_mark}0850`} autoComplete="off" autoFocus onChange={(e) => setText(e.target.value)} required />
            <span>{page.system_code}</span>
          </span>
        </label>
        {rate && (
          <p className="notice info">
            This changes net worth from {formatDate(rate.date)} {rate.until ? `until the next stored rate on ${formatDate(rate.until)}` : "on"}.
          </p>
        )}
        {error && <p className="notice bad" role="alert">{error}</p>}
        <div className="foot">
          <button type="button" className="btn ghost" onClick={props.onClose}>Cancel</button>
          <button className="btn" disabled={busy}>{rate ? "Save" : "Add rate"}</button>
        </div>
      </form>
    </Modal>
  );
}

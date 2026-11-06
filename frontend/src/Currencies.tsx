import { useState } from "react";
import { type CurrencyRow, fetchCurrencies } from "./api";
import { useRequest } from "./useRequest";
import { formatInteger } from "./locale";
import { Link } from "./router";
import { currencyPath } from "./routes";

type Filter = "all" | "use" | "enabled";
const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "use", label: "In use" },
  { id: "enabled", label: "Enabled" },
];

/** Whether a currency matches what was typed: a code that starts with it, or a name that contains it. */
export function matches(currency: CurrencyRow, text: string): boolean {
  const wanted = text.trim().toLowerCase();
  return wanted === "" || currency.code.toLowerCase().startsWith(wanted) || currency.name.toLowerCase().includes(wanted);
}

const shown = (currency: CurrencyRow, filter: Filter) =>
  filter === "all" || (filter === "use" ? currency.account_count > 0 : currency.is_enabled);

/** The admin page listing the currency catalog as it is stored, with how many accounts use each. It is read-only: it does not
 *  know which currency is the system currency. A currency's name opens its page, where it is switched on or off and its rates are kept. */
export function Currencies() {
  const { data, error } = useRequest(fetchCurrencies, []);
  const [text, setText] = useState("");
  const [filter, setFilter] = useState<Filter>("all");

  const all = data?.currencies ?? [];
  const rows = all.filter((c) => shown(c, filter) && matches(c, text));

  return (
    <div className="page">
      <div className="top">
        <div>
          <div className="eyebrow">Admin</div>
          <h1>Currencies</h1>
          <p className="sub">The ISO 4217 catalog. A currency can be used for new accounts when it is enabled.</p>
        </div>
      </div>
      {error && <p className="notice bad" role="alert">{error}</p>}
      {!data && !error && <p className="empty">Loading…</p>}
      {data && (
        <>
          <div className="cur-bar">
            <input aria-label="Search currencies" placeholder="Search by code or name" autoComplete="off" value={text}
              onChange={(e) => setText(e.target.value)} />
            <div className="ranges" role="group" aria-label="Show">
              {FILTERS.map((f) => (
                <button key={f.id} className={filter === f.id ? "on" : ""} aria-pressed={filter === f.id}
                  onClick={() => setFilter(f.id)}>{f.label}</button>
              ))}
            </div>
          </div>
          <div className="panel tablepanel">
            <table>
              <thead>
                <tr><th>Code</th><th>Name</th><th className="r">Decimals</th><th>Enabled</th><th className="r">Accounts</th></tr>
              </thead>
              <tbody>
                {rows.length === 0 ? (
                  <tr><td colSpan={5} className="m">No currency matches.</td></tr>
                ) : rows.map((c) => (
                  <tr key={c.code}>
                    <td className="num cur-code">{c.code}</td>
                    <td><Link to={currencyPath(c.code)}>{c.name}</Link></td>
                    <td className="num r">{c.minor_units}</td>
                    <td>{c.is_enabled ? <span className="cur-yes">Yes</span> : <span className="m">No</span>}</td>
                    <td className="num r">{formatInteger(c.account_count)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="sub cur-count">{formatInteger(rows.length)} of {formatInteger(all.length)} shown</p>
        </>
      )}
    </div>
  );
}

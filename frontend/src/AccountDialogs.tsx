import { type FormEvent, useState } from "react";
import { type AccountOptions, type AccountPage, type BalanceEntry, type NewAccount } from "./api";
import { formatDate } from "./dates";
import { AmountReading } from "./AmountReading";
import { amountPlaceholder } from "./money";
import { Modal, useAction } from "./Dialogs";
import { Link } from "./router";
import { PATHS } from "./routes";
import { formatInteger } from "./locale";

/** Add a balance. The server checks every field, so a refusal shows here and nothing is lost. A balance is changed or deleted on its own page. */
export function BalanceDialog(props: {
  account: AccountPage;
  onSave: (entry: BalanceEntry) => Promise<void>;
  onClose: () => void;
}) {
  const { account } = props;
  const [date, setDate] = useState(account.today);
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const { busy, error, run } = useAction();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    run(() => props.onSave({ date, amount, note }));
  };

  return (
    <Modal title="Add balance" subtitle={account.name} onClose={props.onClose}>
      <form onSubmit={submit}>
        <label>Date
          <input type="date" value={date} max={account.today} onChange={(e) => setDate(e.target.value)} required />
        </label>
        <div className="hint">Not in the future. A date that already has a balance is replaced.</div>
        <label>Balance
          <input inputMode="decimal" placeholder={amountPlaceholder(account.currency)} value={amount} onChange={(e) => setAmount(e.target.value)} required autoFocus />
        </label>
        <AmountReading text={amount} currency={account.currency} />
        <label>Note (optional)
          <input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
        </label>
        {error && <p className="notice bad" role="alert">{error}</p>}
        <div className="foot">
          <button type="button" className="btn ghost" onClick={props.onClose}>Cancel</button>
          <button className="btn" disabled={busy}>Save</button>
        </div>
      </form>
    </Modal>
  );
}

/** Name, type (within the account's class) and notes. The class has its own dialog. */
export function EditAccountDialog(props: {
  account: AccountPage;
  onSave: (change: { name: string; type_id: number; notes: string }) => Promise<void>;
  onClose: () => void;
}) {
  const { account } = props;
  const [name, setName] = useState(account.name);
  const [typeId, setTypeId] = useState(account.type_id);
  const [notes, setNotes] = useState(account.notes ?? "");
  const { busy, error, run } = useAction();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    run(() => props.onSave({ name, type_id: typeId, notes }));
  };

  return (
    <Modal title="Edit account" subtitle={`${account.class_name} account`} onClose={props.onClose}>
      <form onSubmit={submit}>
        <label>Name
          <input value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
        </label>
        <label>Type
          <select value={typeId} onChange={(e) => setTypeId(Number(e.target.value))}>
            {account.types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </label>
        <label>Notes (optional)
          <textarea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
        {error && <p className="notice bad" role="alert">{error}</p>}
        <div className="foot">
          <button type="button" className="btn ghost" onClick={props.onClose}>Cancel</button>
          <button className="btn" disabled={busy}>Save</button>
        </div>
      </form>
    </Modal>
  );
}

/** Moving an account between Asset and Liability rewrites past totals, so this says so first. */
export function ChangeClassDialog(props: {
  account: AccountPage;
  isAdmin: boolean;
  onSave: (typeId: number) => Promise<void>;
  onClose: () => void;
}) {
  const { account } = props;
  const target = account.other_class;
  const [typeId, setTypeId] = useState<number | "">("");
  const { busy, error, run } = useAction();
  const count = account.balance_count;

  return (
    <Modal title="Change class" subtitle={`${account.name}: ${account.class_name} to ${target.name}`} onClose={props.onClose}>
      <p className="sub">
        {count === 0
          ? "This account has no balances, so past net worth does not change."
          : `This account has ${formatInteger(count)} balance${count === 1 ? "" : "s"}, the earliest on ${formatDate(account.earliest_date!)}. Net worth changes from that date onward.`}
      </p>
      {target.types.length === 0 ? (
        <p className="sub">There are no {target.name.toLowerCase()} types yet. {props.isAdmin ? <><Link to={PATHS.types}>Add one on the Account types page</Link> first.</> : "Ask an admin to add one."}</p>
      ) : (
        <form onSubmit={(e) => { e.preventDefault(); if (typeId !== "") run(() => props.onSave(typeId)); }}>
          <label>New type
            <select value={typeId} onChange={(e) => setTypeId(Number(e.target.value))} required autoFocus>
              <option value="" disabled>Choose a {target.name.toLowerCase()} type</option>
              {target.types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </label>
          {error && <p className="notice bad" role="alert">{error}</p>}
          <div className="foot">
            <button type="button" className="btn ghost" onClick={props.onClose}>Cancel</button>
            <button className="btn" disabled={busy || typeId === ""}>Change to {target.name}</button>
          </div>
        </form>
      )}
    </Modal>
  );
}

/** Add an account, and its first balance too when an amount is typed. A blank amount adds the account alone. */
export function AddAccountDialog(props: {
  options: AccountOptions;
  isAdmin: boolean;
  accountClass: "asset" | "liability";
  onSave: (account: NewAccount) => Promise<void>;
  onClose: () => void;
}) {
  const { options, accountClass } = props;
  const cls = options.classes.find((c) => c.name.toLowerCase() === accountClass)!;
  const owed = accountClass === "liability";
  const [name, setName] = useState("");
  const [typeId, setTypeId] = useState<number | "">(cls.types.length === 1 ? cls.types[0].id : "");
  const [notes, setNotes] = useState("");
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState(options.today);
  const [code, setCode] = useState(options.currency?.code ?? "");
  const { busy, error, run } = useAction();
  // A Currency box is offered only when an account can be in a currency other than the system currency.
  const several = options.currencies.length > 1;
  const chosen = options.currencies.find((c) => c.code === code) ?? options.currency;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (typeId === "") return;
    run(() => props.onSave({ account_class: accountClass, name, type_id: typeId, notes, amount, date, ...(several ? { currency: code } : {}) }));
  };

  return (
    <Modal title={`Add ${accountClass} account`} onClose={props.onClose}>
      {options.currency === null ? (
        <div>
          <p className="notice warn" role="alert"><b>Choose the system currency first.</b> Accounts can't be created until it is set, and it can't be changed afterwards.</p>
          <p className="sub">{props.isAdmin ? "An admin sets it on the System properties page." : "Ask an admin to set the system currency."}</p>
          <div className="foot">
            <button type="button" className="btn ghost" onClick={props.onClose}>Close</button>
            {props.isAdmin && <Link className="btn" to={PATHS.properties} onClick={props.onClose}>Open System properties</Link>}
          </div>
        </div>
      ) : cls.types.length === 0 ? (
        <p className="sub">There are no {accountClass} types yet. {props.isAdmin ? <><Link to={PATHS.types}>Add one on the Account types page</Link> first.</> : "Ask an admin to add one."}</p>
      ) : (
        <form onSubmit={submit}>
          <label>Name
            <input value={name} placeholder="e.g. Joint Savings" onChange={(e) => setName(e.target.value)} required autoFocus />
          </label>
          <div className={several ? "two" : undefined}>
            <label>Type
              <select value={typeId} onChange={(e) => setTypeId(Number(e.target.value))} required>
                <option value="" disabled>Choose a type</option>
                {cls.types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
            </label>
            {several && (
              <label>Currency
                <select value={code} onChange={(e) => { setCode(e.target.value); setAmount(""); }}>
                  {options.currencies.map((c, i) => <option key={c.code} value={c.code}>{c.code} · {c.name}{i === 0 ? " (system currency)" : ""}</option>)}
                </select>
              </label>
            )}
          </div>
          <label>Notes (optional)
            <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </label>
          <div className="two">
            <label>{owed ? "Amount owed (optional)" : "Current balance (optional)"}
              <input inputMode="decimal" placeholder={amountPlaceholder(chosen ?? undefined)} value={amount} onChange={(e) => setAmount(e.target.value)} />
            </label>
            <label>As of
              <input type="date" value={date} max={options.today} onChange={(e) => setDate(e.target.value)} />
            </label>
          </div>
          <AmountReading text={amount} currency={chosen ?? undefined} />
          <div className="hint">
            {owed ? "Enter what is owed as a positive number. Leave it blank to add the account without a balance."
              : "Leave the balance blank to add the account without one."} Amounts are in {chosen!.name} ({chosen!.code}).
            {several && props.isAdmin && <> <Link to={PATHS.currencies} onClick={props.onClose}>Need another currency? Enable it and add a rate on the Currencies page.</Link></>}
          </div>
          {error && <p className="notice bad" role="alert">{error}</p>}
          <div className="foot">
            <button type="button" className="btn ghost" onClick={props.onClose}>Cancel</button>
            <button className="btn" disabled={busy || typeId === ""}>Add account</button>
          </div>
        </form>
      )}
    </Modal>
  );
}

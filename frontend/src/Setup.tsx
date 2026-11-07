import { type FormEvent, type ReactNode, useCallback, useEffect, useState } from "react";
import { Brand } from "./Brand";
import { CurrencySearch } from "./CurrencySearch";
import { completeSetup, fetchSetupOptions, fetchSetupState, RequestError, sendSetupToken, type SetupOptions, type SetupState } from "./api";
import { formatDate } from "./dates";
import { formatInteger, setLocale } from "./locale";
import type { Currency } from "./money";
import { PATHS } from "./routes";
import { useRequest } from "./useRequest";

/** Where the finished setup leaves the new administrator's email for the sign-in page to prefill. It holds an email address and never a
 *  password, and it is kept in the browser's session only, not in the address. */
export const SETUP_EMAIL_KEY = "northstar-setup-email";
/** The sign-in page's address after setup, which shows the completion message. */
export const SETUP_COMPLETE_PATH = `${PATHS.login}?setup=complete`;

const EXAMPLE_DATE = "2026-11-07"; // only to show what a date looks like in the chosen format
const SESSION_ENDED = "Your setup session ended. Enter the setup token again. What you typed, except the password, is kept.";

/** What is kept in the page while the setup session ends and starts again. Passwords are never part of it. */
type Draft = { display_name: string; email: string; currency: string; locale: string; timezone: string };

type Screen = "loading" | "token" | "form" | "complete" | "failed";

/** What the page starts with: the screen to show and, for the form, what it offers. A setup session that ended, or setup that was
 *  completed, between the two requests is the answer too, not an error. */
async function load(signal: AbortSignal): Promise<{ state: SetupState; options: SetupOptions | null }> {
  const state = await fetchSetupState(signal);
  if (state !== "form") return { state, options: null };
  try {
    return { state, options: await fetchSetupOptions(signal) };
  } catch (error) {
    if (error instanceof RequestError && error.status === 401) return { state: "token", options: null };
    if (error instanceof RequestError && error.status === 409) return { state: "complete", options: null };
    throw error;
  }
}

const startingDraft = (options: SetupOptions): Draft =>
  ({ display_name: "", email: "", currency: options.currency.value ?? "", locale: options.locale, timezone: options.timezone });

/** The first-run setup page: the token from the container log, then one form for the administrator and the household settings.
 *  It needs no signed-in user, so like the sign-in page it is not part of the app's shell. */
export function Setup() {
  const { data, error, loading } = useRequest(load, []);
  // Where the person's own actions have taken the page since it loaded: the token again, the form, or the end.
  const [moved, setMoved] = useState<{ screen: Screen; options: SetupOptions | null; failure?: string } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [typed, setTyped] = useState<Draft | null>(null);

  const screen: Screen = moved?.screen ?? (data ? data.state : loading ? "loading" : error ? "failed" : "loading");
  const options = moved ? moved.options : data?.options ?? null;
  // Kept across a new setup session, so what was typed is not lost. Only until something is typed does it follow the stored values.
  const draft = typed ?? (options ? startingDraft(options) : null);

  /** Where an answer the current screen cannot handle leaves the page: the session ended (the token again), setup is over (sign in),
   *  or something else broke. */
  const leave = useCallback((failure: unknown) => {
    if (failure instanceof RequestError && failure.status === 401) {
      setNotice(SESSION_ENDED);
      setMoved({ screen: "token", options: null });
    } else if (failure instanceof RequestError && failure.status === 409) {
      setMoved({ screen: "complete", options: null });
    } else {
      setMoved({ screen: "failed", options: null, failure: failure instanceof Error ? failure.message : "Setup could not be loaded." });
    }
  }, []);

  const showForm = useCallback(async () => {
    setMoved({ screen: "form", options: await fetchSetupOptions() });
    setNotice(null);
  }, []);

  let body: ReactNode;
  if (screen === "token") {
    body = <TokenStep notice={notice} onGranted={() => showForm().catch(leave)} onFailure={leave} />;
  } else if (screen === "form" && options && draft) {
    body = <FormStep options={options} draft={draft} onDraft={setTyped} onFailure={leave} />;
  } else if (screen === "complete") {
    body = (
      <>
        <h1>Setup has already been completed</h1>
        <p className="help">Northstar already has an administrator, so there is nothing left to set up here.</p>
        <p><a href={PATHS.login}>Go to sign-in</a></p>
      </>
    );
  } else if (screen === "failed") {
    body = (
      <>
        <h1>Setup could not be loaded</h1>
        <p className="error" role="alert">{moved?.failure ?? error}</p>
        <p><a href={PATHS.setup}>Try again</a></p>
      </>
    );
  } else {
    body = <p className="help">Loading…</p>;
  }

  return (
    <div className="signin-page" role="main">
      <section className={screen === "form" ? "signin wide" : "signin"}>
        <Brand />
        {body}
      </section>
    </div>
  );
}

function TokenStep({ notice, onGranted, onFailure }: { notice: string | null; onGranted: () => void; onFailure: (error: unknown) => void }) {
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await sendSetupToken(token);
      onGranted();
    } catch (failure) {
      if (failure instanceof RequestError && (failure.status === 400 || failure.status === 429)) {
        setError(failure.message); // a wrong token, or too many of them: shown as it is, and the person tries again
        setToken("");
        setBusy(false);
      } else {
        onFailure(failure);
      }
    }
  };

  return (
    <>
      <h1>Welcome to Northstar</h1>
      <p className="help">Enter the setup token from your container log to get started.</p>
      {notice && <p className="notice warn" role="status">{notice}</p>}
      {error && <p className="error" role="alert">{error}</p>}
      <form onSubmit={submit}>
        <div className="field">
          <label htmlFor="setup-token">Setup token</label>
          <input id="setup-token" name="token" value={token} onChange={(event) => setToken(event.target.value)}
            placeholder="Paste your setup token" autoComplete="off" autoCapitalize="off" spellCheck={false} required autoFocus />
        </div>
        <button disabled={busy || !token.trim()}>Continue to setup</button>
      </form>
    </>
  );
}

/** The code of the currency a person typed in the search box: its code, or its name, in any case. Anything else is sent as typed, and the
 *  server says that it is not in the catalog. */
export function currencyCode(text: string, catalog: Currency[]): string {
  const typed = text.trim();
  const lower = typed.toLowerCase();
  return (catalog.find((c) => c.code.toLowerCase() === lower) ?? catalog.find((c) => c.name.toLowerCase() === lower))?.code ?? typed;
}

/** Zone names grouped by their region (America, Europe, ...). Names with no region, such as UTC, go under "Other". The current value is
 *  always listed, so a stored name this list lacks is not silently replaced by the first zone. */
export function zoneGroups(zones: string[], current: string): [string, string[]][] {
  const names = current && !zones.includes(current) ? [current, ...zones] : zones;
  const groups = new Map<string, string[]>();
  for (const zone of names) {
    const region = zone.includes("/") ? zone.slice(0, zone.indexOf("/")) : "Other";
    groups.set(region, [...(groups.get(region) ?? []), zone]);
  }
  return [...groups.entries()].sort(([x], [y]) => (x === "Other" ? 1 : y === "Other" ? -1 : x.localeCompare(y)));
}

function FormStep({ options, draft, onDraft, onFailure }:
  { options: SetupOptions; draft: Draft; onDraft: (draft: Draft) => void; onFailure: (error: unknown) => void }) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [banner, setBanner] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const locked = options.currency.locked;
  const lockedCurrency = options.currencies.find((c) => c.code === options.currency.value);
  const chosenCurrency = options.currencies.find((c) => c.code === currencyCode(draft.currency, options.currencies));
  const locale = options.locales.find((l) => l.tag === draft.locale) ?? null;
  setLocale(locale); // the example under the format choice is written in that format
  const example = locale ? `${formatInteger(1234)}${locale.decimal_mark}56 · ${formatDate(EXAMPLE_DATE)}` : "";
  const set = (change: Partial<Draft>) => onDraft({ ...draft, ...change });

  // After a refusal, take the person to the first field that needs fixing: the list can be long and the banner is at the top.
  useEffect(() => {
    if (Object.keys(errors).length > 0) document.querySelector<HTMLElement>("[aria-invalid='true']")?.focus();
  }, [errors]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBanner(null);
    if (password !== confirm) {
      setErrors({ confirm: "The passwords don't match." });
      return;
    }
    setErrors({});
    setBusy(true);
    try {
      const email = await completeSetup({
        email: draft.email, display_name: draft.display_name, password,
        currency: locked ? null : currencyCode(draft.currency, options.currencies), locale: draft.locale, timezone: draft.timezone,
      });
      try {
        sessionStorage.setItem(SETUP_EMAIL_KEY, email); // a convenience only: sign-in works without it
      } catch {
        /* storage can be blocked */
      }
      window.location.assign(SETUP_COMPLETE_PATH); // nobody is signed in: the person signs in normally
    } catch (failure) {
      setBusy(false);
      if (failure instanceof RequestError && failure.status === 422) {
        setErrors(failure.errors);
        setBanner(Object.keys(failure.errors).length > 0 ? "Check the fields marked below. Nothing was saved." : failure.message);
      } else {
        onFailure(failure); // the session ended, setup was completed elsewhere, or something broke
      }
    }
  };

  const problem = (name: string): ReactNode => errors[name] && <p className="field-error" id={`setup-${name}-error`} role="alert">{errors[name]}</p>;
  const invalid = (name: string) => (errors[name] ? { "aria-invalid": true, "aria-describedby": `setup-${name}-error` } : {});

  return (
    <>
      <h1>Set up Northstar</h1>
      <p className="help">Create your administrator account and choose your household settings.</p>
      {banner && <p className="error" role="alert">{banner}</p>}
      <form onSubmit={submit} noValidate>
        <h2>Your administrator account</h2>
        <div className="setup-row">
          <div className="field">
            <label htmlFor="setup-name">Display name</label>
            <input id="setup-name" name="display_name" value={draft.display_name} onChange={(event) => set({ display_name: event.target.value })}
              autoComplete="name" required autoFocus {...invalid("display_name")} />
            {problem("display_name")}
          </div>
          <div className="field">
            <label htmlFor="setup-email">Email</label>
            <input id="setup-email" name="email" type="email" value={draft.email} onChange={(event) => set({ email: event.target.value })}
              autoComplete="username" required {...invalid("email")} />
            {problem("email")}
          </div>
        </div>
        <div className="field">
          <label htmlFor="setup-password">Password</label>
          <div className="password-row">
            <input id="setup-password" name="password" type={show ? "text" : "password"} value={password}
              onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" required {...invalid("password")} />
            <button type="button" className="quiet" aria-pressed={show} onClick={() => setShow(!show)}>{show ? "Hide" : "Show"}</button>
          </div>
          <p className="help">At least 12 characters.</p>
          {problem("password")}
        </div>
        <div className="field">
          <label htmlFor="setup-confirm">Confirm password</label>
          <input id="setup-confirm" name="confirm" type={show ? "text" : "password"} value={confirm}
            onChange={(event) => setConfirm(event.target.value)} autoComplete="new-password" required {...invalid("confirm")} />
          {problem("confirm")}
        </div>
        <p className="help">This account can manage users and system settings.</p>

        <h2>Household settings</h2>
        <div className="field">
          <label htmlFor="setup-currency">Household reporting currency</label>
          {locked ? (
            <input id="setup-currency" value={lockedCurrency ? `${lockedCurrency.code} · ${lockedCurrency.name}` : options.currency.value ?? ""} readOnly />
          ) : (
            <>
              <CurrencySearch id="setup-currency" catalog={options.currencies} value={draft.currency}
                onChange={(text) => set({ currency: text })} invalid={invalid("currency")} />
              {chosenCurrency && <p className="help">{chosenCurrency.code} · {chosenCurrency.name}</p>}
            </>
          )}
          <p className="help">Used for household totals. Individual accounts can use other currencies.</p>
          <p className="warning">{locked ? "Already set. It cannot be changed." : "Choose carefully. This cannot be changed after setup."}</p>
          {problem("currency")}
        </div>
        <div className="field">
          <label htmlFor="setup-locale">Default number and date format</label>
          <select id="setup-locale" name="locale" value={draft.locale} onChange={(event) => set({ locale: event.target.value })} {...invalid("locale")}>
            {options.locales.map((l) => <option key={l.tag} value={l.tag}>{l.label}</option>)}
          </select>
          <p className="help" aria-live="polite">{example}</p>
          <p className="help">Used for your account and as the default for new users. Each person can change their own format.</p>
          {problem("locale")}
        </div>
        <div className="field">
          <label htmlFor="setup-timezone">Time zone</label>
          <select id="setup-timezone" name="timezone" value={draft.timezone} onChange={(event) => set({ timezone: event.target.value })} {...invalid("timezone")}>
            {zoneGroups(options.timezones, draft.timezone).map(([group, zones]) => (
              <optgroup key={group} label={group}>
                {zones.map((zone) => <option key={zone} value={zone}>{zone}</option>)}
              </optgroup>
            ))}
          </select>
          <p className="help">Controls today's date and when scheduled jobs run.</p>
          {problem("timezone")}
        </div>
        <button disabled={busy}>Create administrator and finish setup</button>
        <p className="help centered">You'll sign in with your new account when setup is complete.</p>
      </form>
    </>
  );
}

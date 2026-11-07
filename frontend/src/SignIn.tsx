import { type FormEvent, useState } from "react";
import { requestSignIn } from "./api";
import { Brand } from "./Brand";
import { SETUP_EMAIL_KEY } from "./Setup";

/** The email the setup page left for this visit, read once and then forgotten. It is only there right after setup. */
function takeSetupEmail(): string {
  try {
    const email = sessionStorage.getItem(SETUP_EMAIL_KEY) ?? "";
    sessionStorage.removeItem(SETUP_EMAIL_KEY);
    return email;
  } catch {
    return ""; // storage can be blocked: the person just types it
  }
}

/** The sign-in page. The server decides where to go next (it checks the `next` address), and the page goes there with a
 *  full load, so the app starts afresh with the new session. Right after first-run setup it says so and starts with the new
 *  administrator's email filled in, and never a password. */
export function SignIn() {
  const justSetUp = new URLSearchParams(window.location.search).get("setup") === "complete";
  const [prefilled] = useState(() => (justSetUp ? takeSetupEmail() : ""));
  const [email, setEmail] = useState(prefilled);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const next = new URLSearchParams(window.location.search).get("next") ?? "/";
      window.location.assign(await requestSignIn(email, password, next));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Sign-in failed.");
      setPassword("");
      setBusy(false);
    }
  };

  return (
    <div className="signin-page" role="main">
      <section className="signin">
        <Brand />
        {justSetUp ? (
          <>
            <h1>Setup complete</h1>
            <p className="help">Your administrator account and household settings are ready.</p>
            <h2>Sign in to Northstar</h2>
          </>
        ) : (
          <h1>Sign in</h1>
        )}
        {error && <p className="error" role="alert">{error}</p>}
        <form onSubmit={submit}>
          <label>Email
            <input name="email" type="email" value={email} onChange={(event) => setEmail(event.target.value)}
              autoComplete="username" required autoFocus={!prefilled} />
          </label>
          <label>Password
            <input name="password" type="password" value={password} onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password" required autoFocus={!!prefilled} />
          </label>
          <button disabled={busy}>Sign in</button>
        </form>
      </section>
    </div>
  );
}

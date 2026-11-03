import { type FormEvent, useState } from "react";
import { requestSignIn } from "./api";
import { Brand } from "./Brand";

/** The sign-in page. The server decides where to go next (it checks the `next` address), and the page goes there with a
 *  full load, so the app starts afresh with the new session. */
export function SignIn() {
  const [email, setEmail] = useState("");
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
        <h1>Sign in</h1>
        {error && <p className="error" role="alert">{error}</p>}
        <form onSubmit={submit}>
          <label>Email
            <input name="email" type="email" value={email} onChange={(event) => setEmail(event.target.value)}
              autoComplete="username" required autoFocus />
          </label>
          <label>Password
            <input name="password" type="password" value={password} onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password" required />
          </label>
          <button disabled={busy}>Sign in</button>
        </form>
      </section>
    </div>
  );
}

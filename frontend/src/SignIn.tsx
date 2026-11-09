import { type FormEvent, useState } from "react";
import { fetchSignInMethods, requestSignIn, type SignInMethods } from "./api";
import { Brand } from "./Brand";
import { SETUP_EMAIL_KEY } from "./Setup";
import { useRequest } from "./useRequest";

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

/** What the page says when the identity provider sends the browser back with a code. The server sends only a code from a fixed
 *  list, never text from the provider, and the page words it. `local` says whether the password is still a way in. */
export function providerMessage(code: string, provider: string | null, local: boolean): string {
  const name = provider ?? "your identity provider";
  const Name = name.charAt(0).toUpperCase() + name.slice(1);
  const retry = local ? "Try again, or use your password." : "Try again.";
  switch (code) {
    case "not_allowed": return "This account can't sign in to Northstar. Ask a Northstar admin for access.";
    case "email_unverified": return `${Name} hasn't confirmed your email address. Verify it there, then try again.`;
    case "provider_unavailable": return `Couldn't reach ${name}. ${retry}`;
    case "invalid_token": return `${Name} sent an answer Northstar couldn't accept. ${retry}`;
    case "expired": return "That sign-in took too long or was already used. Start again.";
    case "cancelled": return `Sign-in with ${name} was cancelled.`;
    case "not_configured": return `Sign-in with ${name} isn't set up.`;
    case "busy": return "Too many sign-ins are in progress. Try again in a moment.";
    case "throttled": return "Too many sign-in attempts. Try again in a few minutes.";
    default: return `Sign-in with ${name} failed. ${retry}`;
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
  // Which ways in are on. Until the server says, only the heading shows, so a page that has password sign-in off never offers
  // a form. If it cannot be asked, the password form is shown: the server refuses whatever is not allowed.
  const { data: asked, error: askFailed } = useRequest(fetchSignInMethods, []);
  const methods: SignInMethods | null = asked ?? (askFailed ? { local: true, oidc: false, provider: null } : null);
  const providerError = new URLSearchParams(window.location.search).get("oidc_error");
  const nextAddress = () => new URLSearchParams(window.location.search).get("next") ?? "/";

  /** The provider's button is a navigation to Northstar's own address, which redirects on to the provider: a form would be
   *  refused by the page's form-action policy. */
  const continueWithProvider = () => {
    window.location.assign(`/api/auth/oidc/login?next=${encodeURIComponent(nextAddress())}`);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      window.location.assign(await requestSignIn(email, password, nextAddress()));
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
        {methods && (error || providerError) && (
          <p className="error" role="alert">{error ?? providerMessage(providerError!, methods.provider, methods.local)}</p>
        )}
        {methods?.oidc && (
          <form className="provider" onSubmit={(event) => { event.preventDefault(); continueWithProvider(); }}>
            <button>{methods.provider ? `Continue with ${methods.provider}` : "Continue with your identity provider"}</button>
          </form>
        )}
        {methods?.oidc && methods.local && <p className="help centered">or use your password</p>}
        {methods?.local && (
          <form onSubmit={submit}>
            <label>Email
              <input name="email" type="email" value={email} onChange={(event) => setEmail(event.target.value)}
                autoComplete="username" required autoFocus={!prefilled && !methods.oidc} />
            </label>
            <label>Password
              <input name="password" type="password" value={password} onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password" required autoFocus={!!prefilled} />
            </label>
            <button disabled={busy}>Sign in</button>
          </form>
        )}
      </section>
    </div>
  );
}

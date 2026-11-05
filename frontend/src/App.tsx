import { useEffect, useState } from "react";
import { Brand } from "./Brand";
import { fetchMe, fetchVersion, signOut, type Theme, updateMe } from "./api";
import { AccountPage } from "./AccountPage";
import { AccountsList } from "./AccountsList";
import { AccountTypes } from "./AccountTypes";
import { Currencies } from "./Currencies";
import { Dashboard } from "./Dashboard";
import { ImportBalances } from "./ImportBalances";
import { Imports } from "./Imports";
import { Profile } from "./Profile";
import { SignIn } from "./SignIn";
import { SystemProperties } from "./SystemProperties";
import { setCurrency } from "./money";
import { Link, usePath } from "./router";
import { accountIdFromPath, importAccountIdFromPath, PATHS, routeFromPath } from "./routes";
import { UpdateBalances } from "./UpdateBalances";
import { useRequest } from "./useRequest";
import { Users } from "./Users";
import { versionLabel } from "./version";

/** Show a theme now, and remember it in the browser so the sign-in page and the first paint match. */
function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem("northstar-theme", theme); // a convenience only: the page works without it
  } catch {
    /* storage can be blocked */
  }
}

function NotFound() {
  return (
    <div className="empty">
      <h1>Page not found</h1>
      <p>There is no page at this address.</p>
      <p><Link to={PATHS.dashboard}>Go to the Dashboard</Link></p>
    </div>
  );
}

/** The sign-in page is the one page that needs no signed-in user, so it must not ask who is signed in (that would send a
 *  signed-out visitor straight back to it). Every other page is the app, with its navigation. */
export function App() {
  return routeFromPath(usePath()) === "login" ? <SignIn /> : <Shell />;
}

function Shell() {
  const path = usePath();
  const route = routeFromPath(path);
  const [signOutError, setSignOutError] = useState<string | null>(null);
  const accountId = accountIdFromPath(path);
  const importId = importAccountIdFromPath(path);
  const { data: version } = useRequest(fetchVersion, []);      // a footer only: the app works without it, so a failure is ignored
  const { data: me, setData: setMe } = useRequest(fetchMe, []);

  // Every amount on every page is in the system currency, so tell the money module before the pages render.
  setCurrency(me?.currency ?? null);

  // The account's theme wins over whatever this browser remembered.
  const theme = me?.theme;
  useEffect(() => {
    if (theme) applyTheme(theme);
  }, [theme]);

  const chooseTheme = async (theme: Theme) => {
    const before = me;
    applyTheme(theme); // show it at once
    setMe((current) => (current ? { ...current, theme } : current));
    try {
      setMe(await updateMe({ theme }));
    } catch (error) {
      if (before) {
        applyTheme(before.theme);
        setMe(before);
      }
      throw error;
    }
  };

  return (
    <div className="app">
      <nav>
        <Brand />
        <Link className={route === "dashboard" ? "active" : ""} to={PATHS.dashboard}>Dashboard</Link>
        <Link className={route === "accounts" || route === "account" ? "active" : ""} to={PATHS.accounts}>Accounts</Link>
        <Link className={route === "update" ? "active" : ""} to={PATHS.update}>Update balances</Link>
        {me?.is_admin && (
          <>
            <div className="group">Admin</div>
            <Link className={route === "types" ? "active" : ""} to={PATHS.types}>Account types</Link>
            <Link className={route === "users" ? "active" : ""} to={PATHS.users}>Users</Link>
            <Link className={route === "imports" ? "active" : ""} to={PATHS.imports}>Imports</Link>
            <Link className={route === "currencies" ? "active" : ""} to={PATHS.currencies}>Currencies</Link>
            <Link className={route === "properties" ? "active" : ""} to={PATHS.properties}>System properties</Link>
          </>
        )}
        <div className="spacer" />
        <Link className={route === "profile" ? "active" : ""} to={PATHS.profile}>{me ? me.display_name : "Profile"}</Link>
        <button className="signout" onClick={() => signOut().catch((error: Error) => setSignOutError(error.message))}>Sign out</button>
        {signOutError && <p className="signout-error" role="alert">{signOutError}</p>}
        <div className="version">{versionLabel(version)}</div>
      </nav>
      <main>
        {route === "dashboard" ? (
          <Dashboard />
        ) : route === "accounts" ? (
          <AccountsList isAdmin={me?.is_admin ?? false} />
        ) : route === "update" ? (
          <UpdateBalances />
        ) : route === "notfound" ? (
          <NotFound />
        ) : route === "account" && accountId !== null ? (
          <AccountPage key={accountId} id={accountId} isAdmin={me?.is_admin ?? false} />
        ) : route === "import" && importId !== null ? (
          <ImportBalances key={importId} id={importId} />
        ) : !me ? null : route === "types" ? (
          me.is_admin ? <AccountTypes /> : <p className="empty">Only admins can manage account types.</p>
        ) : route === "imports" ? (
          me.is_admin ? <Imports /> : <p className="empty">Only admins can see imports.</p>
        ) : route === "currencies" ? (
          me.is_admin ? <Currencies /> : <p className="empty">Only admins can see currencies.</p>
        ) : route === "properties" ? (
          me.is_admin ? <SystemProperties onCurrencyChange={() => fetchMe().then(setMe)} /> : <p className="empty">Only admins can manage system properties.</p>
        ) : route === "profile" ? (
          <Profile me={me} onChange={setMe} onTheme={chooseTheme} />
        ) : me.is_admin ? (
          <Users me={me} onMe={setMe} />
        ) : (
          <p className="empty">Only admins can manage users.</p>
        )}
      </main>
    </div>
  );
}

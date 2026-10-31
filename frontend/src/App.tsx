import { useEffect, useState } from "react";
import { fetchMe, type Me, type Theme, updateMe } from "./api";
import { AccountPage } from "./AccountPage";
import { AccountsList } from "./AccountsList";
import { AccountTypes } from "./AccountTypes";
import { Dashboard } from "./Dashboard";
import { Profile } from "./Profile";
import { Link, usePath } from "./router";
import { accountIdFromPath, PATHS, routeFromPath } from "./routes";
import { UpdateBalances } from "./UpdateBalances";
import { Users } from "./Users";

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

export function App() {
  const path = usePath();
  const route = routeFromPath(path);
  const accountId = accountIdFromPath(path);
  const [me, setMe] = useState<Me | null>(null);

  // The account's theme wins over whatever this browser remembered.
  useEffect(() => {
    fetchMe().then((loaded) => {
      setMe(loaded);
      applyTheme(loaded.theme);
    }, () => {});
  }, []);

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
        <div className="brand">
          <i>★</i> Northstar
        </div>
        <Link className={route === "dashboard" ? "active" : ""} to={PATHS.dashboard}>Dashboard</Link>
        <Link className={route === "accounts" || route === "account" ? "active" : ""} to={PATHS.accounts}>Accounts</Link>
        <Link className={route === "update" ? "active" : ""} to={PATHS.update}>Update balances</Link>
        {me?.is_admin && (
          <>
            <div className="group">Admin</div>
            <Link className={route === "types" ? "active" : ""} to={PATHS.types}>Account types</Link>
            <Link className={route === "users" ? "active" : ""} to={PATHS.users}>Users</Link>
          </>
        )}
        <div className="spacer" />
        <Link className={route === "profile" ? "active" : ""} to={PATHS.profile}>{me ? me.display_name : "Profile"}</Link>
        <form method="post" action="/logout">
          <button className="signout">Sign out</button>
        </form>
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
        ) : !me ? null : route === "types" ? (
          me.is_admin ? <AccountTypes /> : <p className="empty">Only admins can manage account types.</p>
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

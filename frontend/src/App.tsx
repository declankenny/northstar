import { useEffect, useState } from "react";
import { fetchMe, type Me, type Theme, updateMe } from "./api";
import { AccountPage } from "./AccountPage";
import { AccountsList } from "./AccountsList";
import { AccountTypes } from "./AccountTypes";
import { Dashboard } from "./Dashboard";
import { Profile } from "./Profile";
import { accountIdFromHash, routeFromHash } from "./routes";
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

function useRoute() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const onChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return { route: routeFromHash(hash), accountId: accountIdFromHash(hash) };
}

export function App() {
  const { route, accountId } = useRoute();
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
        <a className={route === "dashboard" ? "active" : ""} href="#/">Dashboard</a>
        <a className={route === "accounts" || route === "account" ? "active" : ""} href="#/accounts">Accounts</a>
        <a className={route === "update" ? "active" : ""} href="#/update">Update balances</a>
        {me?.is_admin && (
          <>
            <div className="group">Admin</div>
            <a className={route === "types" ? "active" : ""} href="#/types">Account types</a>
            <a className={route === "users" ? "active" : ""} href="#/users">Users</a>
          </>
        )}
        <div className="spacer" />
        <a className={route === "profile" ? "active" : ""} href="#/profile">{me ? me.display_name : "Profile"}</a>
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
        ) : route === "account" && accountId !== null ? (
          <AccountPage id={accountId} isAdmin={me?.is_admin ?? false} />
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

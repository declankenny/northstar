import { useState } from "react";
import { Dashboard } from "./Dashboard";

type Theme = "light" | "dark";

function useTheme(): [Theme, (theme: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(
    document.documentElement.dataset.theme === "light" ? "light" : "dark",
  );
  const choose = (next: Theme) => {
    document.documentElement.dataset.theme = next;
    setTheme(next);
    try {
      localStorage.setItem("northstar-theme", next); // a convenience only: the page works without it
    } catch {
      /* storage can be blocked */
    }
  };
  return [theme, choose];
}

// The other screens are still the server-rendered pages, so these are ordinary links to them.
export function App() {
  const [theme, setTheme] = useTheme();
  return (
    <div className="app">
      <nav>
        <div className="brand">
          <i>★</i> Northstar
        </div>
        <a className="active" href="/app/">Dashboard</a>
        <a href="/balances/update">Update balances</a>
        <a href="/accounts">Accounts</a>
        <div className="group">Admin</div>
        <a href="/types">Account types</a>
        <div className="spacer" />
        <form method="post" action="/logout">
          <button className="signout">Sign out</button>
        </form>
        <div className="theme" role="group" aria-label="Theme">
          {(["light", "dark"] as const).map((t) => (
            <button key={t} className={theme === t ? "on" : ""} aria-pressed={theme === t} onClick={() => setTheme(t)}>
              {t === "light" ? "Light" : "Dark"}
            </button>
          ))}
        </div>
      </nav>
      <main>
        <Dashboard />
      </main>
    </div>
  );
}

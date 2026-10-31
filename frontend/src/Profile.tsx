import { type FormEvent, useState } from "react";
import { changePassword, type Me, type Theme, updateMe } from "./api";

type Notice = { ok: boolean; text: string } | null;

function Message({ notice }: { notice: Notice }) {
  if (!notice) return null;
  return <p className={notice.ok ? "notice ok" : "notice bad"} role={notice.ok ? "status" : "alert"}>{notice.text}</p>;
}

function NameForm({ me, onChange }: { me: Me; onChange: (me: Me) => void }) {
  const [name, setName] = useState(me.display_name);
  const [notice, setNotice] = useState<Notice>(null);

  const save = (event: FormEvent) => {
    event.preventDefault();
    updateMe({ display_name: name }).then(
      (updated) => {
        onChange(updated);
        setName(updated.display_name);
        setNotice({ ok: true, text: "Saved." });
      },
      (e: Error) => setNotice({ ok: false, text: e.message }),
    );
  };

  return (
    <form className="panel" onSubmit={save}>
      <h2>Profile</h2>
      <label>Email<input value={me.email} readOnly aria-describedby="email-note" /></label>
      <div className="hint" id="email-note">Your email is how you sign in. Ask an admin to change it.</div>
      <label>Display name<input value={name} onChange={(e) => setName(e.target.value)} required /></label>
      <Message notice={notice} />
      <button className="btn" disabled={name.trim() === me.display_name}>Save name</button>
    </form>
  );
}

function ThemeForm({ me, onTheme }: { me: Me; onTheme: (theme: Theme) => Promise<void> }) {
  const [notice, setNotice] = useState<Notice>(null);
  const choose = (theme: Theme) => {
    onTheme(theme).then(
      () => setNotice(null),
      (e: Error) => setNotice({ ok: false, text: e.message }),
    );
  };
  return (
    <div className="panel">
      <h2>Appearance</h2>
      <div className="ranges" role="group" aria-label="Theme">
        {(["light", "dark"] as const).map((t) => (
          <button key={t} className={me.theme === t ? "on" : ""} aria-pressed={me.theme === t} onClick={() => choose(t)}>
            {t === "light" ? "Light" : "Dark"}
          </button>
        ))}
      </div>
      <div className="hint">Saved to your account, so it follows you to other browsers.</div>
      <Message notice={notice} />
    </div>
  );
}

function PasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [notice, setNotice] = useState<Notice>(null);

  const save = (event: FormEvent) => {
    event.preventDefault();
    if (next !== again) {
      setNotice({ ok: false, text: "The two new passwords don't match." });
      return;
    }
    changePassword(current, next).then(
      () => {
        setCurrent("");
        setNext("");
        setAgain("");
        setNotice({ ok: true, text: "Password changed. Your other browsers were signed out." });
      },
      (e: Error) => setNotice({ ok: false, text: e.message }),
    );
  };

  return (
    <form className="panel" onSubmit={save}>
      <h2>Change password</h2>
      <label>Current password
        <input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
      </label>
      <label>New password
        <input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required />
      </label>
      <label>Repeat the new password
        <input type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} required />
      </label>
      <Message notice={notice} />
      <button className="btn">Change password</button>
    </form>
  );
}

export function Profile(props: { me: Me; onChange: (me: Me) => void; onTheme: (theme: Theme) => Promise<void> }) {
  return (
    <div className="page">
      <div className="top">
        <div>
          <div className="eyebrow">Account</div>
          <h1>Profile</h1>
        </div>
      </div>
      <div className="panels two">
        <div className="col">
          <NameForm me={props.me} onChange={props.onChange} />
          <ThemeForm me={props.me} onTheme={props.onTheme} />
        </div>
        <div className="col">
          <PasswordForm />
        </div>
      </div>
    </div>
  );
}

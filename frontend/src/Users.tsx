import { type FormEvent, useEffect, useState } from "react";
import { addUser, deleteUser, fetchUsers, type Me, resetPassword, setAdmin, type UserRow } from "./api";

type Notice = { ok: boolean; text: string } | null;

function AddUserForm({ onAdded }: { onAdded: (user: UserRow) => void }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [admin, setAdminFlag] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    addUser({ email, display_name: name, password, is_admin: admin }).then(
      (user) => {
        onAdded(user);
        setEmail("");
        setName("");
        setPassword("");
        setAdminFlag(false);
        setNotice({ ok: true, text: `Added ${user.email}.` });
      },
      (e: Error) => setNotice({ ok: false, text: e.message }),
    );
  };

  return (
    <form className="panel" onSubmit={submit}>
      <h2>Add a user</h2>
      <div className="formgrid">
        <label>Email
          <input type="email" autoComplete="off" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label>Display name
          <input value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <label>Starting password
          <input type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </label>
      </div>
      <label className="check">
        <input type="checkbox" checked={admin} onChange={(e) => setAdminFlag(e.target.checked)} /> Admin
      </label>
      {notice && <p className={notice.ok ? "notice ok" : "notice bad"} role={notice.ok ? "status" : "alert"}>{notice.text}</p>}
      <button className="btn">Add user</button>
    </form>
  );
}

type RowMode = "none" | "reset" | "delete";

function Row(props: { user: UserRow; isMe: boolean; onChanged: (user: UserRow) => void; onRemoved: (id: number) => void; onNotice: (n: Notice) => void }) {
  const { user, isMe, onChanged, onRemoved, onNotice } = props;
  const [mode, setMode] = useState<RowMode>("none");
  const [password, setPassword] = useState("");

  const fail = (e: Error) => onNotice({ ok: false, text: e.message });

  const toggleAdmin = () =>
    setAdmin(user.id, !user.is_admin).then((updated) => {
      onChanged(updated);
      onNotice({ ok: true, text: `${updated.email} is ${updated.is_admin ? "now an admin" : "no longer an admin"}.` });
    }, fail);

  const reset = (event: FormEvent) => {
    event.preventDefault();
    resetPassword(user.id, password).then(() => {
      setPassword("");
      setMode("none");
      onNotice({ ok: true, text: `Password reset for ${user.email}. They were signed out everywhere.` });
    }, fail);
  };

  const remove = () =>
    deleteUser(user.id).then(() => {
      onRemoved(user.id);
      onNotice({ ok: true, text: `Deleted ${user.email}.` });
    }, fail);

  return (
    <tr>
      <td>{user.display_name}{isMe && <span className="badge you">You</span>}</td>
      <td>{user.email}</td>
      <td>{user.is_admin ? <span className="badge admin">Admin</span> : "User"}</td>
      <td className="num">{user.created_at.slice(0, 10)}</td>
      <td className="actions">
        {isMe ? (
          <span className="m">Use your Profile</span>
        ) : mode === "reset" ? (
          <form className="inline" onSubmit={reset}>
            <input type="password" autoComplete="new-password" placeholder="New password" aria-label={`New password for ${user.email}`}
              value={password} onChange={(e) => setPassword(e.target.value)} required autoFocus />
            <button className="link">Set</button>
            <button type="button" className="link" onClick={() => { setMode("none"); setPassword(""); }}>Cancel</button>
          </form>
        ) : mode === "delete" ? (
          <span className="inline">
            Delete {user.display_name}?
            <button className="link danger" onClick={remove}>Delete</button>
            <button className="link" onClick={() => setMode("none")}>Cancel</button>
          </span>
        ) : (
          <span className="inline">
            <button className="link" onClick={toggleAdmin}>{user.is_admin ? "Remove admin" : "Make admin"}</button>
            <button className="link" onClick={() => setMode("reset")}>Reset password</button>
            <button className="link danger" onClick={() => setMode("delete")}>Delete</button>
          </span>
        )}
      </td>
    </tr>
  );
}

export function Users({ me }: { me: Me }) {
  const [users, setUsers] = useState<UserRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice>(null);

  useEffect(() => {
    fetchUsers().then(setUsers, (e: Error) => setError(e.message));
  }, []);

  const sorted = (list: UserRow[]) => [...list].sort((a, b) => a.email.localeCompare(b.email));

  return (
    <div className="page">
      <div className="top">
        <div>
          <div className="eyebrow">Admin</div>
          <h1>Users</h1>
        </div>
      </div>
      {error && <p className="notice bad" role="alert">{error}</p>}
      {notice && <p className={notice.ok ? "notice ok top-notice" : "notice bad top-notice"} role={notice.ok ? "status" : "alert"}>{notice.text}</p>}
      {users && (
        <div className="panel tablepanel">
          <table>
            <thead>
              <tr><th>Name</th><th>Email</th><th>Role</th><th>Added</th><th /></tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <Row key={user.id} user={user} isMe={user.id === me.id} onNotice={setNotice}
                  onChanged={(updated) => setUsers((list) => list && list.map((u) => (u.id === updated.id ? updated : u)))}
                  onRemoved={(id) => setUsers((list) => list && list.filter((u) => u.id !== id))} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="panels wide">
        <AddUserForm onAdded={(user) => setUsers((list) => sorted([...(list ?? []), user]))} />
      </div>
    </div>
  );
}

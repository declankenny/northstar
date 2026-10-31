import { type FormEvent, useEffect, useState } from "react";
import { addUser, deleteUser, fetchUsers, type Me, resetPassword, type UserRow, updateUser } from "./api";
import { ConfirmDialog, Modal, useAction } from "./Dialogs";
import { RowMenu } from "./RowMenu";

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

/** An admin sets another user's password. The user is signed out everywhere. */
function ResetPasswordDialog(props: { user: UserRow; onDone: () => void; onClose: () => void }) {
  const [password, setPassword] = useState("");
  const { busy, error, run } = useAction();
  const submit = (event: FormEvent) => {
    event.preventDefault();
    run(async () => {
      await resetPassword(props.user.id, password);
      props.onDone();
    });
  };
  return (
    <Modal title="Reset password" subtitle={props.user.email} onClose={props.onClose}>
      <form onSubmit={submit}>
        <label>New password
          <input type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} required autoFocus />
        </label>
        <div className="hint">They are signed out everywhere and use this to sign in again.</div>
        {error && <p className="notice bad" role="alert">{error}</p>}
        <div className="foot">
          <button type="button" className="btn ghost" onClick={props.onClose}>Cancel</button>
          <button className="btn" disabled={busy}>Set password</button>
        </div>
      </form>
    </Modal>
  );
}

/** An admin changes a user's name, email and whether they are an admin, in one save. */
function EditUserDialog(props: {
  user: UserRow;
  isYou: boolean;
  onSave: (change: { email: string; display_name: string; is_admin: boolean }) => Promise<void>;
  onClose: () => void;
}) {
  const { user } = props;
  const [name, setName] = useState(user.display_name);
  const [email, setEmail] = useState(user.email);
  const [admin, setAdminFlag] = useState(user.is_admin);
  const { busy, error, run } = useAction();
  const submit = (event: FormEvent) => {
    event.preventDefault();
    run(() => props.onSave({ email, display_name: name, is_admin: admin }));
  };
  return (
    <Modal title="Edit user" subtitle={user.email} onClose={props.onClose}>
      <form onSubmit={submit}>
        <label>Name
          <input value={name} maxLength={100} onChange={(e) => setName(e.target.value)} required autoFocus />
        </label>
        <label>Email
          <input type="email" autoComplete="off" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <div className="hint">
          {props.isYou
            ? "This is how you sign in. You stay signed in now, but use the new address next time."
            : "They sign in with this email. They stay signed in, so tell them the new address."}
        </div>
        <label className="check">
          <input type="checkbox" checked={admin} disabled={props.isYou && user.is_admin} onChange={(e) => setAdminFlag(e.target.checked)} /> Admin
        </label>
        <div className="hint">
          {props.isYou && user.is_admin ? "You can't remove your own admin. Ask another admin." : "Admins manage users and account types."}
        </div>
        {error && <p className="notice bad" role="alert">{error}</p>}
        <div className="foot">
          <button type="button" className="btn ghost" onClick={props.onClose}>Cancel</button>
          <button className="btn" disabled={busy}>Save</button>
        </div>
      </form>
    </Modal>
  );
}

type Dialog = { kind: "edit"; user: UserRow } | { kind: "reset"; user: UserRow } | { kind: "delete"; user: UserRow };

export function Users({ me, onMe }: { me: Me; onMe: (me: Me) => void }) {
  const [users, setUsers] = useState<UserRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [dialog, setDialog] = useState<Dialog | null>(null);

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
                <tr key={user.id}>
                  <td>{user.display_name}{user.id === me.id && <span className="badge you">You</span>}</td>
                  <td>{user.email}</td>
                  <td>{user.is_admin ? <span className="badge admin">Admin</span> : "User"}</td>
                  <td className="num">{user.created_at.slice(0, 10)}</td>
                  <td className="k">
                    {/* Your own row has only Edit: you change your password on your Profile and can't delete yourself. */}
                    <RowMenu label={`Actions for ${user.email}`} items={[
                      { label: "Edit", onClick: () => setDialog({ kind: "edit", user }) },
                      ...(user.id === me.id ? [] : [
                        { label: "Reset password", onClick: () => setDialog({ kind: "reset", user }) },
                        { label: "Delete", danger: true, onClick: () => setDialog({ kind: "delete", user }) },
                      ]),
                    ]} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="panels wide">
        <AddUserForm onAdded={(user) => setUsers((list) => sorted([...(list ?? []), user]))} />
      </div>

      {dialog?.kind === "edit" && (
        <EditUserDialog user={dialog.user} isYou={dialog.user.id === me.id} onClose={() => setDialog(null)}
          onSave={async (change) => {
            const updated = await updateUser(dialog.user.id, change);
            setUsers((list) => list && sorted(list.map((u) => (u.id === updated.id ? updated : u))));
            if (updated.id === me.id) onMe({ ...me, email: updated.email, display_name: updated.display_name });
            setNotice({ ok: true, text: `Saved ${updated.email}.` });
            setDialog(null);
          }} />
      )}
      {dialog?.kind === "reset" && (
        <ResetPasswordDialog user={dialog.user} onClose={() => setDialog(null)}
          onDone={() => {
            setNotice({ ok: true, text: `Password reset for ${dialog.user.email}. They were signed out everywhere.` });
            setDialog(null);
          }} />
      )}
      {dialog?.kind === "delete" && (
        <ConfirmDialog title={`Delete ${dialog.user.display_name}?`} confirmLabel="Delete user" danger onClose={() => setDialog(null)}
          text={`${dialog.user.email} is removed and signed out at once. This can't be undone.`}
          onConfirm={async () => {
            await deleteUser(dialog.user.id);
            setUsers((list) => list && list.filter((u) => u.id !== dialog.user.id));
            setNotice({ ok: true, text: `Deleted ${dialog.user.email}.` });
            setDialog(null);
          }} />
      )}
    </div>
  );
}

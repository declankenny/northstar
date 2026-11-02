import { fetchImports, type ImportEntry } from "./api";
import { plural } from "./importLogic";
import { Link } from "./router";
import { accountPath } from "./routes";
import { useRequest } from "./useRequest";

function AccountCell({ entry }: { entry: ImportEntry }) {
  if (entry.account_id === null) return <span className="reverted">Unknown account</span>;
  if (entry.account_deleted) return <span className="reverted">(deleted account)</span>;
  return (
    <>
      <Link to={accountPath(entry.account_id)}>{entry.account_name}</Link>
      {!entry.account_open && <span className="badge">Closed</span>}
    </>
  );
}

/** The admin page listing past imports, newest first. */
export function Imports() {
  const { data, error } = useRequest(fetchImports, []);

  return (
    <div className="page">
      <div className="top">
        <div>
          <div className="eyebrow">Admin</div>
          <h1>Imports</h1>
          <p className="sub">Balances imported from CSV files, newest first.</p>
        </div>
      </div>
      {error && <p className="notice bad" role="alert">{error}</p>}
      {data && data.imports.length === 0 && (
        <p className="empty">No imports yet. Balances you import from a CSV file will be listed here.</p>
      )}
      {data && data.imports.length > 0 && (
        <>
          <div className="panel tablepanel">
            <table>
              <thead>
                <tr>
                  <th>Import Date</th><th>Import By</th><th>Account</th><th>File Name</th>
                  <th className="r">Added</th><th className="r">Replaced</th><th>Status</th>
                </tr>
              </thead>
              <tbody>
                {data.imports.map((entry) => (
                  <tr key={entry.id}>
                    <td className="num">{entry.date}</td>
                    <td>{entry.by}</td>
                    <td><AccountCell entry={entry} /></td>
                    <td>{entry.file ?? "Unnamed file"}</td>
                    <td className="num r">{entry.added.toLocaleString("en-US")}</td>
                    <td className="num r">{entry.replaced.toLocaleString("en-US")}</td>
                    <td>{entry.reverted_on !== null && <span className="reverted">Reverted on {entry.reverted_on}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.more && <p className="sub">Showing the newest {plural(data.limit, "import")}. Older ones are not listed.</p>}
        </>
      )}
    </div>
  );
}

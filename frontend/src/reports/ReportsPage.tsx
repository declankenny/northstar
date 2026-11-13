import { useEffect } from "react";
import { navigate, replaceAddress, usePath } from "../router";
import { PATHS, reportKeyFromPath, reportPath } from "../routes";
import { useRequest } from "../useRequest";
import { fetchReports } from "./api";
import { Report } from "./Report";

/** The Reports page: the reports this person may see, and the one the address names. `/reports` alone opens the first in the list; no
 *  report is remembered from the last visit. */
export function ReportsPage({ isAdmin }: { isAdmin: boolean }) {
  const path = usePath();
  const key = reportKeyFromPath(path);
  const list = useRequest((signal) => fetchReports(signal), []);
  const reports = list.data;
  const item = reports?.find((r) => r.key === key) ?? null;
  const first = reports && reports.length > 0 ? reports[0].key : null;

  useEffect(() => {
    if (key === null && first !== null) replaceAddress(reportPath(first));       // no report named: the first one, without a history entry
  }, [key, first]);

  if (list.error) return <p className="empty" role="alert">Could not load the reports. {list.error}</p>;
  if (!reports) return <p className="empty" role="status">Loading…</p>;
  if (reports.length === 0) {
    return (
      <>
        <div className="top"><div><div className="eyebrow">Reports</div><h1>Reports</h1></div></div>
        <div className="empty"><p>There are no reports yet.</p></div>
      </>
    );
  }
  if (key !== null && !item) {
    return (
      <div className="empty">
        <h1>Report not found</h1>
        <p>There is no report at this address, or you may not see it.</p>
        <p><button className="link" onClick={() => navigate(reportPath(reports[0].key))}>Open {reports[0].title}</button> or go to the <a href={PATHS.dashboard}>Dashboard</a>.</p>
      </div>
    );
  }
  if (!item) return <p className="empty" role="status">Loading…</p>;
  return <Report key={item.key} item={item} reports={reports} isAdmin={isAdmin} onPick={(next) => navigate(reportPath(next))} />;
}

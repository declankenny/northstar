import { type DragEvent, type ReactNode, useState } from "react";
import type { ImportOutcome, ImportPolicy, ImportRead, ImportResult, ImportReview } from "./api";
import { formatDate } from "./dates";
import { hiddenSummary, plural, readiness, type Readiness, styleLabel, TARGETS, type Use, USE_LABEL, writeCount, writeSummary } from "./importLogic";
import { formatCents, getCurrency, type Currency } from "./money";
import { formatInteger } from "./locale";

// The four screens of the import, one component each. They show what they are given and report what the person does; the page
// (ImportBalances) owns every choice and every request.

const STEPS = ["Choose file", "Map columns", "Review", "Result"] as const;
export type Step = "file" | "map" | "review" | "result";
const ORDER: Step[] = ["file", "map", "review", "result"];

export function Steps({ step }: { step: Step }) {
  const at = ORDER.indexOf(step);
  return (
    <div className="steps" role="group" aria-label="Steps">
      {STEPS.map((name, index) => (
        <span key={name} className={index === at ? "on" : index < at ? "done" : ""} aria-current={index === at ? "step" : undefined}>
          {index + 1} {name}
        </span>
      ))}
    </div>
  );
}

// -- 1. Choose file --

/** The wizard's own way out, in the same row as its other buttons. Red because it throws the choices away. */
function CancelButton({ onCancel, disabled }: { onCancel: () => void; disabled?: boolean }) {
  return <button className="btn danger" disabled={disabled} onClick={onCancel}>Cancel</button>;
}

export function ChooseFileStep(props: {
  reading: boolean; error: string | null; onPick: () => void; onDropFile: (file: File) => void; onCancel: () => void;
}) {
  const [over, setOver] = useState(false);
  const drop = (event: DragEvent) => {
    event.preventDefault();
    setOver(false);
    const file = event.dataTransfer.files[0];
    if (file) props.onDropFile(file);
  };
  return (
    <div className="imp-body">
      {props.error && <p className="notice bad" role="alert">{props.error}</p>}
      <div className="imp-card">
        <div className={over ? "imp-drop over" : "imp-drop"}
          onDragOver={(event) => { event.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={drop}>
          {props.reading ? (
            <p role="status"><b>Reading the file…</b></p>
          ) : (
            <>
              <p><b>Choose a CSV file</b> or drop it here</p>
              <p className="m">Nothing is saved until you press Import on the last screen.</p>
              <div className="imp-nav centered">
                <CancelButton onCancel={props.onCancel} />
                <button className="btn" onClick={props.onPick}>Choose file…</button>
              </div>
            </>
          )}
        </div>
        <ul className="imp-rules">
          <li>A header row and at least one row of data. Commas, semicolons or tabs.</li>
          <li>UTF-8 text, up to 2 MB and {formatInteger(20000)} rows.</li>
          <li>Only balances are imported, into this account. Amounts are read in this account’s currency.</li>
          <li>The file is read for this import and is not kept.</li>
        </ul>
      </div>
    </div>
  );
}

// -- 2. Map columns --

const AS_READ = "The review shows the dates as they are read.";

export function MapStep(props: {
  fileName: string;
  read: ImportRead;
  uses: Use[];
  onUse: (column: number, use: Use) => void;
  dateFormat: string | null;
  formatChoices: string[];
  onFormat: (format: string | null) => void;
  numberFormat: string | null;
  onNumberFormat: (format: string | null) => void;
  onPick: () => void;
  onBack: () => void;
  onContinue: () => void;
  onCancel: () => void;
}) {
  const { read, uses } = props;
  const ready: Readiness = readiness(uses, read, props.dateFormat, props.numberFormat);
  const delimiter = { ",": "comma", ";": "semicolon", "\t": "tab" }[read.delimiter] ?? "comma";
  return (
    <>
      <div className="imp-body">
        <div className="imp-card">
          <p>
            <b>{props.fileName}</b> · {plural(read.columns.length, "column")} · {plural(read.row_count, "row")} · {delimiter} separated{" "}
            <button className="link" onClick={props.onPick}>Choose another file</button>
          </p>
          <p className="m">Tell Northstar what each column holds. Date and Balance are required.</p>
          <table className="imp-map">
            <thead><tr><th>Column</th><th>First values</th><th>Use as</th></tr></thead>
            <tbody>
              {read.columns.map((column) => {
                const use = uses[column.index];
                return (
                  <tr key={column.index}>
                    <td><b>{column.header.trim() === "" ? `Column ${column.index + 1}` : column.header}</b></td>
                    <td className="imp-samples">{column.samples.length === 0 ? <div>(empty)</div> : column.samples.slice(0, 3).map((value, at) => <div key={at}>{value}</div>)}</td>
                    <td>
                      <div className="imp-use">
                        <select aria-label={`Use of column ${column.header || column.index + 1}`} value={use}
                          onChange={(event) => props.onUse(column.index, event.target.value as Use)}>
                          <option value="ignore">{USE_LABEL.ignore}</option>
                          {TARGETS.map((target) => <option key={target} value={target}>{USE_LABEL[target]}</option>)}
                        </select>
                        {use === "date" && (
                          <>
                            <span className="lbl">in the format</span>
                            <select aria-label="Date format" value={props.dateFormat ?? ""}
                              onChange={(event) => props.onFormat(event.target.value === "" ? null : event.target.value)}>
                              {(props.dateFormat === null || column.date_formats.length !== 1) && (
                                <option value="">{column.date_formats.length === 0 ? "Detect" : "Choose…"}</option>
                              )}
                              {props.formatChoices.map((format) => <option key={format} value={format}>{format}</option>)}
                            </select>
                          </>
                        )}
                        {use === "balance" && (
                          <>
                            <span className="lbl">in the format</span>
                            {read.canonical && column.index === read.suggested.balance && uses[read.suggested.date ?? -1] === "date" ? <span>Plain decimal (Northstar CSV)</span> : (
                              <select aria-label="Number style" value={props.numberFormat ?? ""}
                                onChange={(event) => props.onNumberFormat(event.target.value || null)}>
                                <option value="">{column.number_formats.length ? "Choose…" : "Detect"}</option>
                                {(column.number_formats.length ? column.number_formats : read.number_formats).map(format => (
                                  <option key={format} value={format}>{styleLabel(format, read.currency.minor_units)}</option>
                                ))}
                              </select>
                            )}
                          </>
                        )}
                      </div>
                      {use === "balance" && <div className="imp-fmt">
                        {props.numberFormat && column.number_previews[props.numberFormat] != null
                          ? <span className="ok">✓ {column.samples[0]} reads as {formatCents(column.number_previews[props.numberFormat]!, read.currency)}. The review shows every amount as read.</span>
                          : <span className="warn">{column.number_formats.length > 1
                            ? "These values can be read more than one way. Choose the format they are written in."
                            : "Some values may not fit this currency’s precision. The review lists the problems."}</span>}
                      </div>}
                      {use === "date" && <DateFormatNote column={column} chosen={props.dateFormat} />}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
      <div className="ub-foot">
        <div className="ub-status">{ready.reason ?? "All set."}</div>
        <div className="imp-nav">
          <CancelButton onCancel={props.onCancel} />
          <button className="btn ghost" onClick={props.onBack}>Back</button>
          <button className="btn" disabled={!ready.ready} onClick={props.onContinue}>Continue to review</button>
        </div>
      </div>
    </>
  );
}

function DateFormatNote({ column, chosen }: { column: { date_formats: string[] }; chosen: string | null }) {
  const fits = column.date_formats.length;
  if (fits === 1) return <div className="imp-fmt"><span className="ok">✓ Every value fits this format. {AS_READ}</span></div>;
  if (fits > 1) {
    return (
      <div className="imp-fmt">
        {chosen === null
          ? <span className="warn">These values can be read more than one way. Choose the format they are written in.</span>
          : <span className="ok">✓ Read as {chosen}. {AS_READ}</span>}
      </div>
    );
  }
  return <div className="imp-fmt"><span className="warn">Some values are not dates in a format Northstar reads. The review lists them.</span></div>;
}

// -- 3. Review --

const OUTCOME_LABEL: Record<ImportOutcome, string> = { add: "Add", replace: "Replace", skip: "Skip", unchanged: "Same" };
const PROBLEMS_SHOWN = 100;

export type ReviewState = { data: ImportReview | null; error: string | null; loading: boolean };

export function ReviewStep(props: {
  currency?: Currency;
  fileName: string;
  review: ReviewState;
  policy: ImportPolicy;
  onPolicy: (policy: ImportPolicy) => void;
  stale: { message: string; dates: string[] } | null;
  failure: string | null;
  committing: boolean;
  onBack: () => void;
  onImport: () => void;
  onPick: () => void;
  onCancel: () => void;
}) {
  const { review, stale } = props;
  const data = review.data;
  const counts = data?.counts ?? null;
  const writes = counts ? writeCount(counts) : 0;
  const problems = data && !data.can_commit ? data.errors : [];
  const changed = new Set(stale?.dates ?? []);
  const checking = review.loading;
  const canImport = !!data?.can_commit && !checking && !props.committing && writes > 0;

  let status: ReactNode = "Checking the file…";
  if (review.error) status = "The file could not be checked.";
  else if (problems.length > 0) status = "Problems must be fixed in the file.";
  else if (counts && !checking) status = <>{writeSummary(counts)}. It can be undone from the Imports page.</>;

  return (
    <>
      <div className="imp-body">
        {stale && <p className="notice bad" role="alert">{stale.message} The review below is up to date.</p>}
        {props.failure && <p className="notice bad" role="alert">Nothing was saved. {props.failure}</p>}
        {review.error && <p className="notice bad" role="alert">{review.error}</p>}
        <div className="imp-card fill">
          {problems.length > 0 ? (
            <>
              <p className="notice bad" role="alert">
                The file has {plural(problems.length, "problem")}. Nothing can be imported until {problems.length === 1 ? "it is" : "they are"} fixed
                in the file. Choose the corrected file to check it again.
              </p>
              <ul className="imp-errs">
                {problems.slice(0, PROBLEMS_SHOWN).map((problem, index) => (
                  <li key={index}>{problem.record !== null ? `Record ${problem.record}: ` : ""}{problem.message}</li>
                ))}
              </ul>
              {problems.length > PROBLEMS_SHOWN && <p className="imp-more">and {formatInteger(problems.length - PROBLEMS_SHOWN)} more.</p>}
            </>
          ) : (
            <>
              <p>Nothing has been saved yet. Dates are shown as read, and all balances are treated as {(props.currency ?? getCurrency()).code}.</p>
              {(data?.notes ?? []).map((note) => <p key={note} className="notice warn" role="status">{note}</p>)}
              {counts && (
                <div className="imp-counts" aria-label="What will happen">
                  <div><b>{formatInteger(counts.add)}</b><small>will be added</small></div>
                  <div><b>{formatInteger(counts.replace)}</b><small>will replace a balance</small></div>
                  <div><b>{formatInteger(counts.unchanged)}</b><small>already the same</small></div>
                  <div><b>{formatInteger(counts.skip)}</b><small>left alone (skipped)</small></div>
                </div>
              )}
              <fieldset className="imp-policy">
                <legend>Dates that already have a balance</legend>
                <label>
                  <input type="radio" name="policy" checked={props.policy === "skip"} onChange={() => props.onPolicy("skip")} />
                  Skip them: keep what is there (recommended)
                </label>
                <label>
                  <input type="radio" name="policy" checked={props.policy === "replace"} onChange={() => props.onPolicy("replace")} />
                  Replace them with the file's amount (old and new shown below)
                </label>
              </fieldset>
              {checking && !data && <p role="status" className="m">Checking the file…</p>}
              {data && (
                <div className="imp-list" tabIndex={0} aria-label="Changes">
                  <table>
                    <thead><tr><th>Date</th><th>What happens</th><th className="r">In the account now</th><th className="r">In the file</th></tr></thead>
                    <tbody>
                      {data.rows.map((row) => (
                        <tr key={row.record}>
                          <td>{formatDate(row.date)}</td>
                          <td>
                            <span className={`tag ${row.outcome}`}>{OUTCOME_LABEL[row.outcome]}</span>
                            {row.outcome === "skip" && <span className="m"> differs</span>}
                            {changed.has(row.date) && <span className="tag chg">changed</span>}
                          </td>
                          <td className="r">{row.old_cents === null ? "–" : formatCents(row.old_cents, props.currency)}</td>
                          <td className="r">{formatCents(row.amount_cents, props.currency)}{row.note && <div className="m">{row.note}</div>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {data && (data.rows.length === 0 ? <p className="imp-more">No dates would change.</p> : (
                <p className="imp-more">
                  Showing the newest 200 changes of each kind.{hiddenSummary(data.hidden) !== "" && <> Also: {hiddenSummary(data.hidden)}.</>} All of the
                  additions and replacements will be imported.
                </p>
              ))}
            </>
          )}
        </div>
      </div>
      <div className="ub-foot">
        <div className="ub-status">{status}</div>
        <div className="imp-nav">
          <CancelButton onCancel={props.onCancel} disabled={props.committing} />
          <button className="btn ghost" onClick={props.onBack} disabled={props.committing}>Back</button>
          {problems.length > 0
            ? <button className="btn" onClick={props.onPick}>Choose corrected file…</button>
            : <button className="btn" disabled={!canImport} onClick={props.onImport}>{props.committing ? "Importing…" : `Import ${plural(writes, "balance")}`}</button>}
        </div>
      </div>
    </>
  );
}

// -- 4. Result --

export function ResultStep(props: { fileName: string; result: ImportResult; onExit: () => void; onAnother: () => void }) {
  const { result } = props;
  return (
    <div className="imp-body">
      <div className="imp-card">
        <p className="notice ok" role="status">Imported from {props.fileName}.</p>
        <div className="imp-counts" aria-label="What was imported">
          <div><b>{formatInteger(result.added)}</b><small>added</small></div>
          <div><b>{formatInteger(result.updated)}</b><small>updated</small></div>
          <div><b>{formatInteger(result.unchanged)}</b><small>unchanged</small></div>
          <div><b>{formatInteger(result.skipped)}</b><small>skipped</small></div>
        </div>
        <div className="imp-actions">
          <button className="btn" onClick={props.onExit}>Exit</button>
          <button className="btn ghost" onClick={props.onAnother}>Import another file</button>
        </div>
      </div>
    </div>
  );
}

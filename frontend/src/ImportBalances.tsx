import { useEffect, useRef, useState } from "react";
import {
  commitImport, fetchAccount, fetchImportRead, fetchImportReview, type ImportFile, type ImportPolicy, type ImportResult,
  MAX_IMPORT_BYTES, readImportFile, RequestError,
} from "./api";
import { ChooseFileStep, MapStep, ResultStep, ReviewStep, type Step, Steps } from "./ImportSteps";
import { decidedFormat, formatChoices, mappingFrom, setUse, type Use, usesFrom } from "./importLogic";
import { goBack, Link, useLeaveGuard } from "./router";
import { accountPath, PATHS } from "./routes";
import { useRequest } from "./useRequest";

const LEAVE = "Leave this page? The file you chose and your choices will be lost. Nothing has been imported.";
const TOO_BIG = "That file is larger than 2 MB. Split it and import the parts one at a time.";

/**
 * Import balances from a CSV file into one account: choose the file, map its columns, review what would happen, import.
 * Every choice lives here, in memory. The server keeps nothing between the steps, so each request sends the file again, and
 * nothing is written until Import is pressed on the review.
 */
export function ImportBalances({ id }: { id: number }) {
  const account = useRequest((signal) => fetchAccount(id, signal), [id], { reset: true });
  const [step, setStep] = useState<Step>("file");
  const [file, setFile] = useState<ImportFile | null>(null);
  const [reading, setReading] = useState(false);              // the browser is reading the file into memory
  const [fileError, setFileError] = useState<string | null>(null);
  const [changedUses, setChangedUses] = useState<Use[] | null>(null);       // null until the person changes a column's use
  const [chosenFormat, setChosenFormat] = useState<string | null>(null);    // null until the person chooses one
  const [chosenNumberFormat, setChosenNumberFormat] = useState<string | null>(null);
  const [policy, setPolicy] = useState<ImportPolicy>("skip");
  const [committing, setCommitting] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);              // the import was refused for some other reason
  const [stale, setStale] = useState<{ message: string; dates: string[] } | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const picker = useRef<HTMLInputElement>(null);

  // The file's columns, read once for each file. The review follows from the file and every choice.
  const read = useRequest((signal) => fetchImportRead(id, file!, signal), [id, file], { skip: file === null, reset: true });

  const columns = read.data?.columns ?? [];
  const uses = changedUses ?? (read.data ? usesFrom(read.data.suggested, columns.length) : []);
  const mapping = mappingFrom(uses);
  const dateColumn = mapping.date === null ? undefined : columns[mapping.date];
  const dateFormat = chosenFormat ?? decidedFormat(dateColumn);
  const balanceColumn = mapping.balance === null ? undefined : columns[mapping.balance];
  const numberFormat = chosenNumberFormat ?? (balanceColumn?.number_formats.length === 1 ? balanceColumn.number_formats[0] : null);
  const settings = file && read.data ? { file, mapping, dateFormat, numberFormat, policy } : null;

  const review = useRequest(
    (signal) => fetchImportReview(id, settings!, signal),
    [id, file, JSON.stringify(mapping), dateFormat, numberFormat, policy],
    { skip: step !== "review" || settings === null, reset: true },
  );

  // Leaving with a file chosen and nothing imported yet asks first.
  useLeaveGuard(file !== null && step !== "result", LEAVE);

  // The first answer for a file moves on from the file screen. Going back to it later does not move on again.
  useEffect(() => {
    if (read.data) setStep((current) => (current === "file" ? "map" : current));
  }, [read.data]);

  const choose = async (picked: File) => {
    // Choosing a file, whether it works or not, starts again from the first step.
    setFile(null);
    setStep("file");
    setChangedUses(null);
    setChosenFormat(null);
    setChosenNumberFormat(null);
    setPolicy("skip");
    setStale(null);
    setFailure(null);
    setResult(null);
    setFileError(null);
    if (picked.size > MAX_IMPORT_BYTES) {
      setFileError(TOO_BIG);
      return;
    }
    setReading(true);
    try {
      setFile(await readImportFile(picked));
    } catch (e) {
      setFileError((e as Error).message);
    } finally {
      setReading(false);
    }
  };

  const importNow = async () => {
    if (!settings || !review.data?.reviewed) return;
    setCommitting(true);
    setFailure(null);
    setStale(null);
    try {
      setResult(await commitImport(id, settings, review.data.reviewed));
      setStep("result");
    } catch (e) {
      const refused = e as RequestError;
      if (refused.status === 409) {
        setStale({ message: refused.message, dates: refused.dates }); // the account moved on: look at it again
        review.reload();
      } else {
        setFailure(refused.message);
      }
    } finally {
      setCommitting(false);
    }
  };

  const name = account.data?.name ?? "";
  // Cancel and Exit both do what the browser's Back button does (asking first while there is something to lose), and fall back to
  // the account when the page was not opened from another page of the app.
  const leave = () => { goBack(accountPath(id)); };
  const back = <Link className="btn" to={accountPath(id)}>Back to {name || "the account"}</Link>;

  let body;
  if (account.error) {
    body = <p className="empty">Could not load this account. {account.error} <Link to={PATHS.accounts}>Back to Accounts</Link></p>;
  } else if (!account.data) {
    body = <p className="empty">Loading…</p>;
  } else if (!account.data.is_open) {
    body = <p className="empty">This account is closed. Reopen it to import balances. {back}</p>;
  } else if (step === "map" && read.data && file) {
    body = (
      <MapStep fileName={file.name} read={read.data} uses={uses} dateFormat={dateFormat}
        formatChoices={formatChoices(dateColumn, read.data.date_formats)} numberFormat={numberFormat} onNumberFormat={setChosenNumberFormat}
        onUse={(column, use) => {
          setChangedUses(setUse(uses, column, use));
          if (use === "balance" || uses[column] === "balance") setChosenNumberFormat(null);
          if (use === "date" || uses[column] === "date") setChosenFormat(null);      // another column, another format
        }}
        onFormat={setChosenFormat} onPick={() => picker.current?.click()} onBack={() => setStep("file")}
        onContinue={() => { setStale(null); setFailure(null); setStep("review"); }} onCancel={leave} />
    );
  } else if (step === "review" && file) {
    body = (
      <ReviewStep currency={read.data?.currency} fileName={file.name} review={review} policy={policy} onPolicy={setPolicy} stale={stale} failure={failure}
        committing={committing} onBack={() => setStep("map")} onImport={() => void importNow()} onPick={() => picker.current?.click()}
        onCancel={leave} />
    );
  } else if (step === "result" && file && result) {
    body = (
      <ResultStep fileName={file.name} result={result} onExit={leave}
        onAnother={() => { setFile(null); setStep("file"); setResult(null); setChangedUses(null); setChosenFormat(null); setChosenNumberFormat(null); setPolicy("skip"); }} />
    );
  } else {
    body = (
      <ChooseFileStep reading={reading || (file !== null && read.loading)} error={fileError ?? read.error}
        onPick={() => picker.current?.click()} onDropFile={(dropped) => void choose(dropped)} onCancel={leave} />
    );
  }

  return (
    <div className="imp">
      <div className="crumb">
        <Link to={PATHS.accounts}>Accounts</Link> / <Link to={accountPath(id)}>{name || "Account"}</Link> / Import CSV
      </div>
      <div className="top">
        <div>
          <div className="eyebrow">Import balances into</div>
          <h1>{name || "…"}</h1>
        </div>
      </div>
      <Steps step={step} />
      {body}
      <input ref={picker} type="file" hidden aria-label="CSV file" accept=".csv,.txt,text/csv,text/plain"
        onChange={(event) => {
          const picked = event.target.files?.[0];
          event.target.value = "";            // so choosing the same file again still counts as a choice
          if (picked) void choose(picked);
        }} />
    </div>
  );
}

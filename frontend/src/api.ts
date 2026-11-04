/** One point of the series: the totals on a date, in integer cents. */
export type Point = { date: string; assets: number; liabilities: number; net_worth: number };

export type Period = "day" | "week" | "month";

export type NetWorthSeries = {
  today: string; // the server's today(), so the page never reads the browser's clock
  start: string; // the dates actually used: the server never starts before the first balance
  end: string;
  period: Period;
  series: Point[];
};

/** Net worth at regular dates. With no start the server begins at the first balance. With an
 * accountId the series covers that one account (its balance is in assets or liabilities by class). */
export async function fetchNetWorth(
  query: { start?: string; period?: Period; accountId?: number } = {},
  signal?: AbortSignal,
): Promise<NetWorthSeries> {
  const params = new URLSearchParams();
  if (query.start) params.set("start", query.start);
  if (query.period) params.set("period", query.period);
  if (query.accountId !== undefined) params.set("account_id", String(query.accountId));
  return (await send<NetWorthSeries>("GET", `/api/networth?${params}`, undefined, signal))!;
}

export type Theme = "light" | "dark";

/** The signed-in user. The email and is_admin are read-only here. */
export type Me = { id: number; email: string; display_name: string; is_admin: boolean; theme: Theme };

/** Go to the sign-in page, which brings the person back to this page afterwards. */
function signIn() {
  window.location.href = `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`;
}

/** Sign in. Resolves to the address to go to next, which the server has checked; a refusal (wrong email or password, or too
 *  many attempts) is an Error whose message is fit to show. */
export async function requestSignIn(email: string, password: string, next: string): Promise<string> {
  return (await send<{ next: string }>("POST", "/api/auth/login", { email, password, next }))!.next;
}

/** End the session on the server, then go to the sign-in page. Throws if the server could not be asked, so the person is not
 *  told they are signed out when they are not. An answer of 401 means the session had already ended. */
export async function signOut(): Promise<void> {
  let response: Response;
  try {
    response = await fetch("/api/auth/logout", { method: "POST" });
  } catch {
    throw new Error("Could not sign out. Check the connection and try again.");
  }
  if (!response.ok && response.status !== 401) throw new Error("Could not sign out. Try again.");
  window.location.assign("/login");
}

/** A refusal from the server. The message is fit to show the user. `errors` maps a row's id to its own
 *  message, for a save that is refused because of particular rows. */
/** A balance that is no longer what the person opened (409 from an edit, a delete or an Update save). `kind` is `changed`, `deleted`,
 *  or `added` (a date that had no balance). The balance is as it is now: `amount_cents` is null once it is gone, and `version` is
 *  what to send next. `by` and `on` say who changed it and on what UTC date. */
export type Conflict = {
  kind: "changed" | "deleted" | "added"; account_id: number; account_name: string; date: string | null; balance_id: number | null;
  version: number | null; amount_cents: number | null; note: string | null; by: string | null; on: string | null;
};

export class RequestError extends Error {
  errors: Record<string, string>;
  status: number;
  dates: string[]; // the dates whose balance changed, when an import is refused because the account moved on (409)
  refusal: Omit<UndoRefusal, "refused"> | null; // why an import cannot be undone (409)
  conflicts: Conflict[]; // the balances that changed since the person opened them (409)
  constructor(message: string, errors: Record<string, string> = {}, status = 0, dates: string[] = [], refusal: RequestError["refusal"] = null,
    conflicts: Conflict[] = []) {
    super(message);
    this.errors = errors;
    this.status = status;
    this.dates = dates;
    this.refusal = refusal;
    this.conflicts = conflicts;
  }
}

/** Send a change and return the JSON answer, or throw an Error whose message is fit to show the user. */
async function send<T>(method: string, url: string, body: unknown, signal?: AbortSignal): Promise<T | null> {
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (response.status === 401) {
    signIn(); // the session ended: sign in again
    throw new Error("You are signed out.");
  }
  if (!response.ok) {
    const answer = await response.json().catch(() => null);
    const detail = answer?.detail;
    throw new RequestError(typeof detail === "string" ? detail : `The server answered ${response.status}`, answer?.errors ?? {},
      response.status, Array.isArray(answer?.dates) ? answer.dates : [],
      typeof answer?.reason === "string" && Array.isArray(answer.blocked)
        ? { message: String(detail), reason: answer.reason, blocked: answer.blocked, more: answer.more ?? 0 } : null,
      Array.isArray(answer?.conflicts) ? answer.conflicts : []);
  }
  return response.status === 204 ? null : response.json();
}

export async function fetchMe(signal?: AbortSignal): Promise<Me> {
  const response = await fetch("/api/me", { signal });
  if (response.status === 401) {
    signIn();
    throw new Error("You are signed out.");
  }
  if (!response.ok) throw new Error(`The server answered ${response.status}`);
  return response.json();
}

/** Change the display name and/or the theme. Only the fields given change. */
export async function updateMe(change: { display_name?: string; theme?: Theme }): Promise<Me> {
  return (await send<Me>("PATCH", "/api/me", change))!;
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await send("POST", "/api/me/password", { current_password: currentPassword, new_password: newPassword });
}

/** One row of the admin Users page. created_at is UTC text. `reactivated` is true only on the answer to adding a user whose
 * email belonged to a deleted user, who is now restored. */
export type UserRow = {
  id: number; email: string; display_name: string; is_admin: boolean; created_at: string; reactivated?: boolean;
};

export async function fetchUsers(signal?: AbortSignal): Promise<UserRow[]> {
  return (await send<UserRow[]>("GET", "/api/users", undefined, signal))!;
}

/** One past import on the admin Imports page. `date` and `reverted_on` are UTC dates; the file is the base name only. */
export type ImportEntry = {
  id: number; date: string; by: string; account_id: number | null; account_name: string | null;
  account_deleted: boolean; account_open: boolean; file: string | null; added: number; replaced: number; reverted_on: string | null;
};
export type ImportRegister = { imports: ImportEntry[]; more: boolean; limit: number };

export async function fetchImports(signal?: AbortSignal): Promise<ImportRegister> {
  return (await send<ImportRegister>("GET", "/api/imports", undefined, signal))!;
}

/** What undoing an import would do, for the confirmation. */
export type UndoPlan = {
  import_id: number; file: string | null; date: string; by: string; account_id: number | null; account_name: string | null;
  delete: number; restore: number;
};
/** Why an import cannot be undone as things are now (409): `changed` lists the dates in the way, the other reasons only the message. */
export type UndoRefusal = {
  refused: true; message: string; reason: "reverted" | "account_closed" | "account_deleted" | "changed";
  blocked: { date: string; why: string }[]; more: number;
};
export type UndoDone = { refused?: false; deleted: number; restored: number; after: ImportRegister };

async function orRefusal<T>(request: Promise<T>): Promise<T | UndoRefusal> {
  try {
    return await request;
  } catch (e) {
    if (e instanceof RequestError && e.status === 409 && e.refusal) return { refused: true, ...e.refusal } as UndoRefusal;
    throw e;
  }
}

export function fetchUndoPlan(importId: number, signal?: AbortSignal): Promise<UndoPlan | UndoRefusal> {
  return orRefusal(send<UndoPlan>("GET", `/api/imports/${importId}/undo`, undefined, signal).then((plan) => plan!));
}

export function undoImport(importId: number): Promise<UndoDone | UndoRefusal> {
  return orRefusal(send<UndoDone>("POST", `/api/imports/${importId}/undo`, {}).then((done) => done!));
}

export async function addUser(user: { email: string; display_name: string; password: string; is_admin: boolean }): Promise<UserRow> {
  return (await send<UserRow>("POST", "/api/users", user))!;
}

export async function updateUser(id: number, change: { email: string; display_name: string; is_admin: boolean }): Promise<UserRow> {
  return (await send<UserRow>("PATCH", `/api/users/${id}`, change))!;
}

export async function resetPassword(id: number, password: string): Promise<void> {
  await send("POST", `/api/users/${id}/password`, { password });
}

export async function deleteUser(id: number): Promise<void> {
  await send("DELETE", `/api/users/${id}`, undefined);
}

/** One balance of an account. as_of_date is a calendar date, YYYY-MM-DD. */
export type BalanceRow = { id: number; as_of_date: string; amount_cents: number; note: string | null; version: number };
export type TypeChoice = { id: number; name: string };

/** Everything the account page shows. Every change below answers with a fresh copy of this. */
export type AccountPage = {
  id: number;
  name: string;
  class_name: "Asset" | "Liability";
  type_id: number;
  type_name: string;
  is_open: boolean;
  notes: string | null;
  stale_after_days: number;
  balance_count: number;
  earliest_date: string | null;
  last_date: string | null;
  last_cents: number | null;
  days_since: number | null;
  stale: boolean;
  balances: BalanceRow[]; // newest first
  types: TypeChoice[]; // what an edit may choose from (the account's own class)
  other_class: { id: number; name: string; types: TypeChoice[] }; // where a class change would move it
  today: string;
};

/** Typed text, sent as typed: the server checks it with the same rules as every other page. */
export type BalanceEntry = { date: string; amount: string; note: string };

export async function fetchAccount(id: number, signal?: AbortSignal): Promise<AccountPage> {
  return (await send<AccountPage>("GET", `/api/accounts/${id}`, undefined, signal))!;
}

export async function editAccount(id: number, change: { name: string; type_id: number; notes: string }): Promise<AccountPage> {
  return (await send<AccountPage>("PATCH", `/api/accounts/${id}`, change))!;
}

export async function changeClass(id: number, typeId: number): Promise<AccountPage> {
  return (await send<AccountPage>("POST", `/api/accounts/${id}/change-class`, { type_id: typeId }))!;
}

export async function closeAccount(id: number): Promise<AccountPage> {
  return (await send<AccountPage>("POST", `/api/accounts/${id}/close`, undefined))!;
}

export async function reopenAccount(id: number): Promise<AccountPage> {
  return (await send<AccountPage>("POST", `/api/accounts/${id}/reopen`, undefined))!;
}

export async function deleteAccount(id: number): Promise<void> {
  await send("DELETE", `/api/accounts/${id}`, undefined);
}

/** A date that already has a balance is edited. */
export async function addBalance(accountId: number, entry: BalanceEntry): Promise<AccountPage> {
  return (await send<AccountPage>("POST", `/api/accounts/${accountId}/balances`, entry))!;
}

/** `version` is the balance's version when the page loaded it. A balance written since is a RequestError whose `conflicts` say so. */
export async function editBalance(balanceId: number, entry: BalanceEntry, version: number): Promise<AccountPage> {
  return (await send<AccountPage>("PATCH", `/api/balances/${balanceId}`, { ...entry, version }))!;
}

export async function deleteBalance(balanceId: number, version: number): Promise<AccountPage> {
  return (await send<AccountPage>("DELETE", `/api/balances/${balanceId}?version=${version}`, undefined))!;
}

/** One row of the Accounts list. last_* are the latest balance, null for an account with none. */
export type ListedAccount = {
  id: number;
  name: string;
  class_name: "Asset" | "Liability";
  type_name: string;
  notes: string | null;
  balance_count: number;
  last_date: string | null;
  last_cents: number | null;
  days_since: number | null;
  stale: boolean;
};

export type ClassTypes = { id: number; name: string; types: TypeChoice[] };

export type AccountList = {
  closed: boolean;
  accounts: ListedAccount[]; // grouped by class, then type, then name
  totals: { assets: number; liabilities: number } | null; // as of today; only for the open list
  classes: ClassTypes[]; // what the Add account dialog offers
  today: string;
};

export type NewAccount = {
  account_class: "asset" | "liability";
  name: string;
  type_id: number;
  notes: string;
  amount: string; // typed text; blank adds the account with no balance
  date: string; // as of; ignored when the amount is blank
};

export async function fetchAccounts(closed: boolean, signal?: AbortSignal): Promise<AccountList> {
  return (await send<AccountList>("GET", `/api/accounts?closed=${closed}`, undefined, signal))!;
}

/** Answers with the open list, which now includes the new account. */
export async function addAccount(account: NewAccount): Promise<AccountList> {
  return (await send<AccountList>("POST", "/api/accounts", account))!;
}

/** One account type. account_count is how many accounts use it, and deleted_account_count how many deleted accounts still do
 * (they keep their type until they can be restored): a type in use by either can't be deleted or change class. */
export type TypeRow = {
  id: number; name: string; class_id: number; class_name: string; stale_after_days: number; account_count: number;
  deleted_account_count: number;
};
/** `default_stale_after_days` is what a new type's form starts at: the server's balance.stale system property. */
export type TypeList = { types: TypeRow[]; classes: { id: number; name: string }[]; default_stale_after_days: number };

export async function fetchTypes(signal?: AbortSignal): Promise<TypeList> {
  return (await send<TypeList>("GET", "/api/types", undefined, signal))!;
}

/** Each of these answers with the whole list as it now is. */
export async function addType(type: { name: string; class_id: number; stale_after_days: number }): Promise<TypeList> {
  return (await send<TypeList>("POST", "/api/types", type))!;
}

export async function editType(id: number, type: { name: string; class_id: number; stale_after_days: number }): Promise<TypeList> {
  return (await send<TypeList>("PATCH", `/api/types/${id}`, type))!;
}

export async function deleteType(id: number): Promise<TypeList> {
  return (await send<TypeList>("DELETE", `/api/types/${id}`, undefined))!;
}

/** One system property. The first segment of its name is the group the page lists it under. `value` is always text, null when unset.
 *  `options` are the allowed values of a Lookup, else empty. */
export type PropertyOption = { value: string; label: string };
export type PropertyRow = {
  name: string; type: "String" | "Integer" | "Lookup"; value: string | null; allow_null: boolean; hint: string;
  read_only: boolean; options: PropertyOption[];
};
export type PropertyList = { properties: PropertyRow[] };

export async function fetchProperties(signal?: AbortSignal): Promise<PropertyList> {
  return (await send<PropertyList>("GET", "/api/system-properties", undefined, signal))!;
}

/** Save one property from the text typed (blank means unset). Answers with the whole list as it now is; a refused value is a
 *  RequestError whose message is fit to show beside the property. */
export async function saveProperty(name: string, value: string): Promise<PropertyList> {
  return (await send<PropertyList>("PUT", `/api/system-properties/${encodeURIComponent(name)}`, { value }))!;
}

/** One open account on the Update balances screen. existing_cents is what is already saved on the chosen date. */
export type UpdateRow = {
  id: number;
  name: string;
  class_name: "Asset" | "Liability";
  type_name: string;
  stale_after_days: number;
  last_date: string | null;
  last_cents: number | null;
  days_since: number | null;
  stale: boolean;
  existing_cents: number | null;
  existing_version: number | null; // the version of that balance, which a save sends back
};

/** The open accounts for one date, grouped by class (assets first). `saved` is set only on the answer to a save. */
export type UpdatePage = {
  date: string;
  today: string;
  rows: UpdateRow[];
  saved: { added: number; updated: number; unchanged: number } | null;
};

/** Reading a date writes nothing. With no date the server uses today. */
export async function fetchUpdate(date?: string, signal?: AbortSignal): Promise<UpdatePage> {
  const query = date ? `?date=${encodeURIComponent(date)}` : "";
  return (await send<UpdatePage>("GET", `/api/balances/update${query}`, undefined, signal))!;
}

/** Amounts are typed text by account id, and `versions` the version each account's balance on the date had when it was loaded
 *  (null for none). A bad amount is a RequestError whose `errors` say which; a balance that changed since is one whose `conflicts`
 *  say which. Either way nothing is saved. */
export async function saveUpdate(date: string, amounts: Record<number, string>, versions: Record<number, number | null>): Promise<UpdatePage> {
  return (await send<UpdatePage>("POST", "/api/balances/update", { date, amounts, versions }))!;
}

/** The version of the running app, for the footer of the navigation. */
export async function fetchVersion(signal?: AbortSignal): Promise<string> {
  const response = await fetch("/api/version", { signal });
  if (response.status === 401) {
    signIn();
    throw new Error("You are signed out.");
  }
  if (!response.ok) throw new Error(`The server answered ${response.status}`);
  return (await response.json()).version;
}

// -- Importing balances from a CSV file --

/** The most the server reads of a file; a bigger one is refused here too, so it is never sent. */
export const MAX_IMPORT_BYTES = 2 * 1024 * 1024;

/** The account's balances as a CSV file. The server answers with an attachment, so the browser saves it and the page stays. */
export function downloadExport(accountId: number): void {
  window.location.assign(`/api/accounts/${accountId}/export`);
}

/** The column for each thing the import needs, by position in the file, or null. */
export type ImportMapping = { date: number | null; balance: number | null; note: number | null; currency: number | null };

export type ImportColumn = {
  index: number;
  header: string;
  samples: string[]; // the first values that are not blank
  date_formats: string[]; // the formats under which every value is a date: one decides it, several need a choice
};

export type ImportRead = {
  delimiter: string;
  row_count: number;
  columns: ImportColumn[];
  suggested: ImportMapping;
  date_formats: string[]; // every format the import reads
  today: string;
};

/** A problem in the file. `record` is its record number (the header is 1), or null when it is about the whole file. */
export type ImportProblem = { record: number | null; column: number | null; message: string };

export type ImportOutcome = "add" | "replace" | "unchanged" | "skip";

export type ImportRow = {
  record: number;
  date: string;
  outcome: ImportOutcome;
  amount_cents: number;
  old_cents: number | null;
  note: string | null;
  old_note: string | null;
  result_note: string | null;
};

/** What the review saw, handed back with the commit so it can refuse if the account has moved on. */
export type ImportReviewed = {
  fingerprint: string;
  expectations: { date: string; balance_id: number | null; version: number | null }[];
};

export type ImportReview = {
  can_commit: boolean;
  errors: ImportProblem[];
  unsupported_currencies: string[];
  date_format: string | null;
  counts: Record<ImportOutcome, number> | null; // complete, whatever is listed
  rows: ImportRow[]; // newest first, at most 200 of each outcome that is not "unchanged"
  hidden: Partial<Record<ImportOutcome, number>>; // how many more of each there are than are listed
  reviewed: ImportReviewed | null;
};

export type ImportResult = { added: number; updated: number; unchanged: number; skipped: number };

export type ImportPolicy = "skip" | "replace";

/** The file as the server takes it: its name and its bytes as base64 text. */
export type ImportFile = { name: string; content: string };

export type ImportSettings = { file: ImportFile; mapping: ImportMapping; dateFormat: string | null; policy: ImportPolicy };

/** Read a file chosen in the browser into memory. It is sent again with every step and kept nowhere on the server. */
export function readImportFile(file: File): Promise<ImportFile> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("The file could not be read. Choose it again."));
    reader.onload = () => {
      const url = String(reader.result);
      resolve({ name: file.name, content: url.slice(url.indexOf(",") + 1) }); // "data:text/csv;base64,<content>"
    };
    reader.readAsDataURL(file);
  });
}

const importUrl = (accountId: number, step: "read" | "review" | "commit") => `/api/accounts/${accountId}/import/${step}`;

const importBody = (settings: ImportSettings) => ({
  content: settings.file.content,
  file_name: settings.file.name,
  mapping: settings.mapping,
  date_format: settings.dateFormat,
  policy: settings.policy,
});

/** The columns of a file, with their first values and the formats they can be read in. Writes nothing. */
export async function fetchImportRead(accountId: number, file: ImportFile, signal?: AbortSignal): Promise<ImportRead> {
  return (await send<ImportRead>("POST", importUrl(accountId, "read"), { content: file.content, file_name: file.name }, signal))!;
}

/** What importing would do. Problems in the file are part of the answer, not a refusal. Writes nothing. */
export async function fetchImportReview(accountId: number, settings: ImportSettings, signal?: AbortSignal): Promise<ImportReview> {
  return (await send<ImportReview>("POST", importUrl(accountId, "review"), importBody(settings), signal))!;
}

/** Write the import. Refused (a RequestError with status 409 and the changed dates) when the account moved on since the review. */
export async function commitImport(accountId: number, settings: ImportSettings, reviewed: ImportReviewed): Promise<ImportResult> {
  return (await send<ImportResult>("POST", importUrl(accountId, "commit"), { ...importBody(settings), reviewed }))!;
}

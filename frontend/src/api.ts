import { fileNameOf, saveFile } from "./download";
import { getLocale, type Locale } from "./locale";
import type { Currency } from "./money";

/** One point of the series: the totals on a date, in integer cents. */
export type Point = { date: string; assets: number; liabilities: number; net_worth: number };

export type Period = "day" | "week" | "month";

export type NetWorthSeries = {
  today: string; // the server's today(), so the page never reads the browser's clock
  start: string; // the dates actually used: the server never starts before the first balance
  end: string;
  period: Period;
  series: Point[];
  /** Set when dates were left out because a currency has no rate for them: where the series now starts (null when no date can be
   *  worked out) and the currencies that lack a rate before then. */
  limited: { starts_on: string | null; currencies: string[] } | null;
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
export type Me = {
  id: number; email: string; display_name: string; is_admin: boolean; theme: Theme;
  has_password: boolean; // false for someone who signs in only through the identity provider
  currency: Currency | null; // the system currency every amount is in; null until an admin sets it
  locale: Locale; // how this person's numbers and dates are shown and typed
};

/** The number and date formats a person can choose, by label, and the one a new user starts with. */
export type LocaleChoices = { locales: { tag: string; label: string }[]; default: string };

export async function fetchLocales(signal?: AbortSignal): Promise<LocaleChoices> {
  const response = await fetch("/api/me/locales", { signal });
  if (response.status === 401) {
    signIn();
    throw new Error("You are signed out.");
  }
  if (!response.ok) throw new Error(`The server answered ${response.status}`);
  return response.json();
}

/** Go to the sign-in page, which brings the person back to this page afterwards. */
function signIn() {
  window.location.href = `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`;
}

/** Sign in. Resolves to the address to go to next, which the server has checked; a refusal (wrong email or password, or too
 *  many attempts) is an Error whose message is fit to show. */
/** Which ways of signing in are on, and the name for the provider's button (null when none was set). Public. */
export type SignInMethods = { local: boolean; oidc: boolean; provider: string | null };

export async function fetchSignInMethods(signal?: AbortSignal): Promise<SignInMethods> {
  const response = await fetch("/api/auth/methods", { signal });
  if (!response.ok) throw new Error(`The server answered ${response.status}`);
  return response.json();
}

export async function requestSignIn(email: string, password: string, next: string): Promise<string> {
  return (await send<{ next: string }>("POST", "/api/auth/login", { email, password, next }))!.next;
}

// -- First-run setup. Nobody is signed in, so a 401 here means the setup session is missing or ended, never "sign in". --

/** Which screen setup shows: the token, the form (a setup session exists), or "complete" once an administrator exists. */
export type SetupState = "token" | "form" | "complete";

/** What the setup form offers and where each choice starts. An existing locked currency comes as it is, to be shown read-only. */
export type SetupOptions = {
  currency: { value: string | null; locked: boolean };
  currencies: Currency[];
  locale: string; // the stored default format's tag
  locales: Locale[]; // whole rows, so the form can show an example in each format
  timezone: string; // the stored zone, UTC when none is set
  timezones: string[];
};

export type SetupForm = {
  email: string; display_name: string; password: string; currency: string | null; locale: string; timezone: string;
};

export async function fetchSetupState(signal?: AbortSignal): Promise<SetupState> {
  return (await send<{ state: SetupState }>("GET", "/api/setup/status", undefined, signal, false))!.state;
}

/** Give the setup token and get a setup session (a cookie the page never sees). A wrong token is a RequestError (400), too many
 *  a 429, and 409 means setup is already complete. */
export async function sendSetupToken(token: string): Promise<void> {
  await send("POST", "/api/setup/token", { token }, undefined, false);
}

/** A RequestError with status 401 means the setup session has ended and the token is needed again. */
export async function fetchSetupOptions(signal?: AbortSignal): Promise<SetupOptions> {
  return (await send<SetupOptions>("GET", "/api/setup/options", undefined, signal, false))!;
}

/** Create the administrator and save the initial settings, or save nothing. Resolves to the administrator's email. A refused field is
 *  a RequestError whose `errors` say which (422), 401 means the setup session ended and 409 that setup was already completed. */
export async function completeSetup(form: SetupForm): Promise<string> {
  return (await send<{ email: string }>("POST", "/api/setup", form, undefined, false))!.email;
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
  kind: "changed" | "deleted" | "added"; account_id: number; account_name: string; currency: Currency; date: string | null; balance_id: number | null;
  version: number | null; amount_cents: number | null; note: string | null; by: string | null; on: string | null;
};

export class RequestError extends Error {
  errors: Record<string, string>;
  status: number;
  dates: string[]; // the dates whose balance changed, when an import is refused because the account moved on (409)
  refusal: Omit<UndoRefusal, "refused"> | null; // why an import cannot be undone (409)
  conflicts: Conflict[]; // the balances that changed since the person opened them (409)
  localeChanged: { tag: string; label: string } | null; // the number and date format the person now has, when theirs changed since the page loaded (409)
  constructor(message: string, errors: Record<string, string> = {}, status = 0, dates: string[] = [], refusal: RequestError["refusal"] = null,
    conflicts: Conflict[] = [], localeChanged: RequestError["localeChanged"] = null) {
    super(message);
    this.errors = errors;
    this.status = status;
    this.dates = dates;
    this.refusal = refusal;
    this.conflicts = conflicts;
    this.localeChanged = localeChanged;
  }
}

/** Send a change and return the JSON answer, or throw an Error whose message is fit to show the user. */
async function send<T>(method: string, url: string, body: unknown, signal?: AbortSignal, signInOn401 = true): Promise<T | null> {
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (response.status === 401 && signInOn401) {
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
      Array.isArray(answer?.conflicts) ? answer.conflicts : [],
      typeof answer?.locale_changed?.tag === "string" ? { tag: answer.locale_changed.tag, label: String(answer.locale_changed.label) } : null);
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
export async function updateMe(change: { display_name?: string; theme?: Theme; locale?: string }): Promise<Me> {
  return (await send<Me>("PATCH", "/api/me", change))!;
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await send("POST", "/api/me/password", { current_password: currentPassword, new_password: newPassword });
}

/** One row of the admin Users page. created_at is UTC text. `reactivated` is true only on the answer to adding a user whose
 * email belonged to a deleted user, who is now restored. */
export type UserRow = {
  id: number; email: string; display_name: string; is_admin: boolean; created_at: string; reactivated?: boolean;
  sign_in: "local" | "oidc" | "both" | "none"; // a password, the identity provider, or both
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

export async function addUser(user: { email: string; display_name: string; password: string; is_admin: boolean; locale?: string }): Promise<UserRow> {
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
  currency: Currency; // the account's own currency: every amount on its page is in it
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
  return (await send<AccountPage>("POST", `/api/accounts/${accountId}/balances`, { ...entry, locale: getLocale().tag }))!;
}

/** `version` is the balance's version when the page loaded it. A balance written since is a RequestError whose `conflicts` say so. */
export async function editBalance(balanceId: number, entry: BalanceEntry, version: number): Promise<AccountPage> {
  return (await send<AccountPage>("PATCH", `/api/balances/${balanceId}`, { ...entry, version, locale: getLocale().tag }))!;
}

export async function deleteBalance(balanceId: number, version: number): Promise<AccountPage> {
  return (await send<AccountPage>("DELETE", `/api/balances/${balanceId}?version=${version}`, undefined))!;
}

/** What a balance's own page shows. `reporting` is null when there is nothing to convert (the account is in the system currency), and
 *  its `value` is null, with no `rate_date`, when the account's currency has no rate on or before the date. */
export type BalancePageData = {
  account: AccountPage; // the balance's account, whose balances hold the version of each
  balance: BalanceRow;
  reporting: { value: number | null; scale: number; unit: string; rate_date: string | null } | null;
  entered_by: string; entered_on: string; // the UTC date it was entered
  changed_by: string; changed_on: string;
};

export async function fetchBalance(id: number, signal?: AbortSignal): Promise<BalancePageData> {
  return (await send<BalancePageData>("GET", `/api/balances/${id}`, undefined, signal))!;
}

export type ClassTypes = { id: number; name: string; types: TypeChoice[] };

/** What the Add account dialog offers. The list of accounts is a list of the framework (listKey "accounts"). */
export type AccountOptions = {
  currency: Currency | null; // the system currency; null while it is unset, when no account can be added
  currencies: Currency[]; // what a new account can be in: the system currency first, then the other usable ones
  classes: ClassTypes[]; // the types each class offers
  today: string;
};

export type NewAccount = {
  account_class: "asset" | "liability";
  name: string;
  type_id: number;
  notes: string;
  currency?: string; // a currency code; left out means the system currency
  amount: string; // typed text; blank adds the account with no balance
  date: string; // as of; ignored when the amount is blank
};

export async function fetchAccountOptions(signal?: AbortSignal): Promise<AccountOptions> {
  return (await send<AccountOptions>("GET", "/api/accounts/options", undefined, signal))!;
}

/** Answers with the new account's id. */
export async function addAccount(account: NewAccount): Promise<{ id: number }> {
  return (await send<{ id: number }>("POST", "/api/accounts", { ...account, locale: getLocale().tag }))!;
}

/** One account type. account_count is how many accounts use it, and deleted_account_count how many deleted accounts still do
 * (they keep their type until they can be restored): a type in use by either can't be deleted or change class. */
export type TypeRow = {
  id: number; name: string; class_id: number; class_name: string; stale_after_days: number; account_count: number;
  deleted_account_count: number;
};
/** `default_stale_after_days` is what a new type's form starts at: the server's system.balance.stale_days system property. */
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
 *  `options` are the allowed values of a Lookup, else empty. A Boolean's value is the text `true` or `false`. */
export type PropertyOption = { value: string; label: string };
export type PropertyRow = {
  name: string; type: "String" | "Integer" | "Lookup" | "Date" | "Time" | "Boolean"; value: string | null; allow_null: boolean; hint: string;
  read_only: boolean; options: PropertyOption[];
};
/** The catalogs feed the search boxes of the system currency and of the default number and date format. */
export type PropertyList = { properties: PropertyRow[]; currencies: Currency[]; locales: { tag: string; label: string }[] };

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
  currency: Currency; // what is typed and shown on this row is in it
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
  return (await send<UpdatePage>("POST", "/api/balances/update", { date, amounts, versions, locale: getLocale().tag }))!;
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
export type ImportMapping = { date: number | null; balance: number | null; note: number | null };

export type ImportColumn = {
  index: number;
  header: string;
  samples: string[]; // the first values that are not blank
  number_formats: string[];
  number_previews: Record<string, number | null>;
  date_formats: string[]; // the formats under which every value is a date: one decides it, several need a choice
};

export type ImportRead = {
  currency: Currency;
  number_formats: string[];
  canonical: boolean;
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
  notes: string[]; // what in the file says another currency than the account's: shown, and they do not block the import
  can_commit: boolean;
  errors: ImportProblem[];
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

export type ImportSettings = { file: ImportFile; mapping: ImportMapping; dateFormat: string | null; numberFormat: string | null; policy: ImportPolicy };

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
  number_format: settings.numberFormat,
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

/** One stored rate: 1 unit of the currency = `rate` units of the system currency on `date`. `rate` is the exact decimal text.
 *  `until` is the date of the next newer rate (null for the newest): a correction changes net worth up to it. */
export type RateRow = { id: number; date: string; rate: string; source: string; changed: string; until: string | null };

/** The automatic rate fetch as the currency page shows it: its daily start time (null when it is off), the time zone that time is in,
 *  and the last run, whose date and time are in that zone. `detail` is a message Northstar wrote, never the provider's text. */
export type FetchStatus = {
  time: string | null; zone: string;
  last_run: { date: string; time: string; outcome: "running" | "succeeded" | "failed" | "abandoned"; detail: string | null } | null;
};

/** A currency's page. `rates_start` is the date rates are wanted from (null until the currency is first enabled, and always for
 *  the system currency); `stale` is set when the newest rate is older than the threshold and an account is open. */
export type CurrencyPageData = {
  code: string; name: string; minor_units: number; is_enabled: boolean; is_system: boolean; system_code: string | null;
  rates_start: string | null; default_rates_start: string; account_count: number; open_account_count: number;
  can_add_rates: boolean; rates: RateRow[]; stale: { last_date: string; days: number; threshold: number } | null;
  fetch: FetchStatus | null; today: string;
};

export async function fetchCurrency(code: string, signal?: AbortSignal): Promise<CurrencyPageData> {
  return (await send<CurrencyPageData>("GET", `/api/currencies/${code}`, undefined, signal))!;
}

/** Switch a currency on or off and set the date its rates start from. A field that is left out stays as it is. Each of these
 *  answers with the page as it now is. */
export async function changeCurrency(code: string, change: { is_enabled?: boolean; rates_start?: string }): Promise<CurrencyPageData> {
  return (await send<CurrencyPageData>("PATCH", `/api/currencies/${code}`, change))!;
}

export async function addRate(code: string, rate: { date: string; rate: string }): Promise<CurrencyPageData> {
  return (await send<CurrencyPageData>("POST", `/api/currencies/${code}/rates`, { ...rate, locale: getLocale().tag }))!;
}

export async function correctRate(code: string, id: number, rate: string): Promise<CurrencyPageData> {
  return (await send<CurrencyPageData>("PUT", `/api/currencies/${code}/rates/${id}`, { rate, locale: getLocale().tag }))!;
}

// -- lists: every list is read the same way, from POST /api/lists/{key} --

/** What a column holds, so the page can draw and align it: a stored whole number with a scale (`decimal`), an amount whose scale
 *  and unit are in the row (`amount`), a UTC timestamp shown as its date, and so on. */
export type ListColumn = {
  key: string; label: string; path_label: string; linked: boolean;
  groupable: boolean; // may the list be grouped by it? Not an amount: the same number in two currencies would be one group
  kind: "text" | "integer" | "number" | "decimal" | "date" | "timestamp" | "yes_no" | "choice" | "amount";
  scale: number | null;
};

/** One row: its values by column key, `_id`, and the route each linked column opens. An amount is {value, scale, unit}, or null. */
/** When the list is grouped a row also has `_group` (the value it is grouped by), `_group_count` (the size of its group across all pages) and
 *  `_group_before` (how many rows of its group come before it, so a page can tell that it opens on a group continued from the page before). */
export type ListRow = { _id: number; _links: Record<string, string>; [key: string]: unknown };

/** One condition of a filter: a column by key, an operator, and a value whose shape the operator decides (none, text, a number or
 *  date as text, a pair for "between", a list of choices). Conditions are data; the server checks every one. */
export type Condition = { field: string; operator: string; value?: unknown };

export type ListPage = {
  columns: ListColumn[]; rows: ListRow[];
  total: number; page: number; pages: number; page_size: number; // total counts every matching row, not this page
  group: string | null;
  sort: { field: string; direction: "asc" | "desc" }; // the sort applied: the one asked for, or the list's own
  filters: Condition[];                               // the conditions applied: the request's, or the default filter's when it named none
  skipped: { field: string | null; reason: string }[]; // conditions of the default filter that no longer fit the list and were left out
  default_filter_id: number | null;                   // the saved filter the list opened with, when the request named no filters
  default_columns: string[];                          // the keys of the columns the list shows when a person has chosen none
  customised: boolean;                                // are the columns shown the person's own saved choice
  skipped_columns: { field: string | null; reason: string }[]; // columns of the person's choice the list no longer offers, left out
};

/** What a view of a list asks for. Anything left out is the list's own default. */
export type ListRequest = {
  columns?: string[]; search?: string; page?: number; page_size?: number; group?: string | null;
  filters?: Condition[]; // none at all means the person's default filter; an empty list means no filter
  sort?: { field: string; direction: "asc" | "desc" } | null;
  params?: Record<string, number>;                  // what a list's scope needs: the id of the account whose balances it lists
};

export async function fetchList(key: string, request: ListRequest, signal?: AbortSignal): Promise<ListPage> {
  const { sort, ...rest } = request;
  return (await send<ListPage>("POST", `/api/lists/${encodeURIComponent(key)}`, sort ? { ...rest, sort } : rest, signal))!;
}

/** A list's view as a CSV file, saved by the browser. The view is the list's own request, sent as a POST so that a filter's values are in
 *  no address or log; the page and the page size are left out, because the file has every row. A request that names no columns or
 *  filters gets the person's own on the server, so the file is the list as they see it. A refusal is an Error, with the server's words. */
export async function exportList(key: string, request: ListRequest): Promise<void> {
  const { page: _page, page_size: _size, sort, ...rest } = request;
  const response = await fetch(`/api/lists/${encodeURIComponent(key)}/export`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(sort ? { ...rest, sort } : rest),
  });
  if (response.status === 401) {
    signIn();
    throw new Error("You are signed out.");
  }
  if (!response.ok) {
    const answer = await response.json().catch(() => null);
    throw new Error(typeof answer?.detail === "string" ? answer.detail : `The server answered ${response.status}`);
  }
  saveFile(await response.blob(), fileNameOf(response.headers.get("Content-Disposition"), `${key}.csv`));
}

/** Remember how many rows a page of this list shows, for this person. */
export async function saveListPageSize(key: string, pageSize: number): Promise<number> {
  return (await send<{ page_size: number }>("PUT", `/api/lists/${encodeURIComponent(key)}/page-size`, { page_size: pageSize }))!.page_size;
}

/** Remember which columns this person wants for this list, in this order, or (null) forget the choice so the list's own apply. */
export async function saveListColumns(key: string, columns: string[] | null): Promise<{ columns: string[]; customised: boolean }> {
  return (await send<{ columns: string[]; customised: boolean }>("PUT", `/api/lists/${encodeURIComponent(key)}/columns`, { columns }))!;
}

// -- filters: what a column can be filtered by, what to choose from, and the saved filters of a list --

/** One column of the tree a list offers: its kind, the operators that suit it, and where its choices come from. A relation is a
 *  column too (it filters by a choice of the records it points at) and has `children` when its table has more to offer. */
export type FieldNode = {
  key: string; label: string; path_label: string; kind: ListColumn["kind"]; scale: number | null;
  operators: { name: string; label: string }[];
  choices: "records" | "values" | null; values?: string[];
  children?: FieldTree | null;
};
export type FieldTree = { fields: FieldNode[]; relations: FieldNode[] };

export async function fetchListFields(key: string, signal?: AbortSignal): Promise<FieldTree> {
  return (await send<FieldTree>("GET", `/api/lists/${encodeURIComponent(key)}/fields`, undefined, signal))!;
}

export type Choices = {
  kind: "values" | "records"; values: string[]; more: boolean; // `more`: there were others than the ones listed
  options: { id: number; value: string; detail: string | null }[];
};

export async function fetchListChoices(key: string, field: string, signal?: AbortSignal): Promise<Choices> {
  return (await send<Choices>("GET", `/api/lists/${encodeURIComponent(key)}/choices/${encodeURIComponent(field)}`, undefined, signal))!;
}

export type SavedFilter = {
  id: number; name: string;
  shared: boolean;       // for everyone who can see the list; only an admin changes it
  is_default: boolean;   // the list opens with it: this person's own default, or the shared one
  can_edit: boolean;
  conditions: Condition[];
  problems: { field: string | null; reason: string }[]; // conditions that no longer fit the list: skipped when it is applied
};
export type SavedFilters = { filters: SavedFilter[]; default_id: number | null };

const filtersUrl = (key: string, id?: number) => `/api/lists/${encodeURIComponent(key)}/filters${id === undefined ? "" : `/${id}`}`;

export async function fetchSavedFilters(key: string, signal?: AbortSignal): Promise<SavedFilters> {
  return (await send<SavedFilters>("GET", filtersUrl(key), undefined, signal))!;
}

/** Each of these answers with the saved filters as they now are. A refusal (a name already taken, a condition the list does not
 *  accept) is an Error whose message is fit to show. */
export async function saveSavedFilter(key: string, filter: { name: string; conditions: Condition[]; shared: boolean }): Promise<SavedFilters> {
  return (await send<SavedFilters>("POST", filtersUrl(key), filter))!;
}

export async function changeSavedFilter(
  key: string, id: number, change: { name?: string; conditions?: Condition[]; is_default?: boolean },
): Promise<SavedFilters> {
  return (await send<SavedFilters>("PUT", filtersUrl(key, id), change))!;
}

export async function deleteSavedFilter(key: string, id: number): Promise<SavedFilters> {
  return (await send<SavedFilters>("DELETE", filtersUrl(key, id), undefined))!;
}

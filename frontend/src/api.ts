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
): Promise<NetWorthSeries> {
  const params = new URLSearchParams();
  if (query.start) params.set("start", query.start);
  if (query.period) params.set("period", query.period);
  if (query.accountId !== undefined) params.set("account_id", String(query.accountId));
  return (await send<NetWorthSeries>("GET", `/api/networth?${params}`, undefined))!;
}

export type Theme = "light" | "dark";

/** The signed-in user. The email and is_admin are read-only here. */
export type Me = { id: number; email: string; display_name: string; is_admin: boolean; theme: Theme };

/** Go to the sign-in page, which brings the person back to this page afterwards. */
function signIn() {
  window.location.href = `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`;
}

/** A refusal from the server. The message is fit to show the user. `errors` maps a row's id to its own
 *  message, for a save that is refused because of particular rows. */
export class RequestError extends Error {
  errors: Record<string, string>;
  constructor(message: string, errors: Record<string, string> = {}) {
    super(message);
    this.errors = errors;
  }
}

/** Send a change and return the JSON answer, or throw an Error whose message is fit to show the user. */
async function send<T>(method: string, url: string, body: unknown): Promise<T | null> {
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (response.status === 401) {
    signIn(); // the session ended: sign in again
    throw new Error("You are signed out.");
  }
  if (!response.ok) {
    const answer = await response.json().catch(() => null);
    const detail = answer?.detail;
    throw new RequestError(typeof detail === "string" ? detail : `The server answered ${response.status}`, answer?.errors ?? {});
  }
  return response.status === 204 ? null : response.json();
}

export async function fetchMe(): Promise<Me> {
  const response = await fetch("/api/me");
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

/** One row of the admin Users page. created_at is UTC text. */
export type UserRow = { id: number; email: string; display_name: string; is_admin: boolean; created_at: string };

export async function fetchUsers(): Promise<UserRow[]> {
  return (await send<UserRow[]>("GET", "/api/users", undefined))!;
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
export type BalanceRow = { id: number; as_of_date: string; amount_cents: number; note: string | null };
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

export async function fetchAccount(id: number): Promise<AccountPage> {
  return (await send<AccountPage>("GET", `/api/accounts/${id}`, undefined))!;
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

export async function editBalance(balanceId: number, entry: BalanceEntry): Promise<AccountPage> {
  return (await send<AccountPage>("PATCH", `/api/balances/${balanceId}`, entry))!;
}

export async function deleteBalance(balanceId: number): Promise<AccountPage> {
  return (await send<AccountPage>("DELETE", `/api/balances/${balanceId}`, undefined))!;
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

export async function fetchAccounts(closed: boolean): Promise<AccountList> {
  return (await send<AccountList>("GET", `/api/accounts?closed=${closed}`, undefined))!;
}

/** Answers with the open list, which now includes the new account. */
export async function addAccount(account: NewAccount): Promise<AccountList> {
  return (await send<AccountList>("POST", "/api/accounts", account))!;
}

/** One account type. account_count is how many accounts use it: a type in use can't be deleted or change class. */
export type TypeRow = { id: number; name: string; class_id: number; class_name: string; stale_after_days: number; account_count: number };
export type TypeList = { types: TypeRow[]; classes: { id: number; name: string }[] };

export async function fetchTypes(): Promise<TypeList> {
  return (await send<TypeList>("GET", "/api/types", undefined))!;
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
};

/** The open accounts for one date, grouped by class (assets first). `saved` is set only on the answer to a save. */
export type UpdatePage = {
  date: string;
  today: string;
  rows: UpdateRow[];
  saved: { added: number; updated: number; unchanged: number } | null;
};

/** Reading a date writes nothing. With no date the server uses today. */
export async function fetchUpdate(date?: string): Promise<UpdatePage> {
  const query = date ? `?date=${encodeURIComponent(date)}` : "";
  return (await send<UpdatePage>("GET", `/api/balances/update${query}`, undefined))!;
}

/** Amounts are typed text by account id. A bad amount is a RequestError whose `errors` say which, and nothing is saved. */
export async function saveUpdate(date: string, amounts: Record<number, string>): Promise<UpdatePage> {
  return (await send<UpdatePage>("POST", "/api/balances/update", { date, amounts }))!;
}

/** The version of the running app, for the footer of the navigation. */
export async function fetchVersion(): Promise<string> {
  const response = await fetch("/api/version");
  if (response.status === 401) {
    signIn();
    throw new Error("You are signed out.");
  }
  if (!response.ok) throw new Error(`The server answered ${response.status}`);
  return (await response.json()).version;
}

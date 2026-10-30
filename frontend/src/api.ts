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

/** Net worth at regular dates. With no start the server begins at the first balance. */
export async function fetchNetWorth(query: { start?: string; period?: Period } = {}): Promise<NetWorthSeries> {
  const params = new URLSearchParams();
  if (query.start) params.set("start", query.start);
  if (query.period) params.set("period", query.period);
  const response = await fetch(`/api/networth?${params}`);
  if (!response.ok) throw new Error(`The server answered ${response.status}`);
  return response.json();
}

export type Theme = "light" | "dark";

/** The signed-in user. The email and is_admin are read-only here. */
export type Me = { id: number; email: string; display_name: string; is_admin: boolean; theme: Theme };

/** Send a change and return the JSON answer, or throw an Error whose message is fit to show the user. */
async function send<T>(method: string, url: string, body: unknown): Promise<T | null> {
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (response.status === 401) {
    window.location.href = "/login"; // the session ended: sign in again
    throw new Error("You are signed out.");
  }
  if (!response.ok) {
    const detail = (await response.json().catch(() => null))?.detail;
    throw new Error(typeof detail === "string" ? detail : `The server answered ${response.status}`);
  }
  return response.status === 204 ? null : response.json();
}

export async function fetchMe(): Promise<Me> {
  const response = await fetch("/api/me");
  if (response.status === 401) {
    window.location.href = "/login";
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

export async function setAdmin(id: number, isAdmin: boolean): Promise<UserRow> {
  return (await send<UserRow>("PATCH", `/api/users/${id}`, { is_admin: isAdmin }))!;
}

export async function resetPassword(id: number, password: string): Promise<void> {
  await send("POST", `/api/users/${id}/password`, { password });
}

export async function deleteUser(id: number): Promise<void> {
  await send("DELETE", `/api/users/${id}`, undefined);
}

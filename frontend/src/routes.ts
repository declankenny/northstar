/** The app's pages. The page is chosen by the part of the address after the #, so no router library is needed. */
export type Route = "dashboard" | "profile" | "users" | "accounts" | "account";

const ACCOUNT = /^#\/accounts\/(\d+)$/;

export function routeFromHash(hash: string): Route {
  if (hash === "#/profile") return "profile";
  if (hash === "#/users") return "users";
  if (hash === "#/accounts") return "accounts";
  if (ACCOUNT.test(hash)) return "account";
  return "dashboard";
}

/** The account id in #/accounts/12, or null for any other address. */
export function accountIdFromHash(hash: string): number | null {
  const match = ACCOUNT.exec(hash);
  return match ? Number(match[1]) : null;
}

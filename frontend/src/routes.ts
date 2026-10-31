/** The app's pages. The page is chosen by the address path, so no router library is needed. */
export type Route = "dashboard" | "profile" | "users" | "accounts" | "account" | "types" | "update" | "notfound";

/** Where each page without a parameter lives. Links use these, so an address is spelled in one place. */
export const PATHS = {
  dashboard: "/dashboard",
  accounts: "/accounts",
  update: "/balance-update",
  types: "/types",
  users: "/users",
  profile: "/profile",
} as const;

const ACCOUNT = /^\/accounts\/(\d+)$/;

/** The address of one account's page. */
export const accountPath = (id: number) => `/accounts/${id}`;

/** The page for an address path. The site root shows the Dashboard (the server sends it to /dashboard),
 *  one trailing slash is ignored, and anything else is not a page. */
export function routeFromPath(path: string): Route {
  const clean = path.length > 1 && path.endsWith("/") ? path.slice(0, -1) : path;
  if (clean === "/" || clean === PATHS.dashboard) return "dashboard";
  if (clean === PATHS.profile) return "profile";
  if (clean === PATHS.users) return "users";
  if (clean === PATHS.accounts) return "accounts";
  if (clean === PATHS.types) return "types";
  if (clean === PATHS.update) return "update";
  if (ACCOUNT.test(clean)) return "account";
  return "notfound";
}

/** The account id in /accounts/12, or null for any other address. */
export function accountIdFromPath(path: string): number | null {
  const clean = path.length > 1 && path.endsWith("/") ? path.slice(0, -1) : path;
  const match = ACCOUNT.exec(clean);
  return match ? Number(match[1]) : null;
}

/** The app's pages. The page is chosen by the part of the address after the #, so no router library is needed. */
export type Route = "dashboard" | "profile" | "users";

export function routeFromHash(hash: string): Route {
  if (hash === "#/profile") return "profile";
  if (hash === "#/users") return "users";
  return "dashboard";
}

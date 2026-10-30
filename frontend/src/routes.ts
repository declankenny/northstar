/** The app's pages. The page is chosen by the part of the address after the #, so no router library is needed. */
export type Route = "dashboard" | "profile";

export function routeFromHash(hash: string): Route {
  return hash === "#/profile" ? "profile" : "dashboard";
}

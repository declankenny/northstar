import { describe, expect, it } from "vitest";
import { accountIdFromPath, accountPath, PATHS, routeFromPath } from "./routes";

describe("routeFromPath", () => {
  it("opens each page at its own address", () => {
    expect(routeFromPath("/dashboard")).toBe("dashboard");
    expect(routeFromPath("/accounts")).toBe("accounts");
    expect(routeFromPath("/balance-update")).toBe("update");
    expect(routeFromPath("/types")).toBe("types");
    expect(routeFromPath("/users")).toBe("users");
    expect(routeFromPath("/profile")).toBe("profile");
  });

  it("opens an account at /accounts/<number>", () => {
    expect(routeFromPath("/accounts/12")).toBe("account");
    expect(accountIdFromPath("/accounts/12")).toBe(12);
    expect(accountPath(12)).toBe("/accounts/12");
  });

  it("shows the Dashboard at the site root, which the server sends to /dashboard", () => {
    expect(routeFromPath("/")).toBe("dashboard");
  });

  it("ignores one trailing slash", () => {
    expect(routeFromPath("/accounts/")).toBe("accounts");
    expect(routeFromPath("/accounts/12/")).toBe("account");
    expect(accountIdFromPath("/accounts/12/")).toBe(12);
  });

  it("says anything else is not a page", () => {
    for (const path of ["", "/nope", "/profile/extra", "/users/1", "/accounts/x", "/accounts/1/edit", "/types/1", "/balance-update/1",
      "/app/", "/app/accounts", "/#/accounts", "/Dashboard", "/accounts//", "/api/networth", "/login"]) {
      expect(routeFromPath(path), path).toBe("notfound");
    }
  });

  it("has no account id for other addresses", () => {
    for (const path of ["", "/", "/accounts", "/accounts/x", "/accounts/1/edit", "/dashboard"]) expect(accountIdFromPath(path), path).toBeNull();
  });

  it("gives every page without a parameter an address that opens it", () => {
    expect(routeFromPath(PATHS.dashboard)).toBe("dashboard");
    expect(routeFromPath(PATHS.accounts)).toBe("accounts");
    expect(routeFromPath(PATHS.update)).toBe("update");
    expect(routeFromPath(PATHS.types)).toBe("types");
    expect(routeFromPath(PATHS.users)).toBe("users");
    expect(routeFromPath(PATHS.profile)).toBe("profile");
  });
});

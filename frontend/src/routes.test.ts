import { describe, expect, it } from "vitest";
import { accountIdFromPath, accountPath, importAccountIdFromPath, importPath, PATHS, routeFromPath } from "./routes";

describe("routeFromPath", () => {
  it("opens each page at its own address", () => {
    expect(routeFromPath("/dashboard")).toBe("dashboard");
    expect(routeFromPath("/accounts")).toBe("accounts");
    expect(routeFromPath("/balance-update")).toBe("update");
    expect(routeFromPath("/types")).toBe("types");
    expect(routeFromPath("/users")).toBe("users");
    expect(routeFromPath("/imports")).toBe("imports");
    expect(routeFromPath("/profile")).toBe("profile");
    expect(routeFromPath("/login")).toBe("login");
  });

  it("opens an account at /accounts/<number>", () => {
    expect(routeFromPath("/accounts/12")).toBe("account");
    expect(accountIdFromPath("/accounts/12")).toBe(12);
    expect(accountPath(12)).toBe("/accounts/12");
  });

  it("opens the import of an account's balances at /accounts/<number>/import", () => {
    expect(routeFromPath("/accounts/12/import")).toBe("import");
    expect(routeFromPath("/accounts/12/import/")).toBe("import");
    expect(importAccountIdFromPath("/accounts/12/import")).toBe(12);
    expect(importPath(12)).toBe("/accounts/12/import");
    for (const path of ["", "/", "/accounts", "/accounts/12", "/accounts/x/import", "/accounts/12/imports", "/import", "/accounts/12/import/x"]) {
      expect(importAccountIdFromPath(path), path).toBeNull();
    }
    expect(accountIdFromPath("/accounts/12/import")).toBeNull();      // it is not the account's own page
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
      "/app/", "/app/accounts", "/#/accounts", "/Dashboard", "/accounts//", "/api/networth", "/login/extra", "/logout"]) {
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

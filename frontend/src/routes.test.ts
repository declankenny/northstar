import { describe, expect, it } from "vitest";
import { accountIdFromPath, accountPath, balanceIdFromPath, balancePath, currencyCodeFromPath, currencyPath, importAccountIdFromPath, importPath, PATHS, reportKeyFromPath, reportPath, routeFromPath } from "./routes";

describe("routeFromPath", () => {
  it("opens each page at its own address", () => {
    expect(routeFromPath("/dashboard")).toBe("dashboard");
    expect(routeFromPath("/accounts")).toBe("accounts");
    expect(routeFromPath("/balances")).toBe("balances");
    expect(routeFromPath("/balances/12")).toBe("balance");
    expect(routeFromPath("/balances/12/")).toBe("balance");
    expect(routeFromPath("/balance-update")).toBe("update");
    expect(routeFromPath("/types")).toBe("types");
    expect(routeFromPath("/users")).toBe("users");
    expect(routeFromPath("/imports")).toBe("imports");
    expect(routeFromPath("/system-properties")).toBe("properties");
    expect(routeFromPath("/currencies")).toBe("currencies");
    expect(routeFromPath("/profile")).toBe("profile");
    expect(routeFromPath("/login")).toBe("login");
    expect(routeFromPath("/setup")).toBe("setup");
  });

  it("opens an account at /accounts/<number>", () => {
    expect(routeFromPath("/accounts/12")).toBe("account");
    expect(accountIdFromPath("/accounts/12")).toBe(12);
    expect(accountPath(12)).toBe("/accounts/12");
  });

  it("opens a currency at /currencies/<code>", () => {
    expect(routeFromPath("/currencies/EUR")).toBe("currency");
    expect(routeFromPath("/currencies/EUR/")).toBe("currency");
    expect(currencyCodeFromPath("/currencies/EUR")).toBe("EUR");
    expect(currencyPath("EUR")).toBe("/currencies/EUR");
    for (const path of ["/currencies", "/currencies/eur", "/currencies/EU", "/currencies/EURO", "/currencies/EUR/rates", "/currency/EUR"]) {
      expect(currencyCodeFromPath(path), path).toBeNull();
    }
    expect(routeFromPath("/currencies/eur")).toBe("notfound");
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
    for (const path of ["", "/nope", "/profile/extra", "/users/1", "/accounts/x", "/accounts/1/edit", "/types/1", "/balance-update/1", "/balances/x", "/balances/1/edit",
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
    expect(routeFromPath(PATHS.properties)).toBe("properties");
    expect(routeFromPath(PATHS.currencies)).toBe("currencies");
    expect(routeFromPath(PATHS.profile)).toBe("profile");
  });
});

describe("a balance's page", () => {
  it("has an address that reads back as the balance's id", () => {
    expect(balancePath(12)).toBe("/balances/12");
    expect(balanceIdFromPath("/balances/12")).toBe(12);
    expect(balanceIdFromPath("/balances/12/")).toBe(12);
    for (const path of ["/balances", "/balances/x", "/balances/12/edit", "/accounts/12", "/balances/-1"]) expect(balanceIdFromPath(path), path).toBeNull();
  });
});

describe("the Reports page", () => {
  it("is at /reports, and a report at /reports/<key>", () => {
    expect(PATHS.reports).toBe("/reports");
    expect(routeFromPath("/reports")).toBe("reports");
    expect(routeFromPath("/reports/")).toBe("reports");
    expect(routeFromPath("/reports/assets_liabilities")).toBe("reports");
    expect(routeFromPath("/reports/assets_liabilities/")).toBe("reports");
    expect(reportPath("assets_liabilities")).toBe("/reports/assets_liabilities");
  });

  it("names the report by its key, and only a plain lowercase key", () => {
    expect(reportKeyFromPath("/reports/assets_liabilities")).toBe("assets_liabilities");
    expect(reportKeyFromPath("/reports/assets_liabilities/")).toBe("assets_liabilities");
    expect(reportKeyFromPath("/reports")).toBeNull();
    for (const bad of ["/reports/Assets", "/reports/1a", "/reports/a-b", "/reports/a/b", "/reports/a b", "/report/a", "/accounts/12"]) expect(reportKeyFromPath(bad), bad).toBeNull();
    for (const bad of ["/reports/Assets", "/reports/a-b", "/reports/a/b"]) expect(routeFromPath(bad), bad).toBe("notfound");
  });
});

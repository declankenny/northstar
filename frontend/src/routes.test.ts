import { describe, expect, it } from "vitest";
import { accountIdFromHash, routeFromHash } from "./routes";

describe("routeFromHash", () => {
  it("opens the profile at #/profile", () => expect(routeFromHash("#/profile")).toBe("profile"));
  it("opens the users page at #/users", () => expect(routeFromHash("#/users")).toBe("users"));
  it("opens an account at #/accounts/<number>", () => {
    expect(routeFromHash("#/accounts/12")).toBe("account");
    expect(accountIdFromHash("#/accounts/12")).toBe(12);
  });
  it("opens the dashboard for no hash, #/ and anything unknown", () => {
    for (const hash of ["", "#", "#/", "#/nope", "#/profile/extra", "#/users/1", "#/accounts", "#/accounts/", "#/accounts/x", "#/accounts/1/edit"]) {
      expect(routeFromHash(hash)).toBe("dashboard");
    }
  });
  it("has no account id for other addresses", () => {
    for (const hash of ["", "#/", "#/accounts", "#/accounts/x", "#/accounts/1/edit"]) expect(accountIdFromHash(hash)).toBeNull();
  });
});

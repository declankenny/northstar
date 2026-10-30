import { describe, expect, it } from "vitest";
import { routeFromHash } from "./routes";

describe("routeFromHash", () => {
  it("opens the profile at #/profile", () => expect(routeFromHash("#/profile")).toBe("profile"));
  it("opens the users page at #/users", () => expect(routeFromHash("#/users")).toBe("users"));
  it("opens the dashboard for no hash, #/ and anything unknown", () => {
    for (const hash of ["", "#", "#/", "#/nope", "#/profile/extra", "#/users/1"]) {
      expect(routeFromHash(hash)).toBe("dashboard");
    }
  });
});

import { describe, expect, it } from "vitest";
import { siteName, websiteLabel, websiteRemovedNotice } from "./website";

describe("an account's website", () => {
  it("is named by its host, without a leading www.", () => {
    expect(siteName("https://www.bank.example/login")).toBe("bank.example");
    expect(siteName("https://secure.bank.example:8443/a")).toBe("secure.bank.example:8443");
    expect(siteName("http://bank.example")).toBe("bank.example");
  });

  it("is shown as it is when it cannot be read as an address", () => {
    expect(siteName("not an address")).toBe("not an address");
  });

  it("has an accessible name that starts with the text on screen", () => {
    expect(websiteLabel("https://www.bank.example/", "Visa Card")).toBe("bank.example — Open Visa Card's website (opens in a new tab)");
    expect(websiteLabel("https://www.bank.example/")).toBe("bank.example — Open the account's website (opens in a new tab)");
  });

  it("says nothing when nothing was removed", () => {
    expect(websiteRemovedNotice([])).toBeNull();
    expect(websiteRemovedNotice(["something the page does not know"])).toBeNull();
  });

  it("says what was removed, in words", () => {
    expect(websiteRemovedNotice(["query"])).toBe("Saved. The website was saved without the part after “?”, which can carry a sign-in token.");
    expect(websiteRemovedNotice(["fragment"])).toContain("without the part after “#”,");
    expect(websiteRemovedNotice(["login", "query", "fragment"]))
      .toBe("Saved. The website was saved without the sign-in details, the part after “?” and the part after “#”, which can carry a sign-in token.");
  });
});

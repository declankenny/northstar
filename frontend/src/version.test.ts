import { describe, expect, it } from "vitest";
import { versionLabel } from "./version";

describe("versionLabel", () => {
  it("puts a v in front of the version", () => {
    expect(versionLabel("0.1.0")).toBe("v0.1.0");
    expect(versionLabel("0.2.0rc1")).toBe("v0.2.0rc1");
  });

  it("shows nothing before the version has loaded", () => {
    expect(versionLabel(null)).toBe("");
    expect(versionLabel("")).toBe("");
  });
});

import { describe, expect, it } from "vitest";
import { dueDayText, dueIn, ordinal } from "./dueDay";

describe("ordinal", () => {
  it.each([[1, "1st"], [2, "2nd"], [3, "3rd"], [4, "4th"], [11, "11th"], [12, "12th"], [13, "13th"], [21, "21st"], [22, "22nd"], [23, "23rd"], [30, "30th"], [31, "31st"]])(
    "%i is %s", (n, text) => expect(ordinal(n)).toBe(text));
});

describe("dueDayText", () => {
  it("says when in the month and that payments are not tracked", () => {
    expect(dueDayText(15)).toBe("The 15th of each month. Payments aren't tracked.");
  });
  it("says what happens in a shorter month for the 29th, 30th and 31st only", () => {
    expect(dueDayText(28)).not.toContain("shorter");
    for (const day of [29, 30, 31]) expect(dueDayText(day)).toContain("or the last day of a shorter month");
  });
});

describe("dueIn", () => {
  it("is today, tomorrow or a number of days, by the server's own today", () => {
    expect(dueIn("2026-11-15", "2026-11-15")).toBe("Due today");
    expect(dueIn("2026-11-15", "2026-11-16")).toBe("Due tomorrow");
    expect(dueIn("2026-11-15", "2026-12-15")).toBe("in 30 days");
    expect(dueIn("2026-12-30", "2027-01-02")).toBe("in 3 days");          // across a year
    expect(dueIn("2028-02-27", "2028-03-01")).toBe("in 3 days");          // across a leap day
  });
});

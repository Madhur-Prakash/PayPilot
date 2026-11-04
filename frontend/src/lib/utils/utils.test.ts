import { describe, expect, it } from "vitest";

import {
  clamp,
  cn,
  formatCompactCurrency,
  formatCurrency,
  formatDelta,
  formatMoney,
  formatNumber,
  initials,
  isImprovement,
  titleCase,
  toNumber,
  truncate,
} from "@/lib/utils";

describe("money formatting (USD)", () => {
  it("formats whole and precise dollars", () => {
    expect(formatCurrency(1234)).toBe("$1,234");
    expect(formatCurrency(1234.5, true)).toBe("$1,234.50");
  });

  it("accepts the decimal strings the API sends", () => {
    expect(formatMoney("1455.00")).toBe("$1,455.00");
    expect(toNumber("10.8000")).toBe(10.8);
    expect(toNumber("")).toBeNull();
  });

  it("compacts large figures", () => {
    expect(formatCompactCurrency(24700)).toBe("$24.7K");
    expect(formatCompactCurrency(1_200_000)).toBe("$1.20M");
    expect(formatCompactCurrency(980)).toBe("$980");
  });

  it("renders missing values as a dash, never NaN", () => {
    expect(formatCurrency(null)).toBe("--");
    expect(formatMoney("not a number")).toBe("--");
  });

  it("groups numbers the US way", () => {
    expect(formatNumber(1234567)).toBe("1,234,567");
  });
});

describe("semantics", () => {
  it("knows that some metrics improve downward", () => {
    expect(isImprovement(-10, "DOWN_IS_GOOD")).toBe(true);
    expect(isImprovement(10, "UP_IS_GOOD")).toBe(true);
    expect(isImprovement(0.01, "UP_IS_GOOD")).toBeNull();
  });

  it("always signs a delta", () => {
    expect(formatDelta(5)).toBe("+5.0%");
    expect(formatDelta(-2.25)).toBe("-2.3%");
  });
});

describe("helpers", () => {
  it("merges classes", () => {
    expect(cn("px-2", "px-4", false && "hidden")).toBe("px-4");
  });

  it("title-cases enum values", () => {
    expect(titleCase("AWAITING_APPROVAL")).toBe("Awaiting Approval");
  });

  it("clamps, truncates and builds initials", () => {
    expect(clamp(12, 0, 10)).toBe(10);
    expect(truncate("abcdef", 4)).toBe("abc…");
    expect(initials("Morgan Hayes")).toBe("MH");
  });
});

import { beforeEach, describe, expect, it } from "vitest";

import { MAX_COMPARE, useCompareStore } from "./compare";

const item = (id: string) => ({ id, title: `Product ${id}` });

describe("compare store", () => {
  beforeEach(() => useCompareStore.getState().clear());

  it("toggles products in and out", () => {
    const { toggle } = useCompareStore.getState();
    expect(toggle(item("a"))).toBe(true);
    expect(useCompareStore.getState().has("a")).toBe(true);
    expect(toggle(item("a"))).toBe(true);
    expect(useCompareStore.getState().items).toHaveLength(0);
  });

  it(`refuses more than ${MAX_COMPARE} products`, () => {
    const { toggle } = useCompareStore.getState();
    for (let i = 0; i < MAX_COMPARE; i += 1) expect(toggle(item(String(i)))).toBe(true);
    expect(toggle(item("extra"))).toBe(false);
    expect(useCompareStore.getState().items).toHaveLength(MAX_COMPARE);
  });

  it("removes one product and clears all", () => {
    const { toggle, remove, clear } = useCompareStore.getState();
    toggle(item("a"));
    toggle(item("b"));
    remove("a");
    expect(useCompareStore.getState().items.map((i) => i.id)).toEqual(["b"]);
    clear();
    expect(useCompareStore.getState().items).toEqual([]);
  });
});

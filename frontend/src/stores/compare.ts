"use client";

/** The products a merchant has picked to compare (2-4), shared across discovery screens. */

import { create } from "zustand";

export interface CompareItem {
  id: string;
  title: string;
  image_url?: string;
  price?: string | null;
  currency?: string;
}

export const MAX_COMPARE = 4;

interface CompareState {
  items: CompareItem[];
  toggle: (item: CompareItem) => boolean;
  remove: (id: string) => void;
  clear: () => void;
  has: (id: string) => boolean;
}

export const useCompareStore = create<CompareState>((set, get) => ({
  items: [],
  toggle: (item) => {
    const items = get().items;
    if (items.some((i) => i.id === item.id)) {
      set({ items: items.filter((i) => i.id !== item.id) });
      return true;
    }
    if (items.length >= MAX_COMPARE) return false;
    set({ items: [...items, item] });
    return true;
  },
  remove: (id) => set({ items: get().items.filter((i) => i.id !== id) }),
  clear: () => set({ items: [] }),
  has: (id) => get().items.some((i) => i.id === id),
}));

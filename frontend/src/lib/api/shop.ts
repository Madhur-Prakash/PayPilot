/**
 * The public online store (no sign-in). The server prices the cart: the browser sends
 * product ids and quantities, never amounts.
 */

import { apiGet, apiPost } from "@/lib/api/client";

export interface ShopProduct {
  id: string;
  sku: string;
  name: string;
  description: string;
  price: string;
  currency: string;
  image_url: string | null;
  available: number | null;
  in_stock: boolean;
}

export interface ShopCatalog {
  merchant: { name: string; city: string | null; slug: string };
  mode: "SANDBOX" | "LIVE" | "SIMULATED";
  currency: string;
  max_quantity: number;
  note: string;
  products: ShopProduct[];
}

export interface ShopOrder {
  order_id: string;
  status: string;
  approve_url: string | null;
  needs_payer_approval: boolean;
  mode: string;
  total: string;
  currency: string;
  items: { name: string; quantity: number; unit_price: string }[];
}

export interface ShopStockMove {
  sku: string;
  name: string;
  quantity: number;
  on_hand_before: number;
  on_hand_after: number;
  status: string;
  oversold: boolean;
  crossed_reorder_point: boolean;
}

export interface ShopSale {
  recorded_now: boolean;
  order_ref: string;
  paypal_order_id: string;
  capture_id: string | null;
  mode: string | null;
  total: string;
  currency: string;
  items: { name: string; quantity: number; unit_price: string }[];
  stock: ShopStockMove[];
  paid_at: string;
}

export const SHOP_SLUG = process.env.NEXT_PUBLIC_SHOP_SLUG ?? "juniper-oak-coffee";

export const shopApi = {
  catalog: (slug: string) => apiGet<ShopCatalog>(`/shop/${encodeURIComponent(slug)}`),
  createOrder: (slug: string, items: { product_id: string; quantity: number }[], clientKey: string) =>
    apiPost<ShopOrder>(`/shop/${encodeURIComponent(slug)}/orders`, { items, client_key: clientKey }),
  capture: (slug: string, orderId: string) =>
    apiPost<ShopSale>(`/shop/${encodeURIComponent(slug)}/orders/${encodeURIComponent(orderId)}/capture`),
};

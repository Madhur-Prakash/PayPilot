/** The gear shelf: complementary Channel3 products for the merchant's best seller. */

export interface ShelfProduct {
  title: string;
  price: string;
  currency: string;
  brand: string;
  merchant: string;
  /** Affiliate-tracked and short-lived - always use the one from the latest response. */
  url: string;
  in_stock: boolean | null;
  product_id: string;
  image_url: string;
  category: string;
  compare_at_price: string | null;
  /** Fraction, e.g. "0.0700" = 7%. */
  commission_rate: string | null;
  offers_count: number;
}

export interface ShelfSlot {
  key: string;
  label: string;
  category: string;
  mode?: string;
  products: ShelfProduct[];
  error?: string;
}

export interface ShelfEstimate {
  buyers_30d: number;
  attach_rate: string;
  typical_item_price: string | null;
  typical_commission_rate: string | null;
  monthly_shelf_sales: string | null;
  monthly_commission: string | null;
  assumptions: string[];
}

export interface Shelf {
  mode: string;
  anchor: {
    product_id: string;
    name: string;
    sku: string;
    price: string;
    buyers: number;
    orders: number;
    window_end: string | null;
  } | null;
  slots: ShelfSlot[];
  estimate: ShelfEstimate | null;
  generated_at?: string;
  cache_ttl_seconds?: number;
  cached?: boolean;
  note: string;
  disclaimer?: string;
}

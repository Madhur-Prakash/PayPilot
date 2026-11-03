/**
 * The pages the voice assistant can move the merchant to.
 *
 * Derived from `NAV_SECTIONS` so the key set can never drift from what's
 * actually in the sidebar. The `key` strings also match the backend's
 * `navigate_page` tool (`backend/app/integrations/vapi.py`, `PAGE_DIRECTORY`)
 * for whenever the assistant does call it - Python can't import this file, so
 * that list is kept in sync by hand.
 *
 * But the tool call is a bonus, not the mechanism this relies on: an LLM
 * deciding to call a function is a coin flip in practice, and Vapi's own
 * assistant has to have that tool configured on its side, which drifts. What
 * actually drives navigation is `matchVoicePage` below, run against the
 * merchant's own transcribed speech - "show me the campaigns" moves the
 * screen the instant Vapi finishes transcribing it, with no round trip
 * through the assistant's reasoning at all.
 */

import { ALL_NAV_ITEMS, type NavItem } from "@/lib/constants/navigation";

export interface VoicePage {
  key: string;
  label: string;
  href: string;
  description: string;
  permission?: string;
}

/** "/inventory/automation" -> "inventory_automation" */
function keyFor(item: NavItem): string {
  return item.href.replace(/^\//, "").replace(/\//g, "_");
}

export const VOICE_PAGES: VoicePage[] = ALL_NAV_ITEMS.map((item) => ({
  key: keyFor(item),
  label: item.label,
  href: item.href,
  description: item.description,
  permission: item.permission,
}));

const BY_KEY = new Map(VOICE_PAGES.map((page) => [page.key, page]));

export function resolveVoicePage(key: string): VoicePage | undefined {
  return BY_KEY.get(key);
}

/** Best-effort match for a page the merchant is currently on, for context feed. */
export function voicePageForPath(pathname: string): VoicePage | undefined {
  return (
    VOICE_PAGES.find((page) => page.href === pathname) ??
    VOICE_PAGES.find((page) => pathname.startsWith(`${page.href}/`))
  );
}

// --------------------------------------------------------------------------- //
// Speech -> page, without an LLM in the loop.
// --------------------------------------------------------------------------- //

/** Extra words merchants actually say that a page's own label wouldn't catch. */
const ALIASES: Record<string, string[]> = {
  dashboard: ["home", "command center", "main screen", "overview"],
  growth: ["growth chart", "growth graph"],
  opportunities: ["opportunity", "opportunity radar"],
  reviews: ["review", "customer reviews", "feedback"],
  competitors: ["competitor", "competition", "rivals"],
  campaigns: ["campaign"],
  experiments: ["experiment", "a/b test", "ab test", "test results"],
  impact: ["impact tree"],
  customers: ["customer", "clients"],
  products: ["product", "catalogue", "catalog"],
  inventory: ["stock", "stock levels"],
  purchase_orders: ["purchase order", "purchase orders", "orders"],
  inventory_automation: ["automation", "automated ordering", "auto reorder"],
  agents: ["agent activity", "agent log", "agent runs"],
  voice: ["voice studio"],
  observability: ["traces", "langfuse", "token usage"],
  activity: ["audit log", "activity log"],
  settings: ["setting", "preferences", "configuration"],
};

/** "go to", "open", "show (me)", "take me to", "navigate to", "pull up"… */
const NAV_TRIGGER = /\b(go to|open|show(?:\s+me)?|navigate to|take me to|switch to|pull up|bring up|display|jump to)\b/i;

/**
 * Matches a spoken utterance against a page, the way a merchant actually
 * talks rather than the exact key a function-calling model would need. Only
 * fires when a navigation verb is present, so ordinary conversation
 * ("the campaign underperformed") never triggers a jump. Returns the page
 * whose label/alias is the longest match, since that is the most specific
 * (and least likely to be an accidental substring) one heard.
 */
export function matchVoicePage(utterance: string): VoicePage | undefined {
  const text = utterance.toLowerCase();
  if (!NAV_TRIGGER.test(text)) return undefined;

  let best: VoicePage | undefined;
  let bestLength = 0;

  for (const page of VOICE_PAGES) {
    const candidates = [page.label, page.key.replace(/_/g, " "), ...(ALIASES[page.key] ?? [])];
    for (const candidate of candidates) {
      const needle = candidate.toLowerCase();
      if (needle.length < 4 || !text.includes(needle)) continue;
      if (needle.length > bestLength) {
        best = page;
        bestLength = needle.length;
      }
    }
  }
  return best;
}

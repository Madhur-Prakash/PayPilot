"use client";

import { create } from "zustand";

import { authApi } from "@/lib/api/endpoints";
import { setAccessToken, setUnauthorizedHandler } from "@/lib/api/client";
import type { CurrentUser, MerchantSummary, Role } from "@/types/api";

/**
 * Session state.
 *
 * The access token is held in memory only - never localStorage - so an XSS bug
 * cannot read it back out. Durability comes from the HttpOnly refresh cookie:
 * on a page load `bootstrap()` silently exchanges it for a fresh access token.
 *
 * `permissions` here is for *rendering only*. It hides controls the user cannot
 * use; the backend re-checks every permission on every request regardless.
 */
interface AuthState {
  user: CurrentUser | null;
  status: "idle" | "loading" | "authenticated" | "unauthenticated";
  error: string | null;

  bootstrap: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  register: (payload: {
    email: string;
    password: string;
    full_name: string;
    merchant_name?: string;
  }) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;

  can: (permission: string) => boolean;
  canAny: (...permissions: string[]) => boolean;
  merchant: () => MerchantSummary | null;
  role: () => string | null;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  status: "idle",
  error: null,

  bootstrap: async () => {
    set({ status: "loading", error: null });
    try {
      const session = await authApi.refresh();
      setAccessToken(session.tokens.access_token);
      set({ user: session.user, status: "authenticated" });
    } catch {
      // No valid refresh cookie: a normal first visit, not an error to surface.
      setAccessToken(null);
      set({ user: null, status: "unauthenticated" });
    }
  },

  login: async (email, password) => {
    set({ status: "loading", error: null });
    try {
      const session = await authApi.login(email, password);
      setAccessToken(session.tokens.access_token);
      set({ user: session.user, status: "authenticated" });
    } catch (error) {
      set({ status: "unauthenticated", user: null });
      throw error;
    }
  },

  register: async (payload) => {
    set({ status: "loading", error: null });
    try {
      const session = await authApi.register(payload);
      setAccessToken(session.tokens.access_token);
      set({ user: session.user, status: "authenticated" });
    } catch (error) {
      set({ status: "unauthenticated", user: null });
      throw error;
    }
  },

  logout: async () => {
    try {
      await authApi.logout();
    } catch {
      // Signing out locally must succeed even if the server call does not.
    }
    setAccessToken(null);
    set({ user: null, status: "unauthenticated" });
  },

  refreshUser: async () => {
    try {
      const user = await authApi.me();
      set({ user });
    } catch {
      /* keep the existing session view */
    }
  },

  can: (permission) => get().user?.permissions.includes(permission) ?? false,
  canAny: (...permissions) => {
    const held = get().user?.permissions ?? [];
    return permissions.some((p) => held.includes(p));
  },
  merchant: () => get().user?.active_merchant ?? null,
  role: () => get().user?.role ?? null,
}));

/** Wired once by the providers: a failed refresh drops the session cleanly. */
export function installUnauthorizedHandler() {
  setUnauthorizedHandler(() => {
    setAccessToken(null);
    useAuthStore.setState({ user: null, status: "unauthenticated" });
  });
}

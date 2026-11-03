"use client";

import { Check, ChevronDown, LogOut, Menu, Moon, Store, Sun, User } from "lucide-react";
import { useTheme } from "next-themes";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import * as React from "react";

import { VoiceButton } from "@/components/voice/voice-button";
import { Button } from "@/components/ui/button";
import {
  Avatar,
  AvatarFallback,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/overlays";
import { Badge } from "@/components/ui/primitives";
import { ALL_NAV_ITEMS } from "@/lib/constants/navigation";
import { initials } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";

export function Topbar({ onOpenMobileNav }: { onOpenMobileNav: () => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);

  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  React.useEffect(() => setMounted(true), []);

  const current = ALL_NAV_ITEMS.find(
    (item) => pathname === item.href || pathname.startsWith(`${item.href}/`),
  );

  async function handleLogout() {
    await logout();
    router.push("/login");
  }

  return (
    <header className="sticky top-0 z-30 border-b border-border bg-background/85 backdrop-blur-md">
      <div className="flex h-16 items-center gap-3 px-4 lg:px-6">
        <Button
          variant="ghost"
          size="icon"
          className="lg:hidden"
          onClick={onOpenMobileNav}
          aria-label="Open navigation"
        >
          <Menu className="h-5 w-5" />
        </Button>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h1 className="truncate text-[0.9375rem] font-semibold leading-tight">
              {current?.label ?? "Growth Autopilot"}
            </h1>
          </div>
          <p className="hidden truncate text-xs text-muted-foreground sm:block">
            {current?.description ?? "An AI Growth Scientist for every merchant"}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <VoiceButton />

          {/* Merchant switcher: only merchants the user is actually a member of. */}
          {user && user.memberships.length > 0 && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm" className="hidden gap-2 md:inline-flex">
                  <Store className="h-4 w-4 text-muted-foreground" />
                  <span className="max-w-[9rem] truncate">
                    {user.active_merchant?.name ?? "Workspace"}
                  </span>
                  <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-64">
                <DropdownMenuLabel>Your merchants</DropdownMenuLabel>
                {user.memberships.map((membership) => (
                  <DropdownMenuItem key={membership.merchant.id} className="justify-between">
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate text-sm">{membership.merchant.name}</span>
                      <span className="text-2xs text-muted-foreground">{membership.role}</span>
                    </span>
                    {membership.merchant.id === user.active_merchant?.id && (
                      <Check className="h-4 w-4 text-primary" />
                    )}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          )}

          {mounted && (
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              aria-label="Toggle theme"
            >
              {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
          )}

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="rounded-full focus-ring"
                aria-label="Account menu"
              >
                <Avatar>
                  <AvatarFallback>{initials(user?.user.full_name ?? "?")}</AvatarFallback>
                </Avatar>
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-60">
              <div className="px-2 py-1.5">
                <p className="truncate text-sm font-medium">{user?.user.full_name}</p>
                <p className="truncate text-xs text-muted-foreground">{user?.user.email}</p>
                {user?.role && (
                  <Badge variant="secondary" className="mt-1.5">
                    {user.role}
                  </Badge>
                )}
              </div>
              <DropdownMenuSeparator />
              <DropdownMenuItem asChild>
                <Link href="/settings">
                  <User />
                  Profile and settings
                </Link>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={handleLogout} className="text-destructive">
                <LogOut />
                Sign out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </header>
  );
}

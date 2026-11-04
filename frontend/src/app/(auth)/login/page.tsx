"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { AlertCircle, ArrowRight, Gauge } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input, Label, Separator } from "@/components/ui/primitives";
import { FadeIn } from "@/components/ui/motion";
import { ApiError } from "@/lib/api/client";
import { SAMPLE_CREDENTIALS } from "@/lib/constants/config";
import { useAuthStore } from "@/stores/auth";

const schema = z.object({
  email: z.string().email("Enter a valid email address"),
  password: z.string().min(1, "Enter your password"),
});

type FormValues = z.infer<typeof schema>;

/** One account per role, so the RBAC story can be demonstrated, not just described. */
const SAMPLE_ROLES = [
  { email: "owner@juniperoak.com", role: "Owner", note: "full control" },
  { email: "admin@juniperoak.com", role: "Admin", note: "approve and execute" },
  { email: "analyst@juniperoak.com", role: "Analyst", note: "propose, cannot execute" },
  { email: "viewer@juniperoak.com", role: "Viewer", note: "read only" },
];

export default function LoginPage() {
  const router = useRouter();
  const login = useAuthStore((s) => s.login);
  const [serverError, setServerError] = React.useState<string | null>(null);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { email: SAMPLE_CREDENTIALS.email, password: SAMPLE_CREDENTIALS.password },
  });

  async function onSubmit(values: FormValues) {
    setServerError(null);
    try {
      await login(values.email, values.password);
      router.replace("/command");
    } catch (error) {
      setServerError(
        error instanceof ApiError ? error.message : "Could not sign in. Please try again.",
      );
    }
  }

  return (
    <FadeIn className="space-y-7">
      <div className="space-y-2">
        <div className="mb-5 flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-primary-foreground lg:hidden">
          <Gauge className="h-5 w-5" />
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">Sign in</h1>
        <p className="text-sm text-muted-foreground">
          Welcome back. Your Growth Scientist has been working.
        </p>
      </div>

      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <div className="space-y-1.5">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            placeholder="you@merchant.in"
            aria-invalid={Boolean(form.formState.errors.email)}
            {...form.register("email")}
          />
          {form.formState.errors.email && (
            <p className="text-xs text-destructive">{form.formState.errors.email.message}</p>
          )}
        </div>

        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <Label htmlFor="password">Password</Label>
            <Link
              href="/forgot-password"
              className="text-xs text-primary underline-offset-4 hover:underline"
            >
              Forgot password?
            </Link>
          </div>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            aria-invalid={Boolean(form.formState.errors.password)}
            {...form.register("password")}
          />
          {form.formState.errors.password && (
            <p className="text-xs text-destructive">{form.formState.errors.password.message}</p>
          )}
        </div>

        {serverError && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-lg border border-destructive/25 bg-destructive/8 p-3 text-sm text-destructive"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{serverError}</span>
          </div>
        )}

        <Button type="submit" size="lg" className="w-full" loading={form.formState.isSubmitting}>
          Sign in
          {!form.formState.isSubmitting && <ArrowRight className="h-4 w-4" />}
        </Button>
      </form>

      <div className="space-y-3">
        <div className="flex items-center gap-3">
          <Separator className="flex-1" />
          <span className="text-2xs uppercase tracking-widest text-muted-foreground">
            Sample accounts
          </span>
          <Separator className="flex-1" />
        </div>
        <div className="grid gap-1.5">
          {SAMPLE_ROLES.map((account) => (
            <button
              key={account.email}
              type="button"
              onClick={() => {
                form.setValue("email", account.email);
                form.setValue("password", SAMPLE_CREDENTIALS.password);
                setServerError(null);
              }}
              className="flex items-center justify-between rounded-lg border border-border bg-card px-3 py-2 text-left text-sm transition-colors hover:border-primary/40 hover:bg-primary/5 focus-ring"
            >
              <span className="min-w-0">
                <span className="block truncate font-medium">{account.role}</span>
                <span className="block truncate text-2xs text-muted-foreground">
                  {account.email}
                </span>
              </span>
              <span className="ml-3 shrink-0 text-2xs text-muted-foreground">{account.note}</span>
            </button>
          ))}
        </div>
        <p className="text-2xs text-muted-foreground">
          These accounts share the password{" "}
          <code className="font-mono">{SAMPLE_CREDENTIALS.password}</code>. Sign in as different
          roles to see permissions enforced by the backend.
        </p>
      </div>

      <p className="text-center text-sm text-muted-foreground">
        New here?{" "}
        <Link href="/register" className="font-medium text-primary underline-offset-4 hover:underline">
          Create an account
        </Link>
      </p>
    </FadeIn>
  );
}

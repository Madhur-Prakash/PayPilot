"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { AlertCircle, ArrowRight, Check } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/primitives";
import { FadeIn } from "@/components/ui/motion";
import { ApiError } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";

/** Mirrors the backend's Argon2 password policy so the rules are visible up front. */
const PASSWORD_RULES = [
  { label: "At least 10 characters", test: (v: string) => v.length >= 10 },
  { label: "One uppercase letter", test: (v: string) => /[A-Z]/.test(v) },
  { label: "One lowercase letter", test: (v: string) => /[a-z]/.test(v) },
  { label: "One digit", test: (v: string) => /\d/.test(v) },
  { label: "One symbol", test: (v: string) => /[^A-Za-z0-9]/.test(v) },
];

const schema = z.object({
  full_name: z.string().min(2, "Tell us your name"),
  email: z.string().email("Enter a valid email address"),
  merchant_name: z.string().min(2, "Name your business").max(160),
  password: z
    .string()
    .refine((v) => PASSWORD_RULES.every((rule) => rule.test(v)), "Password does not meet the rules"),
});

type FormValues = z.infer<typeof schema>;

export default function RegisterPage() {
  const router = useRouter();
  const register = useAuthStore((s) => s.register);
  const [serverError, setServerError] = React.useState<string | null>(null);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { full_name: "", email: "", merchant_name: "", password: "" },
    mode: "onChange",
  });

  const password = form.watch("password") ?? "";

  async function onSubmit(values: FormValues) {
    setServerError(null);
    try {
      await register(values);
      router.replace("/dashboard");
    } catch (error) {
      setServerError(
        error instanceof ApiError ? error.message : "Could not create the account.",
      );
    }
  }

  return (
    <FadeIn className="space-y-7">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Create your account</h1>
        <p className="text-sm text-muted-foreground">
          You will get an empty workspace you own. To explore the full sample dataset, sign in
          with the Juniper & Oak Coffee accounts instead.
        </p>
      </div>

      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <div className="space-y-1.5">
          <Label htmlFor="full_name">Your name</Label>
          <Input id="full_name" autoComplete="name" {...form.register("full_name")} />
          {form.formState.errors.full_name && (
            <p className="text-xs text-destructive">{form.formState.errors.full_name.message}</p>
          )}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="merchant_name">Business name</Label>
          <Input
            id="merchant_name"
            placeholder="e.g. Juniper & Oak Coffee"
            {...form.register("merchant_name")}
          />
          {form.formState.errors.merchant_name && (
            <p className="text-xs text-destructive">
              {form.formState.errors.merchant_name.message}
            </p>
          )}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="email">Email</Label>
          <Input id="email" type="email" autoComplete="email" {...form.register("email")} />
          {form.formState.errors.email && (
            <p className="text-xs text-destructive">{form.formState.errors.email.message}</p>
          )}
        </div>

        <div className="space-y-2">
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            autoComplete="new-password"
            {...form.register("password")}
          />
          <ul className="grid gap-1 pt-0.5 sm:grid-cols-2">
            {PASSWORD_RULES.map((rule) => {
              const met = rule.test(password);
              return (
                <li
                  key={rule.label}
                  className={cn(
                    "flex items-center gap-1.5 text-2xs transition-colors",
                    met ? "text-success" : "text-muted-foreground",
                  )}
                >
                  <Check className={cn("h-3 w-3", !met && "opacity-30")} />
                  {rule.label}
                </li>
              );
            })}
          </ul>
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
          Create account
          {!form.formState.isSubmitting && <ArrowRight className="h-4 w-4" />}
        </Button>
      </form>

      <p className="text-center text-sm text-muted-foreground">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-primary underline-offset-4 hover:underline">
          Sign in
        </Link>
      </p>
    </FadeIn>
  );
}

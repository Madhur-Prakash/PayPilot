"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowLeft, MailCheck } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Badge, Input, Label } from "@/components/ui/primitives";
import { FadeIn } from "@/components/ui/motion";
import { authApi } from "@/lib/api/endpoints";

const schema = z.object({ email: z.string().email("Enter a valid email address") });
type FormValues = z.infer<typeof schema>;

export default function ForgotPasswordPage() {
  const [sent, setSent] = React.useState(false);
  const [resetToken, setResetToken] = React.useState<string | null>(null);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { email: "" },
  });

  async function onSubmit(values: FormValues) {
    const result = await authApi.forgotPassword(values.email);
    // The API always reports success so the response cannot be used to discover
    // which addresses are registered. In debug builds it returns the token inline
    // instead of emailing it.
    setResetToken(result.resource_id ?? null);
    setSent(true);
  }

  if (sent) {
    return (
      <FadeIn className="space-y-6">
        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-success/12 text-success">
          <MailCheck className="h-5 w-5" />
        </div>
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">Check your email</h1>
          <p className="text-sm text-muted-foreground">
            If that address is registered, a reset link is on its way. We deliberately do not say
            whether an account exists.
          </p>
        </div>

        {resetToken && (
          <div className="space-y-2 rounded-lg border border-dashed border-border bg-muted/40 p-3">
            <Badge variant="warning">No mail server configured</Badge>
            <p className="text-xs text-muted-foreground">
              The reset token is returned inline instead of being emailed:
            </p>
            <code className="block break-all rounded bg-card p-2 font-mono text-2xs">
              {resetToken}
            </code>
          </div>
        )}

        <Button asChild variant="outline" className="w-full">
          <Link href="/login">
            <ArrowLeft className="h-4 w-4" />
            Back to sign in
          </Link>
        </Button>
      </FadeIn>
    );
  }

  return (
    <FadeIn className="space-y-7">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Reset your password</h1>
        <p className="text-sm text-muted-foreground">
          Enter your email and we will send you a reset link.
        </p>
      </div>

      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <div className="space-y-1.5">
          <Label htmlFor="email">Email</Label>
          <Input id="email" type="email" autoComplete="email" {...form.register("email")} />
          {form.formState.errors.email && (
            <p className="text-xs text-destructive">{form.formState.errors.email.message}</p>
          )}
        </div>
        <Button type="submit" size="lg" className="w-full" loading={form.formState.isSubmitting}>
          Send reset link
        </Button>
      </form>

      <Button asChild variant="ghost" className="w-full">
        <Link href="/login">
          <ArrowLeft className="h-4 w-4" />
          Back to sign in
        </Link>
      </Button>
    </FadeIn>
  );
}

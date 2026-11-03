"use client";

import { Copy, Mail, MailCheck, RefreshCw, UserPlus } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { ErrorState, LoadingRows } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/overlays";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Separator,
} from "@/components/ui/primitives";
import {
  useChangeMemberRole,
  useInviteMember,
  useRoles,
  useSendTestEmail,
  useSettings,
  useTeamMembers,
} from "@/hooks/use-api";
import { useAuthStore } from "@/stores/auth";

/** Readable temporary password that still clears the 10-character minimum. */
function generatePassword(): string {
  const words = ["Chai", "Filter", "Ledger", "Orbit", "Sandbox", "Copper", "Harbor", "Quartz"];
  const pick = () => words[Math.floor(Math.random() * words.length)];
  return `${pick()}-${pick()}-${Math.floor(1000 + Math.random() * 9000)}`;
}

export function MembersPanel() {
  const members = useTeamMembers();
  const { data: roles } = useRoles();
  const invite = useInviteMember();
  const changeRole = useChangeMemberRole();
  const testEmail = useSendTestEmail();
  const { data: integrations } = useSettings();
  const emailReady = Boolean(integrations?.integrations.email?.configured);
  const currentUserId = useAuthStore((s) => s.user?.user.id);

  const [email, setEmail] = React.useState("");
  const [fullName, setFullName] = React.useState("");
  const [role, setRole] = React.useState("VIEWER");
  const [password, setPassword] = React.useState(generatePassword);

  const valid = /.+@.+\..+/.test(email) && fullName.trim().length >= 2;

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!valid) return;
    invite.mutate(
      {
        email: email.trim().toLowerCase(),
        full_name: fullName.trim(),
        role,
        temporary_password: password,
      },
      {
        onSuccess: () => {
          setEmail("");
          setFullName("");
          setPassword(generatePassword());
        },
      },
    );
  }

  return (
    <div className="space-y-4">
      {/* Invite */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <UserPlus className="h-4 w-4 text-primary" />
            Invite someone
          </CardTitle>
          <p className="text-sm text-muted-foreground">
            They get access to this merchant only, with exactly the permissions their role
            carries.
          </p>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="invite-name">Full name</Label>
                <Input
                  id="invite-name"
                  value={fullName}
                  onChange={(event) => setFullName(event.target.value)}
                  placeholder="Priya Sharma"
                  required
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="invite-email">Email</Label>
                <div className="relative">
                  <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    id="invite-email"
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    placeholder="colleague@company.com"
                    className="pl-9"
                    required
                  />
                </div>
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="invite-role">Role</Label>
                <Select value={role} onValueChange={setRole}>
                  <SelectTrigger id="invite-role">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(roles ?? []).map((option) => (
                      <SelectItem key={option.name} value={option.name}>
                        {option.name}
                        {option.is_custom ? " (custom)" : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="invite-password">Temporary password</Label>
                <div className="flex gap-2">
                  <Input
                    id="invite-password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    className="font-mono text-xs"
                    minLength={10}
                    required
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    aria-label="Generate a new password"
                    onClick={() => setPassword(generatePassword())}
                  >
                    <RefreshCw className="h-4 w-4" />
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    aria-label="Copy password"
                    onClick={() => {
                      void navigator.clipboard?.writeText(password);
                      toast.success("Password copied");
                    }}
                  >
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between gap-3">
              <p className="text-xs text-muted-foreground">
                {emailReady
                  ? "We email the sign-in link and this password. Keep a copy in case it bounces."
                  : "Email is not configured, so share this password yourself."}
              </p>
              <div className="flex items-center gap-2">
                {emailReady && (
                  <Button
                    type="button"
                    variant="outline"
                    loading={testEmail.isPending}
                    onClick={() => testEmail.mutate()}
                    className="gap-2"
                  >
                    <MailCheck className="h-4 w-4" />
                    Send test
                  </Button>
                )}
                <Button type="submit" loading={invite.isPending} disabled={!valid} className="gap-2">
                  <UserPlus className="h-4 w-4" />
                  Send invite
                </Button>
              </div>
            </div>
          </form>
        </CardContent>
      </Card>

      {/* Members */}
      <Card>
        <CardHeader>
          <CardTitle>Members</CardTitle>
          <p className="text-sm text-muted-foreground">
            {members.data
              ? `${members.data.length} ${members.data.length === 1 ? "person has" : "people have"} access`
              : "Who can reach this merchant"}
          </p>
        </CardHeader>
        <CardContent className="space-y-2">
          {members.isLoading && <LoadingRows rows={3} />}
          {members.error && (
            <ErrorState error={members.error} onRetry={() => void members.refetch()} />
          )}

          {(members.data ?? []).map((member) => (
            <div
              key={member.user.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card p-3"
            >
              <div className="min-w-0">
                <p className="flex items-center gap-2 text-sm font-medium">
                  {member.user.full_name}
                  {member.user.id === currentUserId && <Badge variant="info">You</Badge>}
                </p>
                <p className="truncate text-2xs text-muted-foreground">{member.user.email}</p>
              </div>

              <div className="flex items-center gap-2">
                <Select
                  value={member.role}
                  onValueChange={(next) =>
                    changeRole.mutate({ user_id: member.user.id, role: next })
                  }
                  disabled={changeRole.isPending}
                >
                  <SelectTrigger className="w-[168px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(roles ?? []).map((option) => (
                      <SelectItem key={option.name} value={option.name}>
                        {option.name}
                        {option.is_custom ? " (custom)" : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          ))}

          {members.data && members.data.length === 0 && (
            <p className="py-6 text-center text-sm text-muted-foreground">
              No members yet. Invite someone above.
            </p>
          )}
        </CardContent>
      </Card>

      <Separator />
      <p className="text-xs leading-relaxed text-muted-foreground">
        Changing a role takes effect on the member&apos;s next request. The backend re-derives the
        permission set from the stored role on every call, so a downgrade cannot be outrun by a
        cached page. The last remaining owner cannot be demoted.
      </p>
    </div>
  );
}

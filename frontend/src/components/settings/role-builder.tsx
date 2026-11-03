"use client";

import { Plus, ShieldPlus, Trash2 } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/overlays";
import { Input, Label, Separator } from "@/components/ui/primitives";
import { useCreateRole, useDeleteRole, usePermissionCatalogue } from "@/hooks/use-api";
import { useAuthStore } from "@/stores/auth";
import { cn } from "@/lib/utils";
import type { PermissionOut, RoleOut } from "@/types/api";

/** Human labels for the permission groups, keyed by the resource prefix. */
const GROUP_LABELS: Record<string, string> = {
  dashboard: "Dashboard",
  growth: "Growth and opportunities",
  reviews: "Reviews",
  competitors: "Competitors",
  signals: "Market signals",
  customers: "Customers",
  products: "Products",
  inventory: "Inventory",
  campaign: "Campaigns",
  experiment: "Experiments",
  agents: "Agents",
  audit: "Audit log",
  users: "People and access",
  settings: "Settings",
};

export function RoleBuilder({ roles }: { roles: RoleOut[] }) {
  const [open, setOpen] = React.useState(false);
  const { data: catalogue } = usePermissionCatalogue();
  const create = useCreateRole();
  const remove = useDeleteRole();
  const myPermissions = useAuthStore((s) => s.user?.permissions ?? []);

  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [selected, setSelected] = React.useState<Set<string>>(new Set());

  const groups = React.useMemo(() => {
    const byResource = new Map<string, PermissionOut[]>();
    for (const permission of catalogue ?? []) {
      const list = byResource.get(permission.resource) ?? [];
      list.push(permission);
      byResource.set(permission.resource, list);
    }
    return [...byResource.entries()].sort((a, b) =>
      (GROUP_LABELS[a[0]] ?? a[0]).localeCompare(GROUP_LABELS[b[0]] ?? b[0]),
    );
  }, [catalogue]);

  const customRoles = roles.filter((role) => role.is_custom);
  const valid = name.trim().length >= 2 && selected.size > 0;

  function toggle(code: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }

  function toggleGroup(codes: string[]) {
    const grantable = codes.filter((code) => myPermissions.includes(code));
    const allOn = grantable.every((code) => selected.has(code));
    setSelected((current) => {
      const next = new Set(current);
      for (const code of grantable) {
        if (allOn) next.delete(code);
        else next.add(code);
      }
      return next;
    });
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!valid) return;
    create.mutate(
      {
        name: name.trim(),
        description: description.trim(),
        permissions: [...selected],
      },
      {
        onSuccess: () => {
          setName("");
          setDescription("");
          setSelected(new Set());
          setOpen(false);
        },
      },
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium">Custom roles</p>
          <p className="text-sm text-muted-foreground">
            Built-in roles cannot be renamed or deleted. Create your own to grant exactly what a
            person needs.
          </p>
        </div>

        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button className="gap-2">
              <Plus className="h-4 w-4" />
              Create a role
            </Button>
          </DialogTrigger>

          <DialogContent className="max-h-[88vh] max-w-3xl overflow-y-auto">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <ShieldPlus className="h-4 w-4 text-primary" />
                Create a role
              </DialogTitle>
              <DialogDescription>
                Pick a name, then choose exactly what it can do. You can only grant permissions
                you hold yourself, and the backend re-checks every one on save.
              </DialogDescription>
            </DialogHeader>

            <form onSubmit={submit} className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="role-name">Role name</Label>
                  <Input
                    id="role-name"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder="e.g. Support"
                    required
                    minLength={2}
                    maxLength={32}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="role-description">Description</Label>
                  <Input
                    id="role-description"
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    placeholder="Read-only plus review triage"
                  />
                </div>
              </div>

              <Separator />

              <div className="flex items-center justify-between">
                <p className="text-sm font-medium">Permissions</p>
                <p className="text-2xs text-muted-foreground tabular-nums">
                  {selected.size} selected
                </p>
              </div>

              <div className="space-y-3">
                {groups.map(([resource, permissions]) => {
                  const codes = permissions.map((p) => p.code);
                  const grantable = codes.filter((code) => myPermissions.includes(code));
                  return (
                    <fieldset
                      key={resource}
                      className="rounded-lg border border-border p-3"
                      disabled={grantable.length === 0}
                    >
                      <legend className="flex items-center gap-2 px-1.5 text-xs font-semibold">
                        {GROUP_LABELS[resource] ?? resource}
                        {grantable.length > 0 && (
                          <button
                            type="button"
                            onClick={() => toggleGroup(codes)}
                            className="text-2xs font-medium text-primary hover:underline focus-ring"
                          >
                            Select all
                          </button>
                        )}
                      </legend>

                      <div className="grid gap-x-4 gap-y-1.5 sm:grid-cols-2">
                        {permissions.map((permission) => {
                          const allowed = myPermissions.includes(permission.code);
                          const checked = selected.has(permission.code);
                          return (
                            <label
                              key={permission.code}
                              title={
                                allowed
                                  ? permission.description
                                  : "You do not hold this permission, so you cannot grant it."
                              }
                              className={cn(
                                "flex items-start gap-2 rounded-md px-1.5 py-1 text-sm transition-colors",
                                allowed
                                  ? "cursor-pointer hover:bg-muted"
                                  : "cursor-not-allowed opacity-45",
                              )}
                            >
                              <input
                                type="checkbox"
                                className="mt-0.5 h-3.5 w-3.5 shrink-0 accent-[hsl(var(--primary))]"
                                checked={checked}
                                disabled={!allowed}
                                onChange={() => toggle(permission.code)}
                              />
                              <span className="min-w-0">
                                <span className="font-medium">{permission.action}</span>
                                <span className="ml-1.5 font-mono text-2xs text-muted-foreground">
                                  {permission.code}
                                </span>
                              </span>
                            </label>
                          );
                        })}
                      </div>
                    </fieldset>
                  );
                })}
              </div>

              <DialogFooter>
                <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
                  Cancel
                </Button>
                <Button type="submit" loading={create.isPending} disabled={!valid}>
                  Create role
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      {customRoles.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">
          No custom roles yet. The five built-in roles above cover most teams.
        </p>
      ) : (
        <div className="space-y-2">
          {customRoles.map((role) => (
            <div
              key={role.id ?? role.name}
              className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-border bg-card p-3"
            >
              <div className="min-w-0">
                <p className="text-sm font-semibold">{role.name}</p>
                {role.description && (
                  <p className="text-xs text-muted-foreground">{role.description}</p>
                )}
                <div className="mt-2 flex flex-wrap gap-1">
                  {role.permissions.map((code) => (
                    <span
                      key={code}
                      className="rounded border border-border bg-muted/60 px-1.5 py-0.5 font-mono text-2xs"
                    >
                      {code}
                    </span>
                  ))}
                </div>
              </div>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`Delete the ${role.name} role`}
                disabled={remove.isPending || !role.id}
                onClick={() => role.id && remove.mutate(role.id)}
              >
                <Trash2 className="h-4 w-4 text-destructive" />
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

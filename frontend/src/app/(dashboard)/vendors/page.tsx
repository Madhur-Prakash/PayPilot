"use client";

/**
 * Vendors.
 *
 * The automation picks a vendor for every automatic order, so this page is
 * really about what that choice depends on: which vendors are active, how many
 * SKUs each one can supply, and how long they take. A vendor supplying nothing
 * is called out, because it is the commonest reason an order silently fails to
 * be raised.
 */

import { Building2, Clock, Mail, Phone, Plus, Webhook } from "lucide-react";
import * as React from "react";

import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
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
import { useCreateVendor, useVendors } from "@/hooks/use-api";
import { useAuthStore } from "@/stores/auth";
import { cn, formatNumber } from "@/lib/utils";

const ORDERING_METHODS = [
  { value: "EMAIL", label: "Email", hint: "A purchase order is emailed when one is approved" },
  { value: "WEBHOOK", label: "Webhook", hint: "The order is POSTed to the vendor's endpoint" },
  { value: "MANUAL", label: "Manual", hint: "Nothing is sent; someone places it by hand" },
];

export default function VendorsPage() {
  const [creating, setCreating] = React.useState(false);
  const canManage = useAuthStore((s) => s.can("vendor:manage"));
  const { data, isLoading, error, refetch } = useVendors();

  const vendors = data ?? [];
  const active = vendors.filter((v) => v.is_active);
  const supplyingNothing = active.filter((v) => v.supplies === 0);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">Vendors</h2>
          <p className="text-sm text-muted-foreground">
            Who the automation can order from, and what each one supplies
          </p>
        </div>
        {canManage && (
          <Button size="sm" className="gap-1.5" onClick={() => setCreating(true)}>
            <Plus className="h-3.5 w-3.5" />
            Add vendor
          </Button>
        )}
      </div>

      {supplyingNothing.length > 0 && (
        <div className="rounded-xl border border-warning/40 bg-warning/5 p-3">
          <p className="text-xs font-medium text-warning">
            {supplyingNothing.length} active vendor
            {supplyingNothing.length === 1 ? "" : "s"} supply nothing
          </p>
          <p className="mt-0.5 text-2xs text-muted-foreground">
            A vendor with no linked SKUs can never be selected, so items that name it as their
            default fall through to the next candidate — or raise no order at all.
          </p>
        </div>
      )}

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">
            {formatNumber(active.length)} active
            {vendors.length !== active.length && ` · ${vendors.length - active.length} inactive`}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {isLoading && <LoadingRows rows={4} />}
          {error && <ErrorState error={error} onRetry={() => void refetch()} />}

          {!isLoading && !error && vendors.length === 0 && (
            <EmptyState
              icon={Building2}
              title="No vendors yet"
              description="Automatic ordering needs at least one vendor that supplies the item."
            />
          )}

          {vendors.map((vendor) => (
            <div
              key={vendor.id}
              className={cn(
                "rounded-xl border border-border bg-card p-3",
                !vendor.is_active && "opacity-60",
              )}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold">{vendor.name}</span>
                    <Badge variant="outline" className="gap-1 text-2xs">
                      {vendor.ordering_method === "WEBHOOK" ? (
                        <Webhook className="h-3 w-3" />
                      ) : vendor.ordering_method === "EMAIL" ? (
                        <Mail className="h-3 w-3" />
                      ) : null}
                      {vendor.ordering_method.toLowerCase()}
                    </Badge>
                    {!vendor.is_active && (
                      <span className="rounded-md bg-muted px-1.5 py-0.5 text-2xs font-semibold text-muted-foreground">
                        inactive
                      </span>
                    )}
                    {vendor.is_active && vendor.supplies === 0 && (
                      <span className="rounded-md bg-warning/10 px-1.5 py-0.5 text-2xs font-semibold text-warning">
                        supplies nothing
                      </span>
                    )}
                  </div>

                  <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-muted-foreground">
                    {vendor.contact_name && <span>{vendor.contact_name}</span>}
                    {vendor.email && (
                      <span className="inline-flex items-center gap-1">
                        <Mail className="h-3 w-3" />
                        {vendor.email}
                      </span>
                    )}
                    {vendor.phone && (
                      <span className="inline-flex items-center gap-1">
                        <Phone className="h-3 w-3" />
                        {vendor.phone}
                      </span>
                    )}
                    <span className="inline-flex items-center gap-1 tabular-nums">
                      <Clock className="h-3 w-3" />
                      {formatNumber(vendor.lead_time_days)} day lead time
                    </span>
                  </div>
                </div>

                <div className="text-right">
                  <p className="text-lg font-semibold leading-none tabular-nums">
                    {formatNumber(vendor.supplies)}
                  </p>
                  <p className="mt-1 text-2xs text-muted-foreground">
                    SKU{vendor.supplies === 1 ? "" : "s"} supplied
                  </p>
                </div>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <CreateVendorDialog open={creating} onClose={() => setCreating(false)} />
    </div>
  );
}

function CreateVendorDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const create = useCreateVendor();
  const [form, setForm] = React.useState({
    name: "",
    contact_name: "",
    email: "",
    phone: "",
    ordering_method: "EMAIL",
    webhook_url: "",
    lead_time_days: "3",
    is_active: true,
  });

  React.useEffect(() => {
    if (open) {
      setForm({
        name: "",
        contact_name: "",
        email: "",
        phone: "",
        ordering_method: "EMAIL",
        webhook_url: "",
        lead_time_days: "3",
        is_active: true,
      });
    }
  }, [open]);

  const method = form.ordering_method;
  // Each ordering method has one field it cannot work without, and finding that
  // out when an order fails to send is far too late.
  const missingEmail = method === "EMAIL" && !form.email.trim();
  const missingWebhook = method === "WEBHOOK" && !form.webhook_url.trim();
  const valid = form.name.trim().length >= 2 && !missingEmail && !missingWebhook;

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Add a vendor</DialogTitle>
          <DialogDescription>
            A vendor becomes selectable once it is linked to the items it supplies.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <Field
            id="vendor-name"
            label="Name"
            value={form.name}
            onChange={(v) => setForm((f) => ({ ...f, name: v }))}
            placeholder="Konkan Coffee Traders"
          />
          <Field
            id="vendor-contact"
            label="Contact person"
            value={form.contact_name}
            onChange={(v) => setForm((f) => ({ ...f, contact_name: v }))}
            placeholder="Optional"
          />

          <div className="space-y-1.5">
            <Label htmlFor="ordering-method">How orders reach them</Label>
            <Select
              value={form.ordering_method}
              onValueChange={(value) => setForm((f) => ({ ...f, ordering_method: value }))}
            >
              <SelectTrigger id="ordering-method">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ORDERING_METHODS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-2xs text-muted-foreground">
              {ORDERING_METHODS.find((o) => o.value === method)?.hint}
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field
              id="vendor-email"
              label="Email"
              type="email"
              value={form.email}
              onChange={(v) => setForm((f) => ({ ...f, email: v }))}
              invalid={missingEmail}
              hint={missingEmail ? "Required to email orders" : undefined}
            />
            <Field
              id="vendor-phone"
              label="Phone"
              value={form.phone}
              onChange={(v) => setForm((f) => ({ ...f, phone: v }))}
            />
          </div>

          {method === "WEBHOOK" && (
            <Field
              id="vendor-webhook"
              label="Webhook URL"
              value={form.webhook_url}
              onChange={(v) => setForm((f) => ({ ...f, webhook_url: v }))}
              placeholder="https://vendor.example.com/orders"
              invalid={missingWebhook}
              hint={missingWebhook ? "Required to POST orders" : undefined}
            />
          )}

          <Field
            id="vendor-lead"
            label="Lead time (days)"
            type="number"
            value={form.lead_time_days}
            onChange={(v) => setForm((f) => ({ ...f, lead_time_days: v }))}
          />

          <Separator />

          <label className="flex items-center justify-between gap-3">
            <span className="text-sm font-medium">Active</span>
            <Switch
              checked={form.is_active}
              onCheckedChange={(checked: boolean) =>
                setForm((f) => ({ ...f, is_active: checked }))
              }
            />
          </label>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={create.isPending}
            disabled={!valid}
            onClick={() =>
              create.mutate(
                {
                  ...form,
                  name: form.name.trim(),
                  lead_time_days: Number(form.lead_time_days) || 0,
                },
                { onSuccess: onClose },
              )
            }
          >
            Add vendor
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Field({
  id,
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  hint,
  invalid,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
  hint?: string;
  invalid?: boolean;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className={cn(invalid && "border-destructive")}
      />
      {hint && (
        <p className={cn("text-2xs", invalid ? "text-destructive" : "text-muted-foreground")}>
          {hint}
        </p>
      )}
    </div>
  );
}

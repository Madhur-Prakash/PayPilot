"use client";

/**
 * One SKU, end to end.
 *
 * The page is organised around a question an operator actually asks: "why is
 * this thing about to run out, and what is the system going to do about it?"
 * So the reorder decision - including the reasons it decided *not* to order -
 * sits above the policy that produced it, and the ledger below shows every
 * movement that got the stock here.
 */

import {
  AlertTriangle,
  ArrowLeft,
  Boxes,
  CalendarClock,
  Check,
  Pencil,
  ShoppingCart,
  Wifi,
  WifiOff,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";

import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { MovementRow } from "@/components/inventory/movement-row";
import { StatusChip, StockBar } from "@/components/inventory/stock-status";
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
  Textarea,
} from "@/components/ui/primitives";
import {
  useAdjustStock,
  useForceReorder,
  useInventoryItem,
  useInventoryLedger,
  useSetInventoryPolicy,
} from "@/hooks/use-api";
import { useInventoryStream } from "@/hooks/use-inventory-stream";
import { useAuthStore } from "@/stores/auth";
import { cn, formatCompactCurrency, formatDate, formatNumber } from "@/lib/utils";

const STRATEGIES = [
  { value: "FIXED_QUANTITY", label: "Fixed quantity", hint: "Always order the same amount" },
  { value: "TARGET_MAX_STOCK", label: "Top up to maximum", hint: "Order the gap to the ceiling" },
];

const MOVEMENT_TYPES = [
  { value: "ADJUSTMENT", label: "Correction" },
  { value: "DAMAGE", label: "Damaged" },
  { value: "EXPIRY", label: "Expired" },
  { value: "TRANSFER_OUT", label: "Transferred out" },
  { value: "TRANSFER_IN", label: "Transferred in" },
  { value: "CUSTOMER_RETURN", label: "Customer return" },
];

const BATCH_TONE: Record<string, string> = {
  ACTIVE: "bg-success/10 text-success",
  EXPIRING_SOON: "bg-warning/10 text-warning",
  EXPIRED: "bg-destructive/10 text-destructive",
  DEPLETED: "bg-muted text-muted-foreground",
  QUARANTINED: "bg-destructive/10 text-destructive",
};

export default function InventoryItemPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id ?? null;

  const [adjusting, setAdjusting] = React.useState(false);
  const [editingPolicy, setEditingPolicy] = React.useState(false);

  const { status: streamStatus } = useInventoryStream({ notify: false });

  const canWrite = useAuthStore((s) => s.can("inventory:write"));
  const canConfigure = useAuthStore((s) => s.can("inventory:configure"));
  const canReorder = useAuthStore((s) => s.can("purchase_order:create"));
  const canReadLedger = useAuthStore((s) => s.can("inventory:ledger_read"));

  const reorder = useForceReorder();
  const { data: item, isLoading, error, refetch } = useInventoryItem(id);
  const ledger = useInventoryLedger(
    canReadLedger && id ? { inventory_item_id: id, page_size: 25 } : {},
  );

  if (isLoading) {
    return (
      <div className="space-y-4">
        <BackLink />
        <LoadingRows rows={6} />
      </div>
    );
  }

  if (error || !item) {
    return (
      <div className="space-y-4">
        <BackLink />
        <ErrorState
          error={error ?? new Error("That item does not exist for this merchant.")}
          onRetry={() => void refetch()}
        />
      </div>
    );
  }

  const decision = item.decision;
  const movements = ledger.data?.items ?? [];

  return (
    <div className="space-y-6">
      <BackLink />

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-xl font-semibold tracking-tight">{item.product_name}</h2>
            <span className="font-mono text-2xs text-muted-foreground">{item.sku}</span>
            <StatusChip status={item.status} />
            {item.automatic_ordering_enabled && (
              <Badge variant="outline" className="text-2xs">
                auto-ordering on
              </Badge>
            )}
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            Supplied by {item.supplier || "no vendor set"}
            {item.days_of_cover != null && ` · ${formatNumber(item.days_of_cover)} days of cover`}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span
            className={cn(
              "inline-flex items-center gap-1.5 rounded-lg border px-2 py-1 text-2xs font-medium",
              streamStatus === "live"
                ? "border-success/30 bg-success/10 text-success"
                : "border-border bg-muted text-muted-foreground",
            )}
          >
            {streamStatus === "live" ? (
              <Wifi className="h-3 w-3" />
            ) : (
              <WifiOff className="h-3 w-3" />
            )}
            {streamStatus === "live" ? "Live" : streamStatus}
          </span>
          {canWrite && (
            <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setAdjusting(true)}>
              <Pencil className="h-3.5 w-3.5" />
              Adjust stock
            </Button>
          )}
          {canReorder && (
            <Button
              size="sm"
              className="gap-1.5"
              loading={reorder.isPending}
              onClick={() => reorder.mutate(item.id)}
            >
              <ShoppingCart className="h-3.5 w-3.5" />
              Reorder now
            </Button>
          )}
        </div>
      </div>

      {/* Stock position */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Stock position</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Figure label="On hand" value={formatNumber(item.quantity_on_hand)} unit={item.unit} />
            <Figure
              label="Reserved"
              value={formatNumber(item.reserved_quantity)}
              unit={item.unit}
              hint="Committed, not yet shipped"
            />
            <Figure
              label="Available"
              value={formatNumber(item.available_quantity)}
              unit={item.unit}
              hint="What the automation acts on"
              tone={item.available_quantity <= item.reorder_point ? "warning" : "default"}
            />
            {item.stock_value != null ? (
              <Figure label="Stock value" value={formatCompactCurrency(item.stock_value)} />
            ) : (
              <Figure label="Reorder at" value={formatNumber(item.reorder_point)} unit={item.unit} />
            )}
          </div>

          <StockBar
            available={item.available_quantity}
            reorderPoint={item.reorder_point}
            maximum={item.maximum_stock}
          />
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* The decision */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">What the automation decided</CardTitle>
            <p className="text-sm text-muted-foreground">
              Computed live from the policy below - this is the same call the automation makes.
            </p>
          </CardHeader>
          <CardContent className="space-y-3">
            <div
              className={cn(
                "flex items-start gap-3 rounded-xl border p-3",
                decision.should_reorder
                  ? "border-warning/40 bg-warning/5"
                  : "border-border bg-muted/30",
              )}
            >
              <span
                className={cn(
                  "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
                  decision.should_reorder
                    ? "bg-warning/10 text-warning"
                    : "bg-success/10 text-success",
                )}
              >
                {decision.should_reorder ? (
                  <AlertTriangle className="h-4 w-4" />
                ) : (
                  <Check className="h-4 w-4" />
                )}
              </span>
              <div className="min-w-0">
                <p className="text-sm font-medium">
                  {decision.should_reorder
                    ? `Order ${formatNumber(decision.quantity)} ${item.unit}`
                    : "No order needed"}
                </p>
                <p className="mt-0.5 text-2xs leading-relaxed text-muted-foreground">
                  {decision.reason}
                </p>
              </div>
            </div>

            {decision.blockers.length > 0 && (
              <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-3">
                <p className="text-2xs font-semibold text-destructive">
                  Stopping an order from being raised
                </p>
                <ul className="mt-1.5 space-y-1">
                  {decision.blockers.map((blocker) => (
                    <li key={blocker} className="text-2xs text-muted-foreground">
                      · {blocker}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <Separator />

            <dl className="space-y-1.5 text-2xs tabular-nums">
              <Row term="Strategy" value={labelForStrategy(item.reorder_strategy)} />
              <Row term="Reorder point" value={`${formatNumber(item.reorder_point)} ${item.unit}`} />
              <Row
                term="Reorder quantity"
                value={`${formatNumber(item.reorder_quantity)} ${item.unit}`}
              />
              <Row term="Maximum stock" value={`${formatNumber(item.maximum_stock)} ${item.unit}`} />
              <Row
                term="Automatic ordering"
                value={item.automatic_ordering_enabled ? "On" : "Off"}
              />
            </dl>

            {canConfigure && (
              <Button
                variant="outline"
                size="sm"
                className="w-full gap-1.5"
                onClick={() => setEditingPolicy(true)}
              >
                <Pencil className="h-3.5 w-3.5" />
                Edit reorder policy
              </Button>
            )}
          </CardContent>
        </Card>

        {/* Batches */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Batches</CardTitle>
            <p className="text-sm text-muted-foreground">
              {item.expiry_tracking_enabled
                ? "Oldest expiry first - the nightly sweep flags these."
                : "Expiry tracking is off for this item."}
            </p>
          </CardHeader>
          <CardContent className="space-y-2">
            {item.batches.length === 0 && (
              <EmptyState
                icon={CalendarClock}
                title="No batches recorded"
                description="Batches appear when a delivery is received against a batch code."
              />
            )}
            {item.batches.map((batch) => (
              <div
                key={batch.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-card px-3 py-2"
              >
                <div className="min-w-0">
                  <span className="font-mono text-xs font-medium">{batch.batch_code}</span>
                  <p className="mt-0.5 text-2xs text-muted-foreground tabular-nums">
                    {formatNumber(batch.quantity)} {item.unit}
                    {batch.expiry_date && ` · expires ${formatDate(batch.expiry_date)}`}
                  </p>
                </div>
                <span
                  className={cn(
                    "rounded-md px-1.5 py-0.5 text-2xs font-semibold",
                    BATCH_TONE[batch.status] ?? "bg-muted text-muted-foreground",
                  )}
                >
                  {batch.status.toLowerCase().replace(/_/g, " ")}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      {/* Ledger */}
      {canReadLedger && (
        <Card>
          <CardHeader className="pb-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <CardTitle className="text-base">Movement history</CardTitle>
                <p className="text-sm text-muted-foreground">
                  Append-only. Every row records what moved, who moved it and what it left behind.
                </p>
              </div>
              <Button asChild variant="ghost" size="sm">
                <Link href={`/inventory/ledger?item=${item.id}`}>Open full ledger</Link>
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            {ledger.isLoading && <LoadingRows rows={4} />}
            {ledger.error && (
              <ErrorState error={ledger.error} onRetry={() => void ledger.refetch()} />
            )}
            {!ledger.isLoading && !ledger.error && movements.length === 0 && (
              <EmptyState
                icon={Boxes}
                title="Nothing has moved yet"
                description="Sales, receipts and corrections all land here."
              />
            )}
            {movements.map((row) => (
              <MovementRow key={row.id} row={row} unit={item.unit} />
            ))}
          </CardContent>
        </Card>
      )}

      <AdjustDialog
        open={adjusting}
        unit={item.unit}
        onHand={item.quantity_on_hand}
        onClose={() => setAdjusting(false)}
        itemId={item.id}
      />

      <PolicyDialog
        open={editingPolicy}
        item={item}
        onClose={() => setEditingPolicy(false)}
      />
    </div>
  );
}

function BackLink() {
  return (
    <Link
      href="/inventory"
      className="inline-flex items-center gap-1.5 text-2xs font-medium text-muted-foreground transition-colors hover:text-foreground focus-ring"
    >
      <ArrowLeft className="h-3.5 w-3.5" />
      All inventory
    </Link>
  );
}

function Figure({
  label,
  value,
  unit,
  hint,
  tone = "default",
}: {
  label: string;
  value: string;
  unit?: string;
  hint?: string;
  tone?: "default" | "warning";
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-3">
      <p className="text-2xs text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-1 text-lg font-semibold leading-none tracking-tight tabular-nums",
          tone === "warning" && "text-warning",
        )}
      >
        {value}
        {unit && <span className="ml-1 text-2xs font-normal text-muted-foreground">{unit}</span>}
      </p>
      {hint && <p className="mt-1 text-2xs text-muted-foreground/80">{hint}</p>}
    </div>
  );
}

function Row({ term, value }: { term: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-muted-foreground">{term}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}

function labelForStrategy(value: string) {
  return STRATEGIES.find((s) => s.value === value)?.label ?? value.toLowerCase().replace(/_/g, " ");
}

function AdjustDialog({
  open,
  onClose,
  itemId,
  unit,
  onHand,
}: {
  open: boolean;
  onClose: () => void;
  itemId: string;
  unit: string;
  onHand: number;
}) {
  const adjust = useAdjustStock();
  const [movementType, setMovementType] = React.useState("ADJUSTMENT");
  const [quantity, setQuantity] = React.useState("");
  const [note, setNote] = React.useState("");

  React.useEffect(() => {
    if (open) {
      setMovementType("ADJUSTMENT");
      setQuantity("");
      setNote("");
    }
  }, [open]);

  const amount = Number(quantity);
  const valid = amount > 0 && note.trim().length > 0;

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Adjust stock</DialogTitle>
          <DialogDescription>
            This writes a ledger row against your name. Current stock is{" "}
            {formatNumber(onHand)} {unit}.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="movement-type">Reason</Label>
            <Select value={movementType} onValueChange={setMovementType}>
              <SelectTrigger id="movement-type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {MOVEMENT_TYPES.map((type) => (
                  <SelectItem key={type.value} value={type.value}>
                    {type.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="quantity">Quantity ({unit})</Label>
            <Input
              id="quantity"
              type="number"
              min={0}
              step="any"
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
              placeholder="0"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="note">Why</Label>
            <Textarea
              id="note"
              rows={2}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="Three bags found water-damaged in the back store."
            />
            <p className="text-2xs text-muted-foreground">
              Required. An unexplained correction is indistinguishable from shrinkage.
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={adjust.isPending}
            disabled={!valid}
            onClick={() =>
              adjust.mutate(
                { id: itemId, movement_type: movementType, quantity: amount, note: note.trim() },
                { onSuccess: onClose },
              )
            }
          >
            Record adjustment
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PolicyDialog({
  open,
  onClose,
  item,
}: {
  open: boolean;
  onClose: () => void;
  item: {
    id: string;
    unit: string;
    reorder_point: number;
    reorder_quantity: number;
    maximum_stock: number;
    reorder_strategy: string;
    automatic_ordering_enabled: boolean;
  };
}) {
  const save = useSetInventoryPolicy();
  const [form, setForm] = React.useState({
    reorder_point: String(item.reorder_point),
    reorder_quantity: String(item.reorder_quantity),
    maximum_stock: String(item.maximum_stock),
    reorder_strategy: item.reorder_strategy,
    automatic_ordering_enabled: item.automatic_ordering_enabled,
  });

  React.useEffect(() => {
    if (open) {
      setForm({
        reorder_point: String(item.reorder_point),
        reorder_quantity: String(item.reorder_quantity),
        maximum_stock: String(item.maximum_stock),
        reorder_strategy: item.reorder_strategy,
        automatic_ordering_enabled: item.automatic_ordering_enabled,
      });
    }
  }, [open, item]);

  const topUp = form.reorder_strategy === "TARGET_MAX_STOCK";
  const maximum = Number(form.maximum_stock);
  const point = Number(form.reorder_point);
  // The backend rejects this too; catching it here explains it rather than
  // surfacing a validation error after the fact.
  const invalidCeiling = topUp && maximum <= point;

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Reorder policy</DialogTitle>
          <DialogDescription>
            These numbers drive the automation. Changing them changes what it orders tonight.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="strategy">Strategy</Label>
            <Select
              value={form.reorder_strategy}
              onValueChange={(value) => setForm((f) => ({ ...f, reorder_strategy: value }))}
            >
              <SelectTrigger id="strategy">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {STRATEGIES.map((strategy) => (
                  <SelectItem key={strategy.value} value={strategy.value}>
                    {strategy.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-2xs text-muted-foreground">
              {STRATEGIES.find((s) => s.value === form.reorder_strategy)?.hint}
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <NumberField
              id="reorder-point"
              label={`Reorder at (${item.unit})`}
              value={form.reorder_point}
              onChange={(v) => setForm((f) => ({ ...f, reorder_point: v }))}
            />
            <NumberField
              id="reorder-quantity"
              label={`Order quantity (${item.unit})`}
              value={form.reorder_quantity}
              onChange={(v) => setForm((f) => ({ ...f, reorder_quantity: v }))}
              disabled={topUp}
              hint={topUp ? "Ignored by top-up" : undefined}
            />
          </div>

          <NumberField
            id="maximum-stock"
            label={`Maximum stock (${item.unit})`}
            value={form.maximum_stock}
            onChange={(v) => setForm((f) => ({ ...f, maximum_stock: v }))}
            hint={
              invalidCeiling
                ? "Must be above the reorder point, or top-up has nothing to order."
                : undefined
            }
            invalid={invalidCeiling}
          />

          <Separator />

          <label className="flex items-start justify-between gap-3">
            <span>
              <span className="text-sm font-medium">Automatic ordering</span>
              <span className="mt-0.5 block text-2xs text-muted-foreground">
                Off means the system still flags this item, but raises nothing by itself.
              </span>
            </span>
            <Switch
              checked={form.automatic_ordering_enabled}
              onCheckedChange={(checked) =>
                setForm((f) => ({ ...f, automatic_ordering_enabled: checked }))
              }
            />
          </label>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={save.isPending}
            disabled={invalidCeiling}
            onClick={() =>
              save.mutate(
                {
                  id: item.id,
                  reorder_point: Number(form.reorder_point),
                  reorder_quantity: Number(form.reorder_quantity),
                  maximum_stock: Number(form.maximum_stock),
                  reorder_strategy: form.reorder_strategy,
                  automatic_ordering_enabled: form.automatic_ordering_enabled,
                },
                { onSuccess: onClose },
              )
            }
          >
            Save policy
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function NumberField({
  id,
  label,
  value,
  onChange,
  disabled,
  hint,
  invalid,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  hint?: string;
  invalid?: boolean;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="number"
        min={0}
        step="any"
        value={value}
        disabled={disabled}
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

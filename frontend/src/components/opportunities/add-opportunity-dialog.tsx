"use client";

/**
 * Add an opportunity by hand.
 *
 * The detector only sees what is in the transactions. A merchant routinely knows
 * something it cannot: a lease ending, a competitor closing, a supplier offer.
 * This puts that on the same board, ranked by the same formula, so it competes
 * with the detected ones instead of living in someone's head.
 */

import { Lightbulb } from "lucide-react";
import * as React from "react";

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
} from "@/components/ui/overlays";
import { Input, Label, Separator, Textarea } from "@/components/ui/primitives";
import { useCreateOpportunity } from "@/hooks/use-api";
import { formatCompactCurrency } from "@/lib/utils";

/** Mirrors OpportunityKind on the backend; the kind decides which hub it joins. */
const KINDS = [
  { value: "RETENTION", label: "Retention", hint: "Keeping customers who might leave" },
  { value: "BUNDLE", label: "Bundle", hint: "Selling two things together" },
  { value: "DAYPART", label: "Daypart", hint: "A particular time of day" },
  { value: "PRODUCT", label: "Product", hint: "A single item's performance" },
  { value: "PRICING", label: "Pricing", hint: "What you charge" },
  { value: "SERVICE", label: "Service", hint: "Speed, quality, experience" },
  { value: "INVENTORY", label: "Inventory", hint: "Stock and supply" },
];

const LEVELS = ["LOW", "MEDIUM", "HIGH"] as const;

export function AddOpportunityDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  /** Handed the new id so the caller can point at it once it arrives. */
  onCreated?: (id: string) => void;
}) {
  const create = useCreateOpportunity();
  const [form, setForm] = React.useState({
    title: "",
    summary: "",
    kind: "RETENTION",
    estimated_value_monthly: "",
    confidence: "60",
    effort: "MEDIUM" as (typeof LEVELS)[number],
    impact: "MEDIUM" as (typeof LEVELS)[number],
    recommended_action: "",
  });

  React.useEffect(() => {
    if (open) {
      setForm({
        title: "",
        summary: "",
        kind: "RETENTION",
        estimated_value_monthly: "",
        confidence: "60",
        effort: "MEDIUM",
        impact: "MEDIUM",
        recommended_action: "",
      });
    }
  }, [open]);

  const value = Number(form.estimated_value_monthly) || 0;
  const confidence = Math.min(100, Math.max(0, Number(form.confidence) || 0));
  const valid = form.title.trim().length >= 4;

  // The same ranking the detector uses, shown live so nobody is surprised by
  // where their node lands on the board.
  const penalty = { LOW: 1, MEDIUM: 0.85, HIGH: 0.65 }[form.effort];
  const priority = value * (confidence / 100) * penalty;

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent
        className="max-h-[85vh] max-w-lg overflow-y-auto"
        onOpenAutoFocus={(event) => event.preventDefault()}
      >
        <DialogHeader>
          <DialogTitle>Add an opportunity</DialogTitle>
          <DialogDescription>
            For something you know that the data cannot show. It joins the board as a normal
            opportunity and can be approved and measured like any other.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="opp-title">What is it?</Label>
            <Input
              id="opp-title"
              value={form.title}
              onChange={(event) => setForm((f) => ({ ...f, title: event.target.value }))}
              placeholder="Café next door is closing in October"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="opp-summary">Why does it matter?</Label>
            <Textarea
              id="opp-summary"
              rows={2}
              value={form.summary}
              onChange={(event) => setForm((f) => ({ ...f, summary: event.target.value }))}
              placeholder="Their regulars will be looking for somewhere new for a few weeks."
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="opp-kind">Kind</Label>
            <Select
              value={form.kind}
              onValueChange={(kind) => setForm((f) => ({ ...f, kind }))}
            >
              <SelectTrigger id="opp-kind">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {KINDS.map((kind) => (
                  <SelectItem key={kind.value} value={kind.value}>
                    {kind.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-2xs text-muted-foreground">
              {KINDS.find((k) => k.value === form.kind)?.hint} — this decides which hub it
              attaches to on the canvas.
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="opp-value">Worth per month (₹)</Label>
              <Input
                id="opp-value"
                type="number"
                min={0}
                value={form.estimated_value_monthly}
                onChange={(event) =>
                  setForm((f) => ({ ...f, estimated_value_monthly: event.target.value }))
                }
                placeholder="0"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="opp-confidence">How sure are you? (%)</Label>
              <Input
                id="opp-confidence"
                type="number"
                min={0}
                max={100}
                value={form.confidence}
                onChange={(event) => setForm((f) => ({ ...f, confidence: event.target.value }))}
              />
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <LevelField
              id="opp-effort"
              label="Effort"
              value={form.effort}
              onChange={(effort) => setForm((f) => ({ ...f, effort }))}
            />
            <LevelField
              id="opp-impact"
              label="Impact"
              value={form.impact}
              onChange={(impact) => setForm((f) => ({ ...f, impact }))}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="opp-action">What would you do about it?</Label>
            <Textarea
              id="opp-action"
              rows={2}
              value={form.recommended_action}
              onChange={(event) =>
                setForm((f) => ({ ...f, recommended_action: event.target.value }))
              }
              placeholder="Put a welcome offer card in the window for four weeks."
            />
          </div>

          <Separator />

          <div className="flex items-start gap-2 rounded-lg bg-muted/40 p-2.5">
            <Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <p className="text-2xs text-muted-foreground">
              Ranked at{" "}
              <span className="font-semibold tabular-nums text-foreground">
                {formatCompactCurrency(priority)}
              </span>{" "}
              — worth per month, discounted by your confidence and the effort. The same formula
              the detector uses, so this competes with detected opportunities rather than
              jumping the queue.
            </p>
          </div>
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
                  title: form.title.trim(),
                  summary: form.summary.trim(),
                  kind: form.kind,
                  estimated_value_monthly: value,
                  confidence: confidence / 100,
                  effort: form.effort,
                  impact: form.impact,
                  recommended_action: form.recommended_action.trim(),
                },
                {
                  onSuccess: (created) => {
                    onCreated?.(created.id);
                    onClose();
                  },
                },
              )
            }
          >
            Add to board
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function LevelField({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: (typeof LEVELS)[number];
  onChange: (value: (typeof LEVELS)[number]) => void;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Select value={value} onValueChange={(next) => onChange(next as (typeof LEVELS)[number])}>
        <SelectTrigger id={id}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {LEVELS.map((level) => (
            <SelectItem key={level} value={level}>
              {level.charAt(0) + level.slice(1).toLowerCase()}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

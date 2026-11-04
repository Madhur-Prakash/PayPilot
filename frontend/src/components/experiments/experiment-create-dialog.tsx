"use client";

import { Plus } from "lucide-react";
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/overlays";
import { Input, Label, Separator, Textarea } from "@/components/ui/primitives";
import { useCreateExperiment } from "@/hooks/use-api";

const METRICS = [
  { value: "conversion_rate", label: "Conversion rate" },
  { value: "revenue_per_customer", label: "Revenue per customer" },
  { value: "aov", label: "Average order value" },
];

export function ExperimentCreateDialog() {
  const [open, setOpen] = React.useState(false);
  const create = useCreateExperiment();

  const [name, setName] = React.useState("");
  const [hypothesis, setHypothesis] = React.useState("");
  const [metric, setMetric] = React.useState("conversion_rate");
  const [threshold, setThreshold] = React.useState("10");
  const [duration, setDuration] = React.useState("14");
  const [controlSplit, setControlSplit] = React.useState("50");
  const [offer, setOffer] = React.useState("");
  const [unitCost, setUnitCost] = React.useState("");

  const splitValue = Number(controlSplit);
  const splitValid = splitValue > 0 && splitValue < 100;
  const valid = name.trim().length >= 3 && hypothesis.trim().length >= 10 && splitValid;

  function reset() {
    setName("");
    setHypothesis("");
    setMetric("conversion_rate");
    setThreshold("10");
    setDuration("14");
    setControlSplit("50");
    setOffer("");
    setUnitCost("");
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!valid) return;
    create.mutate(
      {
        name: name.trim(),
        hypothesis: hypothesis.trim(),
        success_metric: metric,
        success_threshold_pct: Number(threshold) || 10,
        duration_days: Number(duration) || 14,
        control_split_pct: splitValue,
        test_offer_description: offer.trim(),
        unit_cost: unitCost ? Number(unitCost) : 0,
      },
      {
        onSuccess: () => {
          reset();
          setOpen(false);
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button className="gap-2">
          <Plus className="h-4 w-4" />
          New experiment
        </Button>
      </DialogTrigger>

      <DialogContent className="max-h-[88vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>New experiment</DialogTitle>
          <DialogDescription>
            Creates a draft with a held-out control group. Approving it splits the audience on a
            hash of the customer id, so allocation is stable across re-runs.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="experiment-name">Name</Label>
            <Input
              id="experiment-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Loyalty drip card"
              required
              minLength={3}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="experiment-hypothesis">Hypothesis</Label>
            <Textarea
              id="experiment-hypothesis"
              value={hypothesis}
              onChange={(event) => setHypothesis(event.target.value)}
              placeholder="A pre-paid drip coffee card will increase visit frequency among customers who already order chai at least twice a week."
              rows={3}
              required
              minLength={10}
            />
            <p className="text-xs text-muted-foreground">
              State what you expect to change and for whom. At least 10 characters.
            </p>
          </div>

          <Separator />

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="experiment-metric">Success metric</Label>
              <Select value={metric} onValueChange={setMetric}>
                <SelectTrigger id="experiment-metric">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {METRICS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="experiment-threshold">Success threshold (%)</Label>
              <Input
                id="experiment-threshold"
                type="number"
                min={0}
                max={500}
                value={threshold}
                onChange={(event) => setThreshold(event.target.value)}
              />
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="experiment-duration">Duration (days)</Label>
              <Input
                id="experiment-duration"
                type="number"
                min={1}
                max={120}
                value={duration}
                onChange={(event) => setDuration(event.target.value)}
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="experiment-split">Control split (%)</Label>
              <Input
                id="experiment-split"
                type="number"
                min={1}
                max={99}
                value={controlSplit}
                onChange={(event) => setControlSplit(event.target.value)}
                aria-invalid={!splitValid}
              />
              <p className="text-xs text-muted-foreground tabular-nums">
                {splitValid
                  ? `${splitValue}% control · ${100 - splitValue}% test`
                  : "Must be between 1 and 99."}
              </p>
            </div>
          </div>

          <Separator />

          <div className="space-y-1.5">
            <Label htmlFor="experiment-offer">Test offer</Label>
            <Input
              id="experiment-offer"
              value={offer}
              onChange={(event) => setOffer(event.target.value)}
              placeholder="10 House Drip Coffees for $24.50, valid 30 days"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="experiment-cost">Unit cost ($)</Label>
            <Input
              id="experiment-cost"
              type="number"
              min={0}
              value={unitCost}
              onChange={(event) => setUnitCost(event.target.value)}
              placeholder="0"
            />
            <p className="text-xs text-muted-foreground">
              Used to compute incremental profit and ROI, not just revenue.
            </p>
          </div>

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={create.isPending} disabled={!valid}>
              Create draft
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

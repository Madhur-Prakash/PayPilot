"use client";

import { Plus } from "lucide-react";
import * as React from "react";

import { CampaignSurfaceBadge } from "@/components/campaigns/growth-intelligence";
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
import { useCreateCampaign } from "@/hooks/use-api";
import { cn } from "@/lib/utils";
import type { CampaignSurface } from "@/types/api";

const CHANNELS = [
  { value: "paypal_app", label: "PayPal Checkout offer" },
  { value: "sms", label: "SMS" },
  { value: "whatsapp", label: "WhatsApp" },
  { value: "email", label: "Email" },
  { value: "in_store", label: "In store" },
];

const SURFACES: { value: CampaignSurface; label: string; hint: string }[] = [
  { value: "BUSINESS", label: "Business", hint: "Your own customers, your budget" },
  { value: "PAYPAL", label: "PayPal", hint: "Cashback via PayPal Payouts, Pay Later, checkout offers" },
  { value: "HYBRID", label: "Hybrid", hint: "Both, split across two budgets" },
];

const OBJECTIVE_TYPES: { value: string; label: string }[] = [
  { value: "", label: "Not classified" },
  { value: "RETENTION", label: "Retention" },
  { value: "REACTIVATION", label: "Reactivation" },
  { value: "ACQUISITION", label: "Acquisition" },
  { value: "CROSS_SELL", label: "Cross-sell" },
  { value: "INVENTORY_CLEARANCE", label: "Inventory clearance" },
  { value: "CAPACITY_UTILIZATION", label: "Capacity utilization" },
  { value: "REVENUE_RECOVERY", label: "Revenue recovery" },
  { value: "PROFIT_OPTIMIZATION", label: "Profit optimization" },
];

const OFFER_TYPES = [
  { value: "COMBO", label: "Combo" },
  { value: "PERCENT_DISCOUNT", label: "Percent discount" },
  { value: "FLAT_DISCOUNT", label: "Flat discount" },
  { value: "CASHBACK", label: "Cashback" },
  { value: "FREE_ITEM", label: "Free item" },
  { value: "NONE", label: "No offer" },
];

const DAYPARTS = ["MORNING", "AFTERNOON", "EVENING", "NIGHT"];

export function CampaignCreateDialog() {
  const [open, setOpen] = React.useState(false);
  const create = useCreateCampaign();

  const [name, setName] = React.useState("");
  const [objective, setObjective] = React.useState("");
  const [channel, setChannel] = React.useState("paypal_app");
  const [offerType, setOfferType] = React.useState("COMBO");
  const [offerValue, setOfferValue] = React.useState("");
  const [offerDescription, setOfferDescription] = React.useState("");
  const [message, setMessage] = React.useState("");
  const [budget, setBudget] = React.useState("");
  const [audienceName, setAudienceName] = React.useState("");
  const [dayparts, setDayparts] = React.useState<string[]>([]);
  const [minOrders, setMinOrders] = React.useState("");
  const [surface, setSurface] = React.useState<CampaignSurface>("BUSINESS");
  const [objectiveType, setObjectiveType] = React.useState("");
  const [businessBudget, setBusinessBudget] = React.useState("");
  const [paypalBudget, setPaypalBudget] = React.useState("");

  const isHybrid = surface === "HYBRID";
  const valid =
    name.trim().length >= 3 &&
    message.trim().length > 0 &&
    (!isHybrid || (Number(businessBudget) > 0 && Number(paypalBudget) > 0));

  function reset() {
    setName("");
    setObjective("");
    setChannel("paypal_app");
    setOfferType("COMBO");
    setOfferValue("");
    setOfferDescription("");
    setMessage("");
    setBudget("");
    setAudienceName("");
    setDayparts([]);
    setMinOrders("");
    setSurface("BUSINESS");
    setObjectiveType("");
    setBusinessBudget("");
    setPaypalBudget("");
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!valid) return;

    const audience =
      audienceName.trim() || dayparts.length > 0 || minOrders
        ? {
            name: audienceName.trim() || "Targeted audience",
            dayparts,
            ...(minOrders ? { min_orders: Number(minOrders) } : {}),
          }
        : undefined;

    create.mutate(
      {
        name: name.trim(),
        objective: objective.trim(),
        offer_type: offerType,
        offer_value: offerValue ? Number(offerValue) : 0,
        offer_description: offerDescription.trim(),
        message: message.trim(),
        channel,
        budget: isHybrid ? undefined : budget ? Number(budget) : 0,
        surface,
        objective_type: objectiveType,
        business_budget: businessBudget ? Number(businessBudget) : 0,
        paypal_budget: paypalBudget ? Number(paypalBudget) : 0,
        ...(audience ? { audience } : {}),
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
          New campaign
        </Button>
      </DialogTrigger>

      <DialogContent className="max-h-[88vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>New campaign</DialogTitle>
          <DialogDescription>
            This creates a draft that needs your explicit approval. Nothing is sent until you
            approve and launch it.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="campaign-name">Name</Label>
            <Input
              id="campaign-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Evening win-back"
              required
              minLength={3}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="campaign-objective">Objective</Label>
            <Input
              id="campaign-objective"
              value={objective}
              onChange={(event) => setObjective(event.target.value)}
              placeholder="Recover lapsing evening repeat customers"
            />
          </div>

          <div className="space-y-1.5">
            <Label>Where does this run?</Label>
            <div className="grid grid-cols-3 gap-2">
              {SURFACES.map((option) => {
                const active = surface === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    aria-pressed={active}
                    onClick={() => setSurface(option.value)}
                    className={cn(
                      "rounded-lg border px-2.5 py-2 text-left transition-colors focus-ring",
                      active
                        ? "border-primary bg-primary/5"
                        : "border-border bg-card hover:border-primary/30",
                    )}
                  >
                    <span className="flex items-center justify-between">
                      <span className="text-xs font-medium">{option.label}</span>
                      {active && <CampaignSurfaceBadge surface={option.value} className="px-1 py-0 text-2xs" />}
                    </span>
                    <span className="mt-0.5 block text-2xs text-muted-foreground">{option.hint}</span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="campaign-objective-type">Objective type</Label>
            <Select
              value={objectiveType || "none"}
              onValueChange={(value) => setObjectiveType(value === "none" ? "" : value)}
            >
              <SelectTrigger id="campaign-objective-type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {OBJECTIVE_TYPES.map((option) => (
                  <SelectItem key={option.value || "none"} value={option.value || "none"}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="campaign-channel">Channel</Label>
              <Select value={channel} onValueChange={setChannel}>
                <SelectTrigger id="campaign-channel">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CHANNELS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {!isHybrid && (
              <div className="space-y-1.5">
                <Label htmlFor="campaign-budget">Budget ($)</Label>
                <Input
                  id="campaign-budget"
                  type="number"
                  min={0}
                  value={budget}
                  onChange={(event) => setBudget(event.target.value)}
                  placeholder="5000"
                />
              </div>
            )}
          </div>

          {isHybrid && (
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="campaign-business-budget">Business budget ($)</Label>
                <Input
                  id="campaign-business-budget"
                  type="number"
                  min={0}
                  value={businessBudget}
                  onChange={(event) => setBusinessBudget(event.target.value)}
                  placeholder="3500"
                  required
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="campaign-paypal-budget">PayPal budget ($)</Label>
                <Input
                  id="campaign-paypal-budget"
                  type="number"
                  min={0}
                  value={paypalBudget}
                  onChange={(event) => setPaypalBudget(event.target.value)}
                  placeholder="6500"
                  required
                />
              </div>
              <p className="text-2xs text-muted-foreground sm:col-span-2">
                Total budget is the sum of both legs:{" "}
                {(Number(businessBudget) || 0) + (Number(paypalBudget) || 0) || "—"}
              </p>
            </div>
          )}

          <Separator />

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="campaign-offer-type">Offer type</Label>
              <Select value={offerType} onValueChange={setOfferType}>
                <SelectTrigger id="campaign-offer-type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {OFFER_TYPES.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="campaign-offer-value">Offer value</Label>
              <Input
                id="campaign-offer-value"
                type="number"
                min={0}
                value={offerValue}
                onChange={(event) => setOfferValue(event.target.value)}
                placeholder="60"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="campaign-offer-description">Offer description</Label>
            <Input
              id="campaign-offer-description"
              value={offerDescription}
              onChange={(event) => setOfferDescription(event.target.value)}
              placeholder="Cold brew + brownie combo at $11, evenings only"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="campaign-message">Message</Label>
            <Textarea
              id="campaign-message"
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              placeholder="Your evening cold brew combo is $11 this week."
              rows={3}
              required
            />
          </div>

          <Separator />

          <div className="space-y-3">
            <div>
              <p className="text-sm font-medium">Audience</p>
              <p className="text-xs text-muted-foreground">
                Optional. The segment is materialised server-side from real transaction
                behaviour.
              </p>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="campaign-audience-name">Segment name</Label>
                <Input
                  id="campaign-audience-name"
                  value={audienceName}
                  onChange={(event) => setAudienceName(event.target.value)}
                  placeholder="Lapsed evening regulars"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="campaign-min-orders">Minimum past orders</Label>
                <Input
                  id="campaign-min-orders"
                  type="number"
                  min={0}
                  value={minOrders}
                  onChange={(event) => setMinOrders(event.target.value)}
                  placeholder="2"
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <Label>Trading slots</Label>
              <div className="flex flex-wrap gap-2">
                {DAYPARTS.map((slot) => {
                  const active = dayparts.includes(slot);
                  return (
                    <button
                      key={slot}
                      type="button"
                      aria-pressed={active}
                      onClick={() =>
                        setDayparts((current) =>
                          active ? current.filter((s) => s !== slot) : [...current, slot],
                        )
                      }
                      className={
                        active
                          ? "rounded-lg border border-primary bg-primary px-2.5 py-1.5 text-xs font-medium text-primary-foreground transition-colors focus-ring"
                          : "rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs font-medium transition-colors hover:bg-muted focus-ring"
                      }
                    >
                      {slot.charAt(0) + slot.slice(1).toLowerCase()}
                    </button>
                  );
                })}
              </div>
            </div>
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

---
title: PayPilot API
---

PayPilot is an AI operating system for small merchants on PayPal. Its API lets you
drive the same loop the PayPilot app does:

* **Growth intelligence** - opportunities found in PayPal transactions, campaigns
  and controlled experiments.
* **Supply agents** - stockout detection, an RFQ to independent supplier agents,
  multi-round negotiation with every offer checked against a deterministic limit.
* **PayPal financial operations** - supplier settlement with PayPal Orders v2,
  Invoicing, approval-gated Payouts, Subscriptions, verified webhooks and
  reconciliation to the cent.

## The one rule

**Money never moves without a person.** Limits are computed by a deterministic
engine before any agent speaks. A purchase and a payment each need a recorded human
approval bound to a SHA-256 hash of the exact terms; change the terms and the
approval is invalidated. Agent tools - including any AI coding agent using this
portal's Context Plugin - can propose, never approve or pay.

## Start here

1. [Authenticate](guides/authentication) and make your first call.
2. Walk the [procure-to-pay flow](guides/procure-to-pay): demand -> RFQ ->
   negotiation -> approval -> receipt -> PayPal payment -> reconciliation.
3. Connect your own supplier agent with the
   [signed agent protocol](guides/supplier-agent-protocol).

The demo merchant is *Juniper & Oak Coffee*; log in as `owner@juniperoak.com` /
`Autopilot@2024` (other roles: `admin@`, `analyst@`, `staff@`, `viewer@`). Without
PayPal keys the API runs against a labelled simulator (ids start `SIM-`).

---
title: Money controls
---

How PayPilot keeps AI away from the money, so an integration built on this API -
including one written by an AI coding agent - cannot move funds on its own.

* **Deterministic limits.** `max landed unit price = selling price x (1 - target
  margin)`, budget and target are computed in `Decimal` before negotiation starts.
* **Hash-bound approvals.** An approval stores the canonical terms and their
  SHA-256. Deciding re-reads the live terms; a mismatch invalidates the approval
  (`409`). Approving requires `procurement:approve` / `payment:approve`.
* **Two approvals for money.** One for the purchase, one for the payment, after the
  three-way match passes.
* **Idempotent execution.** Each PayPal call carries a `PayPal-Request-Id`
  (`sender_batch_id` for payouts) derived from the approval; executing twice
  returns the same result.
* **Honest modes.** Without credentials every PayPal object is `SIMULATED` with a
  `SIM-` id; with sandbox keys the mode is `SANDBOX`. The mode is on every payment.
* **Audit.** Approvals, denials (including a `403` for the wrong role) and every
  execution are written to the audit log.

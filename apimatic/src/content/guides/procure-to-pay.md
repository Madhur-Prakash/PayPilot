---
title: Procure to pay
---

# Procure to pay

The signature flow: a product is about to run out, three supplier agents negotiate,
a person approves, PayPal pays the supplier, and the books reconcile.

## 1. Find what to buy

```bash
curl -s "$BASE/api/v1/supply/demand" -H "Authorization: Bearer $ANALYST"
```

Each row has `days_of_cover`, `velocity_recent`, `suggested_quantity` and
`stockout_risk`. In the demo, Premium Coffee Beans have 3.5 days of cover against a
3-day lead time.

## 2. Raise a procurement and negotiate

```bash
curl -s -X POST "$BASE/api/v1/procurement" -H "Authorization: Bearer $ANALYST" \
  -H 'Content-Type: application/json' \
  -d '{"inventory_item_id": "<id from step 1>", "auto_negotiate": true}'
```

The backend computes the limit first (`selling price x (1 - target margin)`), sends
an RFQ to the supplier agents, runs the rounds, scores the eligible offers and stops
at `AWAITING_APPROVAL` with a `recommendation` and an `approval.approval_id`.
`GET /api/v1/procurement/{id}/messages` returns every signed protocol message.

## 3. Approve (a person, with the right role)

```bash
curl -s -X POST "$BASE/api/v1/approvals/$APPROVAL_ID/decide" -H "Authorization: Bearer $OWNER" \
  -H 'Content-Type: application/json' -d '{"approve": true, "note": "Go"}'
```

An Analyst gets **403**. If any term changed since the recommendation, the approval
is invalidated (**409**). Approval issues the purchase order; the supplier agent
confirms delivery and issues its invoice.

## 4. Receive goods - the three-way match

```bash
curl -s -X POST "$BASE/api/v1/purchase-orders/$ORDER_ID/goods-receipts" \
  -H "Authorization: Bearer $STAFF" -H 'Content-Type: application/json' \
  -d '{"lines": [{"line_id": "<line id>", "quantity": 100}]}'
```

Billed 150 but received 100: payment is held. Receive the remaining 50 and the match
clears.

## 5. Pay the supplier with PayPal

```bash
curl -s -X POST "$BASE/api/v1/supplier-invoices/$INVOICE_ID/approve-payment" \
  -H "Authorization: Bearer $OWNER" -H 'Content-Type: application/json' -d '{"approve": true}'
curl -s -X POST "$BASE/api/v1/supplier-invoices/$INVOICE_ID/pay" -H "Authorization: Bearer $OWNER"
```

`pay` creates a PayPal Orders v2 order with the supplier as payee and a
`PayPal-Request-Id` idempotency key. In the sandbox the status is
`PAYER_ACTION_REQUIRED` with an `approve_url`; after approval in PayPal, capture it:

```bash
curl -s -X POST "$BASE/api/v1/payments/$EXECUTION_ID/capture" -H "Authorization: Bearer $OWNER"
```

## 6. Reconciliation

Runs on capture: purchase order x receipt x invoice x PayPal capture must agree to
the cent. Inventory is revalued at weighted-average landed cost and the product's
margin updates. `GET /api/v1/reconciliations` lists the results.

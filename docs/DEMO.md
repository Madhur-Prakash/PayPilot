# Demo walkthrough (three minutes)

[Back to docs](README.md)

Everything below runs with **no API keys**: agents in deterministic mode, PayPal
in simulation (every PayPal object is labelled *Simulated* and its id starts
`SIM-`). With sandbox credentials configured the same flow runs against the
PayPal sandbox.

**Before you start:** `make init` (or `make docker-up migrate seed-reset`), then
`make dev`, and open <http://localhost:3000>. Log in as the **Analyst** in one
browser and the **Owner** in another (private window).

| Role | Email | Password |
| --- | --- | --- |
| Owner | `owner@juniperoak.com` | `Autopilot@2024` |
| Admin | `admin@juniperoak.com` | `Autopilot@2024` |
| Analyst | `analyst@juniperoak.com` | `Autopilot@2024` |
| Staff | `staff@juniperoak.com` | `Autopilot@2024` |
| Viewer | `viewer@juniperoak.com` | `Autopilot@2024` |

The merchant: **Juniper & Oak Coffee**, a Portland coffee shop that also sells
whole-bean coffee through a PayPal-powered online store.

---

### 0:00 - 0:20 · Command Center (`/command`)

*"PayPilot is an AI operating system for small merchants."* Point at: revenue and
gross profit, open growth opportunities, **items at stockout risk** (Premium Coffee Beans among them), zero active
negotiations, the PayPal mode badge, and the business-event stream that connects
growth, supply and finance.

### 0:20 - 0:45 · Growth Intelligence (`/opportunities`)

The Growth Scientist has found **"Capture rising demand for Premium Coffee
Beans"**: online demand up **+71%** (7 -> **12 bags/day**), worth ~$2,700/month,
with the evidence rows (sales velocity, days of cover). Note the action: *restock
through the Supply Agents and hold promotions until it lands* - growth already
knows about the stock problem.

### 0:45 - 1:05 · Inventory Intelligence (`/supply/reorder`)

Premium Coffee Beans: **42 bags, 12/day -> 3.5 days of cover**, 3-day lead time,
**suggest 150**, needed within **3 days**. Open **Policy…** to show the
deterministic limit: `$18.00 × (1 − 40%) = $10.80` max landed per bag, **$1,620**
budget. As the **Analyst**, click **Start RFQ**.

### 1:05 - 1:45 · Agent-to-agent negotiation (`/supply/negotiations/{id}`)

Click **Watch live**. Three independent supplier agents reply to the RFQ:

* **Summit Roastworks** - reliable, fast, opens at $11.54;
* **Pacific Bean Exchange** - cheapest at $9.40, but only 90 bags and 9 days;
* **Cascadia Coffee Collective** - flexible, volume break at 150.

The Buyer Agent counters round by round (asks for free shipping, applies
competitive pressure). Each supplier offer carries the backend's verdict -
*inside policy* or the exact rule it breaks. The price chart shows each supplier
converging toward the merchant's target under the red ceiling line. Open
**Agent conversation**: every line is a typed, HMAC-signed protocol message
(`RFQ_CREATED`, `QUOTE_SUBMITTED`, `COUNTEROFFER`, `OFFER_ACCEPTED`…), marked *verified*.

**Quote comparison**: Cascadia wins - **$1,455.00** landed, 2-day delivery,
score 0.973 vs Summit 0.961; Pacific excluded (too slow, partial quantity).
**$248.77 saved** against the best opening quote.

### 1:45 - 2:10 · Financial control

Still as the **Analyst**, click **Review & approve purchase** -> **Approve**:
**403 - your role cannot perform this action** (and it is logged in the audit
trail). Switch to the **Owner**, open **Approvals** (`/approvals`): the exact
terms, the policy version and the terms hash. **Approve**. The purchase order is
issued and the supplier agent confirms delivery and issues its invoice.

### 2:10 - 2:35 · PayPal workflow (`Purchase order lifecycle` tab)

Invoice `CASCAD-PO-…` for $1,455.00. As **Staff** or **Owner**, **Receive goods:
100** - the three-way match flags *Billed 150 but only 100 received*; payment is
held. **Receive the remaining 50** - the match clears and a payment approval is
requested. **Approve payment**, then **Pay with PayPal**: PayPal Orders v2, payee
= supplier, idempotency key shown, capture `SIM-CAPTURE-…`.

**With sandbox keys (record this - it is the real PayPal moment):** the status
becomes *Payer action required*. Click **Approve in PayPal**, log in with your
sandbox **personal** account and pay. PayPal returns you to **Payments**, where a
*Back from PayPal* card shows the amount, the supplier payee and the order id -
click **Capture payment**. Optionally show the $1,455.00 arriving in the sandbox
supplier's business account at sandbox.paypal.com.

### 2:35 - 2:50 · Receiving and reconciliation

Reconciliation runs automatically: PO × receipt × invoice × PayPal capture agree
to the cent. Inventory is revalued to **$10.12/bag** (weighted-average landed
cost) and the product's gross margin moves **35.6% -> 43.8%**. Cascadia's
reliability updates.

### 2:50 - 3:00 · Back to the Command Center

The margin change, procurement savings and PayPal capture now appear in the
Command Center and the event stream.

> *"PayPilot doesn't just tell merchants what happened. It helps them decide what
> to do next, coordinates the agents that execute it, and measures the impact on
> their business."*

---

## Shortcuts

* **One click:** Supply Command Center -> **Run procurement autopilot** runs the
  LangGraph workflow (inventory monitoring -> requirement -> sourcing ->
  negotiation -> approval gate) for the item most at risk.
* **Reset the demo:** `make seed-reset` (or `make reset-db CONFIRM=yes` to rebuild the database).
* **Approval invalidation:** change an offer's price in the database after the
  recommendation and try to approve - the approval is invalidated (HTTP 409).
* **The original growth loop** (evening win-back experiment -> SCALE) is still
  there: `/dashboard`, `/growth`, `/experiments`.
* **Dashboard Studio (`/studio`, AG Studio) - good for the AG Grid prize:** it opens
  on a pre-built overview (days of cover, revenue at risk, supplier scorecard). In
  the editor, drag a field onto the canvas to add a chart (no LLM needed). The
  *AI Assistant* panel needs a model with more quota than Groq's free tier (see
  [SPONSORS.md](SPONSORS.md#ag-grid-and-ag-studio)) - on the free tier a request
  takes ~9 minutes and may not finish, so do not film it on Groq free.
* **Procurement timeline (`/supply/timeline`, Bryntum Gantt):** after a
  procurement completes, each stage is a bar; a partial delivery shows two
  milestones.

## Growth story numbers (seeded, last 30 days vs previous 30)

From `make calibrate` (café transactions only; the online bean store adds on top):

| Metric | Current | Previous | Change |
| --- | --- | --- | --- |
| Revenue | $24,693 | $28,124 | -12.2% |
| Orders | 2,353 | 2,473 | -4.9% |
| Average order value | $10.49 | $11.37 | -7.7% |
| Evening revenue | | | -31.8% |
| Evening service time | | | +24.5% |

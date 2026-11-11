# Demo video script (under 3 minutes)

[Back to docs](README.md)

One thread, told end to end: **a real PayPal sale -> agents negotiate -> a person approves -> PayPal pays
the supplier -> the books close**. Everything else (voice, Studio, n8n) stays out of the video.

Target runtime **2:55**. The Devpost rules: under 3 minutes, public on YouTube, shows the project working,
no copyrighted music or third-party trademarks beyond what the product naturally shows (PayPal's own checkout
page is fine - it is the sponsor's product).

---

## The numbers on screen

The script starts at the customer checkout, and one sale changes the seeded scenario slightly (see
[DEMO.md](DEMO.md)). **These are the figures you should see after buying 2 bags first.** Check each one in a
rehearsal before you narrate it - if a number differs, say what the screen says.

| Where | You should see |
| --- | --- |
| `/shop` | Premium Coffee Beans (12 oz), **$18.00**, 42 in stock; 2 bags = **$36.00** |
| After paying | stock **42 -> 40** |
| Reorder screen | **40** on hand, **3.3 days** of cover, demand **+73%**, suggest **160** bags within 3 days |
| Policy dialog | ceiling `$18.00 x (1 - 40%) =` **$10.80**/bag, budget **$1,620** |
| Negotiation result | Cascadia Coffee Collective, **$1,552.00** landed (**$9.70**/bag, 2-day delivery), **$262.69** below the best opening quote. Pacific Bean Exchange excluded (9 days, only 90 bags) |
| Analyst approves | **403** |
| Receiving | 110 of 160 -> *Billed 160.00 but only 110.0 received* (payment held); then 50 -> match clears |
| Payment | **$1,552.00**, mode badge *PayPal sandbox* |
| Reconciliation | paid = invoiced = **$1,552.00**; unit cost **$11.60 -> $10.08**; margin **35.6% -> 44.0%** |

---

## Shot list and narration

Narration is about 300 words - roughly two minutes read at a normal pace, which leaves the rest for
the PayPal pages. Record the voice-over **separately** after the screen capture and cut the picture to it.

### 0:00 - 0:10 · The hook (`/shop`, no sign-in)

**Screen:** the online store. Linger on the *PayPal sandbox* badge and "42 in stock". Set quantity to **2**;
the button reads *Pay $36.00 with PayPal*.

> "Juniper and Oak sells whole-bean coffee online - and every sale here is a real PayPal checkout. That sale
> is where PayPilot's AI starts working."

**On screen:** `Real PayPal sandbox checkout`

### 0:10 - 0:30 · The sale lands

**Screen:** click **Pay**. PayPal's sandbox page opens: log in as the buyer (speed this up, or jump-cut), click
**Pay / Continue**. You land on `/shop/return`: *Thank you - payment received*, **42 -> 40 in stock**, and the
*What just happened inside PayPilot* panel.

> "A customer buys two bags and approves on PayPal. PayPilot captures the payment, records the sale, and stock
> drops from forty-two to forty. If the customer closed the tab, PayPal's verified webhook would record the
> same sale - exactly once."

**On screen:** `Orders v2 · idempotent · webhook-backed`

### 0:30 - 0:46 · The agents see it (`/supply/reorder`)

**Screen:** click **Open the merchant's Reorder screen** (you are already signed in as the **Owner**).
Scroll to **Premium Coffee Beans**: 40 on hand, 3.3 days, suggest 160. Click **Policy...**.

> "Demand is up seventy-three percent and cover is down to three point three days. Before any agent speaks, a
> deterministic engine sets the ceiling: eighteen dollars less forty percent margin - ten eighty a bag. No AI
> arithmetic."

**On screen:** `$18.00 x (1 - 40%) = $10.80 · budget $1,620`

### 0:46 - 1:14 · Agent-to-agent negotiation (`/supply/negotiations/{id}`)

**Screen:** close the dialog, click **Start RFQ**. On the negotiation page click **Watch live**: three supplier
agents, the price chart converging under the red ceiling line. Open **Agent conversation** (every message
marked *verified*). Finish on **Quote comparison**: Cascadia $1,552.00, $262.69 saved, Pacific excluded.

> "A buyer agent negotiates with three supplier agents over signed, typed messages. Every offer is checked
> against that ceiling. Cascadia wins at fifteen fifty-two landed - two sixty-two sixty-nine below the best
> opening quote. The cheapest supplier is excluded: nine days, only ninety bags."

**On screen:** `Signed messages · every offer validated by the backend`

### 1:14 - 1:32 · A human approves (two browser profiles)

**Screen (Analyst profile):** **Review & approve purchase -> Approve** -> the **403** toast.
**Screen (Owner profile):** **Approvals** (`/approvals`): the exact terms, the policy version and the terms hash
-> **Approve**. The purchase order is issued.

> "Agents can't spend money. The analyst tries to approve - blocked, four-oh-three. The owner approves terms
> bound to a hash; change a cent and the approval is void."

**On screen:** `HTTP 403` then `terms hash · any change voids it`

### 1:32 - 1:46 · Receiving and the three-way match (*Purchase order lifecycle* tab)

**Screen:** **Receive goods: 110** -> the flag *Billed 160.00 but only 110.0 received*, payment held.
**Receive the remaining 50** -> the match clears and a payment approval is requested.

> "A partial delivery holds the payment - a three-way match. When the rest arrives, payment is released for
> approval."

**On screen:** `Three-way match: PO x receipt x invoice`

### 1:46 - 2:22 · PayPal pays the supplier - the money shot

**Screen:** **Approve payment -> Pay with PayPal**. Show the *PayPal sandbox* badge and the idempotency key; the
status reads *Payer action required*. Click **Approve in PayPal**, approve as the buyer (speed up), return to
**Payments**, see the *Back from PayPal* card, click **Capture payment**. Hold on the captured row: amount, mode,
capture id.

> "Now PayPal pays the supplier. Orders v2, on PayPal's official APIMatic-generated SDK - the supplier is the
> payee, and the idempotency key comes from the approval, so a retry can never pay twice. I approve as the buyer
> in the sandbox, capture - and it's paid."

**On screen:** `PayPal-Request-Id derived from the approval` then `Captured · SANDBOX`

### 2:22 - 2:36 · The books close (`/supply/reconciliation`, then `/command`)

**Screen:** reconciliation: PO, receipt, invoice and capture all **$1,552.00**. Cut to the Command Center's
*Growth <-> Supply, connected* card: **margin 35.6% -> 44.0%**.

> "Purchase order, receipt, invoice and capture agree to the cent. Inventory is revalued to ten-oh-eight a bag,
> and margin goes from thirty-five point six to forty-four percent - straight back into growth."

**On screen:** `$1,552.00 = $1,552.00 = $1,552.00`

### 2:36 - 2:52 · The platform (four quick cuts, about four seconds each)

**Screen:** (1) `/supply/timeline` - the Bryntum Gantt, every stage through to the PayPal payment;
(2) `/finance/subscriptions/radar` - the revenue radar; (3) `/shelf` - live Channel3 products;
(4) `/integrations` - every tool and whether it is live.

> "The same platform: a Bryntum timeline, a subscription radar, live Channel3 products, and an honest
> integrations page - all on one Render blueprint."

**On screen (one line per cut):** `Bryntum Gantt` · `Bryntum Scheduler` · `Channel3 · live` · `Honest status`

### 2:52 - 2:58 · End card

**Screen:** `docs/architecture.png`, then the live-demo URL and repository.

> "PayPilot: agents propose, people approve, PayPal moves the money."

**On screen:** `paypilot-web-0lqv.onrender.com` · `github.com/Madhur-Prakash/PayPilot`

---

## Before you record

**Where to record.** Record **locally** with your sandbox credentials: you can reset between takes
(`make seed-reset`), and "functioning on the device it was built for" is satisfied. The hosted demo cannot be
reset. After filming, do **one complete run on the hosted demo** so judges find a lived-in product (a payment,
a timeline, events) rather than empty screens - and so you know the hosted checkout works.

**Local setup**

1. `.env`: `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_ENVIRONMENT=sandbox`, and
   `PAYPAL_SANDBOX_PAYEE_EMAIL` (a sandbox **business** account - the supplier's payee). Keep
   `FRONTEND_URL=http://localhost:3000` so PayPal returns you to the right place.
2. `make seed-reset`, then `make dev`.
3. A sandbox **personal** (buyer) account. Do one dry-run purchase first so you know the screens.
4. Without a public URL PayPal cannot reach your laptop's webhook, so locally the **return** records the
   sale. Say "the verified webhook records it too" only because it is true by design and tested; do not
   show a webhook arriving unless you recorded it on the hosted demo.

**Screen and windows**

- Two browser profiles: **Owner** (also used for `/shop`) and **Analyst**, signed in and the same size.
- 1920x1080, browser zoom 110-125%, bookmarks bar hidden, notifications off, other tabs closed.
- Pre-scroll the Reorder screen so **Premium Coffee Beans** is easy to find.

**Rehearse twice**, reset, then record. Aim to record each section as its own clip.

## Editing

- Speed the PayPal login 3-4x or jump-cut it; **never show the sandbox password**.
- Burn in short captions (many judges watch muted): use the *On screen* lines above.
- Cut dead waits (page loads, the negotiation finishing). Keep the **403** and the **Capture** click in real time.
- Music: none, or royalty-free with its licence in the description.
- Export 1080p, upload to YouTube as **Public**, then put the link in the Devpost form and in
  [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) and [DEVPOST.md](DEVPOST.md).

## If something goes wrong

| Problem | Do this |
| --- | --- |
| A number differs from the table | Say what the screen shows. If you skipped the customer purchase, use the seeded numbers in [DEMO.md](DEMO.md) (150 bags, $1,455.00, $248.77, margin 35.6% -> 43.8%) |
| PayPal's sandbox is slow | Record the two approvals as separate clips and cut between them |
| No *Payer action required* (the badge says Simulated) | Your `.env` has no sandbox credentials - fix it before recording; a simulated payer approves instantly |
| The hosted demo is asleep | Open `/health` and a few pages five minutes before; the first load takes about a minute |
| The 403 does not appear | You are signed in as the Owner in that profile - use the Analyst profile |
| Running over 3:00 | Drop the *platform* cuts to two, then shorten the negotiation narration |

## YouTube description (paste, then fill the links)

```
PayPilot - an AI operating system for small merchants, built on PayPal.

A customer pays with PayPal on the online store. Agents see the stock risk, negotiate with three supplier
agents over signed messages inside a deterministic limit, and a person approves hash-bound terms. PayPal pays the
supplier only after goods are received and three-way matched - then it reconciles to the cent.

Agents propose. People approve. PayPal moves the money.

0:00 Real PayPal checkout starts the loop
0:30 Agents see the stock risk
0:46 Agent-to-agent negotiation
1:14 Human approval (403 for an analyst)
1:32 Three-way match
1:46 PayPal pays the supplier (Orders v2, APIMatic SDK)
2:22 Reconciliation
2:36 Platform: Bryntum, Channel3, Render

Live demo: https://paypilot-web-0lqv.onrender.com  (owner@juniperoak.com / Autopilot@2024; first load can take a minute)
Code: https://github.com/Madhur-Prakash/PayPilot  (MIT)
Built with: PayPal (Orders v2, Webhooks, Transaction Search, Invoicing, Payouts, Subscriptions, Agent Toolkit),
LangGraph, Groq, FastAPI, Next.js, PostgreSQL + pgvector, Render (Key Value, n8n), Channel3, AG Grid, Bryntum, APIMatic.
```

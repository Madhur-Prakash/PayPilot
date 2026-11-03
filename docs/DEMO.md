<div align="center">

# Demo script

[![Docs index](https://img.shields.io/badge/-Docs_index-475569?style=flat-square&logo=markdown&logoColor=white)](README.md)
[![Installation](https://img.shields.io/badge/-Installation-64748b?style=flat-square)](INSTALLATION.md)
[![Data](https://img.shields.io/badge/-Data-2563eb?style=flat-square)](DATA.md)
[![Architecture](https://img.shields.io/badge/-Architecture-16a34a?style=flat-square)](ARCHITECTURE.md)

</div>

Five minutes. The whole growth loop, end to end.

```bash
make demo    # wipe and rebuild a pristine seeded environment
make dev     # backend :8000, frontend :3000
```

Sign in at <http://localhost:3000> as `owner@sharmacafe.in` / `Autopilot@2024`.

> Every figure below is computed from the seeded ledger at seed `20240917`. They
> reproduce exactly on any machine — the demo anchors on the most recent completed
> Sunday, so the day-of-week composition of the comparison windows never drifts.

---

## 1 · Observe — "How is my business doing?" (30s)

**Growth Command Center.**

| | | |
| --- | --- | --- |
| Revenue | ₹4.94L | **−12.9%** |
| Orders | 2,353 | −7.9% |
| AOV | ₹210 | −5.5% |
| Repeat rate | 38.3% | −11.8% |

> "Revenue is down 12.9%, and the decline concentrates in the evening segment,
> −32.3%."

**Say:** the KPI cards count up because the number was *computed*, not typed. The
colour follows meaning, not direction — each metric declares which way is good, so
a falling service time would read green.

Scroll to **Revenue by trading slot**: morning and afternoon are roughly flat.
Evening is the outlier. The business is not uniformly down.

---

## 2 · Diagnose — "What changed, and where?" (45s)

**Growth Graph.**

```
Revenue                    ₹4.94L   −12.9%
  ├─ Orders                 2,353   −7.9%      decomposes_into
  ├─ AOV                     ₹210   −5.5%      decomposes_into
  └─ Repeat Customers          ...  −11.8%     correlates_with
       └─ Evening segment  ₹1.58L   −32.3%     decomposes_into
            └─ Evening service time 10.6 min  +25.6%   correlates_with
                 └─ Waiting-time complaints  +117%     evidenced_by
```

Click the **evening service time** node. Read the panel:

> "This moved over the same window as the revenue decline — a correlation, not a
> demonstrated cause."

Click the **waiting-time complaints** node:

> "Reviews are an independent source from the transaction ledger, which is what
> makes this corroboration rather than the same number twice."

**Say:** this is the discipline that keeps the product honest. Edges are only
`decomposes_into`, `correlates_with` or `evidenced_by`. Nothing claims causation,
because nothing has established it yet. That is what the experiment is for.

**Worth stressing:** nothing in the codebase says "the answer is waiting time".
Evening regulars churn out on staggered days; reviews are generated *from the
orders they describe*, so when service times drift up, complaints rise on their
own. The analytics layer surfaced the correlation; the agent reasoned over it.

---

## 3 · Hypothesize — run the Growth Scientist (60s)

**Opportunities.** Four detected, ranked by expected value discounted by effort:

| Opportunity | Value | Confidence |
| --- | --- | --- |
| Address the evening service slowdown | ₹18,574/mo | 70% |
| Recover lost evening repeat customers | ₹14,470/mo | 92% |
| Arrest the decline in Paneer Wrap | ₹4,300/mo | 62% |
| Arrest the decline in Chocolate Brownie | ₹3,362/mo | 62% |

Open the top one → **Growth Scientist** tab → **Investigate**.

Seven steps appear, each with what ran and what it returned:

```
1  Growth Orchestrator   Interpreted the request
2  Growth Scientist      Computed the period metrics, segmented them, ran detection
3  Review Intelligence   Analysed the review corpus for emerging complaints
4  Market Intelligence   Compared competitor perception, screened market signals
5  Growth Scientist      Synthesised the evidence into a single recommendation
6  Action Agent          Checked whether the action needs merchant approval
7  Merchant Agent        Composed the reply
```

Expand **Tool call detail**: eight tools, each with its duration.

**Say:** this is a real LangGraph workflow, not a scripted animation. The tools
are typed, permission-checked and merchant-scoped, and every call is persisted —
which is what the trace is rendered from.

Point at the footer: *"This trace shows actions, tools, evidence and decisions.
Internal model reasoning is never recorded or displayed."* Chain-of-thought is not
hidden; it is never captured.

**If no `GROQ_API_KEY` is set**, a "Deterministic mode" badge appears. Worth
calling out: the figures, the opportunity and the decision are identical — only
the prose is simpler. The product does not depend on the model being up.

---

## 4 · Recommend — the approval gate (45s)

The recommendation panel shows, in this order:

- **Estimated impact** ₹14,470/mo · **Confidence** 92% · **Approval** Required
- **Hypothesis**, labelled as a hypothesis
- **Evidence**, grouped by source, with an independence note
- **Recommended intervention**
- **Considered and not chosen:** *blanket percentage discount to all customers*

**Say:** the agent reasoned about the alternative and rejected it. A blanket
discount cuts margin across customers who were never at risk and does not address
the signal the evidence points to.

Click **Approve and run**. The dialog restates impact, confidence, risk and
delivery mode before you can confirm.

**Optional, and the strongest RBAC moment:** open a private window, sign in as
`analyst@sharmacafe.in`, and return to this screen. The button is replaced by:

> "You are signed in as ANALYST. Executing a campaign and launching an experiment
> require the Admin or Owner role. The backend enforces this regardless of what the
> interface shows."

Hitting the endpoint directly returns `403 PERMISSION_DENIED`. The denial is
audited — and it survives the rolled-back request.

---

## 5 · Act — the agents execute (30s)

Approve as the Owner. Four steps run:

```
Created campaign 'Recover lost evening repeat customers' targeting 578 customers
Created experiment with 285 control / 293 test
Launched campaign to 578 customers (simulated)
Simulated the experiment trading window so results are measurable
```

**Say:** the test group is deterministic — a hash of the customer id, so
assignment is stable across re-runs and free of ordering bias. The control group
is genuinely held out.

**Be explicit about the last line:** on a demo tenant the system writes the
transactions the experiment *would* have produced, from a declared ground truth,
so results can be measured now instead of in two weeks. Those rows are stamped
`simulated: true`. The measurement itself is the ordinary one — it aggregates the
ledger and has no idea the rows were generated.

---

## 6 · Measure — "Did it work?" (45s)

**Experiments** → the new experiment → **Measure**.

```
Control conversion     8.9%
Test conversion       14.4%
Conversion lift      +61.0%
Incremental revenue  ₹12,553
Incremental profit    ₹8,900
ROI                    7.85x
Significance         p = 0.042   (two-proportion z-test, α = 0.05)

DECISION: SCALE
```

> "Conversion lift of +61.0% clears the 10% success threshold, incremental revenue
> is ₹12,553, and the difference is statistically significant (p=0.042)."

**Say:** incremental revenue is not the test group's revenue. It is the test
group's revenue minus what the *same number of customers* would have produced at
the control rate. ROI is against the cost of offers actually redeemed.

**The point worth landing:** SCALE requires all three — a lift above the
threshold, positive incremental value, *and* statistical significance. Drop
significance and the decision becomes CONTINUE, not SCALE.

Scroll to the historical experiments:

- **Weekend Brunch Combo** → SCALE (+48.1%, p=0.038)
- **Loyalty Chai Pass** → **STOP** (−18.5%)

**Say:** the system says no. That is the credibility test for anything that claims
to measure its own recommendations.

---

## 7 · Learn (15s)

Under the decision:

> "A targeted intervention on the affected segment, measured against a held-out
> control, produced a readable result. Keep the control group in future tests —
> without it the lift is not attributable."

And on the STOP experiment:

> "Regulars were already visiting at the target frequency, so there was little
> headroom to buy. Target lapsing customers rather than active ones next time."

---

## 8 · Supporting screens (60s, pick two)

- **Reviews** — emerging complaints normalised **per 100 orders**. Worth the
  sentence: when the evening segment shrinks by a third, its raw complaint count
  can *fall* while the experience gets worse. The rate is what moves.
- **Competitors** — the largest gap is Speed, 34 vs 79. The banner states, first
  thing, that competitor scores are seeded benchmark data and no platform is
  scraped; the merchant's own scores are computed from its real reviews.
- **Inventory** — days of cover, stockout risk, revenue at risk. "This
  recommends, it never buys." There is no autonomous purchasing path.
- **Agent Activity** — every run, replayable, with the tool catalogue and the
  permission each tool requires.
- **Audit Log** — approvals, executions and denials, with the actor. Filter to
  **Denials** to show the Analyst attempt on record.
- **Settings → Roles** — the RBAC map the backend actually enforces.

---

## Closing

> "This does not just analyse the business. It finds the opportunity, quantifies
> it, shows the evidence behind it, and helps you run a controlled test to find out
> whether acting on it actually worked.
>
> Every number on screen was computed in SQL. The model interprets and explains —
> it never calculates, and it never approves. Anything that moves money waits for a
> human."

---

## If something goes wrong

| Symptom | Fix |
| --- | --- |
| Dashboard empty | `make seed` (idempotent), or `make demo` to rebuild |
| Port 8000 taken | `make backend PORT=8010` + update the root `.env` |
| Database unreachable | `make db && make wait-db` |
| Agent run fails | Check `/api/v1/health`. It runs without any API key |
| Want a clean slate mid-demo | `make demo` — about 45 seconds |

---

<div align="center">

[Docs index](README.md) · [Installation](INSTALLATION.md) · [Data](DATA.md) ·
[Architecture](ARCHITECTURE.md) · [Troubleshooting](TROUBLESHOOTING.md)

</div>

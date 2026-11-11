"""Build the PayPilot system architecture diagram.

Regenerate with:  python scripts/build_architecture_diagram.py
Output:           docs/assets/architecture.svg

Standard library only. The layout is explicit coordinates so the diagram is
reviewable in a diff; every figure on it is a count taken from the code (see
docs/ARCHITECTURE.md for where each one comes from).
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

W, H = 1600, 1140
FONT = "Segoe UI, Inter, Helvetica Neue, Helvetica, Arial, sans-serif"

NAVY = "#0b2a6f"
PAYPAL = "#003087"
CYAN = "#0aa6e0"
INK = "#1e2b4a"
BODY = "#45577a"
MUTE = "#7b8bab"
PANEL = "#f4f7fc"
LINE = "#d5deec"
ORANGE = "#b45309"
ORANGE_BG = "#fff5e9"
GREEN = "#12805c"
GREEN_BG = "#eef8f3"
WHITE = "#ffffff"
PAYPAL_SOFT = "#cfdcf5"

parts: list[str] = []


def rect(x, y, w, h, fill=PANEL, stroke=None, sw=1.5, rx=12, dash=None):
    attrs = f'x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"'
    if stroke:
        attrs += f' stroke="{stroke}" stroke-width="{sw}"'
    if dash:
        attrs += f' stroke-dasharray="{dash}"'
    parts.append(f"<rect {attrs}/>")


def text(x, y, s, size=13, weight=400, fill=BODY, anchor="start", spacing=None):
    extra = f' letter-spacing="{spacing}"' if spacing else ""
    parts.append(
        f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
        f'text-anchor="{anchor}"{extra}>{escape(s)}</text>'
    )


def arrow(x1, y1, x2, y2, color=NAVY, both=False, width=2):
    mid = color.lstrip("#")
    start = f' marker-start="url(#ah-{mid})"' if both else ""
    parts.append(
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}"'
        f' marker-end="url(#ah-{mid})"{start}/>'
    )


def card(x, y, w, h, title, lines, *, fill=PANEL, stroke=LINE, title_fill=INK, line_fill=BODY,
         title_size=14, line_size=12.5, pad=14, rx=10, sw=1.2):
    rect(x, y, w, h, fill=fill, stroke=stroke, rx=rx, sw=sw)
    text(x + pad, y + pad + title_size, title, size=title_size, weight=700, fill=title_fill)
    for i, line in enumerate(lines):
        text(x + pad, y + pad + title_size + 8 + (i + 1) * (line_size + 6), line, size=line_size,
             fill=line_fill)


def section(x, y, label, color=CYAN):
    text(x, y, label, size=12, weight=700, fill=color, spacing=1.6)


# --------------------------------------------------------------------------- header
text(48, 58, "PAYPILOT", size=15, weight=800, fill=CYAN, spacing=2.4)
text(1552, 58, "Team PayFlux", size=15, weight=700, fill=NAVY, anchor="end")
text(48, 100, "System architecture", size=34, weight=800, fill=NAVY)
text(48, 132, "A modular monolith on FastAPI and Next.js. Agents propose, deterministic code sets every "
     "limit, a person approves, PayPal moves the money.", size=16, fill=BODY)

LX, LW = 48, 1064          # left column
RX, RW = 1152, 400         # right column
IX, IW = LX + 24, LW - 48  # inside the backend box

# --------------------------------------------------------------------------- clients
section(LX, 172, "CLIENTS")
clients = [
    ("Merchant dashboard", ["Next.js 15, React 19, TypeScript", "65 pages, AG Grid, Bryntum"]),
    ("Online store  /shop", ["Public PayPal checkout", "Starts the loop from a real sale"]),
    ("Voice assistant", ["Vapi server tools", "Same agents as the web UI"]),
    ("External agents and SDKs", ["Signed inbound agent protocol", "APIMatic SDKs, Postman"]),
]
cw = (LW - 3 * 16) / 4
for i, (title, lines) in enumerate(clients):
    cx = LX + i * (cw + 16)
    card(cx, 184, cw, 92, title, lines, fill=WHITE, stroke=LINE)
    arrow(cx + cw / 2, 278, cx + cw / 2, 322, color=NAVY)

# --------------------------------------------------------------------------- backend
rect(LX, 326, LW, 574, fill="#fbfcfe", stroke=NAVY, sw=2, rx=16)
text(IX, 358, "FASTAPI BACKEND", size=15, weight=800, fill=NAVY, spacing=1.6)
text(LX + LW - 24, 358, "Python 3.12, Pydantic v2, SQLAlchemy 2 async   |   200 operations under /api/v1",
     size=13, fill=MUTE, anchor="end")

# request pipeline
chips = ["Request ID", "CORS", "Rate limit", "Security headers", "Authenticate JWT",
         "Resolve merchant", "require_permission"]
gap = 18
chip_w = (IW - gap * (len(chips) - 1)) / len(chips)
for i, label in enumerate(chips):
    x = IX + i * (chip_w + gap)
    last = i == len(chips) - 1
    rect(x, 376, chip_w, 40, fill=NAVY if last else WHITE, stroke=NAVY, sw=1.2, rx=20)
    text(x + chip_w / 2, 401, label, size=12.5, weight=600, fill=WHITE if last else NAVY, anchor="middle")
    if not last:
        arrow(x + chip_w + 2, 396, x + chip_w + gap - 2, 396, color=CYAN, width=1.6)

# domain services
section(IX, 446, "DOMAIN SERVICES")
text(IX + 136, 446, "business logic and transactions over tenant-scoped repositories", size=12.5, fill=MUTE)
services = [
    ("Growth", ["Analytics, Growth Graph", "Opportunities", "Campaigns, experiments"]),
    ("Supply Agents", ["Buyer + 3 suppliers", "Signed HMAC protocol", "Negotiation, scoring"]),
    ("Procure-to-pay", ["Purchase orders", "Receiving, 3-way match", "Reconciliation"]),
    ("Supply Intelligence", ["Channel3 discovery", "Recommendations", "Market pricing"]),
    ("Finance", ["PayPal gateway", "Sync, webhooks", "Invoicing, payouts"]),
    ("Governance", ["Approval inbox", "Audit log", "RBAC, 51 permissions"]),
]
sw_ = (IW - 5 * 12) / 6
for i, (title, lines) in enumerate(services):
    card(IX + i * (sw_ + 12), 458, sw_, 112, title, lines, title_size=13.5, line_size=12, pad=12)

# agent layer
section(IX, 594, "AGENT LAYER")
agent_cards = [
    ("LangGraph workflows", ["Growth investigation", "Procurement autopilot", "Merchant OS: 7 agents",
                             "LLM words, never calculates"]),
    ("Tool registry: 49 tools", ["Typed arguments", "Permission-checked, merchant-scoped",
                                 "Logged and Langfuse-traced", "Persisted for the trace UI"]),
    ("Deterministic engines", ["Decimal price ceiling and budget", "Offer validation and scoring",
                               "Three-way match, revaluation", "Experiment statistics"]),
]
aw = (IW - 2 * 34) / 3
for i, (title, lines) in enumerate(agent_cards):
    ax = IX + i * (aw + 34)
    card(ax, 606, aw, 126, title, lines, fill=WHITE, stroke=NAVY, sw=1.2, line_size=12.5)
    if i < 2:
        arrow(ax + aw + 3, 669, ax + aw + 31, 669, color=NAVY)

# approval gate
rect(IX, 750, IW, 56, fill=ORANGE_BG, stroke=ORANGE, sw=1.8, rx=10)
text(IX + 18, 784, "APPROVAL GATE", size=14, weight=800, fill=ORANGE, spacing=1.4)
text(IX + 168, 784, "Every workflow stops here. A person approves a SHA-256 of the exact terms; "
     "agents request, never approve or pay.", size=13.5, fill=INK)

# platform row
platform = ["Transactional outbox + relay", "Realtime hub: WebSocket + Redis pub/sub",
            "Structured logs, redaction, traces"]
pw = (IW - 2 * 12) / 3
for i, label in enumerate(platform):
    px = IX + i * (pw + 12)
    rect(px, 824, pw, 52, fill=PANEL, stroke=LINE, rx=10)
    text(px + pw / 2, 855, label, size=13, weight=600, fill=INK, anchor="middle")

# --------------------------------------------------------------------------- data
section(LX, 934, "DATA", color=GREEN)
card(LX, 946, 640, 96, "PostgreSQL 16 + pgvector",
     ["System of record: 62 tables, Alembic migrations",
      "Agent memory: vector(384), HNSW cosine, filtered by merchant"],
     fill=GREEN_BG, stroke=GREEN, title_fill=GREEN, line_size=13)
card(LX + 656, 946, LW - 656, 96, "Redis / Render Key Value (optional)",
     ["Rate limits, Channel3 caches, realtime pub/sub",
      "Never a source of truth; in-process fallback"],
     fill=GREEN_BG, stroke=GREEN, title_fill=GREEN, line_size=13)
arrow(LX + 320, 902, LX + 320, 942, color=GREEN, both=True)
arrow(LX + 656 + (LW - 656) / 2, 902, LX + 656 + (LW - 656) / 2, 942, color=GREEN, both=True)

text(LX, 1082, "200 API operations   |   62 tables   |   49 agent tools   |   51 permissions   |   "
     "3 LangGraph workflows   |   65 pages", size=14, weight=700, fill=NAVY)
text(LX, 1108, "Without keys, PayPal runs on a labelled simulator (SIM- ids) and every agent node has a "
     "deterministic path.", size=13, fill=MUTE)

# --------------------------------------------------------------------------- external
section(RX, 172, "EXTERNAL SERVICES")
rect(RX, 184, RW, 376, fill=PAYPAL, rx=14)
text(RX + 22, 216, "PayPal Developer Platform", size=19, weight=800, fill=WHITE)
text(RX + 22, 238, "The system of record and the only money rail", size=13, fill=PAYPAL_SOFT)
paypal_items = [
    ("Orders v2 on the APIMatic Server SDK", "Store checkout and supplier payments"),
    ("Transaction Search", "Sales, fees and refunds feed growth analytics"),
    ("Invoicing v2 and Payouts", "Win-back invoices, approval-gated cashback"),
    ("Subscriptions", "Revenue radar, failed-payment recovery"),
    ("Webhooks", "Verified on raw bytes, replay-guarded"),
    ("Agent Toolkit over MCP", "Read-only: 16 of 46 tools callable"),
]
for i, (title, desc) in enumerate(paypal_items):
    y = 272 + i * 44
    text(RX + 22, y, title, size=14, weight=700, fill=WHITE)
    text(RX + 22, y + 18, desc, size=12.5, fill=PAYPAL_SOFT)
for i, mode in enumerate(["SANDBOX", "LIVE", "SIMULATED"]):
    mx = RX + 22 + i * 100
    rect(mx, 530, 90, 20, fill="none", stroke=PAYPAL_SOFT, sw=1, rx=10)
    text(mx + 45, 544, mode, size=10.5, weight=700, fill=WHITE, anchor="middle", spacing=0.8)

externals = [
    (576, "AI and observability", ["Groq GPT-OSS-120B (optional)", "Langfuse traces, Vapi voice"]),
    (672, "Channel3 product catalog", ["Live discovery, comparison, similar items", "Shopping agent, market prices"]),
    (768, "Automation", ["n8n: outbox events out, signed callbacks in", "Zapier: signed business notifications"]),
    (864, "Search and verification", ["Elasticsearch: evidence search", "Kernel: observe-only supplier browser"]),
]
for y, title, lines in externals:
    h = 80
    card(RX, y, RW, h, title, lines, fill=WHITE, stroke=LINE, line_size=12.5)
card(RX, 960, RW, 82, "Render Blueprint (free plan)", ["Web, API, Postgres, Key Value, n8n, docs portal"],
     fill=PANEL, stroke=MUTE, line_size=12.5)
parts.append(f'<rect x="{RX}" y="960" width="{RW}" height="82" rx="10" fill="none" stroke="{MUTE}" '
             f'stroke-width="1.2" stroke-dasharray="5 4"/>')

for y in (514, 616, 712, 808, 884):
    arrow(LX + LW + 3, y, RX - 3, y, color=PAYPAL if y == 514 else NAVY, both=True)

# --------------------------------------------------------------------------- write
markers = "".join(
    f'<marker id="ah-{c.lstrip("#")}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" '
    f'markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
    for c in (NAVY, CYAN, GREEN, PAYPAL, ORANGE)
)
svg = (
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
    f'font-family="{FONT}">\n<defs>{markers}</defs>\n'
    f'<rect width="{W}" height="{H}" fill="{WHITE}"/>\n' + "\n".join(parts) + "\n</svg>\n"
)

out = Path(__file__).resolve().parent.parent / "docs" / "assets" / "architecture.svg"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(svg, encoding="utf-8")
print(f"wrote {out.relative_to(out.parents[2])}")

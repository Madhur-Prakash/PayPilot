"""Build the PayPilot architecture diagram.

Regenerate with:  python scripts/build_architecture_diagram.py
Output:           PayFlux-Architecture-Diagram.png  (repo root)

Read in five seconds: one numbered line of steps, the merchant above it, the
data underneath it, and a loop back to the start. Everything else -- layer
names, module paths, middleware -- lives in docs/ARCHITECTURE.md.

Palette is the Paypal brand scheme only -- navy #002970, cyan #00B9F1, white.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

# --------------------------------------------------------------------------

NAVY = "#002970"
CYAN = "#00B9F1"
BODY = "#2E4C8A"
MUTE = "#8BA3C6"
PAPER = "#F1F6FC"
WHITE = "#FFFFFF"

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Arial", "Helvetica", "DejaVu Sans"]

W, H = 160.0, 90.0
DPI = 150
fig = plt.figure(figsize=(W / 9.23, H / 9.23), dpi=DPI)
ax = fig.add_axes((0, 0, 1, 1))
ax.set_xlim(0, W)
ax.set_ylim(0, H)
ax.axis("off")
fig.patch.set_facecolor(WHITE)


def box(x, y, w, h, fill=PAPER, edge=None, lw=1.3, radius=1.1, z=2):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle=f"round,pad=0,rounding_size={radius}",
        facecolor=fill, edgecolor=edge or fill,
        linewidth=lw if edge else 0, zorder=z))


def label(x, y, s, size=9, color=BODY, weight="normal", ha="left", va="center", z=5):
    ax.text(x, y, s, fontsize=size, color=color, fontweight=weight,
            ha=ha, va=va, zorder=z)


def arrow(x0, y0, x1, y1, color=CYAN, lw=2.2, scale=16, z=4):
    ax.add_patch(FancyArrowPatch(
        (x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=scale,
        color=color, linewidth=lw, zorder=z, shrinkA=0, shrinkB=0))


def rule(x, y, w, color=CYAN, lw=2.4):
    ax.plot([x, x + w], [y, y], color=color, linewidth=lw,
            solid_capstyle="butt", zorder=5)


# --------------------------------------------------------------------------
# Title
# --------------------------------------------------------------------------

label(6, 87.0, "PAYPILOT", size=11, color=CYAN, weight="bold")
label(6, 82.6, "HOW IT WORKS", size=22, color=NAVY, weight="bold")
label(154, 86.6, "Team PayFlux", size=10.5, color=NAVY, weight="bold", ha="right")
label(154, 83.0, "One loop: find the opportunity, act on it, prove it worked.",
      size=10, color=MUTE, ha="right")

# --------------------------------------------------------------------------
# The merchant
# --------------------------------------------------------------------------

box(6, 70.5, 148, 8.6, fill=PAPER)
label(9.5, 76.3, "THE MERCHANT", size=12, color=NAVY, weight="bold")
label(9.5, 73.0, "Opens the dashboard, asks questions by text or voice, "
                 "and approves what the AI proposes.", size=9.5, color=BODY)

# --------------------------------------------------------------------------
# The five steps
# --------------------------------------------------------------------------

SP_T, SP_B = 63.0, 45.0
BW = (148 - 4 * 5) / 5
steps = [
    ("1", "Observe", ["Reads the day's sales,", "customers and reviews."]),
    ("2", "Diagnose", ["Finds what changed — and", "the evidence for why."]),
    ("3", "Recommend", ["Proposes one action,", "priced in rupees."]),
    ("4", "Act", ["Launches it as a test against", "a held-back control group."]),
    ("5", "Measure", ["Compares the two, then says", "scale it or stop."]),
]

centres = []
for i, (num, title, lines) in enumerate(steps):
    x = 6 + i * (BW + 5)
    centres.append(x + BW / 2)
    box(x, SP_B, BW, SP_T - SP_B)
    label(x + 2.2, 59.4, num, size=19, color=CYAN, weight="bold")
    label(x + 2.2, 55.0, title.upper(), size=13, color=NAVY, weight="bold")
    rule(x + 2.2, 52.9, 5.4)
    for j, ln in enumerate(lines):
        label(x + 2.2, 50.6 - j * 2.6, ln, size=9.5, color=BODY)
    if i:
        arrow(x - 5 + 0.9, 54.0, x - 0.9, 54.0)

# merchant -> step 1, merchant -> step 4
arrow(centres[0], 70.1, centres[0], 63.4)
label(centres[0] + 1.8, 66.8, "asks", size=9, color=BODY)
arrow(centres[3], 70.1, centres[3], 63.4, color=NAVY)
label(centres[3] + 1.8, 66.8, "you approve", size=9, color=NAVY, weight="bold")

# --------------------------------------------------------------------------
# The data underneath
# --------------------------------------------------------------------------

box(6, 23.0, 148, 10.0, fill=WHITE, edge=NAVY, lw=1.5)
label(9.5, 29.9, "YOUR BUSINESS DATA", size=12, color=NAVY, weight="bold")
label(9.5, 26.6, "Transactions, customers, products and reviews. "
                 "Every number is calculated here — the AI reads them, it never works them out.",
      size=9.5, color=BODY)

arrow(centres[0], 33.6, centres[0], 44.4, color=NAVY)
label(centres[0] + 1.8, 39.0, "the numbers", size=9, color=BODY)
arrow(centres[3], 44.4, centres[3], 33.6, color=NAVY)
label(centres[3] + 1.8, 39.0, "writes the plan", size=9, color=BODY)
arrow(centres[4], 33.6, centres[4], 44.4, color=NAVY)
label(centres[4] - 1.8, 39.0, "the results", size=9, color=BODY, ha="right")

# --------------------------------------------------------------------------
# Round again
# --------------------------------------------------------------------------

LY = 14.0
for seg in ([[154, 157.5], [54, 54]], [[157.5, 157.5], [54, LY]],
            [[157.5, 2.5], [LY, LY]], [[2.5, 2.5], [LY, 54]]):
    ax.plot(seg[0], seg[1], color=CYAN, linewidth=2.2, zorder=3)
arrow(2.5, 54, 5.4, 54)
label(80, 16.6, "and round again — every result sharpens the next cycle",
      size=10, color=NAVY, weight="bold", ha="center")

# --------------------------------------------------------------------------

label(6, 7.6, "BUILT WITH", size=8.5, color=CYAN, weight="bold")
label(6, 4.8, "Next.js  ·  FastAPI  ·  PostgreSQL + pgvector  ·  LangGraph agents  ·  "
              "Groq  ·  Langfuse  ·  Vapi voice", size=9, color=MUTE)
label(154, 4.8, "Demo simulation — seeded merchant data", size=8.5, color=MUTE, ha="right")

out = Path(__file__).resolve().parent.parent / "PayFlux-Architecture-Diagram.png"
fig.savefig(out, dpi=DPI, facecolor=WHITE)
print(f"{out}  ({fig.get_size_inches()[0] * DPI:.0f} x {fig.get_size_inches()[1] * DPI:.0f} px)")

"""Static catalogue for the Juniper & Oak Coffee demo tenant (Portland, OR).

Everything here is fictional, deterministic demo data. It is labelled as such
throughout the product (see ProvenanceMeta) - nothing claims to be real PayPal
transaction, merchant or competitor-platform data.
"""

from __future__ import annotations

from typing import Any

from app.db.models.commerce import DayPart

MERCHANT_SLUG = "juniper-oak-coffee"

# --------------------------------------------------------------------------- #
# Products
# --------------------------------------------------------------------------- #
# `daypart_affinity` drives which slot a product sells in; `base_popularity` is
# its relative pick weight. `evening_combo` marks the items whose attach rate
# collapses in the current period - the mechanism behind the AOV decline.
PRODUCTS: list[dict[str, Any]] = [
    {
        "sku": "JO-COLD-001",
        "name": "Nitro Cold Brew",
        "category": "beverages",
        "description": "Slow-steeped cold brew on nitro, served over ice.",
        "price": 7.45,
        "cost_price": 2.6,
        "prep_time_minutes": 5,
        "tags": ["bestseller", "cold", "coffee"],
        "base_popularity": 1.00,
        "daypart_affinity": {
            DayPart.MORNING: 0.55,
            DayPart.AFTERNOON: 1.20,
            DayPart.EVENING: 1.30,
            DayPart.NIGHT: 0.70,
        },
        "evening_combo": True,
        "is_featured": True,
        "stock": 24,
        "reorder_point": 40,
        "reorder_quantity": 120,
        "unit_cost": 2.6,
        "supplier": "Harbor Coffee Supply",
    },
    {
        "sku": "JO-CAPP-002",
        "name": "Cappuccino",
        "category": "beverages",
        "description": "Single-origin espresso with steamed milk and foam.",
        "price": 6.45,
        "cost_price": 2.2,
        "prep_time_minutes": 4,
        "tags": ["coffee", "hot"],
        "base_popularity": 0.82,
        "daypart_affinity": {
            DayPart.MORNING: 1.60,
            DayPart.AFTERNOON: 0.95,
            DayPart.EVENING: 0.85,
            DayPart.NIGHT: 0.55,
        },
        "evening_combo": False,
        "stock": 88,
        "reorder_point": 45,
        "reorder_quantity": 120,
        "unit_cost": 2.2,
        "supplier": "Harbor Coffee Supply",
    },
    {
        "sku": "JO-DRIP-003",
        "name": "House Drip Coffee",
        "category": "beverages",
        "description": "Fresh-brewed single-origin drip, refilled while you stay.",
        "price": 2.95,
        "cost_price": 0.8,
        "prep_time_minutes": 3,
        "tags": ["coffee", "hot", "value"],
        "base_popularity": 1.15,
        "daypart_affinity": {
            DayPart.MORNING: 1.70,
            DayPart.AFTERNOON: 1.00,
            DayPart.EVENING: 1.25,
            DayPart.NIGHT: 0.80,
        },
        "evening_combo": False,
        "stock": 140,
        "reorder_point": 60,
        "reorder_quantity": 200,
        "unit_cost": 0.8,
        "supplier": "Cascade Provisions",
    },
    {
        "sku": "JO-PANI-004",
        "name": "Turkey Pesto Panini",
        "category": "food",
        "description": "Pressed panini with turkey, provolone and basil pesto.",
        "price": 6.95,
        "cost_price": 2.9,
        "prep_time_minutes": 8,
        "tags": ["snack", "grilled"],
        "base_popularity": 0.78,
        "daypart_affinity": {
            DayPart.MORNING: 0.90,
            DayPart.AFTERNOON: 1.35,
            DayPart.EVENING: 1.05,
            DayPart.NIGHT: 0.60,
        },
        "evening_combo": True,
        "stock": 62,
        "reorder_point": 30,
        "reorder_quantity": 90,
        "unit_cost": 2.9,
        "supplier": "Rose City Fresh Foods",
    },
    {
        "sku": "JO-WRAP-005",
        "name": "Chicken Avocado Wrap",
        "category": "food",
        "description": "Grilled chicken, avocado and chipotle aioli in a spinach wrap.",
        "price": 9.45,
        "cost_price": 4.1,
        "prep_time_minutes": 11,
        "tags": ["meal", "bestseller"],
        "base_popularity": 0.74,
        "daypart_affinity": {
            DayPart.MORNING: 0.35,
            DayPart.AFTERNOON: 1.25,
            DayPart.EVENING: 1.45,
            DayPart.NIGHT: 0.95,
        },
        "evening_combo": True,
        "is_featured": True,
        "stock": 38,
        "reorder_point": 28,
        "reorder_quantity": 80,
        "unit_cost": 4.1,
        "supplier": "Rose City Fresh Foods",
    },
    {
        "sku": "JO-BRWN-006",
        "name": "Triple Chocolate Brownie",
        "category": "desserts",
        "description": "Warm fudge brownie with a dusting of cocoa.",
        "price": 5.95,
        "cost_price": 2.05,
        "prep_time_minutes": 4,
        "tags": ["dessert", "sweet"],
        "base_popularity": 0.66,
        "daypart_affinity": {
            DayPart.MORNING: 0.25,
            DayPart.AFTERNOON: 0.95,
            DayPart.EVENING: 1.55,
            DayPart.NIGHT: 1.10,
        },
        "evening_combo": True,
        "stock": 46,
        "reorder_point": 25,
        "reorder_quantity": 70,
        "unit_cost": 2.05,
        "supplier": "Willamette Bakehouse",
    },
    {
        "sku": "JO-FRYS-007",
        "name": "Rosemary Sea Salt Fries",
        "category": "food",
        "description": "Crispy fries with rosemary salt and house aioli.",
        "price": 4.95,
        "cost_price": 1.7,
        "prep_time_minutes": 7,
        "tags": ["snack", "share"],
        "base_popularity": 0.70,
        "daypart_affinity": {
            DayPart.MORNING: 0.20,
            DayPart.AFTERNOON: 1.10,
            DayPart.EVENING: 1.50,
            DayPart.NIGHT: 1.25,
        },
        "evening_combo": True,
        "stock": 54,
        "reorder_point": 30,
        "reorder_quantity": 100,
        "unit_cost": 1.7,
        "supplier": "Rose City Fresh Foods",
    },
    {
        "sku": "JO-PEAC-008",
        "name": "Iced Peach Green Tea",
        "category": "beverages",
        "description": "Fresh-brewed green tea with peach and mint, over ice.",
        "price": 5.45,
        "cost_price": 1.55,
        "prep_time_minutes": 4,
        "tags": ["cold", "refreshing"],
        "base_popularity": 0.62,
        "daypart_affinity": {
            DayPart.MORNING: 0.45,
            DayPart.AFTERNOON: 1.40,
            DayPart.EVENING: 1.05,
            DayPart.NIGHT: 0.70,
        },
        "evening_combo": False,
        "stock": 96,
        "reorder_point": 40,
        "reorder_quantity": 120,
        "unit_cost": 1.55,
        "supplier": "Cascade Provisions",
    },
]

# --------------------------------------------------------------------------- #
# Competitors (seeded, clearly labelled)
# --------------------------------------------------------------------------- #
COMPETITORS: list[dict[str, Any]] = [
    {
        "name": "Brew & Bytes",
        "slug": "brew-and-bytes",
        "distance_km": 0.4,
        "price_tier": "mid",
        "avg_rating": 4.3,
        # 0-100 perception scores. `speed` is where they beat Juniper & Oak.
        "perception_scores": {
            "speed": 86,
            "service": 78,
            "quality": 74,
            "taste": 72,
            "price": 63,
            "packaging": 70,
            "ambience": 76,
        },
        "strengths": ["Fast evening service", "Quick pickup counter", "Consistent coffee"],
        "weaknesses": ["Limited food menu", "Pricey desserts"],
        "notes": "Opened a dedicated express counter for evening pickup orders.",
        "review_bias": {"waiting_time": 0.06, "service": 0.30, "taste": 0.22},
    },
    {
        "name": "Steamline Espresso Bar",
        "slug": "steamline-espresso",
        "distance_km": 0.9,
        "price_tier": "value",
        "avg_rating": 4.1,
        "perception_scores": {
            "speed": 81,
            "service": 71,
            "quality": 66,
            "taste": 79,
            "price": 88,
            "packaging": 58,
            "ambience": 60,
        },
        "strengths": ["Cheapest espresso drinks", "Fast counter service", "Long evening hours"],
        "weaknesses": ["Basic seating", "Weak packaging"],
        "notes": "Value-led neighborhood espresso bar with heavy evening foot traffic.",
        "review_bias": {"waiting_time": 0.08, "price": 0.34, "packaging": 0.18},
    },
    {
        "name": "The Roastery Co.",
        "slug": "the-roastery-co",
        "distance_km": 1.6,
        "price_tier": "premium",
        "avg_rating": 4.4,
        "perception_scores": {
            "speed": 69,
            "service": 84,
            "quality": 88,
            "taste": 86,
            "price": 48,
            "packaging": 83,
            "ambience": 89,
        },
        "strengths": ["Premium beans", "Excellent packaging", "Great ambience"],
        "weaknesses": ["Expensive", "Slower at peak hours"],
        "notes": "Premium specialty roaster; strongest on quality, weakest on price.",
        "review_bias": {"price": 0.30, "quality": 0.28, "waiting_time": 0.14},
    },
]

# --------------------------------------------------------------------------- #
# External signals - each tied to a real revenue exposure for this merchant
# --------------------------------------------------------------------------- #
EXTERNAL_SIGNALS: list[dict[str, Any]] = [
    {
        "title": "Arabica input prices climbing for a third straight month",
        "summary": (
            "Wholesale arabica prices are up roughly 14% quarter-on-quarter for US roasters, "
            "driven by lower Brazilian output and higher ocean freight costs."
        ),
        "category": "INPUT_COST",
        "icon": "coffee",
        "linked_category": "beverages",
        "direction": "NEGATIVE",
        "relevance": "HIGH",
        "relevance_score": 0.88,
        "potential_impact": "Margin pressure on your highest-volume category.",
        "recommended_action": (
            "Review coffee pricing or shift volume toward a bundled combo that protects "
            "margin without a headline price rise."
        ),
        "source_name": "Market Digest",
        "days_ago": 4,
        "tags": ["coffee", "input-cost", "margin"],
    },
    {
        "title": "Evening café traffic shifting toward quick-service formats",
        "summary": (
            "Neighborhood cafés in major US metros report evening customers increasingly "
            "choosing express pickup over dine-in, with sub-10-minute service the key driver."
        ),
        "category": "DEMAND",
        "icon": "clock",
        "linked_category": "food",
        "direction": "NEGATIVE",
        "relevance": "HIGH",
        "relevance_score": 0.84,
        "potential_impact": "Your evening slot is the most exposed to this shift.",
        "recommended_action": (
            "Test a pre-assembled evening combo that can be handed over in under five minutes."
        ),
        "source_name": "Hospitality Pulse",
        "days_ago": 9,
        "tags": ["evening", "service-speed", "demand"],
    },
    {
        "title": "Atmospheric river advisory: heavy evening rain forecast for two weeks",
        "summary": (
            "The National Weather Service expects above-normal evening rainfall across the "
            "Portland metro for two weeks, which historically suppresses walk-in traffic after 6pm."
        ),
        "category": "WEATHER",
        "icon": "cloud-rain",
        "linked_category": None,
        "direction": "NEGATIVE",
        "relevance": "MEDIUM",
        "relevance_score": 0.61,
        "potential_impact": "Short-term evening traffic risk on top of an existing decline.",
        "recommended_action": "Weight the evening experiment toward pre-order and pickup.",
        "source_name": "Regional Weather Outlook",
        "days_ago": 2,
        "tags": ["weather", "evening", "foot-traffic"],
    },
    {
        "title": "Dessert attach rates rising across US cafés",
        "summary": (
            "Cafés pairing a dessert with an evening beverage are reporting higher average "
            "tickets, with brownie-and-coffee the most common pairing."
        ),
        "category": "TREND",
        "icon": "trending-up",
        "linked_category": "desserts",
        "direction": "POSITIVE",
        "relevance": "MEDIUM",
        "relevance_score": 0.58,
        "potential_impact": "An upside lever for average order value in your weakest slot.",
        "recommended_action": "Include a dessert in the evening combo to lift ticket size.",
        "source_name": "Food Service Weekly",
        "days_ago": 12,
        "tags": ["dessert", "aov", "bundle"],
    },
]

# --------------------------------------------------------------------------- #
# US customer name pools (same pool sizes as before, so generation is unchanged)
# --------------------------------------------------------------------------- #
FIRST_NAMES: tuple[str, ...] = (
    "Liam",
    "Noah",
    "Oliver",
    "Elijah",
    "James",
    "William",
    "Benjamin",
    "Lucas",
    "Henry",
    "Theodore",
    "Jack",
    "Levi",
    "Mateo",
    "Owen",
    "Wyatt",
    "Caleb",
    "Olivia",
    "Emma",
    "Charlotte",
    "Amelia",
    "Sophia",
    "Mia",
    "Isabella",
    "Ava",
    "Evelyn",
    "Harper",
    "Luna",
    "Camila",
    "Gianna",
    "Abigail",
    "Ella",
    "Nora",
    "Ethan",
    "Logan",
    "Daniel",
    "Samuel",
    "Julian",
    "Aiden",
    "Hudson",
    "Ezra",
    "Scarlett",
    "Aria",
    "Riley",
    "Zoey",
    "Hazel",
    "Violet",
    "Aurora",
    "Stella",
)

LAST_NAMES: tuple[str, ...] = (
    "Smith",
    "Johnson",
    "Williams",
    "Brown",
    "Jones",
    "Garcia",
    "Miller",
    "Davis",
    "Rodriguez",
    "Martinez",
    "Hernandez",
    "Lopez",
    "Gonzalez",
    "Wilson",
    "Anderson",
    "Thomas",
    "Taylor",
    "Moore",
    "Jackson",
    "Martin",
    "Lee",
    "Nguyen",
    "Kim",
    "Patel",
)

"""Review generation for the demo dataset.

Reviews are derived from real orders. The waiting-time complaint rate is never
set directly: a review's topic is chosen from the order it describes, so when
evening service times drift up, more of those orders cross the complaint
threshold and the complaint volume rises on its own.

That is what makes the correlation the Growth Scientist finds genuine rather
than planted - nothing in the codebase says "the answer is waiting time".
"""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from app.db.models.commerce import DayPart
from app.db.models.review import ReviewTopic, Sentiment
from app.seed.generators.dataset import (
    COMPETITOR_REVIEWS_PER_RIVAL,
    HISTORY_DAYS,
    REVIEW_COUNT,
    CustomerRecord,
    ReviewRecord,
    TransactionRecord,
)

#: Phrase banks per topic and polarity. Deliberately varied so topic classification
#: and the embedding index have real lexical signal to work with.
REVIEW_PHRASES: dict[str, dict[str, list[str]]] = {
    ReviewTopic.WAITING_TIME: {
        "negative": [
            "Waited almost 20 minutes for one cold coffee. The queue barely moved.",
            "Took forever to get our order. Evening crowd and only one person at the counter.",
            "Good coffee but the wait is getting worse every week. Nearly half an hour today.",
            "Ordered at 7pm, got it at 7:25. Ended up late for my class.",
            "The wait time here has really gone downhill. It used to be quick.",
            "Long queue, slow service. Had to cancel and leave.",
            "Service was painfully slow during the evening rush.",
            "Great wrap, terrible wait. Twenty-five minutes is too long for a takeaway.",
            "Standing around for 18 minutes on a weekday evening is not acceptable.",
            "They need more staff in the evening. The wait keeps stretching.",
        ],
        "positive": [
            "In and out in five minutes even during the rush. Impressive.",
            "Quick service, order was ready before I finished paying.",
            "No waiting at all this morning, straight to the counter.",
        ],
    },
    ReviewTopic.TASTE: {
        "positive": [
            "The cold coffee here is genuinely the best in the area. Perfect balance.",
            "Masala chai tastes exactly like it should. Strong and properly spiced.",
            "Paneer wrap was delicious, well seasoned and generously filled.",
            "That brownie is dangerously good. Warm, fudgy, not too sweet.",
            "Cappuccino had a lovely flavour, proper espresso base.",
            "Flavours are consistently excellent. Never had a bad cup here.",
            "Honestly the chai alone is worth the trip.",
        ],
        "negative": [
            "The iced tea tasted watered down today.",
            "Coffee was bitter and over-extracted this time.",
        ],
    },
    ReviewTopic.QUALITY: {
        "positive": [
            "Consistently good quality. You know what you are getting.",
            "Ingredients taste fresh and the coffee beans are clearly good.",
            "Quality has stayed high even as they got busier.",
        ],
        "negative": [
            "Sandwich was soggy and the bread tasted stale.",
            "Quality seems to have slipped lately. Not what it was.",
        ],
    },
    ReviewTopic.SERVICE: {
        "positive": [
            "Staff were lovely, remembered my usual order.",
            "Very helpful team, sorted out a wrong order immediately.",
        ],
        "negative": [
            "Nobody at the counter for ten minutes in the evening.",
            "Felt understaffed. The one person working was clearly overwhelmed.",
            "Service was disorganised, they mixed up two orders ahead of me.",
        ],
    },
    ReviewTopic.PRICE: {
        "positive": [
            "Reasonable prices for the portion sizes.",
            "Good value, especially the chai.",
        ],
        "negative": [
            "Getting expensive for what it is. The wrap went up again.",
            "Prices are creeping up while portions shrink.",
        ],
    },
    ReviewTopic.PACKAGING: {
        "positive": ["Takeaway packaging was sturdy, nothing spilled on the ride home."],
        "negative": [
            "Coffee leaked all over the bag on the way back.",
            "Flimsy packaging, the lid popped off in my scooter.",
        ],
    },
    ReviewTopic.STAFF: {
        "positive": [
            "The barista is genuinely friendly and knows the menu inside out.",
            "Warm, welcoming staff. Makes the place.",
        ],
        "negative": ["Staff seemed rushed and a bit short with customers tonight."],
    },
    ReviewTopic.AMBIENCE: {
        "positive": [
            "Nice place to sit and work, good music and plenty of plug points.",
            "Comfortable seating and not too loud.",
        ],
        "negative": ["Very cramped in the evenings, could not find a seat."],
    },
    ReviewTopic.AVAILABILITY: {
        "positive": ["Everything on the menu was available even late in the evening."],
        "negative": [
            "Cold coffee was sold out by 7pm. Second time this month.",
            "They had run out of brownies again.",
        ],
    },
    ReviewTopic.DELIVERY: {
        "positive": ["Delivery arrived hot and on time."],
        "negative": ["Delivery took over an hour and arrived lukewarm."],
    },
}

REVIEW_TITLES: dict[str, list[str]] = {
    "positive": [
        "Great as always",
        "Solid neighbourhood cafe",
        "Love this place",
        "Consistently good",
    ],
    "neutral": ["Decent", "Fine", "Mixed experience", "It was okay"],
    "negative": [
        "Disappointing",
        "Not what it used to be",
        "Needs improvement",
        "Frustrating visit",
    ],
}

#: Wait beyond which a customer becomes likely to complain about the wait itself.
WAIT_COMPLAINT_THRESHOLD_MINUTES = 9.0
#: How sharply complaint probability rises per extra minute over the threshold.
WAIT_COMPLAINT_SLOPE = 0.135
#: Baseline chance of a grumble regardless of wait.
BASE_COMPLAINT_PROB = 0.08


def _sentiment_for_rating(rating: int) -> tuple[str, float]:
    if rating >= 4:
        return Sentiment.POSITIVE, round(0.45 + 0.12 * (rating - 4), 3)
    if rating == 3:
        return Sentiment.NEUTRAL, 0.0
    return Sentiment.NEGATIVE, round(-0.45 - 0.15 * (3 - rating), 3)


_SATISFIED_TOPICS: tuple[tuple[str, float], ...] = (
    (ReviewTopic.TASTE, 0.34),
    (ReviewTopic.QUALITY, 0.18),
    (ReviewTopic.STAFF, 0.12),
    (ReviewTopic.AMBIENCE, 0.10),
    (ReviewTopic.PRICE, 0.09),
    (ReviewTopic.PACKAGING, 0.08),
    (ReviewTopic.AVAILABILITY, 0.05),
    (ReviewTopic.DELIVERY, 0.04),
)


def generate_reviews(
    rng: random.Random,
    customers: list[CustomerRecord],
    transactions: list[TransactionRecord],
    *,
    target_count: int = REVIEW_COUNT,
) -> list[ReviewRecord]:
    by_ref = {c.external_ref: c for c in customers}
    rate = min(target_count / max(len(transactions), 1), 0.95)
    reviews: list[ReviewRecord] = []

    for txn in transactions:
        if rng.random() >= rate:
            continue
        customer = by_ref.get(txn.customer_ref)
        wait = float(txn.service_minutes or 0.0)

        # Complaint likelihood is a function of the wait on *this* order.
        wait_excess = max(wait - WAIT_COMPLAINT_THRESHOLD_MINUTES, 0.0)
        complain_p = min(BASE_COMPLAINT_PROB + wait_excess * WAIT_COMPLAINT_SLOPE, 0.86)

        if rng.random() < complain_p:
            topic = ReviewTopic.WAITING_TIME if rng.random() < 0.72 else ReviewTopic.SERVICE
            polarity = "negative"
            rating = 2 if wait_excess > 4 else rng.choice((2, 3))
        else:
            topic = rng.choices(
                [t for t, _ in _SATISFIED_TOPICS], weights=[w for _, w in _SATISFIED_TOPICS]
            )[0]
            polarity = "positive" if rng.random() < 0.80 else "negative"
            rating = (
                rng.choices((5, 4, 3), weights=(0.55, 0.32, 0.13))[0]
                if polarity == "positive"
                else 3
            )

        bank = (
            REVIEW_PHRASES.get(topic, {}).get(polarity)
            or REVIEW_PHRASES[ReviewTopic.TASTE]["positive"]
        )
        sentiment, score = _sentiment_for_rating(rating)
        tier = "positive" if rating >= 4 else "negative" if rating <= 2 else "neutral"

        topics = [topic]
        if rng.random() < 0.22:
            extra = rng.choice(
                [
                    t
                    for t in (ReviewTopic.TASTE, ReviewTopic.PRICE, ReviewTopic.SERVICE)
                    if t != topic
                ]
            )
            topics.append(extra)

        reviewed_at = txn.occurred_at + timedelta(hours=rng.randint(2, 40))
        reviews.append(
            ReviewRecord(
                author_name=customer.name if customer else "Paypal Customer",
                customer_ref=txn.customer_ref,
                rating=rating,
                title=rng.choice(REVIEW_TITLES[tier]),
                body=rng.choice(bank),
                sentiment=sentiment,
                sentiment_score=score,
                primary_topic=topic,
                topics=topics,
                daypart=txn.daypart,
                reviewed_at=reviewed_at,
                review_date=reviewed_at.date(),
                product_sku=txn.items[0].sku if txn.items else None,
                source=rng.choices(("paypal", "google", "zomato"), weights=(0.62, 0.24, 0.14))[0],
            )
        )
    return reviews


def generate_competitor_reviews(
    rng: random.Random,
    competitors: list[dict[str, Any]],
    *,
    anchor: date,
    per_competitor: int = COMPETITOR_REVIEWS_PER_RIVAL,
) -> dict[str, list[ReviewRecord]]:
    """Seeded competitor review corpora, shaped by each rival's perception profile.

    Clearly labelled simulated data. No competitor platform is accessed or scraped.
    """
    result: dict[str, list[ReviewRecord]] = {}
    for competitor in competitors:
        bias: dict[str, float] = dict(competitor.get("review_bias", {}))
        speed_score = float(competitor["perception_scores"].get("speed", 70))
        topics = [*list(bias.keys()), ReviewTopic.TASTE, ReviewTopic.QUALITY, ReviewTopic.AMBIENCE]
        weights = [*list(bias.values()), 0.18, 0.14, 0.1]

        reviews: list[ReviewRecord] = []
        for _ in range(per_competitor):
            topic = rng.choices(topics, weights=weights)[0]
            # A rival with a high speed score is mostly *praised* for waiting time,
            # which is exactly the comparison the Market Intelligence agent surfaces.
            if topic == ReviewTopic.WAITING_TIME:
                polarity = "positive" if rng.random() < (speed_score / 100.0) else "negative"
            else:
                polarity = "positive" if rng.random() < 0.74 else "negative"

            bank = (
                REVIEW_PHRASES.get(topic, {}).get(polarity)
                or REVIEW_PHRASES[ReviewTopic.TASTE]["positive"]
            )
            rating = (
                rng.choices((5, 4), weights=(0.6, 0.4))[0]
                if polarity == "positive"
                else rng.choices((2, 3), weights=(0.55, 0.45))[0]
            )
            sentiment, score = _sentiment_for_rating(rating)
            reviewed_at = datetime.combine(
                anchor - timedelta(days=rng.randint(0, HISTORY_DAYS - 1)),
                time(rng.randint(9, 22), rng.randint(0, 59)),
                tzinfo=UTC,
            )
            reviews.append(
                ReviewRecord(
                    author_name="Verified reviewer",
                    customer_ref=None,
                    rating=rating,
                    title="",
                    body=rng.choice(bank),
                    sentiment=sentiment,
                    sentiment_score=score,
                    primary_topic=topic,
                    topics=[topic],
                    daypart=rng.choice(DayPart.ALL),
                    reviewed_at=reviewed_at,
                    review_date=reviewed_at.date(),
                    product_sku=None,
                    source="seeded",
                )
            )
        result[competitor["slug"]] = reviews
    return result

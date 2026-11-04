"""Test harness.

The suite runs on SQLite so the whole auth / RBAC / tenant-isolation surface can
be exercised with no Postgres and no Docker (`make test` works anywhere). The
portable column types in ``app.db.types`` are what make that possible.

Two merchants and one user per role are created, because the tests that matter
most are about what a given role *cannot* do, and what one tenant cannot see.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

# Configure the environment before anything imports app.core.config.
#: Overridable so two suites can run side by side without sharing one file.
TEST_DB = Path(
    os.environ.get("PGA_TEST_DB") or (Path(__file__).parent / ".pytest_autopilot.sqlite3")
)
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB}"
os.environ["JWT_SECRET"] = "test-secret-key-for-the-suite-only-not-a-real-secret"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["LOG_LEVEL"] = "ERROR"
os.environ["LOG_FORMAT"] = "json"
os.environ["GROQ_API_KEY"] = ""
os.environ["LANGFUSE_ENABLED"] = "false"
os.environ["EMBEDDING_PROVIDER"] = "hash"
# The suite runs against the PayPal simulator only - never real credentials from .env.
for _key in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_WEBHOOK_ID", "PAYPAL_SANDBOX_PAYEE_EMAIL"):
    os.environ[_key] = ""
os.environ["PAYPAL_ENVIRONMENT"] = "sandbox"
os.environ["PAYPAL_SIMULATION_ENABLED"] = "true"

import httpx  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.db.session as db_session  # noqa: E402
from app.core.permissions import Role  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.models.auth import User, UserStatus  # noqa: E402
from app.db.models.commerce import (  # noqa: E402
    Customer,
    DayPart,
    Product,
    Transaction,
    TransactionItem,
)
from app.db.models.merchant import MembershipStatus, Merchant, MerchantMembership  # noqa: E402
from app.db.models.review import Review, Sentiment  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402

TEST_PASSWORD = "TestPassw0rd!2024"

#: Anchored so period maths is deterministic regardless of when the suite runs.
ANCHOR = date(2025, 6, 30)


# --------------------------------------------------------------------------- #
# Engine / session
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
async def engine():
    if TEST_DB.exists():
        TEST_DB.unlink()
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{TEST_DB}", future=True)

    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    # Point the application's own session factory at the test database, so code
    # that opens its own transaction (durable security auditing) also lands here.
    session_factory = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    db_session.engine = test_engine
    db_session.SessionLocal = session_factory

    yield test_engine

    await test_engine.dispose()
    if TEST_DB.exists():
        TEST_DB.unlink()


@pytest.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    async with factory() as s:
        yield s
        await s.commit()


# --------------------------------------------------------------------------- #
# Seed data
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
async def seeded(engine) -> dict:
    """Two tenants, a user per role, and enough commerce data to compute metrics."""
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    password_hash = hash_password(TEST_PASSWORD)

    async with factory() as s:
        primary = Merchant(
            name="Test Cafe", slug="test-cafe", category="cafe", city="Pune", is_demo=True
        )
        rival = Merchant(name="Other Cafe", slug="other-cafe", category="cafe", city="Mumbai")
        s.add_all([primary, rival])
        await s.flush()

        users: dict[str, User] = {}
        for role in (Role.OWNER, Role.ADMIN, Role.ANALYST, Role.STAFF, Role.VIEWER):
            user = User(
                email=f"{role.lower()}@test.in",
                password_hash=password_hash,
                full_name=f"{role.title()} User",
                status=UserStatus.ACTIVE,
                email_verified=True,
            )
            s.add(user)
            await s.flush()
            s.add(
                MerchantMembership(
                    user_id=user.id,
                    merchant_id=primary.id,
                    role=str(role),
                    status=MembershipStatus.ACTIVE,
                    is_default=True,
                    joined_at=datetime.now(tz=UTC),
                )
            )
            users[str(role)] = user

        # A user who belongs only to the *other* tenant.
        outsider = User(
            email="outsider@other.in",
            password_hash=password_hash,
            full_name="Outsider Owner",
            status=UserStatus.ACTIVE,
        )
        s.add(outsider)
        await s.flush()
        s.add(
            MerchantMembership(
                user_id=outsider.id,
                merchant_id=rival.id,
                role=str(Role.OWNER),
                status=MembershipStatus.ACTIVE,
                is_default=True,
                joined_at=datetime.now(tz=UTC),
            )
        )

        # ---- commerce data for both tenants -------------------------------
        for merchant, revenue_scale in ((primary, 1.0), (rival, 0.5)):
            product = Product(
                merchant_id=merchant.id,
                sku=f"{merchant.slug}-SKU1",
                name="Cold Coffee",
                category="beverages",
                price=100,
                cost_price=40,
            )
            s.add(product)
            await s.flush()

            customers = []
            for index in range(12):
                customer = Customer(
                    merchant_id=merchant.id,
                    external_ref=f"{merchant.slug}-C{index}",
                    name=f"Customer {index}",
                    preferred_daypart=DayPart.EVENING if index % 2 else DayPart.MORNING,
                )
                s.add(customer)
                customers.append(customer)
            await s.flush()

            # 60 days of orders: the last 30 deliberately weaker than the prior 30,
            # so period-over-period assertions have something real to measure.
            order_number = 0
            for offset in range(60):
                day = ANCHOR - timedelta(days=offset)
                recent = offset < 30
                orders_today = 2 if recent else 4
                for index in range(orders_today):
                    customer = customers[(offset + index) % len(customers)]
                    amount = round(100 * revenue_scale * (0.8 if recent else 1.0), 2)
                    order_number += 1
                    txn = Transaction(
                        merchant_id=merchant.id,
                        customer_id=customer.id,
                        order_ref=f"{merchant.slug}-ORD-{order_number}",
                        occurred_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC).replace(
                            hour=18 if index % 2 else 9
                        ),
                        business_date=day,
                        daypart=DayPart.EVENING if index % 2 else DayPart.MORNING,
                        hour_of_day=18 if index % 2 else 9,
                        day_of_week=day.weekday(),
                        gross_amount=amount,
                        discount_amount=0,
                        net_amount=amount,
                        cost_amount=round(amount * 0.4, 2),
                        item_count=1,
                        is_repeat=index > 0,
                        service_minutes=11.0 if recent else 6.0,
                    )
                    s.add(txn)
                    await s.flush()
                    s.add(
                        TransactionItem(
                            merchant_id=merchant.id,
                            transaction_id=txn.id,
                            product_id=product.id,
                            product_name=product.name,
                            quantity=1,
                            unit_price=product.price,
                            unit_cost=product.cost_price,
                            line_total=amount,
                        )
                    )

            # Reviews, weighted so the recent window is materially worse.
            for offset in range(60):
                day = ANCHOR - timedelta(days=offset)
                recent = offset < 30
                rating = 2 if recent else 5
                s.add(
                    Review(
                        merchant_id=merchant.id,
                        source="paypal",
                        author_name="Reviewer",
                        rating=rating,
                        body=(
                            "Waited far too long for my coffee this evening."
                            if recent
                            else "Great coffee, quick service."
                        ),
                        sentiment=Sentiment.NEGATIVE if recent else Sentiment.POSITIVE,
                        sentiment_score=-0.6 if recent else 0.6,
                        primary_topic="waiting_time" if recent else "taste",
                        topics=["waiting_time"] if recent else ["taste"],
                        daypart=DayPart.EVENING,
                        review_date=day,
                        reviewed_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
                    )
                )

        await s.commit()

        return {
            "merchant_id": primary.id,
            "other_merchant_id": rival.id,
            "users": {role: user.id for role, user in users.items()},
            "outsider_id": outsider.id,
            "anchor": ANCHOR,
        }


# --------------------------------------------------------------------------- #
# HTTP client
# --------------------------------------------------------------------------- #
@pytest.fixture
async def client(engine, seeded) -> AsyncIterator[httpx.AsyncClient]:
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with factory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test/api/v1", timeout=60.0
    ) as c:
        yield c
    app.dependency_overrides.clear()


async def login(client: httpx.AsyncClient, role: str) -> dict[str, str]:
    """Return an Authorization header for the user holding `role`."""
    response = await client.post(
        "/auth/login", json={"email": f"{role.lower()}@test.in", "password": TEST_PASSWORD}
    )
    assert response.status_code == 200, response.text
    token = response.json()["data"]["tokens"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def owner_headers(client) -> dict[str, str]:
    return await login(client, "OWNER")


@pytest.fixture
async def admin_headers(client) -> dict[str, str]:
    return await login(client, "ADMIN")


@pytest.fixture
async def analyst_headers(client) -> dict[str, str]:
    return await login(client, "ANALYST")


@pytest.fixture
async def staff_headers(client) -> dict[str, str]:
    return await login(client, "STAFF")


@pytest.fixture
async def viewer_headers(client) -> dict[str, str]:
    return await login(client, "VIEWER")


@pytest.fixture
async def outsider_headers(client) -> dict[str, str]:
    response = await client.post(
        "/auth/login", json={"email": "outsider@other.in", "password": TEST_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['tokens']['access_token']}"}

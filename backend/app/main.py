"""FastAPI application entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse, ORJSONResponse

from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, logging_backend, setup_logging
from app.core.middleware import register_middleware
from app.db.session import dispose_engine, ensure_extensions, ping_database
from app.integrations.external_search import external_search
from app.integrations.groq import llm_service
from app.integrations.langfuse import tracer
from app.integrations.paypal import close_paypal_gateway
from app.integrations.vapi import vapi_client
from app.integrations.vector_memory import memory
from app.services.integrations.zapier import zapier_relay
from app.services.inventory.relay import relay

setup_logging()
log = get_logger("app.main")

DESCRIPTION = """
An AI Growth Scientist for every merchant.

The product runs one loop: **Observe -> Diagnose -> Hypothesize -> Recommend ->
Act -> Measure -> Learn**. Every feature feeds it.

### Principles enforced by this API
* **Numbers are deterministic.** Every financial figure is computed in SQL/Python.
  The LLM reasons over structured results; it never calculates one.
* **Correlation is not causation.** The growth graph and agent outputs describe
  signals, correlations and hypotheses. Only a controlled experiment resolves them.
* **Humans approve money.** Campaign execution and experiment launch require a
  recorded approval from a user holding the permission. An agent cannot approve
  its own recommendation.
* **Tenant isolation is structural.** The merchant is resolved from membership,
  never from a client-supplied id.
* **Honest provenance.** Every response labels where its data came from and
  whether an action actually executed. Nothing claims live PayPal, messaging or
  competitor-platform access it doesn't have.

### Works without any API keys
With no `GROQ_API_KEY`, `LANGFUSE_*` or `VAPI_*` configured, the dashboard,
analytics, opportunity detection, experiments and the full agent workflow still
run - the recommendations are deterministic and only the prose is simpler.
""".strip()

TAGS_METADATA = [
    {"name": "health", "description": "Liveness and integration status."},
    {"name": "auth", "description": "Registration, sessions, profile and password management."},
    {
        "name": "dashboard",
        "description": "Growth Command Center, growth graph, customers, products.",
    },
    {"name": "growth", "description": "Opportunities, reviews, competitors, signals, inventory."},
    {"name": "campaigns", "description": "Campaigns and experiments, with their approval gates."},
    {"name": "agents", "description": "The LangGraph growth workflow, approvals and agent traces."},
    {"name": "voice", "description": "Vapi voice session and server-tool bridge."},
    {"name": "admin", "description": "Merchants, RBAC reference, team management and audit log."},
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log.info(
        "application_starting",
        environment=settings.app_env,
        version=settings.app_version,
        logging_backend=logging_backend(),
        llm=llm_service.enabled,
        # `tracer.enabled` rather than `settings.langfuse_active`: the keys being
        # present is not the same as the client having started. Reading it here also
        # forces initialisation, so a bad SDK/credential combination is reported at
        # boot instead of silently disabling tracing until the first agent run.
        langfuse=tracer.enabled,
        vapi=settings.vapi_active,
        embeddings=settings.embedding_provider,
        memory=settings.memory_enabled,
        paypal=settings.paypal_mode,
    )
    if await ping_database():
        extensions = await ensure_extensions()
        log.info("database_ready", extensions=extensions)
    else:
        # The app still boots so /health can report the problem clearly.
        log.error(
            "database_unavailable",
            hint="Run 'make db' to start Postgres, then 'make migrate' and 'make seed'.",
        )

    # Nothing else carries inventory events out to n8n, so this starts after
    # the database check rather than before it.
    if settings.outbox_relay_in_process:
        relay.start()
    else:
        log.info("outbox_relay_external", hint="Run 'python -m app.worker' to deliver events.")
    if settings.outbox_relay_in_process:
        zapier_relay.start()  # no-op unless ZAPIER_WEBHOOK_URL is set

    if settings.vapi_active:
        # The assistant's tools and prompt live on Vapi's platform, not in this
        # backend - a tool added to VOICE_TOOLS does nothing until it's pushed
        # there. Doing that on every boot means the live assistant can never
        # silently drift out of sync with the code that executes its tool calls.
        synced = await vapi_client.sync_assistant()
        log.info("vapi_assistant_sync", synced=synced)

    yield

    log.info("application_stopping")
    await relay.stop()
    await zapier_relay.stop()
    # Memory writes are queued off the request path, so a shutdown mid-flight
    # would otherwise silently drop what the last few runs concluded.
    await memory.drain()
    await close_paypal_gateway()
    tracer.shutdown()
    await llm_service.close()
    await vapi_client.close()
    await external_search.close()
    await dispose_engine()


app = FastAPI(
    title="PayPilot",
    description=DESCRIPTION,
    version=settings.app_version,
    lifespan=lifespan,
    default_response_class=ORJSONResponse,
    openapi_tags=TAGS_METADATA,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    contact={"name": "PayPilot"},
    license_info={"name": "MIT"},
    swagger_ui_parameters={"persistAuthorization": True, "docExpansion": "none"},
)

register_middleware(app)
register_exception_handlers(app)
app.include_router(api_router)


@app.get("/", include_in_schema=False)
async def root() -> JSONResponse:
    return JSONResponse(
        {
            "name": "PayPilot",
            "tagline": "An AI Growth Scientist for every merchant.",
            "version": settings.app_version,
            "docs": "/docs",
            "health": "/api/v1/health",
        }
    )

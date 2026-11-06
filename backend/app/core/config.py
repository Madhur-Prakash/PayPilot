"""Application configuration.

Every runtime knob lives here and is sourced from the environment, so nothing
(model names, merchant ids, secrets, hosts) is ever hardcoded deeper in the code.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent


def _env_files() -> tuple[str, ...]:
    """One environment file for the whole project, at the repo root.

    The frontend reads the same file (see frontend/next.config.ts), so there is a
    single place to configure both halves. Real environment variables still take
    precedence, which is what Docker and CI rely on.
    """
    return (str(REPO_ROOT / ".env"),)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_env_files(),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------------------------------------------------------- app
    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_name: str = "paypilot"
    app_version: str = "1.0.0"
    debug: bool = True
    log_level: str = "INFO"
    log_format: Literal["console", "json"] = "console"
    #: Render stdout with Logifyx's coloured layout (structured fields are appended by
    #: LogifyxConsoleFormatter). Set false to use the built-in console renderer instead.
    #: Ignored when Logifyx is not installed or when log_format is "json".
    log_console_logifyx: bool = True

    # ---------------------------------------------------------------- database
    database_url: str = "postgresql+asyncpg://autopilot:autopilot@localhost:5433/autopilot"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # ---------------------------------------------------------------- auth
    jwt_secret: str = "insecure-development-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 14
    refresh_cookie_name: str = "pga_refresh"
    refresh_cookie_secure: bool = False
    refresh_cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    # ---------------------------------------------------------------- llm
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    #: Tried when the primary model errors. llama-3.3-70b-versatile used to sit
    #: here and has been decommissioned by Groq - it returned 404, so the retry
    #: path could never actually recover.
    groq_fallback_model: str = "openai/gpt-oss-20b"
    groq_timeout_seconds: float = 45.0
    groq_max_retries: int = 2
    groq_temperature: float = 0.2
    groq_max_tokens: int = 2048
    #: AG Studio's AI assistant. Any OpenAI-compatible chat-completions API; blank
    #: values fall back to Groq with GROQ_API_KEY / GROQ_MODEL. Studio's agents send
    #: ~4-9k tokens of tool schemas per turn, more than Groq's free tier allows per
    #: minute - use a paid Groq tier or point these at another provider.
    studio_ai_enabled: bool = True
    studio_ai_base_url: str = ""
    studio_ai_api_key: str = ""
    studio_ai_model: str = ""
    studio_ai_fallback_model: str = ""
    #: gpt-oss models only: "low" keeps turns fast and small.
    studio_ai_reasoning_effort: Literal["", "low", "medium", "high"] = "low"
    studio_ai_max_tokens: int = 4096
    studio_ai_timeout_seconds: float = 60.0

    # ---------------------------------------------------------------- embeddings
    embedding_provider: Literal["hash", "fastembed"] = "hash"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dimensions: int = 384

    # ---------------------------------------------------------------- langfuse
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    # Accept both LANGFUSE_HOST and LANGFUSE_BASE_URL (the name used in the .env).
    # pydantic-settings resolves the field name first; validation_alias lets both work.
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_base_url: str = ""  # alias: if set, overrides langfuse_host
    langfuse_enabled: bool = True

    @property
    def langfuse_effective_host(self) -> str:
        """Return the configured Langfuse host, preferring LANGFUSE_BASE_URL."""
        return self.langfuse_base_url or self.langfuse_host

    # ---------------------------------------------------------------- vapi
    vapi_public_key: str = ""
    vapi_private_key: str = ""
    vapi_assistant_id: str = ""
    # Shared secret Vapi presents on every server-URL request. Vapi supports three
    # schemes (docs.vapi.ai/server-url/server-authentication); all three are accepted:
    #   Authorization: Bearer <secret>   - the recommended Bearer Token credential
    #   X-Vapi-Secret: <secret>          - the legacy plain-secret header
    #   <signature header>: <hmac>       - HMAC of the raw body, see below
    vapi_webhook_secret: str = ""
    #: Header carrying the HMAC when the assistant uses an HMAC credential.
    vapi_signature_header: str = "x-vapi-signature"
    #: Digest used for the HMAC scheme. sha256 matches Vapi's default.
    vapi_signature_algorithm: str = "sha256"

    # ---------------------------------------------------------------- email (Gmail API)
    # A single base64 line holding a pickled google.oauth2.credentials.Credentials
    # scoped to gmail.send. Mint it with: python scripts/mint_gmail_token.py
    # Leave it blank and email is rendered into the log instead of sent, which is
    # what lets a fresh checkout complete the invite flow with no credentials.
    gmail_credentials_b64: str = ""
    #: The authorised mailbox. Optional - Gmail fills it in - but setting it is what
    #: buys the display name on the From header.
    gmail_sender: str = ""
    email_from_name: str = "PayPilot"

    # ---------------------------------------------------------------- n8n
    #: Where the backend posts inventory domain events. Blank disables delivery -
    #: events are still recorded, just marked SKIPPED rather than retried forever.
    n8n_inventory_webhook_url: str = ""
    #: Shared secret for HMAC signing in both directions. Without it the inbound
    #: webhook rejects every request, so automation fails closed.
    n8n_webhook_secret: str = ""
    #: Base URL of the n8n instance, used only to build links into its UI.
    n8n_base_url: str = "http://localhost:5678"
    n8n_api_key: str = ""

    # ---------------------------------------------------------------- inventory
    #: Master switch. False stops the backend emitting inventory events at all.
    inventory_automation_enabled: bool = True
    #: Compute and record everything, but never contact a vendor. The UI labels
    #: these orders clearly so a dry run is never mistaken for a real one.
    inventory_dry_run: bool = False
    #: Orders at or above this value need a human approval before they are sent.
    #: 0 means every automatic order needs approval.
    inventory_approval_threshold: float = 500.0
    #: How often the outbox relay delivers pending events to n8n. This is
    #: the only thing that carries a stock change out to the automation, and
    #: the only thing that ever retries a failed delivery - without it,
    #: events sit at PENDING until someone flushes them by hand.
    inventory_dispatch_interval_seconds: float = 15.0
    #: Batch within this many days of expiry is EXPIRING_SOON.
    inventory_expiry_window_days: int = 30
    #: Stock sitting longer than this without movement is AGING.
    inventory_aging_window_days: int = 90

    # ---------------------------------------------------------------- memory (pgvector)
    #: Master switch for agent long-term memory. Memories live in the
    #: ``agent_memories`` table and are embedded locally with the embedding
    #: settings above (no API key, no extra service), so it is on by default.
    memory_enabled: bool = True
    #: How many memories to pull into an agent run.
    memory_recall_top_k: int = 6
    #: A recall that takes longer than this is abandoned. Memory enriches an
    #: answer; it is never allowed to delay one.
    memory_recall_timeout_seconds: float = 5.0

    # ---------------------------------------------------------------- paypal
    #: "sandbox" talks to api-m.sandbox.paypal.com, "live" to api-m.paypal.com.
    paypal_environment: Literal["sandbox", "live"] = "sandbox"
    #: REST app credentials from developer.paypal.com. Server-side only - these
    #: never reach the browser. Blank means the deterministic simulator is used
    #: and every response is labelled SIMULATED.
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    #: The webhook id PayPal assigned when the listener was registered. Required
    #: for signature verification; without it inbound webhooks are rejected.
    paypal_webhook_id: str = ""
    #: Optional override of the REST base URL (tests, proxies).
    paypal_api_base_url: str = ""
    paypal_timeout_seconds: float = 30.0
    paypal_max_retries: int = 2
    #: Route Orders v2 (create / get / capture) through PayPal's official
    #: APIMatic-generated Server SDK (``paypal-server-sdk``) instead of the
    #: hand-written REST call. Ignored when the base URL is a proxy or mock (not
    #: one of PayPal's own hosts) or a test transport is injected, since the SDK
    #: can only target PayPal's environments.
    paypal_orders_via_sdk: bool = True
    #: When credentials are missing, fall back to the simulator rather than
    #: failing. Set false to make a missing credential a hard error.
    paypal_simulation_enabled: bool = True
    paypal_brand_name: str = "PayPilot"
    #: Primary currency for the demo merchant. Amounts in other currencies are
    #: never added to it without an explicit conversion.
    default_currency: str = "USD"
    #: Signs simulator-originated webhook events so the local pipeline can be
    #: exercised end to end. Never accepted when real credentials are configured.
    paypal_simulator_webhook_secret: str = ""
    #: Sandbox business account the demo pays suppliers into. When set, every
    #: seeded supplier agent uses it as its PayPal payee, so supplier payments
    #: complete end to end against a real sandbox.
    paypal_sandbox_payee_email: str = ""

    # ---------------------------------------------------------------- PayPal Agent Toolkit / MCP
    #: Read-only bridge to PayPal's MCP server (the Agent Toolkit tools). Safe to
    #: leave on: only allow-listed *read* tools are callable, whatever the server
    #: offers - see integrations/paypal/mcp.py. Set false to disable it entirely.
    paypal_mcp_enabled: bool = True
    #: Blank derives the sandbox/production MCP endpoint (HTTP+SSE at /sse) from
    #: PAYPAL_ENVIRONMENT. A URL not ending in /sse is treated as Streamable HTTP.
    paypal_mcp_url: str = ""

    # ---------------------------------------------------------------- sponsor integrations
    #: Channel3 product search - market price reference for the buyer agent.
    #: Blank key = a clearly labelled deterministic reference catalogue.
    channel3_api_key: str = ""
    channel3_base_url: str = "https://api.trychannel3.com"
    #: Kernel cloud browsers - supplier-portal verification sessions.
    kernel_api_key: str = ""
    kernel_base_url: str = "https://api.onkernel.com"
    #: Elasticsearch - evidence search. Blank URL = PostgreSQL full-text fallback.
    elastic_url: str = ""
    elastic_api_key: str = ""
    elastic_index_prefix: str = "paypilot"
    #: Zapier "Catch Hook" URL - business events fan out to it, signed.
    zapier_webhook_url: str = ""
    zapier_signing_secret: str = ""

    # ---------------------------------------------------------------- supply agents
    #: HMAC key for agent-to-agent protocol messages. Blank derives one from
    #: JWT_SECRET so a fresh checkout still signs (and verifies) every message.
    agent_protocol_secret: str = ""
    #: Hard ceiling on negotiation rounds, whatever a policy asks for.
    procurement_max_negotiation_rounds: int = 4
    #: How long a supplier quote stays valid.
    procurement_quote_ttl_hours: int = 48
    #: Margin the merchant wants to keep when no product-level target exists.
    procurement_default_target_margin: float = 0.40
    #: Invoice unit-price variance tolerated by three-way matching (0.02 = 2%).
    procurement_price_tolerance_pct: float = 0.02
    #: Absolute tolerance on an invoice total, in the order currency.
    procurement_total_tolerance_amount: float = 1.00

    # ---------------------------------------------------------------- supabase
    supabase_url: str = ""
    supabase_anon_key: str = ""

    # ---------------------------------------------------------------- external
    external_search_provider: Literal["seed", "tavily"] = "seed"
    tavily_api_key: str = ""

    # ---------------------------------------------------------------- networking
    frontend_url: str = "http://localhost:3000"
    backend_url: str = "https://wordier-unconfiding-margrett.ngrok-free.dev"
    # NoDecode: pydantic-settings would otherwise try to JSON-parse this from the
    # environment before the validator below gets to split the comma-separated form.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 300
    rate_limit_window_seconds: int = 60

    # ---------------------------------------------------------------- demo seed
    seed_random_seed: int = 20240917
    demo_owner_email: str = "owner@juniperoak.com"
    demo_owner_password: str = "Autopilot@2024"
    demo_merchant_name: str = "Juniper & Oak Coffee"

    # ---------------------------------------------------------------- worker
    #: Run the outbox relay inside the API process. Set false when a separate
    #: worker (``python -m app.worker``) delivers events, e.g. on Render.
    outbox_relay_in_process: bool = True

    # ---------------------------------------------------------------- validators
    @field_validator("database_url", mode="before")
    @classmethod
    def _normalise_database_url(cls, value: object) -> object:
        """Accept the plain URLs hosting providers hand out (Render, Heroku-style).

        ``postgres://`` / ``postgresql://`` become ``postgresql+asyncpg://``, and a
        ``sslmode`` query parameter (libpq syntax asyncpg does not understand) is
        translated to asyncpg's ``ssl``.
        """
        if not isinstance(value, str):
            return value
        url = value.strip()
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                url = "postgresql+asyncpg://" + url[len(prefix):]
                break
        if url.startswith("postgresql+asyncpg://") and "sslmode=" in url:
            url = url.replace("sslmode=require", "ssl=require").replace("sslmode=disable", "ssl=disable")
        return url

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return str(value).upper() if isinstance(value, str) else value

    # ---------------------------------------------------------------- derived
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_testing(self) -> bool:
        return self.app_env == "test"

    @property
    def llm_enabled(self) -> bool:
        """True when a real LLM provider is reachable; otherwise agents run heuristically."""
        return bool(self.groq_api_key)

    @property
    def langfuse_active(self) -> bool:
        return bool(self.langfuse_enabled and self.langfuse_public_key and self.langfuse_secret_key)

    @property
    def emails_enabled(self) -> bool:
        """Whether a real transport is configured. False renders to the log."""
        return bool(self.gmail_credentials_b64)

    @property
    def vapi_active(self) -> bool:
        return bool(self.vapi_private_key and self.vapi_assistant_id)

    @property
    def paypal_configured(self) -> bool:
        """True when real PayPal REST credentials are present."""
        return bool(self.paypal_client_id and self.paypal_client_secret)

    @property
    def paypal_mode(self) -> Literal["LIVE", "SANDBOX", "SIMULATED"]:
        if not self.paypal_configured:
            return "SIMULATED"
        return "LIVE" if self.paypal_environment == "live" else "SANDBOX"

    @property
    def paypal_base_url(self) -> str:
        if self.paypal_api_base_url:
            return self.paypal_api_base_url.rstrip("/")
        if self.paypal_environment == "live":
            return "https://api-m.paypal.com"
        return "https://api-m.sandbox.paypal.com"

    @property
    def paypal_mcp_endpoint(self) -> str:
        if self.paypal_mcp_url:
            return self.paypal_mcp_url.rstrip("/")
        host = "mcp.paypal.com" if self.paypal_environment == "live" else "mcp.sandbox.paypal.com"
        return f"https://{host}/sse"

    @property
    def zapier_signing_key(self) -> bytes:
        if self.zapier_signing_secret:
            return self.zapier_signing_secret.encode("utf-8")
        import hashlib

        return hashlib.sha256(f"zapier::{self.jwt_secret}".encode()).digest()

    @property
    def agent_protocol_key(self) -> bytes:
        """Key for signing agent messages, derived when not configured."""
        if self.agent_protocol_secret:
            return self.agent_protocol_secret.encode("utf-8")
        import hashlib

        return hashlib.sha256(f"agent-protocol::{self.jwt_secret}".encode()).digest()

    @property
    def sync_database_url(self) -> str:
        """psycopg/sync form of the database URL (used by tooling that cannot await)."""
        return self.database_url.replace("+asyncpg", "").replace("+aiosqlite", "")

    @property
    def db_dialect(self) -> str:
        return self.database_url.split("://", 1)[0].split("+", 1)[0]

    @property
    def is_postgres(self) -> bool:
        return self.db_dialect.startswith("postgres")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    """Clear the settings cache - used by tests that patch the environment."""
    get_settings.cache_clear()
    return get_settings()


# Tests inject their own database before the app imports anything heavyweight.
if os.getenv("PGA_TEST_MODE") == "1":  # pragma: no cover - exercised by the test harness
    os.environ.setdefault("APP_ENV", "test")

settings = get_settings()

"""Transactional email through the Gmail API.

**One transport, in one file.** Loading the credential, minting access tokens,
posting the message, and the message templates are the single path an email takes
out of this application. There is no SMTP fallback: a second transport means two
code paths that can render the same email differently, and the one that is not
exercised is the one that breaks.

Two behaviours, chosen by whether ``GMAIL_CREDENTIALS_B64`` is configured:

* **Configured** - sends through the Gmail API.
* **Not configured** - renders the message and writes it to the structured log,
  including the temporary password and sign-in link. This is not a transport; it is
  what makes a fresh checkout and the test suite work with no credentials at all.

**Why the Gmail API rather than SMTP.** Google refuses plain passwords, and app
passwords need 2FA plus a per-account secret any Workspace admin can switch off
org-wide. A refresh token scoped to ``gmail.send`` grants exactly one capability -
sending - so a leaked credential cannot read the mailbox it sends from.

**The official client, not hand-rolled HTTP.** ``google-api-python-client`` owns the
send and ``google-auth`` owns the token lifecycle, so neither drifts when Google
changes. The catch is that both are synchronous - httplib2 underneath - so a send
must leave the event loop or it stalls every other request; see :func:`_send_sync`.

Configuration is a single base64 line holding a **pickled**
:class:`google.oauth2.credentials.Credentials` - the ``token.pickle`` the Gmail
quickstart writes. Base64 because a ``.env`` value cannot hold arbitrary bytes or
newlines, and quoting a credential through docker compose, a shell and pydantic is
a reliable source of corrupted secrets. Mint it with
``python scripts/mint_gmail_token.py``.

**The pickle is trusted input, and that is a real constraint.** ``pickle.loads``
executes whatever the payload tells it to, so this blob is not data - it carries the
same authority as the code in this repository. It is safe here because it comes from
the operator's own ``.env``. It would not be safe sourced from a database, an upload,
an API request, or a shared config service. :func:`_load_credentials` does not
validate the payload before unpickling it, so that constraint is the only thing
keeping this safe.

Sending never raises into a request. An invitation that created the account must not
report failure because Google was briefly unreachable - the operator can always
re-send, but a rolled-back invitation is confusing. A transient failure is retried a
few times and logged as a warning; a permanent one is logged at error level.
"""

from __future__ import annotations

import asyncio
import base64
import pickle
import threading
from email.message import EmailMessage
from email.policy import SMTP as SMTP_POLICY
from typing import Any, Final

import anyio.to_thread
from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from jinja2 import Environment, select_autoescape
from markupsafe import Markup

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

#: The scope the refresh token must carry. Not requested here - it is fixed when the
#: token is minted - but named so the error path can say what is missing.
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

#: Attempts per message, and the waits between them.
#:
#: Deliberately short. Sends are awaited inside the request that triggered them, so
#: every second here is a second a merchant waits on the invite form. Three quick
#: attempts ride out a blip; a longer ladder just makes a failure feel broken. Only
#: transient failures are retried, so a bad credential still fails on the first.
_MAX_ATTEMPTS: Final = 3
_RETRY_WAITS: Final = (1.0, 2.0)


class GmailConfigurationError(RuntimeError):
    """The configured credential is absent, malformed, or not usable.

    Separate from a delivery failure because it is never worth retrying and never
    fixes itself: every instance is a deployment problem with a specific fix.
    """


# =============================================================================
# Credentials
# =============================================================================
def _load_credentials() -> Any:
    """Unpickle the configured credential and build an authorised Gmail client.

    Returns the *client*, not the credential - hence ``Any``: googleapiclient ships
    no stubs, so ``build()`` is untyped.
    """
    blob = settings.gmail_credentials_b64
    if not blob:
        raise GmailConfigurationError("GMAIL_CREDENTIALS_B64 is not set.")

    try:
        # The blob is the operator's own configuration and carries the same authority
        # as this repository's code - see the module docstring. It must never be
        # sourced from a database, an upload, or an untrusted config service.
        creds = pickle.loads(base64.b64decode(blob))
    except GmailConfigurationError:
        raise
    except Exception as exc:
        raise GmailConfigurationError(
            "GMAIL_CREDENTIALS_B64 is not a base64-encoded pickled Credentials object. "
            "Re-mint it with: python scripts/mint_gmail_token.py"
        ) from exc

    if not hasattr(creds, "refresh_token"):
        raise GmailConfigurationError(
            "GMAIL_CREDENTIALS_B64 decoded to something that is not a Credentials object."
        )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


#: Sends are serialised.
#:
#: Neither the httplib2 connection inside a service object nor a shared
#: ``Credentials`` is thread-safe, and two worker threads refreshing the same
#: credential at once is a race on the token. Transactional mail is a handful of
#: messages, so serialising costs nothing measurable and removes the whole class
#: of problem.
_send_lock = threading.Lock()


def _send_sync(message: EmailMessage) -> None:
    """Post one message. Blocking - the whole reason this runs in a thread."""
    # `raw` is a complete RFC 5322 message, so it is serialised with the SMTP policy:
    # CRLF line endings and folded headers, the same bytes any transport would put
    # on the wire.
    raw = base64.urlsafe_b64encode(message.as_bytes(policy=SMTP_POLICY)).decode("ascii")
    with _send_lock:
        service = _load_credentials()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()


def _is_transient(exc: BaseException) -> bool:
    """Whether retrying this failure could plausibly succeed.

    The caller is a user waiting on a response. Retrying a revoked token or a missing
    scope cannot work - it only adds delay to a failure that is already certain - so
    those give up immediately.
    """
    if isinstance(exc, GmailConfigurationError | RefreshError):
        return False
    if isinstance(exc, HttpError):
        status = exc.status_code
        # 429 and 5xx are Google saying "not now". Every other 4xx is "not ever".
        return status is not None and (status == 429 or status >= 500)
    return isinstance(exc, TransportError | OSError | TimeoutError)


def _describe(exc: BaseException) -> str:
    """A one-line reason, carrying Google's own wording where there is one."""
    if isinstance(exc, RefreshError):
        detail = f"RefreshError: {exc}"
        if "invalid_grant" in str(exc):
            # The one Gmail failure whose message says nothing useful. `invalid_grant`
            # on a refresh means Google has rejected the refresh token itself, so no
            # amount of retrying helps - it has to be replaced. The first cause is
            # overwhelmingly the common one and is invisible from the error.
            return (
                f"{detail} - Google has rejected the refresh token itself; it is dead "
                "rather than misconfigured. Causes, in order of likelihood: the OAuth "
                "consent screen is still in Testing (Google expires those refresh "
                "tokens after 7 days - publish the app to stop it), the token was "
                "revoked from the account's third-party access, the account password "
                "changed, the OAuth client was deleted or recreated."
            )
        return detail
    if isinstance(exc, HttpError):
        return f"HTTP {exc.status_code}: {exc}"
    return f"{type(exc).__name__}: {exc}"


# =============================================================================
# Rendering
# =============================================================================
#: ``autoescape`` is non-negotiable: merchant-supplied names go into these bodies,
#: and an unescaped one is HTML injection into whatever the recipient's client
#: renders.
_jinja = Environment(autoescape=select_autoescape(["html", "xml"]), enable_async=False)

_BASE_STYLES: Final = """
  body{margin:0;padding:0;background:#EDF3FA;font-family:-apple-system,BlinkMacSystemFont,
    'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;color:#0B1B33;}
  .wrap{max-width:560px;margin:0 auto;padding:36px 24px;}
  .card{background:#fff;border:1px solid #E7ECF3;border-radius:14px;padding:30px;}
  .brand{font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;
    margin:0 0 20px;color:#00BAF2;}
  h1{font-size:20px;font-weight:600;letter-spacing:-.02em;margin:0 0 12px;color:#0B1B33;}
  p{font-size:14px;line-height:1.6;color:#5B6B82;margin:0 0 16px;}
  .btn{display:inline-block;background:#002E6E;color:#fff!important;text-decoration:none;
    font-size:14px;font-weight:600;padding:11px 20px;border-radius:8px;margin:8px 0 20px;}
  .code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:22px;font-weight:600;
    letter-spacing:.12em;background:#F4F7FB;border:1px solid #E7ECF3;border-radius:10px;
    padding:16px;text-align:center;margin:18px 0;color:#0B1B33;}
  .kv{background:#F4F7FB;border:1px solid #E7ECF3;border-radius:10px;padding:14px 16px;
    margin:0 0 20px;}
  .kv .label{font-size:12px;color:#5B6B82;margin:0 0 4px;}
  .kv .value{font-size:14px;color:#0B1B33;margin:0 0 12px;}
  .fallback{font-size:12px;color:#5B6B82;word-break:break-all;}
  .foot{font-size:12px;color:#8FA6C7;margin:24px 0 0;padding-top:18px;border-top:1px solid #F4F7FB;}
"""

_LAYOUT: Final = """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ subject }}</title><style>{{ styles }}</style></head>
<body><div class="wrap"><div class="card">
  <p class="brand">PayPilot</p>
  {{ body }}
  {# `true` as the second argument is load-bearing: Jinja's `default` filter
     substitutes only for an *undefined* variable, and `_render` always passes
     `footer` - as `None` when the caller omitted it. Without the flag every email
     that does not name its own footer renders the literal word "None". #}
  <p class="foot">{{ footer|default("You are receiving this because someone gave this
    address access to a merchant on PayPilot. If that was not expected,
    you can ignore this email.", true) }}</p>
</div></div></body></html>
"""


def _render(body_template: str, *, subject: str, footer: str | None = None, **context: Any) -> str:
    """Render a body template, then wrap it in the shared layout.

    **``Markup`` is what makes the two stages work.** ``render()`` returns a plain
    ``str``, and dropping that into the layout's ``{{ body }}`` escapes it a second
    time - which turns the email into a wall of visible source, ``&lt;h1&gt;`` and
    all, with the button rendered as text rather than a link.

    This is safe rather than a hole in the autoescaping, and the ordering is the
    reason: the inner render escapes every value in ``context`` as it interpolates,
    so by the time the result is marked safe the only markup left is the template's
    own. ``footer`` is deliberately *not* marked - it is prose, and leaving it
    escaped means a caller cannot smuggle markup through it.
    """
    body = _jinja.from_string(body_template).render(**context)
    return _jinja.from_string(_LAYOUT).render(
        subject=subject,
        # S704 is the right rule in general and cannot see either argument's
        # provenance. `_BASE_STYLES` is a module constant and `body` was escaped by
        # the render above; see the docstring.
        styles=Markup(_BASE_STYLES),
        body=Markup(body),
        footer=footer,
    )


# =============================================================================
# Send
# =============================================================================
async def send_email(
    *,
    to: str,
    subject: str,
    html: str,
    text: str,
    category: str = "transactional",
) -> bool:
    """Send one message. Returns success; never raises.

    A plaintext alternative always accompanies the HTML - some clients refuse to
    render HTML, and multipart messages score better with spam filters.
    """
    if not settings.emails_enabled:
        # Development: the credentials in `text` are the whole point of this branch.
        log.warning(
            "email_suppressed",
            reason="GMAIL_CREDENTIALS_B64 not set",
            to=to,
            subject=subject,
            category=category,
            body=text,
        )
        return False

    message = EmailMessage()
    # Omitted rather than guessed when unset: Gmail fills in the authorised mailbox
    # itself, and inventing an address here would be rewritten or rejected. Setting
    # GMAIL_SENDER is what buys the display name.
    if settings.gmail_sender:
        message["From"] = f"{settings.email_from_name} <{settings.gmail_sender}>"
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    context = {"to": _mask(to), "subject": subject, "category": category}

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            # googleapiclient is synchronous - httplib2 underneath - so it has to
            # leave the event loop or it stalls every other request for the duration
            # of the round trip. anyio rather than asyncio.to_thread because that is
            # the pool FastAPI already sizes and instruments.
            await anyio.to_thread.run_sync(_send_sync, message)
            log.info("email_sent", **context)
            return True
        except Exception as exc:
            retryable = _is_transient(exc) and attempt < _MAX_ATTEMPTS
            # Swallowed either way - see the module docstring. A retryable failure is
            # a warning because it may yet succeed; the last one should page someone.
            payload = {
                **context,
                "attempt": attempt,
                "attempts": _MAX_ATTEMPTS,
                "error": _describe(exc),
                "will_retry": retryable,
            }
            if retryable:
                log.warning("email_delivery_failed", **payload)
            else:
                log.error("email_delivery_failed", **payload)
                return False
            await asyncio.sleep(_RETRY_WAITS[attempt - 1])

    return False


def _sign_in_url() -> str:
    return f"{settings.frontend_url.rstrip('/')}/login"


def _mask(address: str) -> str:
    """Log who we mailed without writing the full address into the log."""
    name, _, domain = address.partition("@")
    if not domain:
        return "***"
    head = name[:2] if len(name) > 2 else name[:1]
    return f"{head}***@{domain}"


# =============================================================================
# Messages
# =============================================================================
async def send_invitation_email(
    *,
    to: str,
    full_name: str,
    merchant_name: str,
    role: str,
    temporary_password: str,
    invited_by: str,
) -> bool:
    subject = f"You have been added to {merchant_name} on PayPilot"
    link = _sign_in_url()

    html = _render(
        """
        <h1>You have access to {{ merchant_name }}</h1>
        <p>Hi {{ full_name }}, {{ invited_by }} added you to
           <strong>{{ merchant_name }}</strong> with the
           <strong>{{ role }}</strong> role.</p>
        <div class="kv">
          <p class="label">Email</p>
          <p class="value">{{ to }}</p>
          <p class="label">Temporary password</p>
          <p class="value" style="font-family:ui-monospace,Menlo,monospace;font-size:16px;
             letter-spacing:.5px;margin:0;">{{ temporary_password }}</p>
        </div>
        <a class="btn" href="{{ link }}">Sign in</a>
        <p class="fallback">Or paste this into your browser:<br>{{ link }}</p>
        <p>Please change this password after your first sign-in.</p>
        """,
        subject=subject,
        full_name=full_name,
        merchant_name=merchant_name,
        role=role,
        to=to,
        temporary_password=temporary_password,
        invited_by=invited_by,
        link=link,
    )
    text = (
        f"Hi {full_name},\n\n"
        f"{invited_by} added you to {merchant_name} on PayPilot "
        f"with the {role} role.\n\n"
        f"Sign in: {link}\n"
        f"Email: {to}\n"
        f"Temporary password: {temporary_password}\n\n"
        "Please change this password after your first sign-in.\n\n"
        "If you were not expecting this, you can ignore this message.\n"
    )
    return await send_email(to=to, subject=subject, html=html, text=text, category="invitation")


async def send_test_email(*, to: str) -> bool:
    """Used by the settings screen to prove the configuration works."""
    subject = "PayPilot - test email"
    html = _render(
        """
        <h1>Your mail settings work</h1>
        <p>This is a test message from PayPilot. If you are reading it,
           outbound email is configured correctly.</p>
        """,
        subject=subject,
        footer="You requested this test from the Settings screen.",
    )
    text = (
        "This is a test message from PayPilot. "
        "If you are reading it, outbound email is configured correctly.\n"
    )
    return await send_email(to=to, subject=subject, html=html, text=text, category="test")


# =============================================================================
# Status, for the health check and the settings screen
# =============================================================================
class EmailService:
    """Thin facade so callers do not import six free functions."""

    @property
    def enabled(self) -> bool:
        return settings.emails_enabled

    @property
    def status(self) -> str:
        return "configured" if self.enabled else "not_configured"

    send_invitation = staticmethod(send_invitation_email)
    send_test = staticmethod(send_test_email)
    send = staticmethod(send_email)


email_service = EmailService()

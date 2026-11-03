"""Password hashing and JWT issuance/verification.

Passwords use Argon2id. Access tokens are short-lived JWTs; refresh tokens are
opaque high-entropy strings that are stored **hashed** and rotated on every use.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings
from app.core.exceptions import InvalidTokenError, TokenExpiredError, ValidationError

_hasher = PasswordHasher(
    time_cost=2, memory_cost=64 * 1024, parallelism=2, hash_len=32, salt_len=16
)

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"
RESET_TOKEN_TYPE = "password_reset"


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
_PASSWORD_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[a-z]"), "one lowercase letter"),
    (re.compile(r"[A-Z]"), "one uppercase letter"),
    (re.compile(r"\d"), "one digit"),
    (re.compile(r"[^A-Za-z0-9]"), "one symbol"),
)
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128


def validate_password_strength(password: str) -> None:
    """Raise ValidationError describing every unmet requirement at once."""
    problems: list[str] = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        problems.append(f"at most {MAX_PASSWORD_LENGTH} characters")
    problems.extend(label for pattern, label in _PASSWORD_RULES if not pattern.search(password))
    if problems:
        raise ValidationError(
            "Password must contain " + ", ".join(problems) + ".",
            details={"requirements": problems},
        )


def hash_password(password: str) -> str:
    validate_password_strength(password)
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# JWT access tokens
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class TokenPayload:
    subject: str
    token_type: str
    jti: str
    issued_at: datetime
    expires_at: datetime
    merchant_id: str | None = None
    roles: tuple[str, ...] = ()
    raw: dict[str, Any] | None = None


def _now() -> datetime:
    return datetime.now(tz=UTC)


def create_access_token(
    subject: str | uuid.UUID,
    *,
    merchant_id: str | uuid.UUID | None = None,
    roles: list[str] | tuple[str, ...] = (),
    expires_minutes: int | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, datetime]:
    issued = _now()
    expires = issued + timedelta(
        minutes=expires_minutes or settings.jwt_access_token_expire_minutes
    )
    claims: dict[str, Any] = {
        "sub": str(subject),
        "type": ACCESS_TOKEN_TYPE,
        "jti": uuid.uuid4().hex,
        "iat": int(issued.timestamp()),
        "nbf": int(issued.timestamp()),
        "exp": int(expires.timestamp()),
        "iss": settings.app_name,
        "roles": list(roles),
    }
    if merchant_id is not None:
        claims["mid"] = str(merchant_id)
    if extra_claims:
        claims.update(extra_claims)
    token = jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires


def decode_token(token: str, *, expected_type: str | None = ACCESS_TOKEN_TYPE) -> TokenPayload:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.app_name,
            options={"require": ["exp", "sub", "iat"]},
        )
    except jwt.ExpiredSignatureError:
        raise TokenExpiredError()
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError(details={"reason": type(exc).__name__})

    token_type = str(claims.get("type", ""))
    if expected_type and token_type != expected_type:
        raise InvalidTokenError(f"Expected a {expected_type} token.")

    return TokenPayload(
        subject=str(claims["sub"]),
        token_type=token_type,
        jti=str(claims.get("jti", "")),
        issued_at=datetime.fromtimestamp(claims["iat"], tz=UTC),
        expires_at=datetime.fromtimestamp(claims["exp"], tz=UTC),
        merchant_id=claims.get("mid"),
        roles=tuple(claims.get("roles", ()) or ()),
        raw=claims,
    )


# --------------------------------------------------------------------------- #
# Refresh tokens (opaque, stored hashed, rotated on use)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class RefreshToken:
    token: str
    token_hash: str
    expires_at: datetime
    family_id: str


def generate_refresh_token(*, family_id: str | None = None) -> RefreshToken:
    raw = secrets.token_urlsafe(48)
    return RefreshToken(
        token=raw,
        token_hash=hash_refresh_token(raw),
        expires_at=_now() + timedelta(days=settings.jwt_refresh_token_expire_days),
        family_id=family_id or uuid.uuid4().hex,
    )


def hash_refresh_token(token: str) -> str:
    """Keyed hash so a database leak alone cannot be replayed."""
    return hmac.new(
        settings.jwt_secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def refresh_tokens_match(candidate: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_refresh_token(candidate), stored_hash)


# --------------------------------------------------------------------------- #
# Password reset tokens
# --------------------------------------------------------------------------- #
def create_password_reset_token(subject: str | uuid.UUID, *, expires_minutes: int = 30) -> str:
    issued = _now()
    claims = {
        "sub": str(subject),
        "type": RESET_TOKEN_TYPE,
        "jti": uuid.uuid4().hex,
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(minutes=expires_minutes)).timestamp()),
        "iss": settings.app_name,
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_password_reset_token(token: str) -> TokenPayload:
    return decode_token(token, expected_type=RESET_TOKEN_TYPE)


# --------------------------------------------------------------------------- #
# Misc
# --------------------------------------------------------------------------- #
def new_request_id() -> str:
    return uuid.uuid4().hex


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)

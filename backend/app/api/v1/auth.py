"""Authentication endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Request, Response, status

from app.api.deps import CurrentPrincipal, CurrentUserDep, DbSession, client_ip, user_agent
from app.core.config import settings
from app.core.exceptions import InvalidTokenError
from app.core.security import create_password_reset_token, verify_password_reset_token
from app.repositories.merchant import MembershipRepository
from app.schemas.auth import (
    AuthSession,
    ChangePasswordRequest,
    CurrentUser,
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    RegisterRequest,
    UpdateProfileRequest,
    UserOut,
)
from app.schemas.common import ActionAck, APIResponse
from app.services.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_refresh_cookie(response: Response, token: str | None) -> None:
    """Refresh tokens live in an HttpOnly cookie so page JS cannot read them."""
    if not token:
        return
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
        max_age=settings.jwt_refresh_token_expire_days * 24 * 3600,
        path="/api/v1/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(settings.refresh_cookie_name, path="/api/v1/auth")


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account",
    description="Creates the user, a merchant workspace they own, and an initial session.",
)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    session: DbSession,
) -> APIResponse[AuthSession]:
    service = AuthService(session)
    result = await service.register(
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        merchant_name=payload.merchant_name,
        phone=payload.phone,
        request_id=getattr(request.state, "request_id", None),
        ip_address=client_ip(request),
        user_agent=user_agent(request),
    )
    _set_refresh_cookie(response, result.tokens.refresh_token)
    return APIResponse(data=result)


@router.post("/login", summary="Sign in", description="Exchange credentials for a token pair.")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: DbSession,
) -> APIResponse[AuthSession]:
    service = AuthService(session)
    result = await service.login(
        email=payload.email,
        password=payload.password,
        request_id=getattr(request.state, "request_id", None),
        ip_address=client_ip(request),
        user_agent=user_agent(request),
    )
    _set_refresh_cookie(response, result.tokens.refresh_token)
    return APIResponse(data=result)


@router.post(
    "/refresh",
    summary="Rotate the session",
    description=(
        "Issues a new access token and rotates the refresh token. Reusing an already "
        "rotated token revokes the whole token family."
    ),
)
async def refresh(
    request: Request,
    response: Response,
    session: DbSession,
    payload: RefreshRequest | None = None,
    refresh_cookie: Annotated[str | None, Cookie(alias=settings.refresh_cookie_name)] = None,
) -> APIResponse[AuthSession]:
    token = (payload.refresh_token if payload else None) or refresh_cookie
    if not token:
        raise InvalidTokenError("No refresh token was supplied.")
    service = AuthService(session)
    result = await service.refresh(
        token,
        ip_address=client_ip(request),
        user_agent=user_agent(request),
        request_id=getattr(request.state, "request_id", None),
    )
    _set_refresh_cookie(response, result.tokens.refresh_token)
    return APIResponse(data=result)


@router.post("/logout", summary="Sign out", description="Revokes the current refresh token.")
async def logout(
    request: Request,
    response: Response,
    session: DbSession,
    user: CurrentUserDep,
    payload: RefreshRequest | None = None,
    refresh_cookie: Annotated[str | None, Cookie(alias=settings.refresh_cookie_name)] = None,
) -> APIResponse[ActionAck]:
    token = (payload.refresh_token if payload else None) or refresh_cookie
    await AuthService(session).logout(
        token, user_id=user.id, request_id=getattr(request.state, "request_id", None)
    )
    _clear_refresh_cookie(response)
    return APIResponse(data=ActionAck(message="Signed out."))


@router.post(
    "/logout-all",
    summary="Sign out everywhere",
    description="Revokes every refresh token for this account.",
)
async def logout_all(
    request: Request,
    response: Response,
    session: DbSession,
    user: CurrentUserDep,
) -> APIResponse[ActionAck]:
    await AuthService(session).logout(
        None,
        user_id=user.id,
        all_sessions=True,
        request_id=getattr(request.state, "request_id", None),
    )
    _clear_refresh_cookie(response)
    return APIResponse(data=ActionAck(message="All sessions revoked."))


@router.get(
    "/me",
    summary="Current user",
    description=(
        "The signed-in user, their active merchant, role and effective permissions. "
        "Permissions are for rendering only - the backend re-checks every request."
    ),
)
async def me(principal: CurrentPrincipal, session: DbSession) -> APIResponse[CurrentUser]:
    memberships = await MembershipRepository(session).list_for_user(principal.user_id)
    return APIResponse(
        data=AuthService.build_current_user(
            principal.user,
            memberships,
            principal.membership,
            permissions=principal.permissions,
        )
    )


@router.patch("/me", summary="Update profile")
async def update_profile(
    payload: UpdateProfileRequest,
    principal: CurrentPrincipal,
    session: DbSession,
) -> APIResponse[UserOut]:
    user = principal.user
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(user, field, value)
    await session.flush()
    return APIResponse(data=UserOut.model_validate(user))


@router.post("/change-password", summary="Change password")
async def change_password(
    payload: ChangePasswordRequest,
    principal: CurrentPrincipal,
    response: Response,
    session: DbSession,
) -> APIResponse[ActionAck]:
    await AuthService(session).change_password(
        principal.user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    _clear_refresh_cookie(response)
    return APIResponse(
        data=ActionAck(message="Password changed. Please sign in again on your other devices.")
    )


@router.post(
    "/forgot-password",
    summary="Request a password reset",
    description=(
        "Always returns success so the response cannot be used to discover which "
        "email addresses are registered. With no mail server configured, the token is "
        "returned directly instead of being emailed."
    ),
)
async def forgot_password(
    payload: PasswordResetRequest, session: DbSession
) -> APIResponse[ActionAck]:
    service = AuthService(session)
    user = await service.users.get_by_email(payload.email)
    token = create_password_reset_token(user.id) if user else None
    return APIResponse(
        data=ActionAck(
            message="If that email is registered, a reset link has been sent.",
            resource_id=token if settings.debug else None,
        ),
        meta={"delivery": "inline" if settings.debug else "email"},
    )


@router.post("/reset-password", summary="Complete a password reset")
async def reset_password(
    payload: PasswordResetConfirm, session: DbSession
) -> APIResponse[ActionAck]:
    claims = verify_password_reset_token(payload.token)
    import uuid as _uuid

    await AuthService(session).reset_password(_uuid.UUID(claims.subject), payload.new_password)
    return APIResponse(data=ActionAck(message="Password reset. You can sign in now."))


@router.get("/session", summary="Access token metadata", include_in_schema=False)
async def session_info(principal: CurrentPrincipal) -> APIResponse[dict]:
    return APIResponse(
        data={
            "user_id": str(principal.user_id),
            "merchant_id": str(principal.merchant_id),
            "role": principal.membership.role,
            "permissions": sorted(principal.permissions),
        }
    )

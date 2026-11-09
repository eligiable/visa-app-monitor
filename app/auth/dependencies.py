"""FastAPI dependencies for session authentication, CSRF, and roles."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Iterator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import hash_token, is_same_origin, token_matches_hash
from app.database.models import Administrator, AdministratorSession


def get_database_session(request: Request) -> Iterator[Session]:
    """Yield a short-lived database session for the current request."""
    factory = request.app.state.session_factory
    with factory() as session:
        yield session


DatabaseSession = Annotated[Session, Depends(get_database_session)]


def get_current_session(
    request: Request,
    session: DatabaseSession,
) -> tuple[Administrator, AdministratorSession]:
    """Resolve the active administrator and opaque session cookie."""
    settings = request.app.state.settings
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    stored_session = session.scalar(
        select(AdministratorSession).where(
            AdministratorSession.token_hash == hash_token(token),
            AdministratorSession.revoked_at.is_(None),
            AdministratorSession.expires_at > datetime.now(UTC),
        )
    )
    if stored_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    administrator = session.get(Administrator, stored_session.administrator_id)
    if administrator is None or not administrator.enabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return administrator, stored_session


def require_csrf(
    request: Request,
    current: Annotated[
        tuple[Administrator, AdministratorSession],
        Depends(get_current_session),
    ],
) -> None:
    """Require a same-origin request and a session-bound CSRF token."""
    settings = request.app.state.settings
    expected_origin = settings.public_origin or str(request.base_url)
    if not is_same_origin(request.headers.get("origin"), expected_origin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A same-origin request is required",
        )

    supplied_token = request.headers.get("x-csrf-token")
    if not supplied_token or not token_matches_hash(
        supplied_token,
        current[1].csrf_token_hash,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed",
        )


def require_role(required_role: str) -> Callable[..., Administrator]:
    """Build a dependency requiring the named administrator role."""

    def role_dependency(
        current: Annotated[
            tuple[Administrator, AdministratorSession],
            Depends(get_current_session),
        ],
    ) -> Administrator:
        administrator = current[0]
        if administrator.role != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return administrator

    return role_dependency

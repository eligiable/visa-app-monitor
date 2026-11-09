"""Administrator login, logout, session inspection, and protected routes."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import (
    DatabaseSession,
    get_current_session,
    require_csrf,
    require_role,
)
from app.auth.security import (
    create_opaque_token,
    hash_password,
    hash_rate_limit_key,
    hash_token,
    is_same_origin,
    verify_password,
)
from app.database.models import (
    Administrator,
    AdministratorSession,
    AuditEvent,
    AuthRateLimit,
    utc_now,
)

router = APIRouter(prefix="/api")
_MAX_PASSWORD_LENGTH = 1024


def _as_utc(value: datetime) -> datetime:
    """Normalize database datetimes, including SQLite's naive values, to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class LoginRequest(BaseModel):
    """Credentials for an administrator session."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=_MAX_PASSWORD_LENGTH)


class LoginResponse(BaseModel):
    """Session bootstrap response; the session token remains HttpOnly."""

    csrf_token: str
    username: str
    role: str


class CsrfTokenResponse(BaseModel):
    """Rotated CSRF token for a previously authenticated browser session."""

    csrf_token: str


class AdministratorResponse(BaseModel):
    """Public administrator fields, excluding all credential material."""

    username: str
    role: str


class StatusResponse(BaseModel):
    """Simple result for an authorized administration endpoint."""

    status: str


class StaffCreateRequest(BaseModel):
    """Credentials for an administrator-provisioned staff account."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=_MAX_PASSWORD_LENGTH)


class StaffSummary(BaseModel):
    """Non-sensitive account information for administrator management."""

    username: str
    role: str
    enabled: bool
    last_login_at: datetime | None = None


def _rate_limit_key(request: Request, username: str) -> str:
    """Return an HMAC identity key without storing the username or IP address."""
    settings = request.app.state.settings
    client_host = request.client.host if request.client else "unknown"
    return hash_rate_limit_key(
        f"{username}\0{client_host}",
        settings.session_security_key.get_secret_value(),
    )


def _get_or_create_rate_bucket(
    session: Session,
    key_hash: str,
    now: datetime,
    window_seconds: int,
) -> AuthRateLimit:
    """Atomically ensure a per-username/client rate bucket exists."""
    bind = session.get_bind()
    values = {
        "key_hash": key_hash,
        "window_started_at": now,
        "failure_count": 0,
        "blocked_until": None,
        "created_at": now,
        "updated_at": now,
    }
    if bind.dialect.name == "postgresql":
        statement = postgresql_insert(AuthRateLimit).values(**values)
        statement = statement.on_conflict_do_nothing(
            index_elements=[AuthRateLimit.key_hash],
        )
    elif bind.dialect.name == "sqlite":
        statement = sqlite_insert(AuthRateLimit).values(**values)
        statement = statement.on_conflict_do_nothing(
            index_elements=[AuthRateLimit.key_hash],
        )
    else:
        raise RuntimeError(
            f"Authentication rate limiting is unsupported for {bind.dialect.name}",
        )
    session.execute(statement)

    bucket = session.scalar(
        select(AuthRateLimit)
        .where(AuthRateLimit.key_hash == key_hash)
        .with_for_update()
    )
    if bucket is None:
        raise RuntimeError("Could not initialize the authentication rate limit")

    if now - _as_utc(bucket.window_started_at) >= timedelta(
        seconds=window_seconds,
    ):
        bucket.window_started_at = now
        bucket.failure_count = 0
        bucket.blocked_until = None
    return bucket


def _check_login_rate_limit(
    session: Session,
    bucket: AuthRateLimit,
    now: datetime,
) -> None:
    """Reject a login attempt when its persistent failure bucket is blocked."""
    blocked_until = _as_utc(bucket.blocked_until) if bucket.blocked_until else None
    if blocked_until and blocked_until > now:
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts; try again later",
            headers={
                "Retry-After": str(
                    max(1, int((blocked_until - now).total_seconds())),
                ),
            },
        )


def _record_failed_login(
    session: Session,
    bucket: AuthRateLimit,
    now: datetime,
    max_attempts: int,
    window_seconds: int,
) -> None:
    """Persist a failed login and enforce its configured lockout window."""
    bucket.failure_count += 1
    bucket.updated_at = now
    if bucket.failure_count >= max_attempts:
        bucket.blocked_until = now + timedelta(seconds=window_seconds)
    session.commit()


def _set_session_cookie(
    response: Response,
    request: Request,
    token: str,
) -> None:
    """Set a host-only, HttpOnly cookie with the configured session lifetime."""
    settings = request.app.state.settings
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/auth/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: DatabaseSession,
) -> LoginResponse:
    """Authenticate an administrator and issue an opaque server-side session."""
    expected_origin = request.app.state.settings.public_origin or str(request.base_url)
    if not is_same_origin(request.headers.get("origin"), expected_origin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A same-origin request is required",
        )
    settings = request.app.state.settings
    now = utc_now()
    username = payload.username.strip().casefold()
    bucket_key = _rate_limit_key(request, username)

    session.execute(
        delete(AuthRateLimit).where(
            AuthRateLimit.updated_at
            < now - timedelta(seconds=settings.auth_rate_limit_retention_seconds)
        )
    )
    bucket = _get_or_create_rate_bucket(
        session,
        bucket_key,
        now,
        settings.auth_rate_limit_window_seconds,
    )
    _check_login_rate_limit(session, bucket, now)

    administrator = session.scalar(
        select(Administrator).where(Administrator.username == username)
    )
    stored_hash = administrator.password_hash if administrator else None
    password_valid = verify_password(payload.password, stored_hash)
    if administrator is None or not administrator.enabled or not password_valid:
        _record_failed_login(
            session,
            bucket,
            now,
            settings.auth_rate_limit_max_attempts,
            settings.auth_rate_limit_window_seconds,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Cookie"},
        )

    bucket.failure_count = 0
    bucket.blocked_until = None
    bucket.updated_at = now
    session.execute(
        delete(AdministratorSession).where(
            (AdministratorSession.expires_at <= now)
            | (AdministratorSession.revoked_at.is_not(None))
        )
    )

    session_token = create_opaque_token()
    csrf_token = create_opaque_token()
    administrator.last_login_at = now
    session.add(
        AdministratorSession(
            administrator_id=administrator.id,
            token_hash=hash_token(session_token),
            csrf_token_hash=hash_token(csrf_token),
            created_at=now,
            expires_at=now + timedelta(seconds=settings.session_max_age_seconds),
        )
    )
    session.add(
        AuditEvent(
            administrator_id=administrator.id,
            action="administrator.login",
            entity_type="administrator",
            entity_id=str(administrator.id),
            occurred_at=now,
            safe_metadata={"role": administrator.role},
        )
    )
    session.commit()
    _set_session_cookie(response, request, session_token)
    return LoginResponse(
        csrf_token=csrf_token,
        username=administrator.username,
        role=administrator.role,
    )


@router.get("/auth/me", response_model=AdministratorResponse)
def get_authenticated_administrator(
    current: Annotated[
        tuple[Administrator, AdministratorSession],
        Depends(get_current_session),
    ],
) -> AdministratorResponse:
    """Return public identity for an authenticated administrator."""
    return AdministratorResponse(
        username=current[0].username,
        role=current[0].role,
    )


@router.get(
    "/admin/staff",
    response_model=list[StaffSummary],
    dependencies=[Depends(require_role("ADMIN"))],
)
def list_staff_accounts(session: DatabaseSession) -> list[StaffSummary]:
    """List staff accounts without exposing password or session material."""
    staff_accounts = session.scalars(
        select(Administrator)
        .where(Administrator.role == "STAFF")
        .order_by(Administrator.username.asc())
    ).all()
    return [
        StaffSummary(
            username=account.username,
            role=account.role,
            enabled=account.enabled,
            last_login_at=account.last_login_at,
        )
        for account in staff_accounts
    ]


@router.post(
    "/admin/staff",
    response_model=StaffSummary,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role("ADMIN")), Depends(require_csrf)],
)
def create_staff_account(
    payload: StaffCreateRequest,
    session: DatabaseSession,
    current: Annotated[
        tuple[Administrator, AdministratorSession],
        Depends(get_current_session),
    ],
) -> StaffSummary:
    """Create a staff account with an Argon2id password hash and audit event."""
    username = payload.username.strip().casefold()
    if not username:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Username must not be blank",
        )
    existing = session.scalar(
        select(Administrator.id).where(Administrator.username == username)
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that username already exists",
        )

    account = Administrator(
        username=username,
        password_hash=hash_password(payload.password),
        role="STAFF",
        enabled=True,
    )
    session.add(account)
    try:
        session.flush()
        session.add(
            AuditEvent(
                administrator_id=current[0].id,
                action="administrator.staff_account_created",
                entity_type="administrator",
                entity_id=str(account.id),
                occurred_at=utc_now(),
                safe_metadata={"role": "STAFF"},
            )
        )
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that username already exists",
        ) from error

    return StaffSummary(
        username=account.username,
        role=account.role,
        enabled=account.enabled,
        last_login_at=account.last_login_at,
    )


@router.post("/auth/csrf", response_model=CsrfTokenResponse)
def refresh_csrf_token(
    request: Request,
    session: DatabaseSession,
    current: Annotated[
        tuple[Administrator, AdministratorSession],
        Depends(get_current_session),
    ],
) -> CsrfTokenResponse:
    """Rotate a session CSRF token for a same-origin authenticated browser."""
    settings = request.app.state.settings
    expected_origin = settings.public_origin or str(request.base_url)
    if not is_same_origin(request.headers.get("origin"), expected_origin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A same-origin request is required",
        )

    csrf_token = create_opaque_token()
    current[1].csrf_token_hash = hash_token(csrf_token)
    session.commit()
    return CsrfTokenResponse(csrf_token=csrf_token)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    session: DatabaseSession,
    _csrf_validated: Annotated[None, Depends(require_csrf)],
    current: Annotated[
        tuple[Administrator, AdministratorSession],
        Depends(get_current_session),
    ],
) -> Response:
    """Revoke the current session after same-origin and CSRF validation."""
    current[1].revoked_at = utc_now()
    session.add(
        AuditEvent(
            administrator_id=current[0].id,
            action="administrator.logout",
            entity_type="administrator",
            entity_id=str(current[0].id),
            occurred_at=utc_now(),
            safe_metadata=None,
        )
    )
    session.commit()
    response.delete_cookie(
        key=request.app.state.settings.session_cookie_name,
        httponly=True,
        secure=request.app.state.settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get(
    "/admin/ping",
    response_model=StatusResponse,
    dependencies=[Depends(require_role("ADMIN"))],
)
def administrator_ping() -> StatusResponse:
    """Provide a minimal protected route for admin authorization checks."""
    return StatusResponse(status="ok")


def create_initial_administrator(
    session: Session,
    username: str,
    password: str,
) -> Administrator:
    """Create the first administrator, refusing to replace an existing account."""
    normalized_username = username.strip().casefold()
    if not normalized_username or len(normalized_username) > 120:
        raise ValueError("Administrator username must be 1 to 120 characters")
    if len(password) < 12 or len(password) > _MAX_PASSWORD_LENGTH:
        raise ValueError("Administrator password must be 12 to 1024 characters")
    if session.scalar(select(Administrator.id).limit(1)) is not None:
        raise ValueError("An administrator already exists; bootstrap is disabled")

    administrator = Administrator(
        username=normalized_username,
        password_hash=hash_password(password),
        role="ADMIN",
        enabled=True,
    )
    session.add(administrator)
    session.flush()
    session.add(
        AuditEvent(
            administrator_id=administrator.id,
            action="administrator.initial_provision",
            entity_type="administrator",
            entity_id=str(administrator.id),
            occurred_at=utc_now(),
            safe_metadata={"role": "ADMIN"},
        )
    )
    return administrator

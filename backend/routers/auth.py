"""
Auth API — JWT bearer tokens for Document Intelligence.

Env:
  JWT_SECRET          (required in prod — long random string)
  JWT_ALGORITHM       default HS256
  JWT_EXPIRE_MINUTES  default 1440 (24h)
  ADMIN_API_KEY       optional bootstrap; also used elsewhere in main.py

Routes:
  POST /api/v1/auth/register
  POST /api/v1/auth/login
  GET  /api/v1/auth/me
  POST /api/v1/auth/logout   (client-side discard; optional denylist later)
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])

JWT_SECRET = os.getenv("JWT_SECRET") or os.getenv("ADMIN_API_KEY") or "dev-only-change-me"
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))

security = HTTPBearer(auto_error=False)

# In-memory user store for MVP — replace with DB (SQLAlchemy / Postgres)
_users: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

Role = Literal["viewer", "analyst", "admin"]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str | None = Field(None, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: Role
    email: str


class UserPublic(BaseModel):
    id: str
    email: str
    full_name: str | None = None
    role: Role
    created_at: float


# ---------------------------------------------------------------------------
# Password + JWT helpers
# ---------------------------------------------------------------------------

def _hash_password(password: str) -> str:
    try:
        from passlib.context import CryptContext

        ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
        return ctx.hash(password)
    except ImportError:
        # Dev fallback — install passlib[bcrypt] for production
        import hashlib

        salt = os.getenv("PASSWORD_SALT", "doc-intel-salt")
        return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        from passlib.context import CryptContext

        ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
        return ctx.verify(password, password_hash)
    except ImportError:
        return _hash_password(password) == password_hash


def _create_access_token(*, sub: str, email: str, role: Role) -> tuple[str, int]:
    try:
        from jose import jwt
    except ImportError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Install python-jose: pip install 'python-jose[cryptography]'",
        ) from exc

    expire_minutes = JWT_EXPIRE_MINUTES
    exp = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
    payload = {
        "sub": sub,
        "email": email,
        "role": role,
        "exp": exp,
        "iat": datetime.now(timezone.utc),
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token, expire_minutes * 60


def _decode_token(token: str) -> dict[str, Any]:
    try:
        from jose import JWTError, jwt
    except ImportError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Install python-jose: pip install 'python-jose[cryptography]'",
        ) from exc

    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ---------------------------------------------------------------------------
# Dependencies (import these from other routers)
# ---------------------------------------------------------------------------

async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict[str, Any]:
    if creds is None or not creds.credentials:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = _decode_token(creds.credentials)
    user_id = str(payload.get("sub") or "")
    user = _users.get(user_id)
    if not user or not user.get("active", True):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User not found or disabled")
    return user


def require_roles(*roles: Role):
    async def _dep(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        if user.get("role") not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return _dep


# Optional: allow either JWT or ADMIN_API_KEY header (X-API-Key)
async def get_current_user_or_admin_key(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
    x_api_key: str | None = None,
) -> dict[str, Any]:
    """Prefer wiring Header in the route; simplified optional path below."""
    admin_key = os.getenv("ADMIN_API_KEY", "")
    if admin_key and x_api_key == admin_key:
        return {
            "id": "admin-key",
            "email": "admin@local",
            "role": "admin",
            "full_name": "API Key Admin",
            "active": True,
            "created_at": time.time(),
        }
    return await get_current_user(creds)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest) -> UserPublic:
    email = body.email.lower().strip()
    if any(u["email"] == email for u in _users.values()):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Email already registered")

    # First user becomes admin (bootstrap)
    role: Role = "admin" if not _users else "viewer"
    user_id = str(uuid.uuid4())
    record = {
        "id": user_id,
        "email": email,
        "full_name": body.full_name,
        "role": role,
        "password_hash": _hash_password(body.password),
        "active": True,
        "created_at": time.time(),
    }
    _users[user_id] = record
    logger.info("Registered user %s role=%s", email, role)
    return UserPublic(
        id=user_id,
        email=email,
        full_name=body.full_name,
        role=role,
        created_at=record["created_at"],
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    email = body.email.lower().strip()
    user = next((u for u in _users.values() if u["email"] == email), None)
    if not user or not _verify_password(body.password, user["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not user.get("active", True):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Account disabled")

    token, expires_in = _create_access_token(
        sub=user["id"],
        email=user["email"],
        role=user["role"],
    )
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        role=user["role"],
        email=user["email"],
    )


@router.get("/me", response_model=UserPublic)
async def me(user: dict[str, Any] = Depends(get_current_user)) -> UserPublic:
    return UserPublic(
        id=user["id"],
        email=user["email"],
        full_name=user.get("full_name"),
        role=user["role"],
        created_at=float(user.get("created_at") or 0),
    )


@router.post("/logout")
async def logout(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, str]:
    # Stateless JWT: client deletes token. Optional: add jti denylist in Redis.
    logger.info("Logout user %s", user.get("email"))
    return {"status": "ok", "message": "Discard the access token client-side."}
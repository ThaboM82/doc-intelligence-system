"""
Async SQL database for Document Intelligence.

- Users / roles (auth + RBAC)
- Document metadata (vectors remain in Qdrant)
- Audit log
- Optional threat_events persistence
- Session dependency for FastAPI

Env:
  DATABASE_URL
    sqlite+aiosqlite:///./backend/data/app.db
    postgresql+asyncpg://user:pass@host:5432/dbname
  SQL_ECHO=true|false
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import AsyncGenerator, Sequence
from typing import Any

from sqlalchemy import (
    Boolean,
    Float,
    Integer,
    String,
    Text,
    delete,
    func,
    select,
    update,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

logger = logging.getLogger(__name__)

DEFAULT_SQLITE = "sqlite+aiosqlite:///./backend/data/app.db"


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def normalize_database_url(url: str | None = None) -> str:
    raw = (url or os.getenv("DATABASE_URL") or DEFAULT_SQLITE).strip()
    if raw.startswith("postgres://"):
        raw = raw.replace("postgres://", "postgresql+asyncpg://", 1)
    elif raw.startswith("postgresql://") and "+asyncpg" not in raw:
        raw = raw.replace("postgresql://", "postgresql+asyncpg://", 1)
    return raw


def database_url() -> str:
    return normalize_database_url()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    role: Mapped[str] = mapped_column(String(32), default="viewer", index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[float] = mapped_column(Float, default=lambda: time.time())
    updated_at: Mapped[float] = mapped_column(Float, default=lambda: time.time())
    last_login_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class DocumentModel(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(32), default="indexed", index=True)
    chunks_upserted: Mapped[int] = mapped_column(Integer, default=0)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    security_scan_passed: Mapped[bool] = mapped_column(Boolean, default=True)
    uploaded_by: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    department: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tags: Mapped[str | None] = mapped_column(String(512), nullable=True)  # comma-separated
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[float] = mapped_column(Float, default=lambda: time.time(), index=True)
    updated_at: Mapped[float] = mapped_column(Float, default=lambda: time.time())


class AuditLogModel(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[float] = mapped_column(Float, default=lambda: time.time(), index=True)
    action: Mapped[str] = mapped_column(String(128), index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resource: Mapped[str | None] = mapped_column(String(255), nullable=True)
    path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class ThreatEventModel(Base):
    """Optional durable copy of high-signal threats (in-memory telemetry still primary for live UI)."""

    __tablename__ = "threat_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[float] = mapped_column(Float, default=lambda: time.time(), index=True)
    threat_type: Mapped[str] = mapped_column(String(128), index=True)
    severity: Mapped[str] = mapped_column(String(32), index=True)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    user_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    detector: Mapped[str] = mapped_column(String(32), default="heuristic")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Engine / sessions
# ---------------------------------------------------------------------------

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        url = database_url()
        kwargs: dict[str, Any] = {
            "echo": os.getenv("SQL_ECHO", "").lower() in ("1", "true", "yes"),
            "pool_pre_ping": True,
        }
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        else:
            kwargs["pool_size"] = int(os.getenv("DB_POOL_SIZE", "5"))
            kwargs["max_overflow"] = int(os.getenv("DB_MAX_OVERFLOW", "10"))
        _engine = create_async_engine(url, **kwargs)
        logger.info("DB engine ready dialect=%s", url.split("://")[0])
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def init_db() -> None:
    url = database_url()
    if url.startswith("sqlite"):
        from pathlib import Path

        path_part = url.split("///")[-1]
        if path_part and path_part != ":memory:":
            Path(path_part).parent.mkdir(parents=True, exist_ok=True)

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("DB schema ensured")


async def close_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("DB engine disposed")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — commits on success, rolls back on error."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Manual async context for scripts / services outside request cycle."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def user_to_dict(u: UserModel) -> dict[str, Any]:
    return {
        "id": u.id,
        "email": u.email,
        "full_name": u.full_name,
        "role": u.role,
        "active": u.active,
        "created_at": u.created_at,
        "updated_at": u.updated_at,
        "last_login_at": u.last_login_at,
        "password_hash": u.password_hash,
    }


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    password_hash: str,
    full_name: str | None = None,
    role: str = "viewer",
    user_id: str | None = None,
) -> UserModel:
    now = time.time()
    user = UserModel(
        id=user_id or str(uuid.uuid4()),
        email=email.lower().strip(),
        full_name=full_name,
        role=role,
        password_hash=password_hash,
        active=True,
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    await session.flush()
    return user


async def get_user_by_email(session: AsyncSession, email: str) -> UserModel | None:
    q = await session.execute(
        select(UserModel).where(UserModel.email == email.lower().strip())
    )
    return q.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: str) -> UserModel | None:
    q = await session.execute(select(UserModel).where(UserModel.id == user_id))
    return q.scalar_one_or_none()


async def count_users(session: AsyncSession) -> int:
    q = await session.execute(select(func.count()).select_from(UserModel))
    return int(q.scalar_one())


async def list_users(
    session: AsyncSession,
    *,
    active_only: bool = False,
    limit: int = 500,
) -> list[UserModel]:
    stmt = select(UserModel).order_by(UserModel.created_at.asc()).limit(limit)
    if active_only:
        stmt = stmt.where(UserModel.active.is_(True))
    q = await session.execute(stmt)
    return list(q.scalars().all())


async def update_user_role(session: AsyncSession, user_id: str, role: str) -> UserModel | None:
    user = await get_user_by_id(session, user_id)
    if not user:
        return None
    user.role = role
    user.updated_at = time.time()
    await session.flush()
    return user


async def set_user_active(
    session: AsyncSession, user_id: str, active: bool
) -> UserModel | None:
    user = await get_user_by_id(session, user_id)
    if not user:
        return None
    user.active = active
    user.updated_at = time.time()
    await session.flush()
    return user


async def touch_last_login(session: AsyncSession, user_id: str) -> None:
    await session.execute(
        update(UserModel)
        .where(UserModel.id == user_id)
        .values(last_login_at=time.time(), updated_at=time.time())
    )


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


async def save_document_row(
    session: AsyncSession,
    *,
    document_id: str,
    filename: str,
    status: str,
    chunks_upserted: int = 0,
    char_count: int = 0,
    security_scan_passed: bool = True,
    uploaded_by: str | None = None,
    department: str | None = None,
    tags: list[str] | None = None,
    message: str | None = None,
    content_type: str | None = None,
    file_size: int = 0,
) -> DocumentModel:
    now = time.time()
    row = DocumentModel(
        id=document_id,
        filename=filename,
        status=status,
        chunks_upserted=chunks_upserted,
        char_count=char_count,
        security_scan_passed=security_scan_passed,
        uploaded_by=uploaded_by,
        department=department,
        tags=",".join(tags) if tags else None,
        message=message,
        content_type=content_type,
        file_size=file_size,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def get_document(session: AsyncSession, document_id: str) -> DocumentModel | None:
    q = await session.execute(
        select(DocumentModel).where(DocumentModel.id == document_id)
    )
    return q.scalar_one_or_none()


async def list_documents(
    session: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[DocumentModel]:
    stmt = (
        select(DocumentModel)
        .order_by(DocumentModel.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if status:
        stmt = stmt.where(DocumentModel.status == status)
    q = await session.execute(stmt)
    return list(q.scalars().all())


async def update_document_status(
    session: AsyncSession,
    document_id: str,
    status: str,
    message: str | None = None,
) -> DocumentModel | None:
    doc = await get_document(session, document_id)
    if not doc:
        return None
    doc.status = status
    doc.updated_at = time.time()
    if message is not None:
        doc.message = message
    await session.flush()
    return doc


async def delete_document_row(session: AsyncSession, document_id: str) -> bool:
    result = await session.execute(
        delete(DocumentModel).where(DocumentModel.id == document_id)
    )
    return bool(result.rowcount)


async def document_stats(session: AsyncSession) -> dict[str, Any]:
    total = await session.execute(select(func.count()).select_from(DocumentModel))
    by_status = await session.execute(
        select(DocumentModel.status, func.count())
        .group_by(DocumentModel.status)
    )
    return {
        "total": int(total.scalar_one()),
        "by_status": {row[0]: int(row[1]) for row in by_status.all()},
    }


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


async def write_audit(
    session: AsyncSession,
    *,
    action: str,
    user_id: str | None = None,
    email: str | None = None,
    role: str | None = None,
    resource: str | None = None,
    path: str | None = None,
    method: str | None = None,
    client_ip: str | None = None,
    detail: str | None = None,
) -> AuditLogModel:
    row = AuditLogModel(
        ts=time.time(),
        action=action,
        user_id=user_id,
        email=email,
        role=role,
        resource=resource,
        path=path,
        method=method,
        client_ip=client_ip,
        detail=detail,
    )
    session.add(row)
    await session.flush()
    return row


async def list_audit(
    session: AsyncSession,
    *,
    action: str | None = None,
    limit: int = 100,
) -> list[AuditLogModel]:
    stmt = select(AuditLogModel).order_by(AuditLogModel.ts.desc()).limit(limit)
    if action:
        stmt = stmt.where(AuditLogModel.action == action)
    q = await session.execute(stmt)
    return list(q.scalars().all())


# ---------------------------------------------------------------------------
# Threat events (durable)
# ---------------------------------------------------------------------------


async def persist_threat_event(
    session: AsyncSession,
    *,
    threat_type: str,
    severity: str,
    confidence_score: float = 0.0,
    source_ip: str | None = None,
    document_id: str | None = None,
    user_email: str | None = None,
    detector: str = "heuristic",
    detail: str | None = None,
) -> ThreatEventModel:
    row = ThreatEventModel(
        ts=time.time(),
        threat_type=threat_type,
        severity=severity,
        confidence_score=confidence_score,
        source_ip=source_ip,
        document_id=document_id,
        user_email=user_email,
        detector=detector,
        detail=detail,
    )
    session.add(row)
    await session.flush()
    return row


async def list_threat_events(
    session: AsyncSession,
    *,
    severity: str | None = None,
    limit: int = 100,
) -> list[ThreatEventModel]:
    stmt = select(ThreatEventModel).order_by(ThreatEventModel.ts.desc()).limit(limit)
    if severity:
        stmt = stmt.where(ThreatEventModel.severity == severity.lower())
    q = await session.execute(stmt)
    return list(q.scalars().all())


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


async def db_health() -> dict[str, Any]:
    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(select(1))
        return {"ok": True, "url_scheme": database_url().split("://")[0]}
    except Exception as exc:
        logger.exception("DB health failed")
        return {"ok": False, "error": str(exc)}
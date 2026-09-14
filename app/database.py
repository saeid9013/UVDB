from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, inspect, text
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import get_settings


class Base(AsyncAttrs, DeclarativeBase):
    pass


class JobStatus(StrEnum):
    RECEIVED = "received"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    last_active_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
    bot_blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    downloads: Mapped[list["DownloadRequest"]] = relationship(back_populates="user")


class DownloadRequest(Base):
    __tablename__ = "download_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    original_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(500))
    output_type: Mapped[str] = mapped_column(String(10), default="video")
    selected_format: Mapped[str] = mapped_column(String(50), default="best")
    status: Mapped[str] = mapped_column(String(30), default=JobStatus.RECEIVED)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship(back_populates="downloads")


settings = get_settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


def _ensure_user_tracking_columns(connection) -> None:
    columns = {column["name"] for column in inspect(connection).get_columns("users")}
    if "last_active_at" not in columns:
        connection.execute(text("ALTER TABLE users ADD COLUMN last_active_at TIMESTAMP"))
    if "bot_blocked_at" not in columns:
        connection.execute(text("ALTER TABLE users ADD COLUMN bot_blocked_at TIMESTAMP"))
    connection.execute(
        text("UPDATE users SET last_active_at = created_at WHERE last_active_at IS NULL")
    )


async def init_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(_ensure_user_tracking_columns)

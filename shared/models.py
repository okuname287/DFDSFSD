from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from shared.config import get_config


class Base(DeclarativeBase):
    pass


class ApplicationStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CALLBACK = "callback"  # На обзвон


class PromotionStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class GameServer(str, enum.Enum):
    MEMPHIS = "memphis"
    PHOENIX = "phoenix"


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    discord_user_id: Mapped[str] = mapped_column(String(32), index=True)
    discord_username: Mapped[str] = mapped_column(String(128))

    character_name: Mapped[str] = mapped_column(String(128))
    static_id: Mapped[str] = mapped_column(String(64))
    ooc_age: Mapped[int] = mapped_column(Integer)
    join_goal: Mapped[str] = mapped_column(Text)
    how_found: Mapped[str] = mapped_column(Text)
    game_server: Mapped[GameServer] = mapped_column(Enum(GameServer), index=True)
    screenshot_url: Mapped[str] = mapped_column(Text)

    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus), default=ApplicationStatus.PENDING, index=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_by_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    discord_message_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    discord_channel_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    callback_text_channel_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    callback_voice_channel_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    callback_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    callback_duration_seconds: Mapped[int] = mapped_column(Integer, default=0)


class PromotionRequest(Base):
    __tablename__ = "promotion_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    discord_user_id: Mapped[str] = mapped_column(String(32), index=True)
    discord_username: Mapped[str] = mapped_column(String(128))
    character_name: Mapped[str] = mapped_column(String(128), default="Не указан")
    game_server: Mapped[GameServer] = mapped_column(Enum(GameServer), index=True)
    target: Mapped[str] = mapped_column(String(32))
    evidence_url: Mapped[str] = mapped_column(Text)
    status: Mapped[PromotionStatus] = mapped_column(
        Enum(PromotionStatus), default=PromotionStatus.PENDING, index=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class ActionLog(Base):
    __tablename__ = "action_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    promotion_request_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    log_type: Mapped[str] = mapped_column(String(16), default="application")
    action: Mapped[str] = mapped_column(String(32))
    actor_name: Mapped[str] = mapped_column(String(128))
    actor_id: Mapped[str] = mapped_column(String(32))
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="web")  # web | discord
    game_server: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class LoginEvent(Base):
    __tablename__ = "login_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    discord_user_id: Mapped[str] = mapped_column(String(32), index=True)
    discord_username: Mapped[str] = mapped_column(String(128))
    roles_snapshot: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )


class BotError(Base):
    __tablename__ = "bot_errors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_name: Mapped[str] = mapped_column(String(128), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="error")
    message: Mapped[str] = mapped_column(Text)
    technical_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    discord_user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )


class SiteAccessSetting(Base):
    __tablename__ = "site_access_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    section: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    role_ids: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class SiteUserAccess(Base):
    __tablename__ = "site_user_access"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    discord_user_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    discord_username: Mapped[str] = mapped_column(String(128))
    roles_snapshot: Mapped[str] = mapped_column(Text, default="[]")
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        db_url = get_config()["database"]["url"]
        _engine = create_engine(db_url, echo=False)
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine())
    return _SessionLocal


def init_db():
    Path = __import__("pathlib").Path
    db_path = get_config()["database"]["url"].replace("sqlite:///", "")
    if db_path and db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(get_engine())
    _migrate_schema()


def _migrate_schema():
    """Add new columns to existing SQLite databases."""
    engine = get_engine()
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        app_columns = {
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info(applications)").fetchall()
        }
        if "discord_channel_id" not in app_columns:
            conn.exec_driver_sql(
                "ALTER TABLE applications ADD COLUMN discord_channel_id VARCHAR(32)"
            )
        if "callback_text_channel_id" not in app_columns:
            conn.exec_driver_sql(
                "ALTER TABLE applications ADD COLUMN callback_text_channel_id VARCHAR(32)"
            )
        if "callback_voice_channel_id" not in app_columns:
            conn.exec_driver_sql(
                "ALTER TABLE applications ADD COLUMN callback_voice_channel_id VARCHAR(32)"
            )
        if "callback_started_at" not in app_columns:
            conn.exec_driver_sql(
                "ALTER TABLE applications ADD COLUMN callback_started_at DATETIME"
            )
        if "callback_duration_seconds" not in app_columns:
            conn.exec_driver_sql(
                "ALTER TABLE applications ADD COLUMN callback_duration_seconds INTEGER DEFAULT 0"
            )

        log_columns = {
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info(action_logs)").fetchall()
        }
        if "game_server" not in log_columns:
            conn.exec_driver_sql(
                "ALTER TABLE action_logs ADD COLUMN game_server VARCHAR(16)"
            )
        if "promotion_request_id" not in log_columns:
            conn.exec_driver_sql(
                "ALTER TABLE action_logs ADD COLUMN promotion_request_id INTEGER"
            )
        if "log_type" not in log_columns:
            conn.exec_driver_sql(
                "ALTER TABLE action_logs ADD COLUMN log_type VARCHAR(16) DEFAULT 'application'"
            )

        application_column = next(
            row for row in conn.exec_driver_sql("PRAGMA table_info(action_logs)").fetchall()
            if row[1] == "application_id"
        )
        if application_column[3]:
            conn.exec_driver_sql("DROP INDEX IF EXISTS ix_action_logs_application_id")
            conn.exec_driver_sql("DROP INDEX IF EXISTS ix_action_logs_game_server")
            conn.exec_driver_sql("ALTER TABLE action_logs RENAME TO action_logs_legacy")
            conn.exec_driver_sql(
                """
                CREATE TABLE action_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    application_id INTEGER,
                    promotion_request_id INTEGER,
                    log_type VARCHAR(16) DEFAULT 'application',
                    action VARCHAR(32) NOT NULL,
                    actor_name VARCHAR(128) NOT NULL,
                    actor_id VARCHAR(32) NOT NULL,
                    details TEXT,
                    source VARCHAR(16) NOT NULL,
                    game_server VARCHAR(16),
                    created_at DATETIME NOT NULL
                )
                """
            )
            conn.exec_driver_sql(
                """
                INSERT INTO action_logs (
                    id, application_id, promotion_request_id, log_type, action,
                    actor_name, actor_id, details, source, game_server, created_at
                )
                SELECT id, application_id, promotion_request_id, log_type, action,
                       actor_name, actor_id, details, source, game_server, created_at
                FROM action_logs_legacy
                """
            )
            conn.exec_driver_sql("DROP TABLE action_logs_legacy")
            conn.exec_driver_sql(
                "CREATE INDEX ix_action_logs_application_id ON action_logs (application_id)"
            )
            conn.exec_driver_sql(
                "CREATE INDEX ix_action_logs_promotion_request_id ON action_logs (promotion_request_id)"
            )
            conn.exec_driver_sql(
                "CREATE INDEX ix_action_logs_game_server ON action_logs (game_server)"
            )

        promotion_columns = {
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info(promotion_requests)").fetchall()
        }
        if promotion_columns and "character_name" not in promotion_columns:
            conn.exec_driver_sql(
                "ALTER TABLE promotion_requests ADD COLUMN character_name VARCHAR(128) DEFAULT 'Не указан'"
            )

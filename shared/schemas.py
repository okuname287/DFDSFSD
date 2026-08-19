from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ApplicationCreate(BaseModel):
    discord_user_id: str
    discord_username: str
    character_name: str
    static_id: str
    ooc_age: int = Field(ge=1, le=99)
    join_goal: str
    how_found: str
    game_server: Literal["memphis", "phoenix"]
    screenshot_url: str
    discord_message_id: str | None = None


class ApplicationResponse(BaseModel):
    id: int
    discord_user_id: str
    discord_username: str
    character_name: str
    static_id: str
    ooc_age: int
    join_goal: str
    how_found: str
    game_server: str
    screenshot_url: str
    status: str
    rejection_reason: str | None
    reviewed_by: str | None
    created_at: datetime
    updated_at: datetime
    callback_duration_seconds: int = 0

    model_config = {"from_attributes": True}


class ApplicationAction(BaseModel):
    action: Literal["approve", "reject", "callback"]
    actor_name: str
    actor_id: str
    rejection_reason_id: str | None = None
    custom_reason: str | None = None
    source: Literal["web", "discord"] = "web"


class PromotionCreate(BaseModel):
    discord_user_id: str
    discord_username: str
    character_name: str
    game_server: Literal["memphis", "phoenix"]
    target: Literal["baby_londo", "young_londo", "main", "recruit"]
    evidence_url: str


class PromotionAction(BaseModel):
    action: Literal["approve", "reject"]
    actor_name: str
    actor_id: str
    rejection_reason_id: str | None = None
    custom_reason: str | None = None
    rejection_reason: str | None = None
    source: Literal["web", "discord"] = "web"


class PromotionResponse(BaseModel):
    id: int
    discord_user_id: str
    discord_username: str
    character_name: str
    game_server: str
    target: str
    evidence_url: str
    status: str
    rejection_reason: str | None
    reviewed_by: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ActionLogResponse(BaseModel):
    id: int
    application_id: int | None
    promotion_request_id: int | None
    log_type: str
    action: str
    actor_name: str
    actor_id: str
    # Fields for the target of the action (application owner)
    target_discord_user_id: str | None = None
    target_static_id: str | None = None
    details: str | None
    source: str
    game_server: str | None
    created_at: datetime

    model_config = {"from_attributes": True}

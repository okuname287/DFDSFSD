from __future__ import annotations

from datetime import datetime, timezone
import json

from shared.config import get_config
from shared.models import (
    ActionLog,
    Application,
    ApplicationStatus,
    GameServer,
    LoginEvent,
    BotError,
    SiteAccessSetting,
    SiteUserAccess,
    PromotionRequest,
    PromotionStatus,
    get_session_factory,
)
from shared.schemas import ApplicationAction, ApplicationCreate


def create_application(data: ApplicationCreate) -> Application:
    session = get_session_factory()()
    try:
        app = Application(
            discord_user_id=data.discord_user_id,
            discord_username=data.discord_username,
            character_name=data.character_name,
            static_id=data.static_id,
            ooc_age=data.ooc_age,
            join_goal=data.join_goal,
            how_found=data.how_found,
            game_server=GameServer(data.game_server),
            screenshot_url=data.screenshot_url,
            discord_message_id=data.discord_message_id,
        )
        session.add(app)
        session.commit()
        session.refresh(app)
        return app
    finally:
        session.close()


def get_application(app_id: int) -> Application | None:
    session = get_session_factory()()
    try:
        return session.get(Application, app_id)
    finally:
        session.close()


def get_application_by_callback_voice(channel_id: int) -> Application | None:
    session = get_session_factory()()
    try:
        return (
            session.query(Application)
            .filter(Application.callback_voice_channel_id == str(channel_id))
            .first()
        )
    finally:
        session.close()


def list_applications(
    game_server: str | None = None,
    status: str | None = None,
) -> list[Application]:
    session = get_session_factory()()
    try:
        query = session.query(Application)
        if game_server:
            query = query.filter(Application.game_server == GameServer(game_server))
        if status:
            query = query.filter(Application.status == ApplicationStatus(status))
        return query.order_by(Application.created_at.desc()).all()
    finally:
        session.close()


def _resolve_rejection_reason(action: ApplicationAction) -> str | None:
    if action.action != "reject":
        return None
    config = get_config()
    reasons = {r["id"]: r for r in config["rejection_reasons"]}
    if action.rejection_reason_id == "other":
        return action.custom_reason or "Заявка отклонена."
    reason = reasons.get(action.rejection_reason_id or "")
    if reason:
        return reason["message"]
    return action.custom_reason or "Заявка отклонена."


def process_action(app_id: int, action: ApplicationAction) -> Application | None:
    session = get_session_factory()()
    try:
        app = session.get(Application, app_id)
        if not app:
            return None

        allowed_statuses = {
            "approve": {ApplicationStatus.PENDING, ApplicationStatus.CALLBACK},
            "reject": {ApplicationStatus.PENDING, ApplicationStatus.CALLBACK},
            "callback": {ApplicationStatus.PENDING},
        }
        if app.status not in allowed_statuses[action.action]:
            return None

        status_map = {
            "approve": ApplicationStatus.APPROVED,
            "reject": ApplicationStatus.REJECTED,
            "callback": ApplicationStatus.CALLBACK,
        }
        app.status = status_map[action.action]
        app.reviewed_by = action.actor_name
        app.reviewed_by_id = action.actor_id
        app.rejection_reason = _resolve_rejection_reason(action)
        app.updated_at = datetime.now(timezone.utc)

        log = ActionLog(
            application_id=app.id,
            log_type="application",
            action=action.action,
            actor_name=action.actor_name,
            actor_id=action.actor_id,
            # Store the target (application owner) identifiers for searching
            target_discord_user_id=app.discord_user_id,
            target_static_id=app.static_id,
            details=app.rejection_reason if action.action == "reject" else None,
            source=action.source,
            game_server=app.game_server.value,
        )
        session.add(log)
        session.commit()
        session.refresh(app)
        return app
    finally:
        session.close()


def update_callback_channels(
    app_id: int, text_channel_id: str | None, voice_channel_id: str | None
) -> None:
    session = get_session_factory()()
    try:
        app = session.get(Application, app_id)
        if app:
            app.callback_text_channel_id = text_channel_id
            app.callback_voice_channel_id = voice_channel_id
            session.commit()
    finally:
        session.close()


def update_callback_voice_state(
    app_id: int,
    *,
    started_at: datetime | None = None,
    duration_seconds: int | None = None,
    clear_started_at: bool = False,
) -> None:
    session = get_session_factory()()
    try:
        app = session.get(Application, app_id)
        if app:
            if clear_started_at:
                app.callback_started_at = None
            elif started_at is not None:
                app.callback_started_at = started_at
            if duration_seconds is not None:
                app.callback_duration_seconds = duration_seconds
            session.commit()
    finally:
        session.close()


def get_logs(
    application_id: int | None = None,
    promotion_request_id: int | None = None,
    game_server: str | None = None,
    discord_user_id: str | None = None,
    actor_discord_user_id: str | None = None,
    log_type: str | None = None,
    limit: int | None = None,
) -> list[ActionLog]:
    """Return action logs. Can filter by application_id, promotion_request_id, game_server, target discord_user_id, actor discord_user_id, or log type.

    Static ID is no longer used for searching — searches are performed only by Discord ID.
    """
    session = get_session_factory()()
    try:
        query = session.query(ActionLog)
        if application_id:
            query = query.filter(ActionLog.application_id == application_id)
        if promotion_request_id:
            query = query.filter(ActionLog.promotion_request_id == promotion_request_id)
        if game_server:
            query = query.filter(ActionLog.game_server == game_server)
        if discord_user_id:
            query = query.filter(ActionLog.target_discord_user_id == str(discord_user_id))
        if actor_discord_user_id:
            query = query.filter(ActionLog.actor_id == str(actor_discord_user_id))
        if log_type:
            query = query.filter(ActionLog.log_type == log_type)

        query = query.order_by(ActionLog.created_at.desc())
        if limit is not None:
            query = query.limit(limit)

        logs = query.all()
        for log in logs:
            if log.log_type == "promotion" and not log.target_discord_user_id and log.promotion_request_id:
                promotion = session.get(PromotionRequest, log.promotion_request_id)
                if promotion:
                    log.target_discord_user_id = promotion.discord_user_id
        return logs
    finally:
        session.close()


def search_logs(*, discord_user_id: str | None = None) -> list[ActionLog]:
    """Convenience search API to find logs by target discord id.

    Pass discord_user_id. Returns matching ActionLog rows ordered by newest first.
    """
    return get_logs(discord_user_id=discord_user_id)


def record_login(discord_user_id: str, discord_username: str, roles: list[int]) -> None:
    session = get_session_factory()()
    try:
        session.add(
            LoginEvent(
                discord_user_id=discord_user_id,
                discord_username=discord_username,
                roles_snapshot=json.dumps(roles),
            )
        )
        session.commit()
    finally:
        session.close()


def log_bot_error(
    event_name: str,
    message: str,
    technical_details: str | None = None,
    discord_user_id: str | None = None,
    severity: str = "error",
) -> None:
    session = get_session_factory()()
    try:
        session.add(
            BotError(
                event_name=event_name,
                message=message,
                technical_details=technical_details,
                discord_user_id=discord_user_id,
                severity=severity,
            )
        )
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


def get_bot_errors() -> list[BotError]:
    session = get_session_factory()()
    try:
        return session.query(BotError).order_by(BotError.created_at.desc()).all()
    finally:
        session.close()


_site_access_cache: dict | None = None
_site_access_cache_ts: float = 0.0


def get_site_access_settings(ttl_seconds: int = 30) -> dict[str, list[int]]:
    """Return site access settings with a short in-process cache to avoid frequent DB hits.

    TTL defaults to 30 seconds. Caller may pass ttl_seconds=0 to disable caching.
    """
    import time
    global _site_access_cache, _site_access_cache_ts
    now = time.time()
    if ttl_seconds and _site_access_cache and (now - _site_access_cache_ts) < ttl_seconds:
        return _site_access_cache

    session = get_session_factory()()
    try:
        rows = session.query(SiteAccessSetting).all()
        result = {
            row.section: [int(value) for value in row.role_ids.split(",") if value.strip().isdigit()]
            for row in rows
        }
        _site_access_cache = result
        _site_access_cache_ts = now
        return result
    finally:
        session.close()


def save_site_access_settings(settings: dict[str, list[int]]) -> None:
    global _site_access_cache, _site_access_cache_ts
    _site_access_cache = None
    _site_access_cache_ts = 0.0
    session = get_session_factory()()
    try:
        for section, role_ids in settings.items():
            row = session.query(SiteAccessSetting).filter_by(section=section).first()
            if row is None:
                row = SiteAccessSetting(section=section)
                session.add(row)
            row.role_ids = ",".join(str(role_id) for role_id in role_ids)
        session.commit()
    finally:
        session.close()


def register_site_user(
    discord_user_id: str,
    discord_username: str,
    roles: list[int],
    auto_approve: bool = False,
) -> SiteUserAccess:
    session = get_session_factory()()
    try:
        profile = session.query(SiteUserAccess).filter_by(discord_user_id=discord_user_id).first()
        if profile is None:
            profile = SiteUserAccess(discord_user_id=discord_user_id)
            session.add(profile)
        profile.discord_username = discord_username
        profile.roles_snapshot = json.dumps(roles)
        if auto_approve and not profile.is_approved:
            profile.is_approved = True
            profile.approved_by = "Автоматически: Owner"
            profile.approved_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(profile)
        return profile
    finally:
        session.close()


def get_site_user_access(discord_user_id: str) -> SiteUserAccess | None:
    session = get_session_factory()()
    try:
        return session.query(SiteUserAccess).filter_by(discord_user_id=discord_user_id).first()
    finally:
        session.close()


def list_site_users() -> list[SiteUserAccess]:
    session = get_session_factory()()
    try:
        return session.query(SiteUserAccess).order_by(SiteUserAccess.created_at.desc()).all()
    finally:
        session.close()


def set_site_user_approval(user_id: str, approved: bool, approved_by: str) -> None:
    session = get_session_factory()()
    try:
        profile = session.query(SiteUserAccess).filter_by(discord_user_id=user_id).first()
        if profile:
            profile.is_approved = approved
            profile.approved_by = approved_by if approved else None
            profile.approved_at = datetime.now(timezone.utc) if approved else None
            session.commit()
    finally:
        session.close()


def get_login_count(role_ids: list[int] | None = None) -> int:
    session = get_session_factory()()
    try:
        if not role_ids:
            return session.query(LoginEvent).count()
        count = 0
        allowed = set(role_ids)
        for event in session.query(LoginEvent).all():
            try:
                if allowed.intersection(json.loads(event.roles_snapshot or "[]")):
                    count += 1
            except (TypeError, ValueError):
                continue
        return count
    finally:
        session.close()


def get_application_stats(game_server: str | None = None) -> dict[str, int]:
    session = get_session_factory()()
    try:
        query = session.query(Application)
        if game_server:
            query = query.filter(Application.game_server == GameServer(game_server))
        return {
            "total": query.count(),
            "approved": query.filter(Application.status == ApplicationStatus.APPROVED).count(),
            "rejected": query.filter(Application.status == ApplicationStatus.REJECTED).count(),
        }
    finally:
        session.close()


def create_promotion(data) -> PromotionRequest:
    session = get_session_factory()()
    try:
        request = PromotionRequest(
            discord_user_id=data.discord_user_id,
            discord_username=data.discord_username,
            character_name=data.character_name,
            game_server=GameServer(data.game_server),
            target=data.target,
            evidence_url=data.evidence_url,
        )
        session.add(request)
        session.commit()
        session.refresh(request)
        return request
    finally:
        session.close()


def list_promotions(game_server: str | None = None, status: str | None = None) -> list[PromotionRequest]:
    session = get_session_factory()()
    try:
        query = session.query(PromotionRequest)
        if game_server:
            query = query.filter(PromotionRequest.game_server == GameServer(game_server))
        if status:
            query = query.filter(PromotionRequest.status == PromotionStatus(status))
        return query.order_by(PromotionRequest.created_at.desc()).all()
    finally:
        session.close()


def get_promotion(request_id: int) -> PromotionRequest | None:
    session = get_session_factory()()
    try:
        return session.get(PromotionRequest, request_id)
    finally:
        session.close()


def process_promotion(request_id: int, action) -> PromotionRequest | None:
    session = get_session_factory()()
    try:
        request = session.get(PromotionRequest, request_id)
        if not request or request.status != PromotionStatus.PENDING:
            return None
        request.status = PromotionStatus.APPROVED if action.action == "approve" else PromotionStatus.REJECTED
        request.reviewed_by = action.actor_name
        if action.action == "reject":
            if action.rejection_reason_id == "other":
                request.rejection_reason = action.custom_reason or "Причина не указана."
            else:
                reasons = {
                    item["id"]: item
                    for item in get_config().get("promotion_rejection_reasons", [])
                }
                reason = reasons.get(action.rejection_reason_id or "")
                request.rejection_reason = (
                    reason["message"] if reason else action.rejection_reason or "Причина не указана."
                )
        else:
            request.rejection_reason = None
        request.updated_at = datetime.now(timezone.utc)
        session.add(
            ActionLog(
                promotion_request_id=request.id,
                log_type="promotion",
                action=action.action,
                actor_name=action.actor_name,
                actor_id=action.actor_id,
                target_discord_user_id=request.discord_user_id,
                details=request.rejection_reason,
                source=action.source,
                game_server=request.game_server.value,
            )
        )
        session.commit()
        session.refresh(request)
        return request
    finally:
        session.close()


def get_recruiter_stats(game_servers: list[str] | None = None) -> list[dict[str, object]]:
    session = get_session_factory()()
    try:
        query = session.query(ActionLog).filter(
            ActionLog.log_type != "promotion",
            ActionLog.action.in_(("approve", "reject", "callback")),
        )
        if game_servers:
            query = query.filter(ActionLog.game_server.in_(game_servers))

        grouped: dict[str, dict[str, object]] = {}
        for log in query.order_by(ActionLog.created_at.desc()).all():
            stats = grouped.setdefault(
                log.actor_id,
                {
                    "actor_id": log.actor_id,
                    "actor_name": log.actor_name,
                    "total": 0,
                    "approved": 0,
                    "rejected": 0,
                    "callbacks": 0,
                    "last_activity": log.created_at,
                },
            )
            stats["total"] = int(stats["total"]) + 1
            if log.action == "approve":
                stats["approved"] = int(stats["approved"]) + 1
            elif log.action == "reject":
                stats["rejected"] = int(stats["rejected"]) + 1
            elif log.action == "callback":
                stats["callbacks"] = int(stats["callbacks"]) + 1

        return sorted(grouped.values(), key=lambda item: (-int(item["total"]), str(item["actor_name"])))
    finally:
        session.close()


def update_discord_message_id(app_id: int, message_id: str, channel_id: str | None = None) -> None:
    session = get_session_factory()()
    try:
        app = session.get(Application, app_id)
        if app:
            app.discord_message_id = message_id
            if channel_id:
                app.discord_channel_id = channel_id
            session.commit()
    finally:
        session.close()

from __future__ import annotations

from typing import Annotated

import httpx
from pathlib import Path
from urllib.parse import urlencode

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from shared.config import get_config, get_role_id
from shared.models import init_db
from shared.schemas import (
    ApplicationAction,
    ApplicationCreate,
    ApplicationResponse,
    PromotionAction,
    PromotionCreate,
    PromotionResponse,
)
from shared.services import (
    create_application,
    get_application_stats,
    get_application,
    get_bot_errors,
    get_site_access_settings,
    get_site_user_access,
    get_login_count,
    get_logs,
    get_recruiter_stats,
    list_applications,
    process_action,
    process_promotion,
    create_promotion,
    get_promotion,
    list_promotions,
    record_login,
    save_site_access_settings,
    register_site_user,
    list_site_users,
    set_site_user_approval,
    update_discord_message_id,
    log_bot_error,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="Londo Family Applications", lifespan=lifespan)
config = get_config()

STATUS_LABELS = {
    "pending": "На рассмотрении",
    "callback": "Вызван на обзвон",
    "approved": "Принят",
    "rejected": "Отклонён",
}
PROMOTION_STATUS_LABELS = {
    "pending": "На рассмотрении",
    "approved": "Одобрен",
    "rejected": "Отклонён",
}
ACTION_LABELS = {
    "approve": "Принял",
    "callback": "Вызвал на обзвон",
    "reject": "Отклонил",
}
SOURCE_LABELS = {"web": "Сайт", "discord": "Discord"}
LOG_TYPE_LABELS = {"application": "Заявка", "promotion": "Повышение"}


def format_duration(seconds: int | None) -> str:
    total = max(0, int(seconds or 0))
    minutes, seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} ч {minutes} мин"
    return f"{minutes} мин {seconds} сек"


def add_notification(request: Request, message: str, level: str = "success") -> None:
    notifications = request.session.setdefault("notifications", [])
    notifications.append({"message": message, "level": level})


def consume_notifications(request: Request) -> list[dict[str, str]]:
    return request.session.pop("notifications", [])

BASE_DIR = Path(__file__).resolve().parent
app.add_middleware(SessionMiddleware, secret_key=config["web"]["secret_key"])

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def verify_api_secret(x_api_secret: Annotated[str, Header()]) -> None:
    if x_api_secret != config["web"]["api_secret"]:
        raise HTTPException(status_code=403, detail="Invalid API secret")


# ── Discord OAuth ──────────────────────────────────────────────

DISCORD_API = "https://discord.com/api/v10"
DISCORD_OAUTH = "https://discord.com/api/oauth2/authorize"


def _has_role(user_roles: list[int], role_key: str) -> bool:
    role_id = config["discord"]["roles"].get(role_key, 0)
    return role_id in user_roles


def _has_recruiter_role(user_roles: list[int]) -> bool:
    return _has_role(user_roles, "recruiter_memphis") or _has_role(
        user_roles, "recruiter_phoenix"
    )


def _has_staff_role(user_roles: list[int]) -> bool:
    return any(
        _has_role(user_roles, role_key)
        for role_key in (
            "recruiter_memphis",
            "recruiter_phoenix",
            "curator_memphis",
            "curator_phoenix",
            "depowner_memphis",
            "depowner_phoenix",
        )
    )


def _has_curator_or_depowner_role(user_roles: list[int]) -> bool:
    return any(
        _has_role(user_roles, role_key)
        for role_key in (
            "curator_memphis",
            "curator_phoenix",
            "depowner_memphis",
            "depowner_phoenix",
        )
    )


def _user_is_reviewer(user: dict) -> bool:
    roles = user.get("roles", [])
    return (
        _has_staff_role(roles)
        or _has_role(roles, "owner")
        or _has_role(roles, "chief_moderator")
    )


def _has_global_site_access(user: dict) -> bool:
    roles = user.get("roles", [])
    return _has_role(roles, "owner") or _has_role(roles, "chief_moderator")


def _is_access_admin(user: dict) -> bool:
    roles = user.get("roles", [])
    return _has_role(roles, "owner") or _has_role(roles, "chief_moderator")


def _profile_is_approved(user: dict) -> bool:
    if _has_role(user.get("roles", []), "owner") or _has_role(
        user.get("roles", []), "chief_moderator"
    ):
        return True
    profile = get_site_user_access(str(user["id"]))
    return bool(profile and profile.is_approved)


def _default_section_roles(section: str) -> list[int]:
    role_config = config["discord"]["roles"]
    defaults = {
        "applications": ("recruiter_memphis", "recruiter_phoenix", "curator_memphis", "curator_phoenix", "depowner_memphis", "depowner_phoenix", "owner", "chief_moderator"),
        "promotions": ("recruiter_memphis", "recruiter_phoenix", "curator_memphis", "curator_phoenix", "depowner_memphis", "depowner_phoenix", "owner", "chief_moderator"),
        "logs": ("curator_memphis", "curator_phoenix", "depowner_memphis", "depowner_phoenix", "owner", "chief_moderator"),
        "bot_errors": ("owner", "chief_moderator"),
    }
    return [int(role_config[key]) for key in defaults[section] if role_config.get(key)]


def _section_role_ids(section: str) -> list[int]:
    settings = get_site_access_settings()
    if section in settings:
        return settings[section]
    return _default_section_roles(section)


def _has_section_access(user: dict, section: str) -> bool:
    return bool(set(user.get("roles", [])) & set(_section_role_ids(section)))


def _has_logs_access(user: dict) -> bool:
    roles = user.get("roles", [])
    return _has_curator_or_depowner_role(roles) or _has_role(roles, "owner") or _has_role(roles, "chief_moderator")


def _has_bot_errors_access(user: dict) -> bool:
    roles = user.get("roles", [])
    return _has_role(roles, "owner") or _has_role(roles, "chief_moderator")


def _has_server_access(user: dict, server: str) -> bool:
    roles = user.get("roles", [])
    if _has_global_site_access(user):
        return True
    server_roles = {
        "memphis": ("recruiter_memphis", "curator_memphis", "depowner_memphis"),
        "phoenix": ("recruiter_phoenix", "curator_phoenix", "depowner_phoenix"),
    }
    if any(_has_role(roles, role_key) for role_key in server_roles.get(server, ())):
        return True
    if _has_staff_role(roles):
        return False
    allowed_roles = config["discord"].get("server_access_roles", {}).get(server, [])
    return bool(set(roles) & set(allowed_roles))


def _visible_servers(user: dict) -> list[str]:
    return [server for server in ("memphis", "phoenix") if _has_server_access(user, server)]


async def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


async def require_reviewer(request: Request) -> dict:
    """Для веб-страниц: перенаправляет на логин, если нет прав."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)
    if not _profile_is_approved(user):
        return RedirectResponse("/access/pending", status_code=303)
    if not _user_is_reviewer(user):
        return RedirectResponse("/access/denied", status_code=303)
    return user


# ── Auth routes ────────────────────────────────────────────────

@app.get("/auth/login")
async def login():
    oauth = config["web"]["oauth"]
    params = {
        "client_id": oauth["client_id"],
        "redirect_uri": oauth["redirect_uri"],
        "response_type": "code",
        "scope": "identify guilds.members.read",
    }
    query = urlencode(params)
    return RedirectResponse(f"{DISCORD_OAUTH}?{query}")


@app.get("/auth/callback")
async def auth_callback(request: Request, code: str):
    oauth = config["web"]["oauth"]
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            f"{DISCORD_API}/oauth2/token",
            data={
                "client_id": oauth["client_id"],
                "client_secret": oauth["client_secret"],
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": oauth["redirect_uri"],
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_resp.status_code != 200:
            error_data = token_resp.json() if token_resp.content else {}
            error_code = error_data.get("error", "unknown")
            error_description = error_data.get("error_description", "")
            log_bot_error(
                "oauth_token_exchange",
                "Discord отклонил обмен OAuth-кода на токен.",
                f"HTTP {token_resp.status_code}: {error_code} {error_description}".strip(),
            )
            raise HTTPException(
                status_code=400,
                detail=f"OAuth failed: {error_code}",
            )
        token_data = token_resp.json()
        access_token = token_data["access_token"]

        user_resp = await client.get(
            f"{DISCORD_API}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_data = user_resp.json()

        guild_id = config["discord"]["guild_id"]
        member_resp = await client.get(
            f"{DISCORD_API}/users/@me/guilds/{guild_id}/member",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        member_data = member_resp.json() if member_resp.status_code == 200 else {}
        roles = member_data.get("roles", [])

    role_ids = [int(r) for r in roles]
    display_name = (
        member_data.get("nick")
        or user_data.get("global_name")
        or user_data["username"]
    )
    profile = register_site_user(
        user_data["id"],
        display_name,
        role_ids,
        auto_approve=_has_role(role_ids, "owner")
        or _has_role(role_ids, "chief_moderator"),
    )
    request.session["user"] = {
        "id": user_data["id"],
        "username": display_name,
        "avatar": user_data.get("avatar"),
        "roles": role_ids,
        "profile_approved": profile.is_approved,
    }
    record_login(user_data["id"], display_name, role_ids)
    if not profile.is_approved:
        return RedirectResponse("/access/pending")
    return RedirectResponse("/")


@app.get("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")


@app.get("/access/pending", response_class=HTMLResponse)
async def access_pending(request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)
    if _profile_is_approved(user):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request,
        "access_pending.html",
        {"user": user, "config": config},
    )


@app.get("/access/denied", response_class=HTMLResponse)
async def access_denied(request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)
    if not _profile_is_approved(user):
        return RedirectResponse("/access/pending", status_code=303)
    if _user_is_reviewer(user):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request,
        "access_denied.html",
        {"user": user, "config": config},
    )


# ── API (bot ↔ site) ───────────────────────────────────────────

@app.post("/api/applications", response_model=ApplicationResponse, dependencies=[Depends(verify_api_secret)])
async def api_create_application(data: ApplicationCreate):
    app_obj = create_application(data)
    from shared.notify import notify_new_application

    await notify_new_application(app_obj.game_server.value)
    return app_obj


@app.get("/api/applications/{app_id}", response_model=ApplicationResponse, dependencies=[Depends(verify_api_secret)])
async def api_get_application(app_id: int):
    app_obj = get_application(app_id)
    if not app_obj:
        raise HTTPException(status_code=404)
    return app_obj


@app.post("/api/applications/{app_id}/action", response_model=ApplicationResponse, dependencies=[Depends(verify_api_secret)])
async def api_process_action(app_id: int, action: ApplicationAction):
    result = process_action(app_id, action)
    if not result:
        raise HTTPException(status_code=400, detail="Application not found or already processed")
    from shared.notify import notify_user_about_application
    await notify_user_about_application(app_id)
    return result


class MessageIdUpdate(BaseModel):
    discord_message_id: str
    discord_channel_id: str | None = None


@app.patch("/api/applications/{app_id}/message", dependencies=[Depends(verify_api_secret)])
async def api_update_message_id(app_id: int, data: MessageIdUpdate):
    update_discord_message_id(app_id, data.discord_message_id, data.discord_channel_id)
    return {"ok": True}


@app.post("/api/promotions", response_model=PromotionResponse, dependencies=[Depends(verify_api_secret)])
async def api_create_promotion(data: PromotionCreate):
    promotion = create_promotion(data)
    from shared.notify import notify_new_promotion

    await notify_new_promotion(promotion.game_server.value)
    return promotion


@app.get("/api/promotions/{request_id}", response_model=PromotionResponse, dependencies=[Depends(verify_api_secret)])
async def api_get_promotion(request_id: int):
    request_obj = get_promotion(request_id)
    if not request_obj:
        raise HTTPException(status_code=404)
    return request_obj


# ── Web UI ─────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = await get_current_user(request)
    if user and not _profile_is_approved(user):
        return RedirectResponse("/access/pending", status_code=303)
    if user and not _user_is_reviewer(user):
        return RedirectResponse("/access/denied", status_code=303)
    visible_servers = _visible_servers(user) if user else []
    if user and len(visible_servers) == 1:
        return RedirectResponse(f"/server/{visible_servers[0]}", status_code=303)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "user": user,
            "config": config,
            "can_view_logs": bool(user and _has_logs_access(user)),
            "visible_servers": visible_servers,
            "is_access_admin": _is_access_admin(user) if user else False,
        },
    )


@app.get("/server/{server}", response_class=HTMLResponse)
async def server_workspace(request: Request, server: str):
    user = await require_reviewer(request)
    if isinstance(user, RedirectResponse):
        return user
    if server not in ("memphis", "phoenix"):
        raise HTTPException(status_code=404)
    if not _has_server_access(user, server):
        raise HTTPException(status_code=403, detail="Нет доступа к разделу этого сервера")
    return templates.TemplateResponse(
        request,
        "server_workspace.html",
        {
            "user": user,
            "config": config,
            "server": server,
            "visible_servers": _visible_servers(user),
            "can_view_logs": _has_logs_access(user),
            "is_access_admin": _is_access_admin(user),
            "notifications": consume_notifications(request),
        },
    )


@app.get("/cabinet/{server}", response_class=HTMLResponse)
async def cabinet(request: Request, server: str, status: str = "pending"):
    user = await require_reviewer(request)
    if isinstance(user, RedirectResponse):
        return user
    if server not in ("memphis", "phoenix"):
        raise HTTPException(status_code=404)
    if not _has_section_access(user, "applications") or not _has_server_access(user, server):
        raise HTTPException(status_code=403, detail="Нет доступа к кабинету этого сервера")
    apps = list_applications(game_server=server, status=status if status != "all" else None)
    return templates.TemplateResponse(
        request,
        "cabinet.html",
        {
            "user": user,
            "config": config,
            "server": server,
            "status": status,
            "applications": apps,
            "can_review": _has_recruiter_role(user["roles"])
            or _has_curator_or_depowner_role(user["roles"])
            or _has_global_site_access(user),
            "can_view_logs": _has_logs_access(user),
            "status_labels": STATUS_LABELS,
            "action_labels": ACTION_LABELS,
            "source_labels": SOURCE_LABELS,
            "format_duration": format_duration,
            "visible_servers": _visible_servers(user),
            "is_access_admin": _is_access_admin(user),
        },
    )


@app.get("/promotions", response_class=HTMLResponse)
async def promotions_page(request: Request, server: str = "all", status: str = "pending"):
    user = await require_reviewer(request)
    if isinstance(user, RedirectResponse):
        return user
    if not _has_section_access(user, "promotions"):
        return RedirectResponse("/", status_code=303)
    visible_servers = _visible_servers(user)
    selected_servers = visible_servers if server == "all" else [server]
    if any(item not in visible_servers for item in selected_servers):
        raise HTTPException(status_code=403)
    promotions = [
        item
        for selected_server in selected_servers
        for item in list_promotions(selected_server, status if status != "all" else None)
    ]
    return templates.TemplateResponse(
        request,
        "promotions.html",
        {
            "user": user,
            "config": config,
            "promotions": promotions,
            "server": server,
            "status": status,
            "visible_servers": visible_servers,
            "can_view_logs": _has_logs_access(user),
            "promotion_labels": {"baby_londo": "Baby Londo", "young_londo": "Young Londo", "main": "Main", "recruit": "Recruit"},
            "promotion_status_labels": PROMOTION_STATUS_LABELS,
            "is_access_admin": _is_access_admin(user),
        },
    )


@app.post("/promotion/{request_id}/action")
async def web_process_promotion(request: Request, request_id: int):
    user = await require_reviewer(request)
    if isinstance(user, RedirectResponse):
        return user
    if not _has_section_access(user, "promotions"):
        raise HTTPException(status_code=403)
    promotion = get_promotion(request_id)
    if not promotion or not _has_server_access(user, promotion.game_server.value):
        raise HTTPException(status_code=404)
    form = await request.form()
    result = process_promotion(
        request_id,
        PromotionAction(
            action=form["action"],
            actor_name=user["username"],
            actor_id=user["id"],
            rejection_reason_id=form.get("rejection_reason_id"),
            custom_reason=form.get("custom_reason"),
            rejection_reason=form.get("rejection_reason"),
        ),
    )
    if not result:
        add_notification(request, "Этот запрос на повышение уже был обработан.", "warning")
        return RedirectResponse(
            f"/promotions?server={promotion.game_server.value}&status=pending",
            status_code=303,
        )
    from shared.notify import notify_promotion_result
    await notify_promotion_result(request_id)
    if form["action"] == "approve":
        add_notification(request, "Запрос на повышение одобрен.")
    else:
        add_notification(request, "Запрос на повышение отклонён.")
    return RedirectResponse(
        f"/promotions?server={promotion.game_server.value}&status=pending",
        status_code=303,
    )


@app.get("/application/{app_id}", response_class=HTMLResponse)
async def application_detail(request: Request, app_id: int):
    user = await require_reviewer(request)
    if isinstance(user, RedirectResponse):
        return user
    app_obj = get_application(app_id)
    if not app_obj:
        raise HTTPException(status_code=404)
    if not _has_section_access(user, "applications") or not _has_server_access(user, app_obj.game_server.value):
        raise HTTPException(status_code=403, detail="Нет доступа к заявкам этого сервера")
    logs = get_logs(application_id=app_id)
    return templates.TemplateResponse(
        request,
        "application.html",
        {
            "user": user,
            "config": config,
            "application": app_obj,
            "logs": logs,
            "can_review": _has_recruiter_role(user["roles"])
            or _has_curator_or_depowner_role(user["roles"])
            or _has_global_site_access(user),
            "can_view_logs": _user_is_reviewer(user),
            "status_labels": STATUS_LABELS,
            "action_labels": ACTION_LABELS,
            "source_labels": SOURCE_LABELS,
            "format_duration": format_duration,
            "is_access_admin": _is_access_admin(user),
            "notifications": consume_notifications(request),
        },
    )


@app.post("/application/{app_id}/action")
async def web_process_action(request: Request, app_id: int):
    user = await require_reviewer(request)
    if isinstance(user, RedirectResponse):
        return user
    if not _has_section_access(user, "applications"):
        raise HTTPException(status_code=403)

    app_obj = get_application(app_id)
    if not app_obj:
        raise HTTPException(status_code=404)
    if not _has_server_access(user, app_obj.game_server.value):
        raise HTTPException(status_code=403, detail="Нет доступа к заявкам этого сервера")

    form = await request.form()
    action_data = ApplicationAction(
        action=form["action"],
        actor_name=user["username"],
        actor_id=user["id"],
        rejection_reason_id=form.get("rejection_reason_id"),
        custom_reason=form.get("custom_reason"),
        source="web",
    )
    result = process_action(app_id, action_data)
    if not result:
        add_notification(request, "Эта заявка уже была обработана.", "warning")
        return RedirectResponse(f"/application/{app_id}", status_code=303)

    from shared.notify import notify_user_about_application
    await notify_user_about_application(app_id)

    action_messages = {
        "approve": "Заявка одобрена.",
        "reject": "Заявка отклонена.",
        "callback": "Пользователь вызван на обзвон.",
    }
    add_notification(request, action_messages[form["action"]])

    return RedirectResponse(f"/application/{app_id}", status_code=303)


@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request, server: str = "all", category: str = "applications", discord_user_id: str | None = None, static_id: str | None = None):
    user = await require_reviewer(request)
    if isinstance(user, RedirectResponse):
        return user
    # По ТЗ логи видят куратор рекрутов и старший состав (рекрут — только свою работу).
    if category == "bot_errors":
        if not _has_bot_errors_access(user):
            return RedirectResponse("/", status_code=303)
    elif not _has_section_access(user, "logs"):
        return RedirectResponse("/", status_code=303)
    if not _visible_servers(user):
        return RedirectResponse("/", status_code=303)

    visible_servers = _visible_servers(user)
    if server == "all":
        selected_servers = visible_servers
    elif server in ("memphis", "phoenix") and server in visible_servers:
        selected_servers = [server]
    else:
        raise HTTPException(status_code=404)
    if category not in ("applications", "bot_errors"):
        raise HTTPException(status_code=404)

    bot_errors = get_bot_errors() if category == "bot_errors" else []

    # If search params provided, filter logs by target discord id or static id for each selected server
    if discord_user_id or static_id:
        all_logs = [
            log
            for selected_server in selected_servers
            for log in get_logs(game_server=selected_server, discord_user_id=discord_user_id, static_id=static_id)
        ]
    else:
        all_logs = [log for selected_server in selected_servers for log in get_logs(game_server=selected_server)]
    stats = {
        "logins": sum(
            get_login_count(config["discord"].get("server_access_roles", {}).get(selected_server, []))
            for selected_server in selected_servers
        ),
        "applications": sum(get_application_stats(selected_server)["total"] for selected_server in selected_servers),
        "approved": sum(get_application_stats(selected_server)["approved"] for selected_server in selected_servers),
        "rejected": sum(get_application_stats(selected_server)["rejected"] for selected_server in selected_servers),
    }
    callback_logs = [log for log in all_logs if log.action == "callback"]
    recruiter_stats = get_recruiter_stats(selected_servers)
    logs_by_server = {
        "memphis": [log for log in all_logs if log.game_server == "memphis"],
        "phoenix": [log for log in all_logs if log.game_server == "phoenix"],
    }
    return templates.TemplateResponse(
        request,
        "logs.html",
        {
            "user": user,
            "config": config,
            "logs": all_logs,
            "logs_by_server": logs_by_server,
            "callback_logs": callback_logs,
            "is_senior": _has_role(user["roles"], "senior_staff"),
            "is_curator": _has_curator_or_depowner_role(user["roles"]),
            "can_view_bot_errors": _has_bot_errors_access(user),
            "action_labels": ACTION_LABELS,
            "source_labels": SOURCE_LABELS,
            "selected_server": server,
            "visible_servers": visible_servers,
            "stats": stats,
            "recruiter_stats": recruiter_stats,
            "selected_category": category,
            "categories": {"applications": "Заявки"},
            "log_type_labels": LOG_TYPE_LABELS,
            "bot_errors": bot_errors,
            "is_access_admin": _is_access_admin(user),
        },
    )


@app.get("/settings/access", response_class=HTMLResponse)
async def access_settings_page(request: Request):
    user = await require_reviewer(request)
    if isinstance(user, RedirectResponse):
        return user
    if not _is_access_admin(user):
        raise HTTPException(status_code=403, detail="Настройки доступны только овнеру и чиф модератору")
    sections = {
        "applications": "Заявки в семью",
        "promotions": "Повышения",
        "logs": "Логи",
        "bot_errors": "Ошибки бота",
    }
    settings = {section: ", ".join(map(str, _section_role_ids(section))) for section in sections}
    site_users = list_site_users()
    return templates.TemplateResponse(
        request,
        "settings_access.html",
        {
            "user": user,
            "config": config,
            "sections": sections,
            "settings": settings,
            "saved": request.query_params.get("saved") == "1",
            "users_saved": request.query_params.get("users_saved") == "1",
            "site_users": site_users,
        },
    )


@app.post("/settings/access")
async def save_access_settings(request: Request):
    user = await require_reviewer(request)
    if isinstance(user, RedirectResponse):
        return user
    if not _is_access_admin(user):
        raise HTTPException(status_code=403)
    form = await request.form()
    settings = {}
    for section in ("applications", "promotions", "logs", "bot_errors"):
        raw_ids = str(form.get(section, ""))
        settings[section] = [int(value) for value in raw_ids.replace(";", ",").split(",") if value.strip().isdigit()]
    save_site_access_settings(settings)
    return RedirectResponse("/settings/access?saved=1", status_code=303)


@app.post("/settings/users/{discord_user_id}/approval")
async def update_user_approval(request: Request, discord_user_id: str):
    user = await require_reviewer(request)
    if isinstance(user, RedirectResponse):
        return user
    if not _has_role(user["roles"], "owner"):
        raise HTTPException(status_code=403, detail="Одобрять профили может только овнер")
    form = await request.form()
    approved = form.get("action") == "approve"
    set_site_user_approval(discord_user_id, approved, user["username"])
    return RedirectResponse("/settings/access?users_saved=1", status_code=303)

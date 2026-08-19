from __future__ import annotations

import httpx
from datetime import datetime, timezone

from shared.config import get_config
from shared.discord_api import _headers
from shared.embeds import (
    build_approved_embed_data,
    build_callback_embed_data,
    build_rejected_embed_data,
    build_review_embed_data,
)
from shared.services import (
    get_application,
    get_promotion,
    log_bot_error,
    update_callback_channels,
    update_callback_voice_state,
)

DISCORD_API = "https://discord.com/api/v10"


def _log_discord_failure(event_name: str, response: httpx.Response) -> None:
    log_bot_error(
        event_name,
        "Discord API не выполнил операцию.",
        f"HTTP {response.status_code}: {response.text[:500]}",
    )


async def _create_callback_channels(guild_id: int, user_id: int, app_id: int, game_server: str) -> dict | None:
    """Create a temporary text + voice channel for callback interview."""
    server = get_config()["servers"].get(game_server, {})
    server_label = server.get("name", game_server)
    category_name = get_config()["discord"].get("callback_category_name", "Обзвоны")

    async with httpx.AsyncClient() as client:
        category_id = str(get_config()["discord"].get("callback_category_id") or "") or None
        if not category_id:
            channels_resp = await client.get(
                f"{DISCORD_API}/guilds/{guild_id}/channels",
                headers=_headers(),
            )
            if channels_resp.status_code != 200:
                _log_discord_failure("callback_list_channels", channels_resp)
                return None
            for ch in channels_resp.json():
                if ch.get("name") == category_name and ch.get("type") == 4:
                    category_id = ch["id"]
                    break
        if not category_id:
            category_resp = await client.post(
                f"{DISCORD_API}/guilds/{guild_id}/channels",
                json={"name": category_name, "type": 4},
                headers=_headers(),
            )
            if category_resp.status_code not in (200, 201):
                _log_discord_failure("callback_create_category", category_resp)
                return None
            category_id = category_resp.json()["id"]

        channel_base = {
            "guild_id": str(guild_id),
            "permission_overwrites": [
                {
                    "id": str(guild_id),
                    "type": 0,
                    "deny": "1024",  # VIEW_CHANNEL
                },
                {
                    "id": str(user_id),
                    "type": 1,
                    "allow": "1049600",  # VIEW_CHANNEL | CONNECT
                },
            ],
        }
        role_keys = ["senior_staff", "owner", "chief_moderator"]
        role_keys.extend(
            {
                "memphis": (
                    "recruiter_memphis",
                    "curator_memphis",
                    "depowner_memphis",
                ),
                "phoenix": (
                    "recruiter_phoenix",
                    "curator_phoenix",
                    "depowner_phoenix",
                ),
            }.get(game_server, ())
        )
        for role_key in role_keys:
            role_id = get_config()["discord"]["roles"].get(role_key)
            if role_id:
                channel_base["permission_overwrites"].append(
                    {
                        "id": str(role_id),
                        "type": 0,
                        "allow": "1049600",  # VIEW_CHANNEL | CONNECT
                    }
                )

        # Create text channel
        text_resp = await client.post(
            f"{DISCORD_API}/guilds/{guild_id}/channels",
            json={
                **channel_base,
                "name": f"обзвон-{app_id}",
                "type": 0,  # GUILD_TEXT
                "topic": f"Обзвон заявки #{app_id} — {server_label}",
                "parent_id": category_id,
            },
            headers=_headers(),
        )
        if text_resp.status_code not in (200, 201):
            _log_discord_failure("callback_create_text_channel", text_resp)
            return None
        text_channel = text_resp.json()

        # Create voice channel
        voice_resp = await client.post(
            f"{DISCORD_API}/guilds/{guild_id}/channels",
            json={
                **channel_base,
                "name": f"🎙 Обзвон-{app_id}",
                "type": 2,  # GUILD_VOICE
                "parent_id": category_id,
            },
            headers=_headers(),
        )
        if voice_resp.status_code not in (200, 201):
            _log_discord_failure("callback_create_voice_channel", voice_resp)
            await client.delete(
                f"{DISCORD_API}/channels/{text_channel['id']}",
                headers=_headers(),
            )
            return None
        voice_channel = voice_resp.json()

        result = {
            "text_id": text_channel["id"],
            "text_name": text_channel["name"],
            "voice_id": voice_channel["id"] if voice_channel else None,
            "voice_name": voice_channel["name"] if voice_channel else None,
        }
        update_callback_channels(app_id, result["text_id"], result["voice_id"])
        return result


async def _delete_callback_channels(app) -> None:
    if app.callback_started_at:
        started_at = app.callback_started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        elapsed = max(0, int((datetime.now(timezone.utc) - started_at).total_seconds()))
        update_callback_voice_state(
            app.id,
            clear_started_at=True,
            duration_seconds=app.callback_duration_seconds + elapsed,
        )
    channel_ids = [app.callback_text_channel_id, app.callback_voice_channel_id]
    channel_ids = [channel_id for channel_id in channel_ids if channel_id]
    if not channel_ids:
        return
    async with httpx.AsyncClient() as client:
        for channel_id in channel_ids:
            await client.delete(
                f"{DISCORD_API}/channels/{channel_id}",
                headers=_headers(),
            )
    update_callback_channels(app.id, None, None)


async def _send_message_to_channel(
    channel_id: str,
    content: str,
    embed: dict | None = None,
    allowed_role_ids: list[int] | None = None,
) -> bool:
    payload: dict = {"content": content}
    if embed:
        payload["embeds"] = [embed]
    if allowed_role_ids:
        payload["allowed_mentions"] = {
            "parse": [],
            "roles": [str(role_id) for role_id in allowed_role_ids],
        }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{DISCORD_API}/channels/{channel_id}/messages",
            json=payload,
            headers=_headers(),
        )
        return resp.status_code in (200, 201)


async def notify_new_application(game_server: str) -> bool:
    config = get_config()
    channel_id = config["discord"].get("notification_channels", {}).get(game_server)
    if not channel_id:
        return False
    server_name = config["servers"].get(game_server, {}).get("name", game_server)
    recruiter_role_id = config["discord"].get("roles", {}).get(
        f"recruiter_{game_server}"
    )
    try:
        return await _send_message_to_channel(
            str(channel_id),
            f"<@&{recruiter_role_id}> 📨 На сервере **{server_name}** подана заявка. Посмотрите на сайте.",
            allowed_role_ids=[recruiter_role_id] if recruiter_role_id else None,
        )
    except httpx.HTTPError:
        return False


async def notify_new_promotion(game_server: str) -> bool:
    config = get_config()
    channel_id = config["discord"].get("notification_channels", {}).get(game_server)
    if not channel_id:
        return False
    server_name = config["servers"].get(game_server, {}).get("name", game_server)
    recruiter_role_id = config["discord"].get("roles", {}).get(
        f"recruiter_{game_server}"
    )
    try:
        return await _send_message_to_channel(
            str(channel_id),
            f"<@&{recruiter_role_id}> 📈 На сервере **{server_name}** подан запрос на повышение. Посмотрите на сайте.",
            allowed_role_ids=[recruiter_role_id] if recruiter_role_id else None,
        )
    except httpx.HTTPError:
        return False


async def notify_user_about_application(application_id: int) -> None:
    app = get_application(application_id)
    if not app:
        return

    config = get_config()
    guild_id = config["discord"]["guild_id"]
    app_dict = {
        "id": app.id,
        "discord_user_id": app.discord_user_id,
        "discord_username": app.discord_username,
        "character_name": app.character_name,
        "static_id": app.static_id,
        "ooc_age": app.ooc_age,
        "join_goal": app.join_goal,
        "how_found": app.how_found,
        "game_server": app.game_server.value,
        "screenshot_url": app.screenshot_url,
        "rejection_reason": app.rejection_reason,
        # Include reviewer fields so embeds can tag the recruiter who acted
        "reviewed_by": getattr(app, "reviewed_by", None),
        "reviewed_by_id": getattr(app, "reviewed_by_id", None),
    }

    status = app.status.value

    # ── Callback: create channels, then send DM with link ──
    if status == "callback":
        try:
            channels = await _create_callback_channels(
                guild_id, int(app.discord_user_id), app.id, app.game_server.value
            )
        except Exception as exc:
            log_bot_error(
                "callback_create_channels",
                "Не удалось создать временные каналы обзвона.",
                repr(exc),
                discord_user_id=app.discord_user_id,
            )
            channels = None
        channel_mention = None
        if channels:
            channel_mention = f"<#{channels['text_id']}>"
            review_embed = build_review_embed_data(app_dict, status=status, reviewer=app.reviewed_by)
            server = config["servers"][app.game_server.value]
            welcome_msg = (
                f"👋 <@{app.discord_user_id}>, вас пригласили на обзвон!\n"
                f"Заявка **#{app.id}** на сервере {server['emoji']} **{server['name']}**.\n\n"
                f"Рекрут свяжется с вами в ближайшее время."
            )
            await _send_message_to_channel(channels["text_id"], welcome_msg, review_embed)

        dm_embed = build_callback_embed_data(app_dict, channel_mention=channel_mention)
        await _send_dm_embed(int(app.discord_user_id), dm_embed)
        _update_review_msg(app, app_dict, status, reviewer=app.reviewed_by)
        return

    # ── Approved: add role, send DM ──
    if status == "approved":
        await _delete_callback_channels(app)
        # Give configured approved roles
        role_ids = config["discord"]["approved_roles"].get(app.game_server.value, [])
        for role_id in role_ids:
            if role_id:
                await _add_role(int(app.discord_user_id), role_id)
        # Give explicit newbie role on approval
        newbie_role_id = 1539607514688258118
        try:
            await _add_role(int(app.discord_user_id), newbie_role_id)
        except Exception:
            # Best-effort: failure to add newbie role shouldn't crash the flow
            pass
        await _set_nickname(
            int(app.discord_user_id),
            f"{app.character_name} | {app.static_id}",
        )
        dm_embed = build_approved_embed_data(app_dict)
        await _send_dm_embed(int(app.discord_user_id), dm_embed)
        _update_review_msg(app, app_dict, status, reviewer=app.reviewed_by)
        return

    # ── Rejected: send DM ──
    if status == "rejected":
        await _delete_callback_channels(app)
        dm_embed = build_rejected_embed_data(app_dict)
        await _send_dm_embed(int(app.discord_user_id), dm_embed)
        _update_review_msg(app, app_dict, status, reviewer=app.reviewed_by)
        return


async def _send_dm_embed(user_id: int, embed: dict) -> bool:
    try:
        async with httpx.AsyncClient() as client:
            channel_resp = await client.post(
                f"{DISCORD_API}/users/@me/channels",
                json={"recipient_id": str(user_id)},
                headers=_headers(),
            )
            if channel_resp.status_code not in (200, 201):
                _log_discord_failure("callback_create_dm", channel_resp)
                return False
            channel_id = channel_resp.json()["id"]

            msg_resp = await client.post(
                f"{DISCORD_API}/channels/{channel_id}/messages",
                json={"embeds": [embed]},
                headers=_headers(),
            )
            if msg_resp.status_code not in (200, 201):
                _log_discord_failure("callback_send_dm", msg_resp)
                return False
            return True
    except httpx.HTTPError as exc:
        log_bot_error("callback_send_dm", "Не удалось отправить DM через Discord API.", repr(exc))
        return False


async def _add_role(user_id: int, role_id: int) -> bool:
    config = get_config()
    guild_id = config["discord"]["guild_id"]
    async with httpx.AsyncClient() as client:
        resp = await client.put(
            f"{DISCORD_API}/guilds/{guild_id}/members/{user_id}/roles/{role_id}",
            headers=_headers(),
        )
        return resp.status_code == 204


async def _remove_role(user_id: int, role_id: int) -> bool:
    config = get_config()
    guild_id = config["discord"]["guild_id"]
    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            f"{DISCORD_API}/guilds/{guild_id}/members/{user_id}/roles/{role_id}",
            headers=_headers(),
        )
        return resp.status_code == 204


async def notify_promotion_result(request_id: int) -> None:
    request = get_promotion(request_id)
    if not request:
        return
    config = get_config()
    labels = {"baby_londo": "Baby Londo", "young_londo": "Young Londo", "main": "Main", "recruit": "Recruit"}
    target_label = labels.get(request.target, request.target)
    if request.status.value == "approved":
        role_map = config["discord"].get("promotion_roles", {}).get(request.game_server.value, {})
        for role_id in role_map.values():
            if role_id:
                await _remove_role(int(request.discord_user_id), int(role_id))
        role_id = role_map.get(request.target, 0)
        if role_id:
            await _add_role(int(request.discord_user_id), int(role_id))
        embed = {
            "title": "🎉 Запрос на повышение одобрен",
            "description": (
                f"Запрос игрока **{request.character_name}** на получение роли "
                f"**{target_label}** одобрен."
            ),
            "color": 0x3BA55D,
            "footer": {"text": "Londo Family • система повышений"},
        }
    else:
        embed = {
            "title": "❌ Запрос на повышение отклонён",
            "description": (
                f"Запрос игрока **{request.character_name}** на получение роли "
                f"**{target_label}** отклонён."
            ),
            "color": 0xED4245,
            "fields": [{"name": "Причина", "value": request.rejection_reason or "Причина не указана."}],
            "footer": {"text": "Londo Family • система повышений"},
        }
    await _send_dm_embed(int(request.discord_user_id), embed)


async def _set_nickname(user_id: int, nickname: str) -> bool:
    config = get_config()
    guild_id = config["discord"]["guild_id"]
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{DISCORD_API}/guilds/{guild_id}/members/{user_id}",
            json={"nick": nickname[:32]},
            headers=_headers(),
        )
        return resp.status_code == 200


def _update_review_msg(app, app_dict: dict, status: str, reviewer: str | None) -> None:
    """Fire-and-forget: update the review channel message (sync wrapper)."""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_async_update_review_msg(app, app_dict, status, reviewer))
    except RuntimeError:
        pass


async def _async_update_review_msg(app, app_dict: dict, status: str, reviewer: str | None) -> None:
    if not app.discord_message_id:
        return

    from shared.config import get_review_channel_id

    channel_id = int(app.discord_channel_id) if app.discord_channel_id else get_review_channel_id(app.game_server.value)

    review_embed = build_review_embed_data(app_dict, status=status, reviewer=reviewer)
    disabled_components = [
        {
            "type": 1,
            "components": [
                {"type": 2, "style": 3, "label": "✅ Одобрить", "custom_id": "done", "disabled": True},
                {"type": 2, "style": 1, "label": "📞 На обзвон", "custom_id": "done2", "disabled": True},
                {"type": 2, "style": 4, "label": "❌ Отклонить", "custom_id": "done3", "disabled": True},
            ],
        }
    ]
    payload = {"embeds": [review_embed], "components": disabled_components}

    async with httpx.AsyncClient() as client:
        await client.patch(
            f"{DISCORD_API}/channels/{channel_id}/messages/{app.discord_message_id}",
            json=payload,
            headers=_headers(),
        )

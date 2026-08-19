from __future__ import annotations

import httpx

from shared.config import get_config, get_review_channel_id

DISCORD_API = "https://discord.com/api/v10"


def _headers() -> dict:
    config = get_config()
    return {"Authorization": f"Bot {config['discord']['token']}"}


async def send_dm_embed(user_id: int, embed: dict) -> bool:
    async with httpx.AsyncClient() as client:
        channel_resp = await client.post(
            f"{DISCORD_API}/users/@me/channels",
            json={"recipient_id": str(user_id)},
            headers=_headers(),
        )
        if channel_resp.status_code not in (200, 201):
            return False
        channel_id = channel_resp.json()["id"]

        msg_resp = await client.post(
            f"{DISCORD_API}/channels/{channel_id}/messages",
            json={"embeds": [embed]},
            headers=_headers(),
        )
        return msg_resp.status_code in (200, 201)


async def edit_review_message(
    message_id: str,
    embed: dict,
    *,
    channel_id: int | str | None = None,
    game_server: str | None = None,
    components: list | None = None,
) -> bool:
    if channel_id is None and game_server:
        channel_id = get_review_channel_id(game_server)
    if channel_id is None:
        channel_id = get_config()["discord"]["review_channel_id"]

    payload: dict = {"embeds": [embed]}
    if components is not None:
        payload["components"] = components

    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{DISCORD_API}/channels/{channel_id}/messages/{message_id}",
            json=payload,
            headers=_headers(),
        )
        return resp.status_code == 200


async def add_role(user_id: int, role_id: int) -> bool:
    config = get_config()
    guild_id = config["discord"]["guild_id"]
    async with httpx.AsyncClient() as client:
        resp = await client.put(
            f"{DISCORD_API}/guilds/{guild_id}/members/{user_id}/roles/{role_id}",
            headers=_headers(),
        )
        return resp.status_code == 204

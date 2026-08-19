from __future__ import annotations

import discord

from shared.embeds import (
    build_approved_embed_data,
    build_callback_embed_data,
    build_rejected_embed_data,
    build_submitted_embed_data,
)


def _dict_to_embed(data: dict) -> discord.Embed:
    embed = discord.Embed(
        title=data.get("title"),
        description=data.get("description"),
        color=data.get("color"),
    )
    for field in data.get("fields", []):
        embed.add_field(
            name=field["name"],
            value=field["value"],
            inline=field.get("inline", False),
        )
    if image := data.get("image"):
        embed.set_image(url=image["url"])
    if footer := data.get("footer"):
        embed.set_footer(text=footer["text"])
    return embed


def build_approved_embed(app_data: dict) -> discord.Embed:
    return _dict_to_embed(build_approved_embed_data(app_data))


def build_rejected_embed(app_data: dict) -> discord.Embed:
    return _dict_to_embed(build_rejected_embed_data(app_data))


def build_callback_embed(app_data: dict, *, channel_mention: str | None = None) -> discord.Embed:
    return _dict_to_embed(build_callback_embed_data(app_data, channel_mention=channel_mention))


def build_submitted_embed(app_data: dict) -> discord.Embed:
    return _dict_to_embed(build_submitted_embed_data(app_data))


async def send_dm_notification(bot: discord.Client, user_id: int, embed: discord.Embed) -> bool:
    try:
        user = await bot.fetch_user(user_id)
        await user.send(embed=embed)
        return True
    except (discord.Forbidden, discord.NotFound):
        return False

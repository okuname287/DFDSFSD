from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_CONFIG: dict[str, Any] | None = None
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def _normalize_snowflake(value: int | str) -> int:
    """Discord snowflakes must fit in 64 bits; fix common trailing-zero typos."""
    if isinstance(value, str):
        value = int(value.strip())
    if value <= 0:
        return value
    while value > (1 << 63) - 1:
        value //= 10
    return value


def _normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    discord = config.setdefault("discord", {})

    for key, value in discord.get("roles", {}).items():
        discord["roles"][key] = _normalize_snowflake(value)

    for key, value in discord.get("approved_roles", {}).items():
        if isinstance(value, list):
            discord["approved_roles"][key] = [
                _normalize_snowflake(role_id) for role_id in value
            ]
        else:
            discord["approved_roles"][key] = [_normalize_snowflake(value)] if value else []

    for server, role_ids in discord.get("server_access_roles", {}).items():
        discord["server_access_roles"][server] = [
            _normalize_snowflake(role_id) for role_id in role_ids if role_id
        ]

    discord["guild_id"] = _normalize_snowflake(discord.get("guild_id", 0))
    if discord.get("callback_category_id"):
        discord["callback_category_id"] = _normalize_snowflake(
            discord["callback_category_id"]
        )
    for server, role_map in discord.get("promotion_roles", {}).items():
        discord["promotion_roles"][server] = {
            target: _normalize_snowflake(role_id) if role_id else 0
            for target, role_id in role_map.items()
        }

    review_channels = discord.get("review_channels")
    legacy_channel = discord.get("review_channel_id")
    if not review_channels:
        fallback = _normalize_snowflake(legacy_channel or 0)
        review_channels = {"memphis": fallback, "phoenix": fallback}
        discord["review_channels"] = review_channels
    else:
        for server in ("memphis", "phoenix"):
            if server in review_channels:
                review_channels[server] = _normalize_snowflake(review_channels[server])
            elif legacy_channel:
                review_channels[server] = _normalize_snowflake(legacy_channel)

    discord["review_channel_id"] = review_channels.get("memphis") or _normalize_snowflake(
        legacy_channel or 0
    )
    return config


def load_config(path: Path | None = None) -> dict[str, Any]:
    global _CONFIG
    config_path = path or CONFIG_PATH
    with open(config_path, encoding="utf-8") as f:
        _CONFIG = _normalize_config(yaml.safe_load(f))
    return _CONFIG


def get_config() -> dict[str, Any]:
    if _CONFIG is None:
        return load_config()
    return _CONFIG


def reload_config() -> dict[str, Any]:
    return load_config()


def get_review_channel_id(game_server: str) -> int:
    channels = get_config()["discord"]["review_channels"]
    channel_id = channels.get(game_server) or channels.get("memphis", 0)
    return int(channel_id or 0)


def validate_review_channels() -> list[str]:
    """Возвращает список проблем с review_channels (пустые/дублирующиеся)."""
    issues: list[str] = []
    cfg = get_config()
    channels = cfg["discord"]["review_channels"]
    if cfg["discord"].get("shared_review_channel"):
        return issues
    for server in ("memphis", "phoenix"):
        channel_id = channels.get(server)
        if not channel_id:
            issues.append(f"Не задан канал review_channels.{server} в config.yaml")
        elif server == "phoenix" and int(channel_id) == int(channels.get("memphis", 0) or 0):
            issues.append(
                "Каналы review_channels.memphis и review_channels.phoenix совпадают — "
                "заявки обоих серверов будут дублироваться в одном канале. "
                "Создайте отдельный канал #заявки-phoenix и укажите его ID."
            )
    return issues


def get_role_id(role_key: str) -> int:
    return int(get_config()["discord"]["roles"].get(role_key, 0))

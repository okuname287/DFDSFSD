from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

_CONFIG: dict[str, Any] | None = None
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
ENV_PATH = CONFIG_PATH.parent / ".env"


def _load_env_file() -> None:
    if not ENV_PATH.exists():
        return
    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _env_bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: list[int]) -> list[int]:
    value = os.environ.get(name)
    if value is None:
        return default
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _apply_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    discord = config["discord"]
    web = config["web"]

    discord["token"] = os.environ.get("DISCORD_TOKEN", discord["token"])
    discord["guild_id"] = _env_int("DISCORD_GUILD_ID", discord["guild_id"])
    discord["shared_review_channel"] = _env_bool(
        "DISCORD_SHARED_REVIEW_CHANNEL", discord.get("shared_review_channel", False)
    )
    discord["auto_post_welcome"] = _env_bool(
        "DISCORD_AUTO_POST_WELCOME", discord.get("auto_post_welcome", False)
    )
    discord["review_channel_id"] = _env_int(
        "DISCORD_REVIEW_CHANNEL_ID", discord.get("review_channel_id", 0)
    )
    discord["review_channels"] = {
        "memphis": _env_int(
            "DISCORD_REVIEW_CHANNEL_MEMPHIS", discord["review_channels"]["memphis"]
        ),
        "phoenix": _env_int(
            "DISCORD_REVIEW_CHANNEL_PHOENIX", discord["review_channels"]["phoenix"]
        ),
    }
    discord["callback_category_id"] = _env_int(
        "DISCORD_CALLBACK_CATEGORY_ID", discord.get("callback_category_id", 0)
    )
    discord["callback_category_name"] = os.environ.get(
        "DISCORD_CALLBACK_CATEGORY_NAME", discord.get("callback_category_name", "Обзвоны")
    )
    discord["promotion_info_channel_id"] = _env_int(
        "DISCORD_PROMOTION_INFO_CHANNEL_ID", discord.get("promotion_info_channel_id", 0)
    )
    discord["promotion_request_channel_id"] = _env_int(
        "DISCORD_PROMOTION_REQUEST_CHANNEL_ID", discord.get("promotion_request_channel_id", 0)
    )
    discord["application_command"] = os.environ.get(
        "DISCORD_APPLICATION_COMMAND", discord.get("application_command", "заявка")
    )

    for role_key in discord.get("roles", {}):
        env_name = f"DISCORD_ROLE_{role_key.upper()}"
        if env_name in os.environ:
            discord["roles"][role_key] = _env_int(env_name, discord["roles"][role_key])

    for server in ("memphis", "phoenix"):
        discord["server_access_roles"][server] = _env_list(
            f"DISCORD_SERVER_ACCESS_ROLES_{server.upper()}",
            discord["server_access_roles"][server],
        )
        discord["approved_roles"][server] = _env_list(
            f"DISCORD_APPROVED_ROLES_{server.upper()}",
            discord["approved_roles"][server],
        )
        for target in discord["promotion_roles"][server]:
            env_name = f"DISCORD_PROMOTION_ROLE_{server.upper()}_{target.upper()}"
            if env_name in os.environ:
                discord["promotion_roles"][server][target] = _env_int(
                    env_name, discord["promotion_roles"][server][target]
                )

    web["host"] = os.environ.get("WEB_HOST", web.get("host", "0.0.0.0"))
    web["port"] = _env_int("WEB_PORT", web.get("port", 8080))
    web["secret_key"] = os.environ.get("WEB_SECRET_KEY", web["secret_key"])
    web["base_url"] = os.environ.get("WEB_BASE_URL", web.get("base_url", ""))
    web["api_secret"] = os.environ.get("WEB_API_SECRET", web["api_secret"])
    web["oauth"]["client_id"] = os.environ.get(
        "DISCORD_OAUTH_CLIENT_ID", web["oauth"]["client_id"]
    )
    web["oauth"]["client_secret"] = os.environ.get(
        "DISCORD_OAUTH_CLIENT_SECRET", web["oauth"]["client_secret"]
    )
    web["oauth"]["redirect_uri"] = os.environ.get(
        "DISCORD_OAUTH_REDIRECT_URI", web["oauth"]["redirect_uri"]
    )
    config["database"]["url"] = os.environ.get(
        "DATABASE_URL", config["database"]["url"]
    )
    return config


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
    _load_env_file()
    config_path = path or CONFIG_PATH
    with open(config_path, encoding="utf-8") as f:
        _CONFIG = _normalize_config(_apply_env_overrides(yaml.safe_load(f)))
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

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_CONFIG: dict[str, Any] | None = None
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATHS = (BASE_DIR / ".env", BASE_DIR / "1.env")


def _load_env_file() -> None:
    for env_path in ENV_PATHS:
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), value)
        break


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _env_bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: list[int]) -> list[int]:
    value = os.environ.get(name)
    if value is None:
        return default
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _build_config_from_env() -> dict[str, Any]:
    servers = {
        key: {
            "name": _env(f"SERVER_{key.upper()}_NAME", key.title()),
            "emoji": _env(f"SERVER_{key.upper()}_EMOJI"),
            "color": _env(f"SERVER_{key.upper()}_COLOR"),
        }
        for key in ("memphis", "phoenix")
    }
    rejection_reasons = [
        {"id": reason, "label": _env(f"REJECTION_REASON_{reason.upper()}_LABEL"), "message": _env(f"REJECTION_REASON_{reason.upper()}_MESSAGE")}
        for reason in ("age", "screenshot", "incomplete", "other")
    ]
    promotion_rejection_reasons = [
        {"id": reason, "label": _env(f"PROMOTION_REJECTION_REASON_{reason.upper()}_LABEL"), "message": _env(f"PROMOTION_REJECTION_REASON_{reason.upper()}_MESSAGE")}
        for reason in ("conditions", "other")
    ]
    role_keys = (
        "recruiter_memphis", "recruiter_phoenix", "curator_memphis", "curator_phoenix",
        "senior_staff", "depowner_memphis", "depowner_phoenix", "owner", "chief_moderator",
    )
    roles = {key: _env_int(f"DISCORD_ROLE_{key.upper()}", 0) for key in role_keys}
    promotion_targets = ("baby_londo", "young_londo", "main", "recruit")
    base_url = _env("WEB_BASE_URL", "http://localhost:8080").rstrip("/")
    configured_redirect_uri = _env("DISCORD_OAUTH_REDIRECT_URI")
    if not configured_redirect_uri or any(
        host in configured_redirect_uri
        for host in ("localhost", "127.0.0.1", "0.0.0.0")
    ) and not any(
        host in base_url for host in ("localhost", "127.0.0.1", "0.0.0.0")
    ):
        configured_redirect_uri = f"{base_url}/auth/callback"
    return {
        "discord": {
            "token": _env("DISCORD_TOKEN"),
            "guild_id": _env_int("DISCORD_GUILD_ID", 0),
            "review_channels": {server: _env_int(f"DISCORD_REVIEW_CHANNEL_{server.upper()}", 0) for server in servers},
            "shared_review_channel": _env_bool("DISCORD_SHARED_REVIEW_CHANNEL", False),
            "auto_post_welcome": _env_bool("DISCORD_AUTO_POST_WELCOME", False),
            "review_channel_id": _env_int("DISCORD_REVIEW_CHANNEL_ID", 0),
            "roles": roles,
            "server_access_roles": {server: _env_list(f"DISCORD_SERVER_ACCESS_ROLES_{server.upper()}", []) for server in servers},
            "approved_roles": {server: _env_list(f"DISCORD_APPROVED_ROLES_{server.upper()}", []) for server in servers},
            "callback_category_id": _env_int("DISCORD_CALLBACK_CATEGORY_ID", 0),
            "callback_category_name": _env("DISCORD_CALLBACK_CATEGORY_NAME", "Обзвоны"),
            "promotion_info_channel_id": _env_int("DISCORD_PROMOTION_INFO_CHANNEL_ID", 0),
            "promotion_request_channel_id": _env_int("DISCORD_PROMOTION_REQUEST_CHANNEL_ID", 0),
            "notification_channels": {server: _env_int(f"DISCORD_NOTIFICATION_CHANNEL_{server.upper()}", 0) for server in servers},
            "promotion_roles": {
                server: {target: _env_int(f"DISCORD_PROMOTION_ROLE_{server.upper()}_{target.upper()}", 0) for target in promotion_targets}
                for server in servers
            },
            "application_command": _env("DISCORD_APPLICATION_COMMAND", "заявка"),
        },
        "web": {
            "host": _env("WEB_HOST", "0.0.0.0"),
            "port": _env_int("PORT", _env_int("WEB_PORT", 8080)),
            "secret_key": _env("WEB_SECRET_KEY"),
            "base_url": base_url,
            "api_secret": _env("WEB_API_SECRET"),
            "oauth": {
                "client_id": _env("DISCORD_OAUTH_CLIENT_ID"),
                "client_secret": _env("DISCORD_OAUTH_CLIENT_SECRET"),
                "redirect_uri": configured_redirect_uri,
            },
        },
        "database": {"url": _env("DATABASE_URL", "sqlite:///./data/applications.db")},
        "servers": servers,
        "rejection_reasons": rejection_reasons,
        "promotion_rejection_reasons": promotion_rejection_reasons,
    }


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
    _CONFIG = _normalize_config(_build_config_from_env())
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
            issues.append(f"Не задан канал DISCORD_REVIEW_CHANNEL_{server.upper()} в ENV")
        elif server == "phoenix" and int(channel_id) == int(channels.get("memphis", 0) or 0):
            issues.append(
                "Каналы review_channels.memphis и review_channels.phoenix совпадают — "
                "заявки обоих серверов будут дублироваться в одном канале. "
                "Создайте отдельный канал #заявки-phoenix и укажите его ID."
            )
    return issues


def get_role_id(role_key: str) -> int:
    return int(get_config()["discord"]["roles"].get(role_key, 0))

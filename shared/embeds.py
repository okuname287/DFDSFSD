from __future__ import annotations

from datetime import datetime, timezone

from shared.config import get_config


def _server_info(game_server: str) -> dict:
    return get_config()["servers"][game_server]


def _server_name(game_server: str) -> str:
    return _server_info(game_server)["name"]


def _server_color(game_server: str) -> int:
    return int(_server_info(game_server)["color"].lstrip("#"), 16)


def _server_emoji(game_server: str) -> str:
    return _server_info(game_server)["emoji"]


def _fmt_date(iso: str | None = None) -> str:
    dt = datetime.fromisoformat(iso) if iso else datetime.now(timezone.utc)
    return f"<t:{int(dt.timestamp())}:R>"


# ── Review channel embed ─────────────────────────────────────────

def build_review_embed_data(app_data: dict, *, status: str = "pending", reviewer: str | None = None) -> dict:
    server = _server_info(app_data["game_server"])
    server_label = f"{server['emoji']} {server['name']}"
    status_config = {
        "pending": {"label": "⏳ На рассмотрении", "color": 0xFEE75C},
        "approved": {"label": "✅ Одобрена", "color": 0x3BA55D},
        "rejected": {"label": "❌ Отклонена", "color": 0xED4245},
        "callback": {"label": "📞 На обзвон", "color": 0x5865F2},
    }
    st = status_config.get(status, status_config["pending"])
    embed_color = st["color"] if status != "pending" else _server_color(app_data["game_server"])

    description_lines = [
        f"**Заявка №{app_data['id']}**  •  {server_label}",
        f"**Статус:** {st['label']}",
    ]
    if reviewer:
        description_lines.append(f"**Рассмотрел:** {reviewer}")
    description = "\n".join(description_lines)

    fields = [
        {"name": "👤 Персонаж", "value": app_data["character_name"], "inline": True},
        {"name": "🆔 Static ID", "value": f"`{app_data['static_id']}`", "inline": True},
        {"name": "🎂 OOC возраст", "value": f"{app_data['ooc_age']} лет", "inline": True},
        {"name": "\u200b", "value": "\u200b", "inline": False},
        {"name": "🎯 Цель вступления", "value": _truncate(app_data.get("join_goal", ""), 1024), "inline": True},
        {"name": "📢 Как узнали", "value": _truncate(app_data.get("how_found", ""), 1024), "inline": True},
        {"name": "\u200b", "value": "\u200b", "inline": False},
        {"name": "🖼️ Скриншот", "value": _screenshot_field(app_data["screenshot_url"]), "inline": False},
    ]

    footer_parts = [f"Заявка #{app_data['id']}", server_label, st["label"]]
    if reviewer:
        footer_parts.append(reviewer)

    return {
        "title": f"Новая заявка — {server['name']}",
        "description": description,
        "color": embed_color,
        "fields": fields,
        "image": _screenshot_image(app_data["screenshot_url"]),
        "footer": {"text": "  •  ".join(footer_parts)},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── DM: заявка отправлена ───────────────────────────────────────

def build_submitted_embed_data(app_data: dict) -> dict:
    server = _server_info(app_data["game_server"])
    return {
        "title": "📨 Заявка успешно отправлена!",
        "description": (
            f"Ваша заявка **#{app_data['id']}** в семью **Londo** "
            f"на сервере {server['emoji']} **{server['name']}** "
            f"принята и ожидает рассмотрения."
        ),
        "color": _server_color(app_data["game_server"]),
        "fields": [
            {"name": "👤 Персонаж", "value": app_data["character_name"], "inline": True},
            {"name": "🆔 Static", "value": app_data["static_id"], "inline": True},
            {"name": "🎂 Возраст", "value": f"{app_data['ooc_age']} лет", "inline": True},
            {"name": "\u200b", "value": "\u200b", "inline": False},
            {"name": "⏳ Что дальше?", "value": "Рекрут или куратор рассмотрит вашу заявку и отправит результат в эти личные сообщения.", "inline": False},
        ],
        "footer": {"text": f"Londo Family  •  {server['emoji']} {server['name']}"},
    }


# ── DM: одобрена ────────────────────────────────────────────────

def build_approved_embed_data(app_data: dict) -> dict:
    server = _server_info(app_data["game_server"])
    return {
        "title": "🎉 Заявка одобрена!",
        "description": (
            f"Поздравляем! Ваша заявка в семью **Londo** "
            f"на сервере {server['emoji']} **{server['name']}** была **одобрена**."
        ),
        "color": 0x3BA55D,
        "fields": [
            {"name": "👤 Персонаж", "value": app_data["character_name"], "inline": True},
            {"name": "🆔 Static", "value": app_data["static_id"], "inline": True},
            {"name": "\u200b", "value": "\u200b", "inline": False},
            {"name": "📋 Дальнейшие шаги", "value": "Рекрут выдаст вам роль и проведёт инструктаж. Ожидайте связи на сервере.", "inline": False},
        ],
        "footer": {"text": f"Londo Family  •  {server['emoji']} {server['name']}"},
    }


# ── DM: отклонена ────────────────────────────────────────────────

def build_rejected_embed_data(app_data: dict) -> dict:
    server = _server_info(app_data["game_server"])
    reason = app_data.get("rejection_reason") or "Причина не указана."
    return {
        "title": "❌ Заявка отклонена",
        "description": (
            f"К сожалению, ваша заявка в семью **Londo** "
            f"на сервере {server['emoji']} **{server['name']}** была **отклонена**."
        ),
        "color": 0xED4245,
        "fields": [
            {"name": "👤 Персонаж", "value": app_data["character_name"], "inline": True},
            {"name": "🆔 Static", "value": app_data["static_id"], "inline": True},
            {"name": "\u200b", "value": "\u200b", "inline": False},
            {"name": "📝 Причина", "value": reason, "inline": False},
            {"name": "💡 Совет", "value": "Вы можете подать заявку повторно, исправив указанные замечания.", "inline": False},
        ],
        "footer": {"text": f"Londo Family  •  {server['emoji']} {server['name']}"},
    }


# ── DM: на обзвон ────────────────────────────────────────────────

def build_callback_embed_data(app_data: dict, *, channel_mention: str | None = None) -> dict:
    server = _server_info(app_data["game_server"])
    lines = [
        f"Ваша заявка в семью **Londo** на сервере {server['emoji']} **{server['name']}** прошла первичный отбор.",
        "",
        "**Рекрут свяжется с вами** для проведения обзвона. Пожалуйста, будьте на связи в Discord.",
    ]
    if channel_mention:
        lines.append("")
        lines.append(f"**Канал обзвона:** {channel_mention}")

    fields = [
        {"name": "👤 Персонаж", "value": app_data["character_name"], "inline": True},
        {"name": "🆔 Static", "value": app_data["static_id"], "inline": True},
        {"name": "\u200b", "value": "\u200b", "inline": False},
        {"name": "⏰ Важно", "value": "Убедитесь, что у вас открыты личные сообщения от участников сервера.", "inline": False},
    ]

    if channel_mention:
        fields.append({
            "name": "💬 Канал обзвона",
            "value": channel_mention,
            "inline": False,
        })

    return {
        "title": "📞 Вы приглашены на обзвон!",
        "description": "\n".join(lines),
        "color": 0x5865F2,
        "fields": fields,
        "footer": {"text": f"Londo Family  •  {server['emoji']} {server['name']}"},
    }


# ── Helpers ──────────────────────────────────────────────────────

def _truncate(text: str, max_len: int) -> str:
    if not text or text.strip() == "":
        return "Не указано"
    return text[:max_len]


def _screenshot_field(url: str) -> str:
    if not url or url.strip() in ("", "Не прикреплено"):
        return "❌ Не прикреплено"
    return f"[Открыть скриншот]({url})"


def _screenshot_image(url: str) -> dict | None:
    if not url or url.strip() in ("", "Не прикреплено"):
        return None
    return {"url": url}

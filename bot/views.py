from __future__ import annotations

import traceback
from urllib.parse import urlparse

import discord
import httpx

from shared.config import get_config, get_review_channel_id, get_role_id
from shared.embeds import build_review_embed_data
from shared.schemas import ApplicationAction, ApplicationCreate, PromotionCreate
from shared.services import get_application, log_bot_error, process_action

config = get_config()
API_BASE = config["web"]["base_url"].rstrip("/")
API_HEADERS = {"X-Api-Secret": config["web"]["api_secret"]}


class ApplicationRequestError(RuntimeError):
    """Бот не смог достучаться до сайта."""


class SafeView(discord.ui.View):
    async def on_error(self, interaction: discord.Interaction, error: Exception, item) -> None:
        log_bot_error(
            "discord_view",
            "Ошибка обработки кнопки или списка Discord.",
            traceback.format_exc(),
            str(interaction.user.id),
        )
        message = "⚠️ Не удалось выполнить действие. Попробуйте ещё раз позже."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


class SafeModal(discord.ui.Modal):
    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log_bot_error(
            "discord_modal",
            "Ошибка обработки формы Discord.",
            traceback.format_exc(),
            str(interaction.user.id),
        )
        message = "⚠️ Не удалось обработать форму. Проверьте данные и попробуйте позже."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


async def _post_application_to_site(app_data: ApplicationCreate) -> dict:
    """Отправляет заявку на сайт; при недоступности сайта бросает ApplicationRequestError."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{API_BASE}/api/applications",
                json=app_data.model_dump(),
                headers=API_HEADERS,
            )
    except httpx.HTTPError as exc:
        log_bot_error("application_site_request", "Не удалось передать заявку на сайт.", repr(exc))
        raise ApplicationRequestError("Не удалось передать заявку на сайт.") from exc

    if resp.status_code != 200:
        log_bot_error(
            "application_site_response",
            "Сайт вернул ошибку при сохранении заявки.",
            f"HTTP {resp.status_code}: {resp.text[:500]}",
        )
        raise ApplicationRequestError("Сайт временно недоступен.")
    return resp.json()


async def _post_promotion_to_site(data: PromotionCreate) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{API_BASE}/api/promotions",
                json=data.model_dump(),
                headers=API_HEADERS,
            )
    except httpx.HTTPError as exc:
        log_bot_error("promotion_site_request", "Не удалось передать повышение на сайт.", repr(exc))
        raise ApplicationRequestError("Не удалось передать запрос на повышение на сайт.") from exc
    if resp.status_code != 200:
        log_bot_error(
            "promotion_site_response",
            "Сайт вернул ошибку при сохранении повышения.",
            f"HTTP {resp.status_code}: {resp.text[:500]}",
        )
        raise ApplicationRequestError("Сайт временно недоступен.")
    return resp.json()


async def _update_message_link(app_id: int, message_id: int, channel_id: int) -> None:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.patch(
                f"{API_BASE}/api/applications/{app_id}/message",
                json={
                    "discord_message_id": str(message_id),
                    "discord_channel_id": str(channel_id),
                },
                headers=API_HEADERS,
            )
    except httpx.HTTPError:
        # Не критично: сообщение уже опубликовано, ссылка обновится при следующем действии.
        pass


def _user_has_review_role(member: discord.Member) -> bool:
    member_role_ids = {r.id for r in member.roles}
    return bool(
        member_role_ids
        & {
            get_role_id("recruiter_memphis"),
            get_role_id("recruiter_phoenix"),
            get_role_id("curator_memphis"),
            get_role_id("curator_phoenix"),
            get_role_id("depowner_memphis"),
            get_role_id("depowner_phoenix"),
            get_role_id("owner"),
            get_role_id("chief_moderator"),
        }
    )


def _user_can_review_server(member: discord.Member, game_server: str) -> bool:
    if not isinstance(member, discord.Member):
        return False
    roles = {role.id for role in member.roles}
    if roles & {get_role_id("owner"), get_role_id("chief_moderator")}:
        return True
    server_role_keys = {
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
    }
    return bool(roles & {get_role_id(key) for key in server_role_keys.get(game_server, ())})


def _app_to_dict(app) -> dict:
    return {
        "id": app.id,
        "discord_user_id": app.discord_user_id,
        "discord_username": app.discord_username,
        "character_name": app.character_name,
        "static_id": app.static_id,
        "ooc_age": app.ooc_age,
        "join_goal": app.join_goal,
        "how_found": app.how_found,
        "game_server": app.game_server.value if hasattr(app.game_server, "value") else app.game_server,
        "screenshot_url": app.screenshot_url,
        "status": app.status.value if hasattr(app.status, "value") else app.status,
        "rejection_reason": app.rejection_reason,
        # Include reviewer info so DM embeds can mention the recruiter who acted
        "reviewed_by": getattr(app, "reviewed_by", None),
        "reviewed_by_id": getattr(app, "reviewed_by_id", None),
    }


def _dict_to_embed(data: dict) -> discord.Embed:
    embed = discord.Embed(
        title=data.get("title"),
        description=data.get("description"),
        color=data.get("color"),
    )
    for field in data.get("fields", []):
        embed.add_field(name=field["name"], value=field["value"], inline=field.get("inline", False))
    if image := data.get("image"):
        embed.set_image(url=image["url"])
    if footer := data.get("footer"):
        embed.set_footer(text=footer["text"])
    if timestamp := data.get("timestamp"):
        embed.timestamp = discord.utils.parse_time(timestamp)
    return embed


def _build_review_embed(app: dict) -> discord.Embed:
    return _dict_to_embed(build_review_embed_data(app))


def _is_valid_screenshot_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


# ── Welcome message + «Подать заявку» button ───────────────────

class WelcomeApplyButton(SafeView):
    """Кнопка «Подать заявку», закреплённая в канале заявок."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Подать заявку",
        style=discord.ButtonStyle.primary,
        emoji="📝",
        custom_id="welcome:apply",
    )
    async def _apply(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message(
            "Выберите игровой сервер, для которого подаёте заявку:",
            view=ServerSelectView(),
            ephemeral=True,
        )


def build_welcome_embed(game_server: str) -> discord.Embed:
    color = 0x5865F2
    embed = discord.Embed(
        title="👋 ПУТЬ В СЕМЬЮ НАЧИНАЕТСЯ ЗДЕСЬ!",
        description=(
            "Нажмите кнопку **📝 Подать заявку**, выберите сервер и заполните форму.\n\n"
            "📋 Обычно заявки обрабатываются в течение **1–3 дней** — "
            "срок зависит от загрузки рекрутеров.\n\n"
            "**В форме потребуется указать:**\n"
            "• игровое имя, фамилию и Static ID\n"
            "• OOC-возраст и цель вступления\n"
            "• как вы узнали о семье\n"
            "• ссылку на скриншот персонажа\n\n"
            "Выберите правильный сервер: **🌴 Memphis** или **🔥 Phoenix**.\n"
            "После отправки заявка попадёт рекрутерам, а результат придёт в личные сообщения."
        ),
        color=color,
    )
    embed.add_field(
        name="🌴 Memphis",
        value="Выберите Memphis в форме, если ваш персонаж играет на этом сервере.",
        inline=False,
    )
    embed.add_field(
        name="🔥 Phoenix",
        value="Выберите Phoenix в форме, если ваш персонаж играет на этом сервере.",
        inline=False,
    )
    embed.set_footer(text="Londo Family • единый канал заявок")
    embed.timestamp = discord.utils.utcnow()
    return embed


def build_promotion_info_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📈 Londo — Иерархия",
        description=(
            "Система рангов и должностей семьи Londo.\n\n"
            "**Основные ранги** — путь развития внутри семьи.\n"
            "**Должности** — дополнительные роли по желанию и доверию.\n\n"
            "**[1] Newbie**\n◇ Вступить в семью.\n\n"
            "**[2] Baby Londo**\n◇ Сменить фамилию на Londo.\n\n"
            "**[3] Young Londo**\n◇ Пробыть неделю в семье.\n\n"
            "**[4] Londo**\n◇ Пробыть месяц в семье и выполнять контракты.\n\n"
            "**[5] Main**\n◇ По решению старшего состава.\n\n"
            "**[6] Londest Londo**\n◇ Ранг можно купить за **300 монет в магазине**.\n"
            "◇ Также можно пополнить счёт семьи на 350.000$ и предоставить доказательство.\n\n"
            "**[7] Recruit**\n◇ Пройти обзвон и согласовать со старшим составом.\n\n"
            "**[8] High Staff**\n◇ По решению Owner и Dep Owner.\n\n"
            "Подать запрос на повышение или роль можно в канале <#1539525309596966912>."
        ),
        color=0xF2B84B,
    )
    embed.set_footer(text="Londo Family • система развития")
    embed.timestamp = discord.utils.utcnow()
    return embed


def build_promotion_request_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📈 Запрос на повышение",
        description=(
            "Выберите нужный пункт в меню и отправьте короткую заявку.\n\n"
            "**Что можно запросить:**\n"
            "• Повышение до Young Londo\n"
            "• Повышение до Baby Londo\n"
            "• Повышение до Main\n"
            "• Получение роли Recruit\n\n"
            "В форме потребуется ссылка на доказательство того, что условия повышения выполнены.\n"
            "Полная система рангов опубликована в информационном канале."
        ),
        color=0x5865F2,
    )
    embed.set_footer(text="Londo Family • запросы рассматриваются на сайте")
    return embed


class PromotionApplyButton(SafeView):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Подать запрос",
        style=discord.ButtonStyle.primary,
        emoji="📈",
        custom_id="promotion:apply",
    )
    async def _apply(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message(
            "Выберите, что хотите запросить:",
            view=PromotionTargetView(),
            ephemeral=True,
        )


class PromotionTargetView(SafeView):
    def __init__(self):
        super().__init__(timeout=600)
        labels = {
            "young_londo": "Повышение до Young Londo",
            "baby_londo": "Повышение до Baby Londo",
            "main": "Повышение до Main",
            "recruit": "Стать Recruit",
        }
        select = discord.ui.Select(
            placeholder="Выберите цель запроса...",
            options=[discord.SelectOption(label=label, value=value) for value, label in labels.items()],
            custom_id="promotion:target",
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        target = interaction.data["values"][0]
        await interaction.response.send_modal(PromotionModal(target))


class PromotionModal(SafeModal, title="Запрос на повышение"):
    def __init__(self, target: str):
        super().__init__()
        self.target = target
        self.character_name = discord.ui.TextInput(
            label="Игровой никнейм на сервере",
            placeholder="Имя Фамилия",
            max_length=128,
            required=True,
        )
        self.evidence_url = discord.ui.TextInput(
            label="Ссылка на доказательство",
            placeholder="https://imgur.com/... или ссылка на подтверждение",
            max_length=500,
            required=True,
        )
        self.add_item(self.character_name)
        self.add_item(self.evidence_url)

    async def on_submit(self, interaction: discord.Interaction):
        evidence_url = self.evidence_url.value.strip()
        character_name = self.character_name.value.strip()
        if not character_name:
            await interaction.response.send_message(
                "❌ Укажите игровой никнейм на выбранном сервере.",
                ephemeral=True,
            )
            return
        if not _is_valid_screenshot_url(evidence_url):
            await interaction.response.send_message(
                "❌ Укажите корректную ссылку, начинающуюся с http:// или https://.",
                ephemeral=True,
            )
            return
        member_roles = {role.id for role in getattr(interaction.user, "roles", [])}
        matching_servers = [
            server for server, role_ids in config["discord"].get("server_access_roles", {}).items()
            if member_roles & set(role_ids)
        ]
        if len(matching_servers) != 1:
            await interaction.response.send_message(
                "❌ Не удалось определить сервер по вашей роли. Убедитесь, что у вас есть ровно одна серверная роль Memphis или Phoenix.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        try:
            request = await _post_promotion_to_site(
                PromotionCreate(
                    discord_user_id=str(interaction.user.id),
                    discord_username=str(interaction.user),
                    character_name=character_name,
                    game_server=matching_servers[0],
                    target=self.target,
                    evidence_url=evidence_url,
                )
            )
        except ApplicationRequestError:
            await interaction.followup.send(
                "⚠️ Не удалось отправить запрос сейчас. Проверьте данные и попробуйте позже.",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            f"✅ Запрос на повышение **#{request['id']}** отправлен на сайт.", ephemeral=True
        )


async def post_promotion_info(channel, *, request_channel: bool = False) -> discord.Message | None:
    embed = build_promotion_request_embed() if request_channel else build_promotion_info_embed()
    try:
        async for message in channel.history(limit=50):
            if message.author.id != channel.guild.me.id:
                continue
            has_button = any(
                getattr(comp, "custom_id", None) == "promotion:apply"
                for row in message.components
                for comp in row.children
            )
            is_info_embed = bool(message.embeds and message.embeds[0].title == "📈 Londo — Иерархия")
            if has_button or is_info_embed:
                if request_channel:
                    await message.edit(embed=embed, view=PromotionApplyButton())
                else:
                    await message.edit(embed=embed, view=None)
                return message
    except (discord.Forbidden, discord.NotFound):
        return None
    return await channel.send(embed=embed, view=PromotionApplyButton() if request_channel else None)


async def post_welcome_message(channel, game_server: str) -> discord.Message | None:
    """Публикует или обновляет welcome-сообщение нужного сервера."""
    try:
        async for message in channel.history(limit=50):
            if message.author.id != channel.guild.me.id:
                continue
            for row in message.components:
                for comp in row.children:
                    if getattr(comp, "custom_id", None) == "welcome:apply":
                        await message.edit(
                            embed=build_welcome_embed(game_server),
                            view=WelcomeApplyButton(),
                        )
                        return message
    except (discord.Forbidden, discord.NotFound):
        return None

    return await channel.send(
        embed=build_welcome_embed(game_server),
        view=WelcomeApplyButton(),
    )


# ── Server selection → Modal ───────────────────────────────────

class ServerSelectView(SafeView):
    def __init__(self):
        super().__init__(timeout=600)
        servers = config["servers"]
        options = [
            discord.SelectOption(
                label=servers["memphis"]["name"],
                value="memphis",
                emoji=servers["memphis"]["emoji"],
                description="Подать заявку на Memphis",
            ),
            discord.SelectOption(
                label=servers["phoenix"]["name"],
                value="phoenix",
                emoji=servers["phoenix"]["emoji"],
                description="Подать заявку на Phoenix",
            ),
        ]
        select = discord.ui.Select(
            placeholder="Выберите сервер...",
            options=options,
            custom_id="server_select",
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        try:
            server = interaction.data["values"][0]
            if server not in config["servers"]:
                raise ValueError("unknown server")
            await interaction.response.send_modal(ApplicationModal(server))
        except (KeyError, IndexError, ValueError):
            await interaction.response.send_message(
                "❌ Не удалось определить сервер. Нажмите кнопку подачи заявки ещё раз.",
                ephemeral=True,
            )
        except discord.HTTPException:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ Discord не смог открыть форму. Нажмите кнопку и попробуйте ещё раз.",
                    ephemeral=True,
                )


class ApplicationModal(SafeModal, title="Заявка в семью Londo"):
    def __init__(self, game_server: str):
        super().__init__()
        self.game_server = game_server
        server_name = config["servers"][game_server]["name"]

        self.character_name = discord.ui.TextInput(
            label="Игровое имя и фамилия",
            placeholder="John Smith",
            max_length=256,
            required=True,
        )
        self.static_id = discord.ui.TextInput(
            label="Static ID",
            placeholder="12345",
            max_length=64,
            required=True,
        )
        self.ooc_age = discord.ui.TextInput(
            label="Ваш OOC возраст",
            placeholder="18",
            max_length=3,
            required=True,
        )
        self.application_details = discord.ui.TextInput(
            label="Цель вступления и как узнали о семье",
            style=discord.TextStyle.paragraph,
            placeholder="Цель: хочу вступить, потому что...\nКак узнал: Discord / друзья / реклама...",
            max_length=1000,
            required=True,
        )
        self.screenshot_url = discord.ui.TextInput(
            label="Ссылка на скриншот персонажа",
            placeholder="https://imgur.com/abc123 или https://i.imgur.com/abc.png",
            max_length=500,
            required=False,
        )

        self.add_item(self.character_name)
        self.add_item(self.static_id)
        self.add_item(self.ooc_age)
        self.add_item(self.application_details)
        self.add_item(self.screenshot_url)

        self._server_label = server_name

    async def on_submit(self, interaction: discord.Interaction):
        char_name = self.character_name.value.strip()
        static_id = self.static_id.value.strip()

        if not char_name:
            await interaction.response.send_message(
                "❌ Укажите игровое имя и фамилию.", ephemeral=True
            )
            return
        if not static_id:
            await interaction.response.send_message(
                "❌ Укажите Static ID отдельным значением.", ephemeral=True
            )
            return

        details = self.application_details.value.strip()
        join_goal = details
        how_found = "Не указано"
        for marker in ("Как узнал:", "Как узнали:"):
            if marker.lower() in details.lower():
                before, after = details.split(marker, 1)
                join_goal = before.replace("Цель:", "", 1).strip()
                how_found = after.strip() or "Не указано"
                break

        try:
            age = int(self.ooc_age.value.strip())
            if age < 1 or age > 99:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ Укажите корректный возраст (число от 1 до 99).", ephemeral=True
            )
            return

        screenshot_url = self.screenshot_url.value.strip() or "Не прикреплено"
        if screenshot_url != "Не прикреплено" and not _is_valid_screenshot_url(screenshot_url):
            await interaction.response.send_message(
                "❌ Вставьте корректную **ссылку** на скриншот (http:// или https://).\n"
                "Например: `https://imgur.com/...` или `https://i.imgur.com/....png`",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        app_data = ApplicationCreate(
            discord_user_id=str(interaction.user.id),
            discord_username=str(interaction.user),
            character_name=char_name,
            static_id=static_id,
            ooc_age=age,
            join_goal=join_goal,
            how_found=how_found,
            game_server=self.game_server,
            screenshot_url=screenshot_url,
        )

        try:
            app = await _post_application_to_site(app_data)
        except ApplicationRequestError:
            await interaction.followup.send(
                "⚠️ Не удалось отправить заявку сейчас. Проверьте данные и попробуйте позже.",
                ephemeral=True,
            )
            return

        from bot.notifications import build_submitted_embed, send_dm_notification

        embed = build_submitted_embed(app)
        await send_dm_notification(interaction.client, interaction.user.id, embed)

        server_emoji = config["servers"][self.game_server]["emoji"]
        await interaction.followup.send(
            f"✅ Заявка **#{app['id']}** отправлена на сервер {server_emoji} **{self._server_label}**!\n"
            "Заявка передана рекрутерам на сайт. Результат придёт в личные сообщения.",
            ephemeral=True,
        )


# ── Review buttons in Discord channel ──────────────────────────

class ReviewButtons(SafeView):
    def __init__(self, application_id: int):
        super().__init__(timeout=None)
        self.application_id = application_id

        approve_btn = discord.ui.Button(
            label="Одобрить",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id=f"review:approve:{application_id}",
        )
        approve_btn.callback = self._approve_callback
        self.add_item(approve_btn)

        callback_btn = discord.ui.Button(
            label="На обзвон",
            style=discord.ButtonStyle.primary,
            emoji="📞",
            custom_id=f"review:callback:{application_id}",
        )
        callback_btn.callback = self._callback_callback
        self.add_item(callback_btn)

        reject_btn = discord.ui.Button(
            label="Отклонить",
            style=discord.ButtonStyle.danger,
            emoji="❌",
            custom_id=f"review:reject:{application_id}",
        )
        reject_btn.callback = self._reject_callback
        self.add_item(reject_btn)

    async def _check_permissions(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        app = get_application(self.application_id)
        if not app or not _user_can_review_server(interaction.user, app.game_server.value):
            await interaction.response.send_message(
                "❌ У вас нет прав для рассмотрения заявок.", ephemeral=True
            )
            return False
        return True

    async def _approve_callback(self, interaction: discord.Interaction):
        if await self._check_permissions(interaction):
            await self._process(interaction, "approve")

    async def _callback_callback(self, interaction: discord.Interaction):
        if await self._check_permissions(interaction):
            await self._process(interaction, "callback")

    async def _reject_callback(self, interaction: discord.Interaction):
        if not await self._check_permissions(interaction):
            return
        view = RejectReasonView(self.application_id)
        await interaction.response.send_message(
            "Выберите причину отклонения:", view=view, ephemeral=True
        )

    async def _process(self, interaction: discord.Interaction, action: str):
        action_data = ApplicationAction(
            action=action,
            actor_name=interaction.user.display_name,
            actor_id=str(interaction.user.id),
            source="discord",
        )

        result = process_action(self.application_id, action_data)
        if not result:
            await interaction.response.send_message("❌ Заявка уже обработана.", ephemeral=True)
            return

        app_dict = _app_to_dict(result)
        await self._notify_user(interaction.client, interaction.guild, app_dict, action)
        await _update_review_message(interaction, self.application_id, action)

        status_labels = {"approve": "✅ Одобрена", "reject": "❌ Отклонена", "callback": "📞 На обзвон"}
        await interaction.response.send_message(
            f"{status_labels[action]} — пользователь уведомлён.", ephemeral=True
        )

    async def _notify_user(self, client, guild, app_dict: dict, action: str):
        from shared.notify import notify_user_about_application

        # Discord buttons and the web cabinet must have identical side effects.
        await notify_user_about_application(self.application_id)

    async def _create_callback_channels(self, guild, app_dict: dict) -> str | None:
        if not guild:
            return None
        user_id = int(app_dict["discord_user_id"])
        app_id = app_dict["id"]
        game_server = app_dict["game_server"]
        server_cfg = config["servers"].get(game_server, {})
        server_label = server_cfg.get("name", game_server)
        overwrites = [
            discord.PermissionOverwrite(view_channel=False, default_permission=False),
            discord.PermissionOverwrite(
                target=discord.Object(id=user_id),
                view_channel=True,
                connect=True,
            ),
            discord.PermissionOverwrite(
                target=discord.Object(id=guild.id),
                view_channel=False,
            ),
        ]

        # Find or create "Обзвоны" category
        category = discord.utils.get(guild.categories, name="Обзвоны")
        if not category:
            category = await guild.create_category_channel("Обзвоны")

        text_channel = await guild.create_text_channel(
            name=f"обзвон-{app_id}",
            topic=f"Обзвон заявки #{app_id} — {server_label}",
            category=category,
            overwrites=overwrites,
        )

        voice_channel = await guild.create_voice_channel(
            name=f"🎙 Обзвон-{app_id}",
            category=category,
            overwrites=overwrites,
        )

        server_emoji = server_cfg.get("emoji", "")
        await text_channel.send(
            f"👋 <@{user_id}>, вас пригласили на обзвон!\n"
            f"Заявка **#{app_id}** на сервере {server_emoji} **{server_label}**.\n\n"
            f"Рекрут свяжется с вами в ближайшее время."
        )

        return f"<#{text_channel.id}>"


class RejectReasonView(SafeView):
    def __init__(self, application_id: int):
        super().__init__(timeout=120)
        self.application_id = application_id
        reasons = config["rejection_reasons"]
        options = [
            discord.SelectOption(label=r["label"], value=r["id"]) for r in reasons
        ]
        select = discord.ui.Select(
            placeholder="Причина отклонения...",
            options=options,
            custom_id=f"reject_reason:{application_id}",
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        reason_id = interaction.data["values"][0]
        if reason_id == "other":
            await interaction.response.send_modal(CustomRejectModal(self.application_id))
            return
        await self._reject(interaction, reason_id, None)

    async def _reject(
        self,
        interaction: discord.Interaction,
        reason_id: str,
        custom_reason: str | None,
    ):
        action_data = ApplicationAction(
            action="reject",
            actor_name=interaction.user.display_name,
            actor_id=str(interaction.user.id),
            rejection_reason_id=reason_id,
            custom_reason=custom_reason,
            source="discord",
        )
        result = process_action(self.application_id, action_data)
        if not result:
            await interaction.response.send_message("❌ Заявка уже обработана.", ephemeral=True)
            return

        app_dict = _app_to_dict(result)
        from bot.notifications import build_rejected_embed, send_dm_notification

        embed = build_rejected_embed(app_dict)
        await send_dm_notification(interaction.client, int(app_dict["discord_user_id"]), embed)
        await _update_review_message(interaction, self.application_id, "reject")
        await interaction.response.edit_message(content="✅ Заявка отклонена.", view=None)


class CustomRejectModal(SafeModal, title="Своя причина отклонения"):
    def __init__(self, application_id: int):
        super().__init__()
        self.application_id = application_id
        self.custom_reason = discord.ui.TextInput(
            label="Укажите причину",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=500,
        )
        self.add_item(self.custom_reason)

    async def on_submit(self, interaction: discord.Interaction):
        action_data = ApplicationAction(
            action="reject",
            actor_name=interaction.user.display_name,
            actor_id=str(interaction.user.id),
            rejection_reason_id="other",
            custom_reason=self.custom_reason.value,
            source="discord",
        )
        result = process_action(self.application_id, action_data)
        if not result:
            await interaction.response.send_message("❌ Заявка уже обработана.", ephemeral=True)
            return

        app_dict = _app_to_dict(result)
        from bot.notifications import build_rejected_embed, send_dm_notification

        embed = build_rejected_embed(app_dict)
        await send_dm_notification(interaction.client, int(app_dict["discord_user_id"]), embed)
        await _update_review_message(interaction, self.application_id, "reject")
        await interaction.response.send_message("✅ Заявка отклонена.", ephemeral=True)


async def _update_review_message(interaction: discord.Interaction, app_id: int, action: str):
    from shared.services import get_application

    app = get_application(app_id)
    if not app or not app.discord_message_id:
        return

    channel_id = int(app.discord_channel_id) if app.discord_channel_id else get_review_channel_id(
        app.game_server.value
    )
    channel = interaction.client.get_channel(channel_id)
    if channel is None and interaction.guild:
        channel = interaction.guild.get_channel(channel_id)
    if not channel:
        return

    try:
        msg = await channel.fetch_message(int(app.discord_message_id))
    except discord.NotFound:
        return

    app_dict = _app_to_dict(app)
    status_map = {"approve": "approved", "reject": "rejected", "callback": "callback"}
    embed = _dict_to_embed(
        build_review_embed_data(
            app_dict,
            status=status_map.get(action, action),
            reviewer=str(interaction.user),
        )
    )

    view = ReviewButtons(app_id)
    for item in view.children:
        item.disabled = True
    await msg.edit(embed=embed, view=view)

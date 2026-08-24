from __future__ import annotations

import traceback

import discord
from discord import app_commands
from discord.ext import commands

from bot.views import (
    ReviewButtons,
    ServerSelectView,
    WelcomeApplyButton,
    post_welcome_message,
    PromotionApplyButton,
    post_promotion_info,
)
from datetime import datetime, timezone
from shared.config import get_config, load_config, validate_review_channels
from shared.models import init_db
from shared.services import (
    get_application_by_callback_voice,
    list_applications,
    update_callback_voice_state,
)
from shared.services import log_bot_error

config = get_config()


class LondoBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        init_db()
        pending_apps = list_applications(status="pending")
        for app in pending_apps:
            view = ReviewButtons(app.id)
            if app.discord_message_id:
                self.add_view(view, message_id=int(app.discord_message_id))
            else:
                self.add_view(view)
        # Персистентная кнопка «Подать заявку» на всех welcome-сообщениях
        self.add_view(WelcomeApplyButton())
        self.add_view(PromotionApplyButton())

        guild_id = config["discord"].get("guild_id") or 0
        if not guild_id:
            print("⚠️ DISCORD_GUILD_ID не задан — пропускаю синхронизацию slash-команд.")
            return

        guild = discord.Object(id=guild_id)
        self.tree.copy_global_to(guild=guild)
        try:
            await self.tree.sync(guild=guild)
        except discord.Forbidden as exc:
            print(
                "⚠️ Не удалось синхронизировать slash-команды в guild "
                f"{guild_id}: {exc}"
            )
            print(
                "Проверьте, что бот добавлен на сервер и приглашён с правами "
                "'applications.commands' / 'Use Application Commands'."
            )
        except discord.HTTPException as exc:
            print(f"⚠️ Ошибка синхронизации slash-команд для guild {guild_id}: {exc}")

    async def on_ready(self):
        print(f"Bot logged in as {self.user} (ID: {self.user.id})")
        print(f"Connected to {len(self.guilds)} guild(s)")
        for issue in validate_review_channels():
            print(f"⚠️ Конфигурация каналов заявок: {issue}")
        await self._publish_welcome_messages()
        await self._publish_promotion_message()

    async def on_error(self, event_method, *args, **kwargs):
        details = traceback.format_exc()
        log_bot_error(
            event_name=event_method,
            message="Внутренняя ошибка обработчика Discord-события.",
            technical_details=details,
        )

    async def on_app_command_error(self, interaction, error):
        log_bot_error(
            event_name="app_command",
            message="Ошибка выполнения команды Discord.",
            technical_details=repr(error),
            discord_user_id=str(interaction.user.id),
        )
        message = "⚠️ Не удалось выполнить команду. Попробуйте ещё раз позже."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def _publish_promotion_message(self):
        channels = (
            (config["discord"].get("promotion_info_channel_id"), "информации о повышениях"),
            (config["discord"].get("promotion_request_channel_id"), "запросов на повышение"),
        )
        for index, (channel_id, label) in enumerate(channels):
            if not channel_id:
                continue
            channel = self.get_channel(int(channel_id))
            if not channel:
                print(f"⚠️ Канал {label} не найден: {channel_id}")
                continue
            try:
                await post_promotion_info(channel, request_channel=index == 1)
                print(f"✅ Сообщение {label} готово в #{channel.name}")
            except discord.Forbidden:
                print(f"❌ Нет прав писать в канал {label} #{channel.name}")

    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return
        before_id = before.channel.id if before.channel else None
        after_id = after.channel.id if after.channel else None
        if before_id == after_id:
            return

        app = None
        if before_id:
            app = get_application_by_callback_voice(before_id)
            if app and str(member.id) == app.discord_user_id and app.callback_started_at:
                started_at = app.callback_started_at
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
                elapsed = max(
                    0,
                    int((datetime.now(timezone.utc) - started_at).total_seconds()),
                )
                update_callback_voice_state(
                    app.id,
                    clear_started_at=True,
                    duration_seconds=app.callback_duration_seconds + elapsed,
                )
        if after_id:
            app = get_application_by_callback_voice(after_id)
            if app and str(member.id) == app.discord_user_id:
                update_callback_voice_state(
                    app.id,
                    started_at=datetime.now(timezone.utc),
                )

    async def _publish_welcome_messages(self):
        """Публикует красивое сообщение с кнопкой «Подать заявку» в каждом канале заявок."""
        review_channels = config["discord"]["review_channels"]
        auto_post = config["discord"].get("auto_post_welcome", True)
        if not auto_post:
            return

        for guild in self.guilds:
            if guild.id != config["discord"]["guild_id"]:
                continue
            seen_channel_ids = set()
            shared_channel = bool(config["discord"].get("shared_review_channel"))
            for game_server in ("memphis", "phoenix"):
                channel_id = review_channels.get(game_server)
                if not channel_id or int(channel_id) in seen_channel_ids:
                    continue
                seen_channel_ids.add(int(channel_id))
                channel = guild.get_channel(int(channel_id))
                if channel is None:
                    print(
                        f"⚠️ Канал {channel_id} для сервера {game_server} не найден "
                        f"(проверьте DISCORD_REVIEW_CHANNEL_{game_server.upper()} в ENV)."
                    )
                    continue
                try:
                    await post_welcome_message(channel, "all" if shared_channel else game_server)
                    label = "Memphis + Phoenix" if shared_channel else game_server
                    print(f"✅ Welcome-сообщение готово в #{channel.name} ({label})")
                except discord.Forbidden:
                    print(f"❌ Нет прав писать в канал #{channel.name} ({game_server}).")
                except discord.HTTPException as exc:
                    print(f"⚠️ Ошибка при подготовке #{channel.name}: {exc}")
            break

    async def _setup_review_channels(self, interaction: discord.Interaction) -> None:
        """Устанавливает welcome-сообщение с кнопкой во все review-каналы."""
        review_channels = config["discord"]["review_channels"]
        seen_channel_ids = set()
        shared_channel = bool(config["discord"].get("shared_review_channel"))
        messages = []
        for game_server in ("memphis", "phoenix"):
            channel_id = review_channels.get(game_server)
            if not channel_id or int(channel_id) in seen_channel_ids:
                continue
            seen_channel_ids.add(int(channel_id))
            channel = interaction.guild.get_channel(int(channel_id))
            if channel is None:
                messages.append(f"⚠️ {game_server}: канал не найден (ID {channel_id})")
                continue
            try:
                msg = await post_welcome_message(channel, "all" if shared_channel else game_server)
                if msg:
                    messages.append(f"✅ {game_server}: готово в #{channel.name}")
                else:
                    messages.append(f"ℹ️ {game_server}: сообщение уже было в #{channel.name}")
            except discord.Forbidden:
                messages.append(f"❌ {game_server}: нет прав писать в #{channel.name}")
            except discord.HTTPException as exc:
                messages.append(f"⚠️ {game_server}: ошибка — {exc}")

        await interaction.response.send_message("\n".join(messages) or "Готово.", ephemeral=True)


bot = LondoBot()


@bot.tree.command(
    name=config["discord"]["application_command"],
    description="Подать заявку в семью Londo",
)
async def application_command(interaction: discord.Interaction):
    view = ServerSelectView()
    await interaction.response.send_message(
        "Выберите сервер для подачи заявки:",
        view=view,
        ephemeral=True,
    )


@bot.tree.command(name="setup-заявки", description="Разместить сообщение с кнопкой «Подать заявку» в каналах")
async def setup_review_command(interaction: discord.Interaction):
    await bot._setup_review_channels(interaction)


def run_bot():
    load_config()
    bot.run(config["discord"]["token"])


if __name__ == "__main__":
    run_bot()

"""
Cog: Temporary Voice Channels (Join-to-Create Voice Hub)
Features:
- Instant temporary private voice channel creation on joining Hub.
- Automatic channel owner management & permissions.
- In-channel Interactive Discord UI Buttons (Lock/Unlock, Limit, Rename, Kick).
- Zero-resource cleanup: automatically deletes voice channel when 0 members remain.
"""
import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone
import config
from database import (
    async_get_guild_settings, async_is_module_enabled,
    async_get_tempvoice_settings, async_add_active_temp_channel,
    async_remove_active_temp_channel, async_get_active_temp_channel,
    async_update_temp_channel_lock
)
from i18n import tr
try:
    from emojis import e, partial, embed_title, clean_title
except (ImportError, ModuleNotFoundError):
    from bot.emojis import e, partial, embed_title, clean_title



class RenameVoiceModal(discord.ui.Modal):
    def __init__(self, channel: discord.VoiceChannel, settings: dict):
        super().__init__(title=tr(settings, "tempvoice.modal_rename_title"))
        self.channel = channel
        self.settings = settings
        self.new_name = discord.ui.TextInput(
            label=tr(settings, "tempvoice.modal_rename_label"),
            placeholder=tr(settings, "tempvoice.modal_rename_placeholder"),
            min_length=1,
            max_length=50,
            required=True
        )
        self.add_item(self.new_name)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await self.channel.edit(name=self.new_name.value)
            await interaction.response.send_message(
                tr(self.settings, "tempvoice.renamed_success", name=self.new_name.value),
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Lỗi: {e}", ephemeral=True)


class LimitVoiceModal(discord.ui.Modal):
    def __init__(self, channel: discord.VoiceChannel, settings: dict):
        super().__init__(title=tr(settings, "tempvoice.modal_limit_title"))
        self.channel = channel
        self.settings = settings
        self.limit_input = discord.ui.TextInput(
            label=tr(settings, "tempvoice.modal_limit_label"),
            placeholder="0 = Không giới hạn (1-99)",
            min_length=1,
            max_length=2,
            required=True
        )
        self.add_item(self.limit_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.limit_input.value)
            if val < 0 or val > 99:
                await interaction.response.send_message(tr(self.settings, "tempvoice.invalid_limit"), ephemeral=True)
                return
            await self.channel.edit(user_limit=val)
            await interaction.response.send_message(
                tr(self.settings, "tempvoice.limit_success", limit=val if val > 0 else "∞"),
                ephemeral=True
            )
        except ValueError:
            await interaction.response.send_message(tr(self.settings, "tempvoice.invalid_number"), ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)


class TempVoiceControlView(discord.ui.View):
    """Bảng điều khiển kênh voice tạm — view bền vững (persistent), không giữ state.

    Trước đây view giữ `channel`/`owner` trong instance và KHÔNG được đăng ký với
    `bot.add_view`, nên sau mỗi lần restart (kể cả watchdog tự restart khi mất mạng)
    các nút trên bảng điều khiển trở thành "interaction failed".

    Giờ kênh + chủ phòng được tra từ DB theo người bấm, nhờ vậy nút sống qua restart.
    """

    def __init__(self):
        super().__init__(timeout=None)

    @staticmethod
    async def _resolve(interaction: discord.Interaction):
        """Trả về (channel, owner_id, settings); channel=None nếu không hợp lệ."""
        settings = await async_get_guild_settings(str(interaction.guild.id)) if interaction.guild else {}

        channel = None
        voice_state = getattr(interaction.user, "voice", None)
        if voice_state and voice_state.channel:
            channel = voice_state.channel
        elif isinstance(interaction.channel, discord.VoiceChannel):
            channel = interaction.channel

        if channel is None:
            await interaction.response.send_message(
                tr(settings, "tempvoice.must_be_in_voice"), ephemeral=True
            )
            return None, None, settings

        active = await async_get_active_temp_channel(str(channel.id))
        if not active:
            await interaction.response.send_message(
                tr(settings, "tempvoice.not_owner"), ephemeral=True
            )
            return None, None, settings

        return channel, str(active.get("owner_id") or ""), settings

    async def _authorize(self, interaction: discord.Interaction, owner_id: str, settings: dict) -> bool:
        """Chỉ chủ phòng (hoặc Admin) được dùng nút."""
        if owner_id == str(interaction.user.id):
            return True
        perms = getattr(interaction.user, "guild_permissions", None)
        if perms and perms.administrator:
            return True
        await interaction.response.send_message(
            tr(settings, "tempvoice.not_owner"), ephemeral=True
        )
        return False

    def _localize(self, settings: dict):
        """Gán nhãn nút theo ngôn ngữ server tại thời điểm bấm."""
        self.toggle_lock.label = tr(settings, "tempvoice.btn_lock_toggle")
        self.set_limit.label = tr(settings, "tempvoice.btn_limit")
        self.rename.label = tr(settings, "tempvoice.btn_rename")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True  # phân quyền chi tiết trong từng nút (theo DB, không theo state)

    @discord.ui.button(label="Lock / Unlock", style=discord.ButtonStyle.primary, emoji=partial("zb_lock", "🔒"), custom_id="tv_lock")
    async def toggle_lock(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel, owner_id, s = await self._resolve(interaction)
        if channel is None:
            return
        if not await self._authorize(interaction, owner_id, s):
            return

        guild = channel.guild
        owner = guild.get_member(int(owner_id)) if owner_id.isdigit() else None

        overwrites = channel.overwrites_for(guild.default_role)
        is_currently_locked = (overwrites.connect is False)

        new_lock = not is_currently_locked
        overwrites.connect = None if not new_lock else False
        await channel.set_permissions(guild.default_role, overwrite=overwrites)

        # Luôn cho phép owner kết nối (kể cả sau restart, owner lấy từ DB)
        if owner is not None:
            owner_ov = channel.overwrites_for(owner)
            owner_ov.connect = True
            await channel.set_permissions(owner, overwrite=owner_ov)

        await async_update_temp_channel_lock(str(channel.id), 1 if new_lock else 0)

        self._localize(s)
        msg = tr(s, "tempvoice.locked") if new_lock else tr(s, "tempvoice.unlocked")
        button.emoji = "🔓" if new_lock else partial("zb_lock", "🔒")
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="Limit", style=discord.ButtonStyle.secondary, emoji="👥", custom_id="tv_limit")
    async def set_limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel, owner_id, s = await self._resolve(interaction)
        if channel is None:
            return
        if not await self._authorize(interaction, owner_id, s):
            return
        await interaction.response.send_modal(LimitVoiceModal(channel, s))

    @discord.ui.button(label="Rename", style=discord.ButtonStyle.secondary, emoji="✏️", custom_id="tv_rename")
    async def rename(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel, owner_id, s = await self._resolve(interaction)
        if channel is None:
            return
        if not await self._authorize(interaction, owner_id, s):
            return
        await interaction.response.send_modal(RenameVoiceModal(channel, s))


class TempVoice(commands.Cog):
    """Module quản lý Kênh Voice Tạm Thời (Join-to-Create Voice Hub)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._creating_lock = set()

    async def cog_check(self, ctx: commands.Context) -> bool:
        if not ctx.guild:
            return False
        return await async_is_module_enabled(str(ctx.guild.id), "tempvoice")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot or not member.guild:
            return

        guild = member.guild
        if not await async_is_module_enabled(str(guild.id), "tempvoice"):
            return

        tv_settings = await async_get_tempvoice_settings(str(guild.id))
        if not tv_settings.get("enabled"):
            return

        hub_id = tv_settings.get("hub_channel_id")

        # 1. Thành viên vào kênh Hub -> Tạo kênh voice tạm
        if after.channel and str(after.channel.id) == hub_id and member.id not in self._creating_lock:
            self._creating_lock.add(member.id)
            try:
                cat_id = tv_settings.get("category_id")
                category = guild.get_channel(int(cat_id)) if cat_id and cat_id.isdigit() else after.channel.category
                
                template = tv_settings.get("name_template") or "🔊 Phòng của {user}"
                ch_name = template.replace("{user}", member.display_name).replace("{user_name}", member.name)
                limit = tv_settings.get("default_limit", 0)

                # Overwrites ban đầu
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(connect=True, speak=True),
                    member: discord.PermissionOverwrite(connect=True, speak=True, manage_channels=True, move_members=True)
                }

                new_voice = await guild.create_voice_channel(
                    name=ch_name,
                    category=category,
                    user_limit=limit,
                    overwrites=overwrites,
                    reason=f"TempVoice: Tạo phòng riêng cho {member.display_name}"
                )

                await async_add_active_temp_channel(str(new_voice.id), str(guild.id), str(member.id))
                await member.move_to(new_voice)

                # Gửi bảng điều khiển nút bấm
                s = await async_get_guild_settings(str(guild.id))
                embed = discord.Embed(
                    title=embed_title("zb_tempvoice", tr(s, "tempvoice.panel_title", name=new_voice.name)),
                    description=tr(s, "tempvoice.panel_desc", user=member.mention),
                    color=0x5865F2,
                    timestamp=datetime.now(timezone.utc)
                )
                embed.set_footer(text=tr(s, "tempvoice.panel_footer"))
                view = TempVoiceControlView()
                view._localize(s)
                try:
                    await new_voice.send(embed=embed, view=view)
                except Exception:
                    pass

            except Exception as e:
                print(f"[TempVoice] Error creating voice channel: {e}")
            finally:
                self._creating_lock.discard(member.id)

        # 2. Thành viên rời kênh voice tạm -> Nếu 0 người thì xóa kênh
        if before.channel and before.channel != after.channel:
            active_info = await async_get_active_temp_channel(str(before.channel.id))
            if active_info:
                # Kiểm tra số lượng thành viên thực tế còn lại trong voice
                if len(before.channel.members) == 0:
                    try:
                        await async_remove_active_temp_channel(str(before.channel.id))
                        await before.channel.delete(reason="TempVoice: Không còn thành viên trong phòng")
                    except Exception as e:
                        print(f"[TempVoice] Error deleting empty voice channel: {e}")

    # ─── Slash Commands for TempVoice ──────────────────────────────────────────
    voice_group = app_commands.Group(name="voice", description="Lệnh điều khiển phòng Voice cá nhân")

    @voice_group.command(name="lock", description="Khóa phòng voice (chỉ người được mời mới vào được)")
    async def voice_lock(self, interaction: discord.Interaction):
        s = await async_get_guild_settings(str(interaction.guild.id))
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(tr(s, "tempvoice.must_be_in_voice"), ephemeral=True)
            return
        ch = interaction.user.voice.channel
        active = await async_get_active_temp_channel(str(ch.id))
        if not active or (active["owner_id"] != str(interaction.user.id) and not interaction.user.guild_permissions.administrator):
            await interaction.response.send_message(tr(s, "tempvoice.not_owner"), ephemeral=True)
            return

        overwrites = ch.overwrites_for(interaction.guild.default_role)
        overwrites.connect = False
        await ch.set_permissions(interaction.guild.default_role, overwrite=overwrites)
        await async_update_temp_channel_lock(str(ch.id), 1)
        await interaction.response.send_message(tr(s, "tempvoice.locked"), ephemeral=True)

    @voice_group.command(name="unlock", description="Mở khóa phòng voice cho mọi người tham gia")
    async def voice_unlock(self, interaction: discord.Interaction):
        s = await async_get_guild_settings(str(interaction.guild.id))
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(tr(s, "tempvoice.must_be_in_voice"), ephemeral=True)
            return
        ch = interaction.user.voice.channel
        active = await async_get_active_temp_channel(str(ch.id))
        if not active or (active["owner_id"] != str(interaction.user.id) and not interaction.user.guild_permissions.administrator):
            await interaction.response.send_message(tr(s, "tempvoice.not_owner"), ephemeral=True)
            return

        overwrites = ch.overwrites_for(interaction.guild.default_role)
        overwrites.connect = None
        await ch.set_permissions(interaction.guild.default_role, overwrite=overwrites)
        await async_update_temp_channel_lock(str(ch.id), 0)
        await interaction.response.send_message(tr(s, "tempvoice.unlocked"), ephemeral=True)

    @voice_group.command(name="limit", description="Giới hạn số người được vào phòng")
    @app_commands.describe(limit="Số lượng tối đa (0 = Không giới hạn, tối đa 99)")
    async def voice_limit(self, interaction: discord.Interaction, limit: int):
        s = await async_get_guild_settings(str(interaction.guild.id))
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(tr(s, "tempvoice.must_be_in_voice"), ephemeral=True)
            return
        if limit < 0 or limit > 99:
            await interaction.response.send_message(tr(s, "tempvoice.invalid_limit"), ephemeral=True)
            return
        ch = interaction.user.voice.channel
        active = await async_get_active_temp_channel(str(ch.id))
        if not active or (active["owner_id"] != str(interaction.user.id) and not interaction.user.guild_permissions.administrator):
            await interaction.response.send_message(tr(s, "tempvoice.not_owner"), ephemeral=True)
            return

        await ch.edit(user_limit=limit)
        await interaction.response.send_message(tr(s, "tempvoice.limit_success", limit=limit if limit > 0 else "∞"), ephemeral=True)

    @voice_group.command(name="rename", description="Đổi tên phòng voice của bạn")
    @app_commands.describe(name="Tên mới cho phòng voice")
    async def voice_rename(self, interaction: discord.Interaction, name: str):
        s = await async_get_guild_settings(str(interaction.guild.id))
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(tr(s, "tempvoice.must_be_in_voice"), ephemeral=True)
            return
        ch = interaction.user.voice.channel
        active = await async_get_active_temp_channel(str(ch.id))
        if not active or (active["owner_id"] != str(interaction.user.id) and not interaction.user.guild_permissions.administrator):
            await interaction.response.send_message(tr(s, "tempvoice.not_owner"), ephemeral=True)
            return

        await ch.edit(name=name[:50])
        await interaction.response.send_message(tr(s, "tempvoice.renamed_success", name=name[:50]), ephemeral=True)


async def setup(bot: commands.Bot):
    # Đăng ký view bền vững: bắt buộc để nút trên bảng điều khiển hoạt động sau
    # khi bot restart (discord.py định tuyến component theo custom_id đã đăng ký).
    bot.add_view(TempVoiceControlView())
    await bot.add_cog(TempVoice(bot))

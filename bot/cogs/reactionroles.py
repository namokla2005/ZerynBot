import discord
from discord.ext import commands
import database as db

class ReactionRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        # Ignore bots
        if payload.member and payload.member.bot:
            return

        # Check if reaction is in a guild
        if not payload.guild_id:
            return
            
        emoji_str = str(payload.emoji)
        
        # Check database for this reaction role
        role_id = await db.async_get_reaction_role_item(str(payload.message_id), emoji_str)
        if not role_id:
            return
            
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
            
        role = guild.get_role(int(role_id))
        if not role:
            return
            
        member = payload.member
        if not member:
            member = guild.get_member(payload.user_id)
            if not member:
                return
                
        try:
            await member.add_roles(role, reason="Reaction Role Add")
        except discord.Forbidden:
            print(f"Reaction Roles: Missing permissions to add role {role.name} in {guild.name}")
        except Exception as e:
            print(f"Reaction Roles: Failed to add role. {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        # Check if reaction is in a guild
        if not payload.guild_id:
            return
            
        emoji_str = str(payload.emoji)
        
        # Check database for this reaction role
        role_id = await db.async_get_reaction_role_item(str(payload.message_id), emoji_str)
        if not role_id:
            return
            
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
            
        role = guild.get_role(int(role_id))
        if not role:
            return
            
        member = guild.get_member(payload.user_id)
        if not member:
            return
            
        if member.bot:
            return
            
        try:
            await member.remove_roles(role, reason="Reaction Role Remove")
        except discord.Forbidden:
            print(f"Reaction Roles: Missing permissions to remove role {role.name} in {guild.name}")
        except Exception as e:
            print(f"Reaction Roles: Failed to remove role. {e}")

async def setup(bot):
    await bot.add_cog(ReactionRoles(bot))

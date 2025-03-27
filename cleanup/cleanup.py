import discord
from discord.ext import commands
from typing import Union
from datetime import datetime, timedelta

class Cleanup(commands.Cog):
    """Commands for cleaning up user messages and assigning punishment roles."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="clean", help="Delete messages from a user in a specific channel and assign 'muted' role.")
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    async def clean_user_channel(
        self,
        ctx,
        user: Union[discord.Member, discord.User] = None,
        channel: discord.TextChannel = None
    ):
        if not user or not channel:
            embed = discord.Embed(
                title="🧼 Clean Command Usage",
                description="Deletes messages from a user in a given channel and assigns the **muted** role.",
                color=discord.Color.orange()
            )
            embed.add_field(name="Usage", value="!clean <@user> <#channel>", inline=False)
            embed.add_field(name="Example", value="!clean @Troublemaker #general", inline=False)
            await ctx.send(embed=embed)
            return

        await ctx.send(f"⚔️ Starting cleanup for `{user}` in {channel.mention}...")

        cutoff = datetime.utcnow() - timedelta(days=14)
        deleted_count = 0

        try:
            async for msg in channel.history(limit=1000, after=cutoff):
                if msg.author.id == user.id:
                    try:
                        await msg.delete()
                        deleted_count += 1
                    except (discord.Forbidden, discord.HTTPException):
                        continue
        except discord.Forbidden:
            await ctx.send(f"❌ I don't have access to `{channel.name}`.")
            return

        await ctx.send(f"✅ Deleted `{deleted_count}` messages from `{user}` in {channel.mention} (last 14 days).")

        # Apply Prisoner role
        if isinstance(user, discord.Member):
            muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
            if not muted_role:
                try:
                    muted_role = await ctx.guild.create_role(name="Muted", reason="OPC punishment")
                    await ctx.send("🪓 Created 'Muted' role.")
                except discord.Forbidden:
                    await ctx.send("❌ I don't have permission to create roles.")
                    return

            try:
                await user.add_roles(muted_role, reason="Marked by OPC")
                await ctx.send(f"🚨 `{user.display_name}` has been imprisoned.")
            except discord.Forbidden:
                await ctx.send("❌ I don't have permission to assign the Muted role.")
        else:
            await ctx.send("⚠️ That user is not a member of this server. Skipping role assignment.")

async def setup(bot):
    await bot.add_cog(Cleanup(bot))

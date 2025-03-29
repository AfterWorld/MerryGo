import discord
from discord.ext import commands, tasks
from typing import Optional, Dict, List, Union, Any, Tuple
from datetime import datetime, timedelta
import asyncio
import time
import json
import os
from collections import deque
import logging

# Set up logging
logger = logging.getLogger('moderation')
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# Default config values
DEFAULT_WARNING_EXPIRY_DAYS = 30
DEFAULT_ACTION_THRESHOLDS = {
    "3": {"action": "mute", "duration": 30, "reason": "Exceeded 3 warning points"},
    "5": {"action": "timeout", "duration": 60, "reason": "Exceeded 5 warning points"},
    "10": {"action": "kick", "reason": "Exceeded 10 warning points"}
}

class GuildConfig:
    """Configuration manager for guild settings"""
    
    def __init__(self, bot):
        self.bot = bot
        self.config_dir = "moderation_config"
        self.ensure_config_dir()
        
    def ensure_config_dir(self):
        """Ensure the config directory exists"""
        if not os.path.exists(self.config_dir):
            os.makedirs(self.config_dir)
    
    def get_guild_config_path(self, guild_id: int) -> str:
        """Get the path to a guild's config file"""
        return os.path.join(self.config_dir, f"{guild_id}.json")
    
    async def get_guild_config(self, guild_id: int) -> dict:
        """Get a guild's configuration"""
        config_path = self.get_guild_config_path(guild_id)
        if not os.path.exists(config_path):
            # Create default config
            config = {
                "log_channel": None,
                "mute_role": None,
                "warning_expiry_days": DEFAULT_WARNING_EXPIRY_DAYS,
                "action_thresholds": DEFAULT_ACTION_THRESHOLDS,
                "members": {}
            }
            await self.save_guild_config(guild_id, config)
            return config
        
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading guild config for {guild_id}: {e}")
            return {
                "log_channel": None,
                "mute_role": None,
                "warning_expiry_days": DEFAULT_WARNING_EXPIRY_DAYS,
                "action_thresholds": DEFAULT_ACTION_THRESHOLDS,
                "members": {}
            }
    
    async def save_guild_config(self, guild_id: int, config: dict) -> None:
        """Save a guild's configuration"""
        config_path = self.get_guild_config_path(guild_id)
        try:
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving guild config for {guild_id}: {e}")
    
    async def get_member_data(self, guild_id: int, member_id: int) -> dict:
        """Get data for a specific member"""
        guild_config = await self.get_guild_config(guild_id)
        members_data = guild_config.get("members", {})
        
        # Initialize if not exists
        if str(member_id) not in members_data:
            members_data[str(member_id)] = {
                "warnings": [],
                "total_points": 0,
                "original_roles": [],
                "muted_until": None
            }
            guild_config["members"] = members_data
            await self.save_guild_config(guild_id, guild_config)
        
        return members_data[str(member_id)]
    
    async def update_member_data(self, guild_id: int, member_id: int, data: dict) -> None:
        """Update data for a specific member"""
        guild_config = await self.get_guild_config(guild_id)
        members_data = guild_config.get("members", {})
        members_data[str(member_id)] = data
        guild_config["members"] = members_data
        await self.save_guild_config(guild_id, guild_config)

class Moderation(commands.Cog):
    """Enhanced moderation cog with point-based warning system."""

    def __init__(self, bot):
        self.bot = bot
        self.config = GuildConfig(bot)
        
        # Rate limiting protection
        self.rate_limit = {
            "message_queue": {},  # Per-channel message queue
            "command_cooldown": {},  # Per-guild command cooldown
            "global_cooldown": deque(maxlen=10),  # Global command timestamps
        }
        
        # Start background tasks
        self.warning_cleanup_task.start()
        self.mute_check_task.start()
    
    def cog_unload(self):
        """Called when the cog is unloaded."""
        self.warning_cleanup_task.cancel()
        self.mute_check_task.cancel()

    @tasks.loop(hours=6)
    async def warning_cleanup_task(self):
        """Background task to check and remove expired warnings."""
        logger.info("Running warning cleanup task")
        
        for guild in self.bot.guilds:
            try:
                guild_data = await self.config.get_guild_config(guild.id)
                expiry_days = guild_data["warning_expiry_days"]
                members_data = guild_data.get("members", {})
                current_time = datetime.utcnow().timestamp()
                
                # Check each member's warnings
                for member_id, member_data in list(members_data.items()):
                    warnings = member_data.get("warnings", [])
                    updated_warnings = []
                    
                    for warning in warnings:
                        issue_time = warning.get("timestamp", 0)
                        expiry_time = issue_time + (expiry_days * 86400)  # Convert days to seconds
                        
                        # Keep warning if not expired
                        if current_time < expiry_time:
                            updated_warnings.append(warning)
                    
                    # Update if warnings were removed
                    if len(warnings) != len(updated_warnings):
                        members_data[member_id]["warnings"] = updated_warnings
                        # Recalculate total points
                        total_points = sum(w.get("points", 1) for w in updated_warnings)
                        members_data[member_id]["total_points"] = total_points
                        
                        # Log that warnings were cleared due to expiry
                        log_channel_id = guild_data.get("log_channel")
                        if log_channel_id:
                            log_channel = guild.get_channel(log_channel_id)
                            if log_channel:
                                member = guild.get_member(int(member_id))
                                if member:
                                    embed = discord.Embed(
                                        title="Warnings Expired",
                                        description=f"Some warnings for {member.mention} have expired.",
                                        color=0x00ff00
                                    )
                                    embed.add_field(name="Current Points", value=str(total_points))
                                    embed.set_footer(text=datetime.utcnow().strftime("%m/%d/%Y %I:%M %p"))
                                    await self.safe_send_message(log_channel, embed=embed)
                
                # Save updated data back to config
                guild_data["members"] = members_data
                await self.config.save_guild_config(guild.id, guild_data)
            
            except Exception as e:
                logger.error(f"Error in warning expiry check: {e}")
    
    @warning_cleanup_task.before_loop
    async def before_warning_cleanup(self):
        """Wait until the bot is ready before starting the task."""
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def mute_check_task(self):
        """Background task to check and remove expired mutes."""
        for guild in self.bot.guilds:
            try:
                # Get the mute role
                guild_data = await self.config.get_guild_config(guild.id)
                mute_role_id = guild_data.get("mute_role")
                if not mute_role_id:
                    continue
                    
                mute_role = guild.get_role(mute_role_id)
                if not mute_role:
                    continue
                
                # Get all members and check their mute status
                members_data = guild_data.get("members", {})
                current_time = datetime.utcnow().timestamp()
                
                for member_id, member_data in list(members_data.items()):
                    # Skip if no mute end time
                    muted_until = member_data.get("muted_until")
                    if not muted_until:
                        continue
                        
                    # Check if mute has expired
                    if current_time > muted_until:
                        try:
                            # Get member
                            member = guild.get_member(int(member_id))
                            if not member:
                                continue
                            
                            # Check if they still have the mute role
                            if mute_role in member.roles:
                                # Restore original roles
                                await self.restore_member_roles(guild, member)
                                
                                # Log unmute
                                await self.log_action(
                                    guild, 
                                    "Auto-Unmute", 
                                    member, 
                                    self.bot.user, 
                                    "Temporary mute duration expired"
                                )
                        except Exception as e:
                            logger.error(f"Error during automatic unmute check: {e}")
            
            except Exception as e:
                logger.error(f"Error in mute check task: {e}")
    
    @mute_check_task.before_loop
    async def before_mute_check(self):
        """Wait until the bot is ready before starting the task."""
        await self.bot.wait_until_ready()

    async def safe_send_message(self, channel, content=None, *, embed=None, file=None):
        """
        Rate-limited message sending to avoid hitting Discord's API limits.
        
        This function queues messages and sends them with a delay if too many
        messages are being sent to the same channel in a short period.
        """
        if not channel:
            return None
            
        channel_id = str(channel.id)
        
        # Initialize queue for this channel if it doesn't exist
        if channel_id not in self.rate_limit["message_queue"]:
            self.rate_limit["message_queue"][channel_id] = {
                "queue": [],
                "last_send": 0,
                "processing": False
            }
            
        # Add message to queue
        message_data = {"content": content, "embed": embed, "file": file}
        self.rate_limit["message_queue"][channel_id]["queue"].append(message_data)
        
        # Start processing queue if not already running
        if not self.rate_limit["message_queue"][channel_id]["processing"]:
            self.rate_limit["message_queue"][channel_id]["processing"] = True
            return await self.process_message_queue(channel)
            
        return None

    async def process_message_queue(self, channel):
        """Process the message queue for a channel with rate limiting."""
        channel_id = str(channel.id)
        queue_data = self.rate_limit["message_queue"][channel_id]
        
        try:
            while queue_data["queue"]:
                # Get the next message
                message_data = queue_data["queue"][0]
                
                # Check if we need to delay sending (rate limit prevention)
                current_time = time.time()
                time_since_last = current_time - queue_data["last_send"]
                
                # If less than 1 second since last message, wait
                if time_since_last < 1:
                    await asyncio.sleep(1 - time_since_last)
                
                # Send the message
                try:
                    await channel.send(
                        content=message_data["content"],
                        embed=message_data["embed"],
                        file=message_data["file"]
                    )
                    queue_data["last_send"] = time.time()
                except discord.HTTPException as e:
                    if e.status == 429:  # Rate limit hit
                        retry_after = e.retry_after if hasattr(e, 'retry_after') else 5
                        logger.info(f"Rate limit hit, waiting {retry_after} seconds")
                        await asyncio.sleep(retry_after)
                        continue  # Try again without removing from queue
                    else:
                        logger.error(f"Error sending message: {e}")
                
                # Remove sent message from queue
                queue_data["queue"].pop(0)
                
                # Small delay between messages
                await asyncio.sleep(0.5)
        
        except Exception as e:
            logger.error(f"Error processing message queue: {e}")
        
        finally:
            # Mark queue as not processing
            queue_data["processing"] = False

    # Settings commands with traditional command support
    @commands.group(name="cautionset", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def caution_settings(self, ctx):
        """Configure the warning system settings."""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Caution System Settings",
                description="Use these commands to configure the warning system.",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="Commands",
                value=(
                    "`!cautionset expiry <days>` - Set warning expiry time\n"
                    "`!cautionset setthreshold <points> <action> [duration] [reason]` - Set action thresholds\n"
                    "`!cautionset removethreshold <points>` - Remove a threshold\n"
                    "`!cautionset showthresholds` - List all thresholds\n"
                    "`!cautionset setlogchannel [channel]` - Set the log channel"
                ),
                inline=False
            )
            await ctx.send(embed=embed)

    @caution_settings.command(name="expiry")
    async def set_warning_expiry(self, ctx, days: int):
        """Set how many days until warnings expire automatically."""
        if days < 1:
            return await ctx.send("Expiry time must be at least 1 day.")
        
        guild_config = await self.config.get_guild_config(ctx.guild.id)
        guild_config["warning_expiry_days"] = days
        await self.config.save_guild_config(ctx.guild.id, guild_config)
        
        await ctx.send(f"Warnings will now expire after {days} days.")

    @caution_settings.command(name="setthreshold")
    async def set_action_threshold(
        self, ctx, 
        points: int, 
        action: str, 
        duration: Optional[int] = None, 
        *, reason: Optional[str] = None
    ):
        """
        Set an automatic action to trigger at a specific warning threshold.
        """
        valid_actions = ["mute", "timeout", "kick", "ban"]
        if action.lower() not in valid_actions:
            return await ctx.send(f"Invalid action. Choose from: {', '.join(valid_actions)}")
        
        if action.lower() in ["mute", "timeout"] and duration is None:
            return await ctx.send(f"Duration (in minutes) is required for {action} action.")
        
        guild_config = await self.config.get_guild_config(ctx.guild.id)
        thresholds = guild_config.get("action_thresholds", {})
        
        # Create new threshold entry
        new_threshold = {"action": action.lower()}
        
        if duration:
            new_threshold["duration"] = duration
            
        if reason:
            new_threshold["reason"] = reason
        else:
            new_threshold["reason"] = f"Exceeded {points} warning points"
        
        # Save the new threshold
        thresholds[str(points)] = new_threshold
        guild_config["action_thresholds"] = thresholds
        await self.config.save_guild_config(ctx.guild.id, guild_config)
        
        # Confirmation message
        confirmation = f"When a member reaches {points} warning points, they will be {action.lower()}ed"
        if duration:
            confirmation += f" for {duration} minutes"
        confirmation += f" with reason: {new_threshold['reason']}"
        
        await ctx.send(confirmation)

    @caution_settings.command(name="removethreshold")
    async def remove_action_threshold(self, ctx, points: int):
        """Remove an automatic action threshold."""
        guild_config = await self.config.get_guild_config(ctx.guild.id)
        thresholds = guild_config.get("action_thresholds", {})
        
        if str(points) in thresholds:
            del thresholds[str(points)]
            guild_config["action_thresholds"] = thresholds
            await self.config.save_guild_config(ctx.guild.id, guild_config)
            await ctx.send(f"Removed action threshold for {points} warning points.")
        else:
            await ctx.send(f"No action threshold set for {points} warning points.")

    @caution_settings.command(name="showthresholds")
    async def show_action_thresholds(self, ctx):
        """Show all configured automatic action thresholds."""
        guild_config = await self.config.get_guild_config(ctx.guild.id)
        thresholds = guild_config.get("action_thresholds", {})
        
        if not thresholds:
            return await ctx.send("No action thresholds are configured.")
        
        embed = discord.Embed(title="Warning Action Thresholds", color=0x00ff00)
        
        # Sort thresholds by point value
        sorted_thresholds = sorted(thresholds.items(), key=lambda x: int(x[0]))
        
        for points, data in sorted_thresholds:
            action = data["action"]
            duration = data.get("duration", "N/A")
            reason = data.get("reason", f"Exceeded {points} warning points")
            
            value = f"Action: {action.capitalize()}\n"
            if action in ["mute", "timeout"]:
                value += f"Duration: {duration} minutes\n"
            value += f"Reason: {reason}"
            
            embed.add_field(name=f"{points} Warning Points", value=value, inline=False)
        
        await ctx.send(embed=embed)

    @caution_settings.command(name="setlogchannel")
    async def set_log_channel(self, ctx, channel: Optional[discord.TextChannel] = None):
        """Set the channel where moderation actions will be logged."""
        if channel is None:
            channel = ctx.channel
            
        guild_config = await self.config.get_guild_config(ctx.guild.id)
        guild_config["log_channel"] = channel.id
        await self.config.save_guild_config(ctx.guild.id, guild_config)
        
        await ctx.send(f"Log channel set to {channel.mention}")

    @commands.command(name="caution")
    @commands.has_permissions(kick_members=True)
    async def warn_member(self, ctx, member: discord.Member, points: int = 1, *, reason: Optional[str] = None):
        """
        Issue a caution/warning to a member with optional point value.
        Default is 1 point if not specified.
        """
        if points < 1:
            return await ctx.send("Warning points must be at least 1.")
        
        # Get current member data
        guild_config = await self.config.get_guild_config(ctx.guild.id)
        members_data = guild_config.get("members", {})
        
        # Initialize member data if not exists
        member_id = str(member.id)
        if member_id not in members_data:
            members_data[member_id] = {
                "warnings": [],
                "total_points": 0
            }
        
        # Create warning entry
        warning = {
            "points": points,
            "reason": reason or "No reason provided",
            "moderator_id": ctx.author.id,
            "timestamp": datetime.utcnow().timestamp(),
            "expiry": (datetime.utcnow() + timedelta(days=guild_config["warning_expiry_days"])).timestamp()
        }
        
        # Add warning and update total points
        members_data[member_id]["warnings"] = members_data[member_id].get("warnings", [])
        members_data[member_id]["warnings"].append(warning)
        members_data[member_id]["total_points"] = sum(w.get("points", 1) for w in members_data[member_id]["warnings"])
        total_points = members_data[member_id]["total_points"]
        
        # Save updated data
        guild_config["members"] = members_data
        await self.config.save_guild_config(ctx.guild.id, guild_config)
        
        # Create warning embed
        embed = discord.Embed(title=f"Warning Issued", color=0xff9900)
        embed.add_field(name="Member", value=member.mention)
        embed.add_field(name="Moderator", value=ctx.author.mention)
        embed.add_field(name="Points", value=str(points))
        embed.add_field(name="Total Points", value=str(total_points))
        embed.add_field(name="Reason", value=warning["reason"], inline=False)
        embed.add_field(name="Expires", value=f"<t:{int(warning['expiry'])}:R>", inline=False)
        embed.set_footer(text=datetime.utcnow().strftime("%m/%d/%Y %I:%M %p"))
        
        # Send warning in channel and log
        await self.safe_send_message(ctx.channel, f"{member.mention} has been cautioned.", embed=embed)
        
        # Log the warning
        await self.log_action(ctx.guild, "Warning", member, ctx.author, warning["reason"], 
                             extra_fields=[
                                 {"name": "Points", "value": str(points)},
                                 {"name": "Total Points", "value": str(total_points)}
                             ])
        
        # Check if any action thresholds were reached
        thresholds = guild_config.get("action_thresholds", {})
        
        # Get thresholds that match or are lower than current points, then get highest
        matching_thresholds = []
        for threshold_points, action_data in thresholds.items():
            if int(threshold_points) <= total_points:
                matching_thresholds.append((int(threshold_points), action_data))
        
        if matching_thresholds:
            # Sort by threshold value (descending) to get highest matching threshold
            matching_thresholds.sort(key=lambda x: x[0], reverse=True)
            threshold_points, action_data = matching_thresholds[0]
            
            # Check if this threshold has already been applied (to prevent repeated actions)
            if not self.has_action_been_applied(members_data[member_id], threshold_points):
                # Mark this threshold as applied
                if "applied_thresholds" not in members_data[member_id]:
                    members_data[member_id]["applied_thresholds"] = []
                members_data[member_id]["applied_thresholds"].append(threshold_points)
                guild_config["members"] = members_data
                await self.config.save_guild_config(ctx.guild.id, guild_config)
                
                # Apply the action
                await self.apply_threshold_action(ctx, member, action_data)

    def has_action_been_applied(self, member_data, threshold_points):
        """Check if an action threshold has already been applied to prevent repeated actions."""
        applied_thresholds = member_data.get("applied_thresholds", [])
        return threshold_points in applied_thresholds

    async def apply_threshold_action(self, ctx, member, action_data):
        """Apply an automatic action based on crossed threshold."""
        action = action_data["action"]
        reason = action_data.get("reason", "Warning threshold exceeded")
        duration = action_data.get("duration")
        
        try:
            if action == "mute":
                # Get the mute role
                guild_config = await self.config.get_guild_config(ctx.guild.id)
                mute_role_id = guild_config.get("mute_role")
                if not mute_role_id:
                    await self.safe_send_message(ctx.channel, "Mute role not found. Please set up a mute role with /setupmute")
                    return
                
                mute_role = ctx.guild.get_role(mute_role_id)
                if not mute_role:
                    await self.safe_send_message(ctx.channel, "Mute role not found. Please set up a mute role with /setupmute")
                    return
                
                # Get member data
                member_data = await self.config.get_member_data(ctx.guild.id, member.id)
                
                # Store member's current roles (except @everyone)
                current_roles = [role.id for role in member.roles if not role.is_default()]
                
                # Store original roles to restore later
                member_data["original_roles"] = current_roles
                
                # Set muted_until time if duration provided
                if duration:
                    muted_until = datetime.utcnow() + timedelta(minutes=duration)
                    member_data["muted_until"] = muted_until.timestamp()
                
                await self.config.update_member_data(ctx.guild.id, member.id, member_data)
                
                # Apply mute
                try:
                    # First remove all roles except @everyone
                    roles_to_remove = [role for role in member.roles if not role.is_default()]
                    if roles_to_remove:
                        await member.remove_roles(*roles_to_remove, reason=f"Applying mute: {reason}")
                    
                    # Then add the mute role 
                    await member.add_roles(mute_role, reason=reason)
                    
                    await self.safe_send_message(ctx.channel, f"{member.mention} has been muted for {duration} minutes due to: {reason}")
                except discord.Forbidden:
                    await self.safe_send_message(ctx.channel, "I don't have permission to manage roles for this member.")
                    return
                except Exception as e:
                    await self.safe_send_message(ctx.channel, f"Error applying mute: {str(e)}")
                    return
                
                # Log the mute action
                await self.log_action(ctx.guild, "Auto-Mute", member, self.bot.user, reason,
                                    extra_fields=[{"name": "Duration", "value": f"{duration} minutes"}])
            
            elif action == "timeout":
                until = datetime.utcnow() + timedelta(minutes=duration)
                await member.timeout(until=until, reason=reason)
                await self.safe_send_message(ctx.channel, f"{member.mention} has been timed out for {duration} minutes due to: {reason}")
                await self.log_action(ctx.guild, "Auto-Timeout", member, self.bot.user, reason,
                                    extra_fields=[{"name": "Duration", "value": f"{duration} minutes"}])
            
            elif action == "kick":
                await member.kick(reason=reason)
                await self.safe_send_message(ctx.channel, f"{member.mention} has been kicked due to: {reason}")
                await self.log_action(ctx.guild, "Auto-Kick", member, self.bot.user, reason)
            
            elif action == "ban":
                await member.ban(reason=reason)
                await self.safe_send_message(ctx.channel, f"{member.mention} has been banned due to: {reason}")
                await self.log_action(ctx.guild, "Auto-Ban", member, self.bot.user, reason)
                
        except Exception as e:
            await self.safe_send_message(ctx.channel, f"Failed to apply automatic {action}: {str(e)}")
            logger.error(f"Error in apply_threshold_action: {e}")

    @commands.command(name="quiet")
    @commands.has_permissions(manage_roles=True)
    async def mute_member(self, ctx, member: discord.Member, duration: int = 30, *, reason: Optional[str] = None):
        """Mute a member for the specified duration (in minutes)."""
        try:
            # Get mute role
            guild_config = await self.config.get_guild_config(ctx.guild.id)
            mute_role_id = guild_config.get("mute_role")
            if not mute_role_id:
                return await ctx.send("Mute role not set up. Please use /setupmute first.")
            
            mute_role = ctx.guild.get_role(mute_role_id)
            if not mute_role:
                return await ctx.send("Mute role not found. Please use /setupmute to create a new one.")
            
            # Get member data
            member_data = await self.config.get_member_data(ctx.guild.id, member.id)
            
            # Store member's current roles (except @everyone)
            current_roles = [role.id for role in member.roles if not role.is_default()]
            
            # Store original roles to restore later
            member_data["original_roles"] = current_roles
            
            # Set muted_until time
            muted_until = datetime.utcnow() + timedelta(minutes=duration)
            member_data["muted_until"] = muted_until.timestamp()
            
            # Save the updated member data
            await self.config.update_member_data(ctx.guild.id, member.id, member_data)
            
            # First remove all roles except @everyone
            roles_to_remove = [role for role in member.roles if not role.is_default()]
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove, reason=f"Manual mute: {reason}")
            
            # Then add the mute role
            await member.add_roles(mute_role, reason=f"Manual mute: {reason}")
            
            # Confirm and log
            await ctx.send(f"{member.mention} has been muted for {duration} minutes. Reason: {reason or 'No reason provided'}")
            
            # Log action
            await self.log_action(ctx.guild, "Mute", member, ctx.author, reason,
                                extra_fields=[{"name": "Duration", "value": f"{duration} minutes"}])
            
        except discord.Forbidden:
            await ctx.send("I don't have permission to manage roles for this member.")
        except Exception as e:
            await ctx.send(f"Error applying mute: {str(e)}")
            logger.error(f"Error in mute_member command: {e}")

    @commands.command(name="setupmute")
    @commands.has_permissions(administrator=True)
    async def setup_mute_role(self, ctx):
        """Set up the muted role for the server."""
        try:
            # Create a new role
            mute_role = await ctx.guild.create_role(name="Muted", reason="Setup for moderation")
            
            # Position the role
            bot_member = ctx.guild.me
            bot_roles = bot_member.roles
            if len(bot_roles) > 1:
                highest_bot_role = max([r for r in bot_roles if not r.is_default()], key=lambda r: r.position)
                position = highest_bot_role.position - 1
                
                # Set role position
                positions = {mute_role: position}
                await ctx.guild.edit_role_positions(positions)
            
            # Save the role ID to config
            guild_config = await self.config.get_guild_config(ctx.guild.id)
            guild_config["mute_role"] = mute_role.id
            await self.config.save_guild_config(ctx.guild.id, guild_config)
            
            # Set up permissions for all channels
            status_msg = await ctx.send("Setting up permissions for the mute role... This may take a moment.")
            
            # First set permissions for all categories
            for category in ctx.guild.categories:
                await category.set_permissions(mute_role, 
                                           send_messages=False, 
                                           speak=False, 
                                           add_reactions=False,
                                           create_public_threads=False,
                                           create_private_threads=False,
                                           send_messages_in_threads=False)
            
            # Then handle any channels that don't have a category
            for channel in [c for c in ctx.guild.channels if c.category is None]:
                await channel.set_permissions(mute_role, 
                                           send_messages=False, 
                                           speak=False, 
                                           add_reactions=False,
                                           create_public_threads=False,
                                           create_private_threads=False,
                                           send_messages_in_threads=False)
            
            await status_msg.edit(content=f"✅ Mute role setup complete! The role {mute_role.mention} has been configured.")
            
        except Exception as e:
            await ctx.send(f"Failed to set up mute role: {str(e)}")
            logger.error(f"Error in setup_mute_role: {e}")

    async def restore_member_roles(self, guild, member):
        """Restore a member's roles after unmuting them."""
        try:
            # Get guild config
            guild_config = await self.config.get_guild_config(guild.id)
            mute_role_id = guild_config.get("mute_role")
            mute_role = guild.get_role(mute_role_id) if mute_role_id else None
            
            # Get member data
            member_data = await self.config.get_member_data(guild.id, member.id)
            original_role_ids = member_data.get("original_roles", [])
            
            # First remove mute role if they have it
            if mute_role and mute_role in member.roles:
                await member.remove_roles(mute_role, reason="Unmuting member")
            
            # Restore original roles
            if original_role_ids:
                roles_to_restore = []
                for role_id in original_role_ids:
                    role = guild.get_role(role_id)
                    if role and role != mute_role:
                        roles_to_restore.append(role)
                
                if roles_to_restore:
                    await member.add_roles(*roles_to_restore, reason="Restoring roles after unmute")
            
            # Clear stored data
            member_data["original_roles"] = []
            member_data["muted_until"] = None
            await self.config.update_member_data(guild.id, member.id, member_data)
            
            # Log the unmute action
            log_channel_id = guild_config.get("log_channel")
            if log_channel_id:
                log_channel = guild.get_channel(log_channel_id)
                if log_channel:
                    await self.safe_send_message(log_channel, f"{member.mention} has been unmuted.")
            
        except Exception as e:
            logger.error(f"Error restoring member roles: {e}")
            # Try to get a channel to send the error
            guild_config = await self.config.get_guild_config(guild.id)
            log_channel_id = guild_config.get("log_channel")
            if log_channel_id:
                log_channel = guild.get_channel(log_channel_id)
                if log_channel:
                    await self.safe_send_message(log_channel, f"Error unmuting {member.mention}: {str(e)}")

    @commands.command(name="unquiet")
    @commands.has_permissions(manage_roles=True)
    async def unmute_member(self, ctx, member: discord.Member):
        """Unmute a member."""
        guild_config = await self.config.get_guild_config(ctx.guild.id)
        mute_role_id = guild_config.get("mute_role")
        
        if not mute_role_id:
            return await ctx.send("No mute role has been set up for this server.")
        
        mute_role = ctx.guild.get_role(mute_role_id)
        
        if mute_role and mute_role in member.roles:
            await self.restore_member_roles(ctx.guild, member)
            await ctx.send(f"{member.mention} has been unmuted.")
            await self.log_action(ctx.guild, "Unmute", member, ctx.author)
        else:
            await ctx.send(f"{member.mention} is not muted.")

    @commands.command(name="cautions")
    async def list_warnings(self, ctx, member: Optional[discord.Member] = None):
        """
        List all active warnings for a member.
        Moderators can check other members. Members can check themselves.
        """
        if member is None:
            member = ctx.author
        
        # Check permissions if checking someone else
        if member != ctx.author and not ctx.author.guild_permissions.kick_members:
            return await ctx.send("You don't have permission to view other members' warnings.")
        
        # Get member data
        guild_config = await self.config.get_guild_config(ctx.guild.id)
        members_data = guild_config.get("members", {})
        member_data = members_data.get(str(member.id), {"warnings": [], "total_points": 0})
        
        warnings = member_data.get("warnings", [])
        
        if not warnings:
            return await ctx.send(f"{member.mention} has no active warnings.")
        
        # Create embed
        embed = discord.Embed(title=f"Warnings for {member.display_name}", color=0xff9900)
        embed.add_field(name="Total Points", value=str(member_data.get("total_points", 0)))
        
        # List all warnings
        for i, warning in enumerate(warnings, start=1):
            moderator = ctx.guild.get_member(warning.get("moderator_id"))
            moderator_mention = moderator.mention if moderator else "Unknown Moderator"
            
            # Format timestamp for display
            timestamp = warning.get("timestamp", 0)
            issued_time = f"<t:{int(timestamp)}:R>"
            
            # Format expiry timestamp
            expiry = warning.get("expiry", 0)
            expiry_time = f"<t:{int(expiry)}:R>"
            
            # Build warning details
            value = f"**Points:** {warning.get('points', 1)}\n"
            value += f"**Reason:** {warning.get('reason', 'No reason provided')}\n"
            value += f"**Moderator:** {moderator_mention}\n"
            value += f"**Issued:** {issued_time}\n"
            value += f"**Expires:** {expiry_time}"
            
            embed.add_field(name=f"Warning #{i}", value=value, inline=False)
        
        await ctx.send(embed=embed)

    @commands.command(name="clearcautions")
    @commands.has_permissions(kick_members=True)
    async def clear_warnings(self, ctx, member: discord.Member):
        """Clear all warnings from a member."""
        # Get member data
        guild_config = await self.config.get_guild_config(ctx.guild.id)
        members_data = guild_config.get("members", {})
        
        member_id = str(member.id)
        if member_id in members_data and members_data[member_id].get("warnings"):
            # Clear warnings and points
            members_data[member_id]["warnings"] = []
            members_data[member_id]["total_points"] = 0
            
            # Clear applied thresholds too
            if "applied_thresholds" in members_data[member_id]:
                members_data[member_id]["applied_thresholds"] = []
            
            # Save data
            guild_config["members"] = members_data
            await self.config.save_guild_config(ctx.guild.id, guild_config)
            
            # Confirm and log
            await ctx.send(f"All warnings for {member.mention} have been cleared.")
            await self.log_action(ctx.guild, "Clear Warnings", member, ctx.author, "Manual clearing of all warnings")
        else:
            await ctx.send(f"{member.mention} has no warnings to clear.")

    @commands.command(name="removecaution")
    @commands.has_permissions(kick_members=True)
    async def remove_warning(self, ctx, member: discord.Member, warning_index: int):
        """Remove a specific warning from a member by index (use '/cautions' to see indexes)."""
        if warning_index < 1:
            return await ctx.send("Warning index must be 1 or higher.")
        
        # Get member data
        guild_config = await self.config.get_guild_config(ctx.guild.id)
        members_data = guild_config.get("members", {})
        
        member_id = str(member.id)
        if member_id not in members_data or not members_data[member_id].get("warnings"):
            return await ctx.send(f"{member.mention} has no warnings.")
        
        warnings = members_data[member_id]["warnings"]
        
        if warning_index > len(warnings):
            return await ctx.send(f"Invalid warning index. {member.mention} only has {len(warnings)} warnings.")
        
        # Remove warning (adjust for 0-based index)
        removed_warning = warnings.pop(warning_index - 1)
        
        # Recalculate total points
        members_data[member_id]["total_points"] = sum(w.get("points", 1) for w in warnings)
        
        # Save data
        guild_config["members"] = members_data
        await self.config.save_guild_config(ctx.guild.id, guild_config)
        
        # Confirm and log
        await ctx.send(f"Warning #{warning_index} for {member.mention} has been removed.")
        await self.log_action(
            ctx.guild, 
            "Remove Warning", 
            member, 
            ctx.author, 
            f"Manually removed warning #{warning_index}",
            extra_fields=[
                {"name": "Warning Points", "value": str(removed_warning.get("points", 1))},
                {"name": "Warning Reason", "value": removed_warning.get("reason", "No reason provided")},
                {"name": "New Total Points", "value": str(members_data[member_id]["total_points"])}
            ]
        )

    async def log_action(self, guild, action, target, moderator, reason=None, extra_fields=None):
        """Log moderation actions to the log channel."""
        guild_config = await self.config.get_guild_config(guild.id)
        log_channel_id = guild_config.get("log_channel")
        if not log_channel_id:
            return
        
        log_channel = guild.get_channel(log_channel_id)
        if not log_channel:
            return
        
        embed = discord.Embed(title=action, description=f"A moderation action has been taken.", color=0xff0000)
        embed.add_field(name="Member", value=target.mention)
        embed.add_field(name="Moderator", value=moderator.mention)
        
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)
        
        # Add any extra fields
        if extra_fields:
            for field in extra_fields:
                if field and field.get("name") and field.get("value"):
                    embed.add_field(name=field["name"], value=field["value"], inline=field.get("inline", True))
        
        embed.set_footer(text=datetime.utcnow().strftime("%m/%d/%Y %I:%M %p"))
        await self.safe_send_message(log_channel, embed=embed)

    # Error handling for commands
    @caution_settings.error
    @warn_member.error
    @mute_member.error
    @unmute_member.error
    @list_warnings.error
    @clear_warnings.error
    @remove_warning.error
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have the required permissions to use this command.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.send("Member not found. Please provide a valid member.")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"Invalid argument: {error}")
        else:
            await ctx.send(f"An error occurred: {error}")
            logger.error(f"Command error in {ctx.command}: {error}")

def setup(bot):
    """Setup function for the moderation cog."""
    bot.add_cog(Moderation(bot))

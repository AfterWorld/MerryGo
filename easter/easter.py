import discord
from discord.ext import commands, tasks
import datetime
import json
import asyncio
import os
from typing import Optional, List, Dict, Union

class EasterHunt(commands.Cog):
    """Easter Egg Hunt event cog for Discord.py bot"""

    def __init__(self, bot, redis_url=None):
        self.bot = bot
        # Redis connection with authentication
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://:onepiece0212!@localhost:6379/0")
        self.redis = None  # Will be initialized in cog_load
        self.is_active = False
        self.main_channel = 0
        self.spawn_channels = []
        self.eggs = {
            "common": {"emoji": "🥚", "points": 50, "chance": 70},
            "rare": {"emoji": "🐣", "points": 200, "chance": 25},
            "legendary": {"emoji": "✨🥚✨", "points": 500, "chance": 5}
        }
        
    async def cog_load(self):
        """Initialize Redis connection when cog is loaded"""
        try:
            # Use aioredis for async Redis operations
            import aioredis
            self.redis = await aioredis.from_url(self.redis_url, decode_responses=True)
            
            # Load configuration from Redis
            self.is_active = (await self.redis.get("egghunt:active")) == "true"
            main_channel = await self.redis.get("egghunt:main_channel")
            self.main_channel = int(main_channel) if main_channel else 0
            
            # Load spawn channels
            channels = await self.redis.smembers("egghunt:spawn_channels")
            self.spawn_channels = [int(c) for c in channels] if channels else []
            
            # Load egg configurations
            egg_config = await self.redis.get("egghunt:eggs")
            if egg_config:
                self.eggs = json.loads(egg_config)
                
            # Start spawning task if event is active
            if self.is_active:
                spawn_rate = await self.redis.get("egghunt:spawn_rate") 
                self.spawn_eggs.start(minutes=int(spawn_rate or 30))
                
            print("EasterHunt: Redis connection established")
        except Exception as e:
            print(f"EasterHunt: Error connecting to Redis: {e}")
            self.redis = None
            
    # Helper method for loading egg configuration
    async def load_egg_config(self) -> Dict:
        """Load egg configuration from Redis or set defaults"""
        egg_config = await self.redis.get("egghunt:eggs")
        if egg_config:
            return json.loads(egg_config)
        else:
            # Default egg configuration
            default_eggs = {
                "common": {"emoji": "🥚", "points": 50, "chance": 70},
                "rare": {"emoji": "🐣", "points": 200, "chance": 25},
                "legendary": {"emoji": "✨🥚✨", "points": 500, "chance": 5}
            }
            await self.redis.set("egghunt:eggs", json.dumps(default_eggs))
            return default_eggs

    @commands.group(invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def egghunt(self, ctx, *, command=None):
        """Main command group for the Easter Egg Hunt event"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="🐰 Easter Egg Hunt - Admin Commands",
                description="Here are the available commands for managing the Easter Egg Hunt event:",
                color=0xffb7c5
            )
            
            # Setup commands
            embed.add_field(
                name="__Setup Commands__",
                value=(
                    "`!egghunt mainchannel #channel` - Set the main channel\n"
                    "`!egghunt includechannel #channel` - Add a channel to spawn pool\n"
                    "`!egghunt removechannel #channel` - Remove a channel\n"
                    "`!egghunt listchannels` - List all spawn channels\n"
                    "`!egghunt setspawnrate [minutes]` - Set spawn frequency"
                ),
                inline=False
            )
            
            # Egg commands
            embed.add_field(
                name="__Egg Management__",
                value=(
                    "`!egghunt addegg [name] [emoji] [points] [chance]` - Add custom egg\n"
                    "`!egghunt removeegg [name]` - Remove an egg type\n"
                    "`!egghunt listeggs` - Show all configured eggs\n"
                    "`!egghunt spawn [type] #channel` - Manually spawn an egg"
                ),
                inline=False
            )
            
            # Event commands
            embed.add_field(
                name="__Event Control__",
                value=(
                    "`!egghuntstart` - Start the event with announcement\n"
                    "`!egghunt stop` - Stop the event\n"
                    "`!egghunt reset` - Reset all event data\n"
                    "`!egghunt announce [message]` - Send announcement to hunt channels"
                ),
                inline=False
            )
            
            # Data commands
            embed.add_field(
                name="__Data Management__",
                value=(
                    "`!egghunt showdata` - Display current Redis data\n"
                    "`!egghunt exportdata` - Export data as JSON\n"
                    "`!egghunt importdata [file]` - Import data from JSON"
                ),
                inline=False
            )
            
            await ctx.send(embed=embed)

    @egghunt.command()
    @commands.has_permissions(administrator=True)
    async def mainchannel(self, ctx, channel: discord.TextChannel):
        """Set the main channel for egg spawns"""
        self.main_channel = channel.id
        self.redis.set("egghunt:main_channel", str(channel.id))
        await ctx.send(f"✅ Main channel set to {channel.mention}")

    @egghunt.command()
    @commands.has_permissions(administrator=True)
    async def includechannel(self, ctx, channel: discord.TextChannel):
        """Add a channel to the spawn pool"""
        if channel.id == self.main_channel:
            return await ctx.send("❌ This channel is already set as the main channel.")
        
        self.redis.sadd("egghunt:spawn_channels", str(channel.id))
        self.redis.set(f"egghunt:channel:{channel.id}:weight", "5")  # Default weight
        self.spawn_channels.append(channel.id)
        await ctx.send(f"✅ Added {channel.mention} to spawn channels")

    @egghunt.command()
    @commands.has_permissions(administrator=True)
    async def removechannel(self, ctx, channel: discord.TextChannel):
        """Remove a channel from the spawn pool"""
        if channel.id == self.main_channel:
            return await ctx.send("❌ You cannot remove the main channel. Use `!egghunt mainchannel` to change it.")
        
        self.redis.srem("egghunt:spawn_channels", str(channel.id))
        self.redis.delete(f"egghunt:channel:{channel.id}:weight")
        
        if channel.id in self.spawn_channels:
            self.spawn_channels.remove(channel.id)
            
        await ctx.send(f"✅ Removed {channel.mention} from spawn channels")

    @egghunt.command()
    @commands.has_permissions(administrator=True)
    async def listchannels(self, ctx):
        """List all channels in the spawn pool"""
        embed = discord.Embed(
            title="🥚 Easter Egg Hunt - Spawn Channels",
            color=0xffb7c5
        )
        
        # Main channel
        main = self.bot.get_channel(self.main_channel)
        if main:
            embed.add_field(
                name="📌 Main Channel",
                value=f"{main.mention} (Weight: 10)",
                inline=False
            )
        else:
            embed.add_field(
                name="📌 Main Channel",
                value="Not set - use `!egghunt mainchannel #channel`",
                inline=False
            )
        
        # Additional channels
        if self.spawn_channels:
            channels_text = []
            for channel_id in self.spawn_channels:
                channel = self.bot.get_channel(channel_id)
                if channel:
                    weight = self.redis.get(f"egghunt:channel:{channel_id}:weight") or "5"
                    channels_text.append(f"{channel.mention} (Weight: {weight})")
            
            embed.add_field(
                name="📋 Additional Channels",
                value="\n".join(channels_text) if channels_text else "None",
                inline=False
            )
        else:
            embed.add_field(
                name="📋 Additional Channels",
                value="None - add with `!egghunt includechannel #channel`",
                inline=False
            )
            
        await ctx.send(embed=embed)

    @egghunt.command()
    @commands.has_permissions(administrator=True)
    async def setspawnrate(self, ctx, minutes: int):
        """Set how frequently eggs spawn (in minutes)"""
        if minutes < 1:
            return await ctx.send("❌ Spawn rate must be at least 1 minute")
        
        self.redis.set("egghunt:spawn_rate", str(minutes))
        
        # Restart the task with new rate if active
        if self.is_active and self.spawn_eggs.is_running():
            self.spawn_eggs.cancel()
            self.spawn_eggs.change_interval(minutes=minutes)
            self.spawn_eggs.start()
            
        await ctx.send(f"✅ Egg spawn rate set to every {minutes} minutes")

    @egghunt.command()
    @commands.has_permissions(administrator=True)
    async def setchannelweight(self, ctx, channel: discord.TextChannel, weight: int):
        """Set spawn weight for a specific channel (1-10)"""
        if channel.id not in self.spawn_channels and channel.id != self.main_channel:
            return await ctx.send("❌ This channel is not in the spawn pool")
            
        if weight < 1 or weight > 10:
            return await ctx.send("❌ Weight must be between 1 and 10")
            
        if channel.id == self.main_channel:
            await ctx.send("ℹ️ Main channel always has maximum weight (10)")
        else:
            self.redis.set(f"egghunt:channel:{channel.id}:weight", str(weight))
            await ctx.send(f"✅ Set spawn weight for {channel.mention} to {weight}")

    @egghunt.command()
    @commands.has_permissions(administrator=True)
    async def addegg(self, ctx, name: str, emoji: str, points: int, chance: int):
        """Add a custom egg type"""
        eggs = self.load_egg_config()
        
        if name in eggs:
            return await ctx.send(f"❌ An egg with name '{name}' already exists")
            
        total_chance = sum(egg["chance"] for egg in eggs.values()) + chance
        if total_chance > 100:
            return await ctx.send(f"❌ Total spawn chance would exceed 100% ({total_chance}%)")
            
        eggs[name] = {
            "emoji": emoji,
            "points": points,
            "chance": chance
        }
        
        self.redis.set("egghunt:eggs", json.dumps(eggs))
        self.eggs = eggs
        
        await ctx.send(f"✅ Added new egg: {emoji} **{name}** ({points} points, {chance}% chance)")

    @egghunt.command()
    @commands.has_permissions(administrator=True)
    async def removeegg(self, ctx, name: str):
        """Remove an egg type"""
        eggs = self.load_egg_config()
        
        if name not in eggs:
            return await ctx.send(f"❌ No egg with name '{name}' exists")
            
        egg = eggs.pop(name)
        self.redis.set("egghunt:eggs", json.dumps(eggs))
        self.eggs = eggs
        
        await ctx.send(f"✅ Removed egg: {egg['emoji']} **{name}**")

    @egghunt.command()
    @commands.has_permissions(administrator=True)
    async def listeggs(self, ctx):
        """List all configured egg types"""
        eggs = self.load_egg_config()
        
        embed = discord.Embed(
            title="🥚 Easter Egg Hunt - Egg Types",
            description="Here are all the configured egg types:",
            color=0xffb7c5
        )
        
        for name, egg in eggs.items():
            embed.add_field(
                name=f"{egg['emoji']} {name.title()}",
                value=f"Points: {egg['points']}\nSpawn chance: {egg['chance']}%",
                inline=True
            )
            
        total_chance = sum(egg["chance"] for egg in eggs.values())
        embed.set_footer(text=f"Total spawn chance: {total_chance}%")
        
        await ctx.send(embed=embed)

    @egghunt.command()
    @commands.has_permissions(administrator=True)
    async def spawn(self, ctx, egg_type: str, channel: Optional[discord.TextChannel] = None):
        """Manually spawn an egg in a channel"""
        eggs = self.load_egg_config()
        
        if egg_type not in eggs:
            return await ctx.send(f"❌ No egg with name '{egg_type}' exists")
            
        spawn_channel = channel or ctx.channel
        egg = eggs[egg_type]
        
        # Create a unique ID for this egg
        egg_id = f"{int(datetime.datetime.now().timestamp())}"
        
        # Spawn the egg
        message = await spawn_channel.send(
            f"{egg['emoji']} An Easter egg has appeared! Type `!findegg` to collect it!"
        )
        
        # Store the egg in Redis
        self.redis.hmset(f"egghunt:egg:{egg_id}", {
            "message_id": str(message.id),
            "channel_id": str(spawn_channel.id),
            "type": egg_type,
            "points": str(egg['points']),
            "collected": "false",
            "spawn_time": datetime.datetime.now().isoformat()
        })
        
        # Set expiration on uncollected eggs (5 minutes)
        self.redis.expire(f"egghunt:egg:{egg_id}", 300)
        
        await ctx.send(f"✅ Manually spawned a {egg_type} egg in {spawn_channel.mention}")

    @egghunt.command()
    @commands.has_permissions(administrator=True)
    async def stop(self, ctx):
        """Stop the Easter Egg Hunt event"""
        if not self.is_active:
            return await ctx.send("❌ The Easter Egg Hunt is not currently active")
            
        self.redis.set("egghunt:active", "false")
        self.is_active = False
        
        if self.spawn_eggs.is_running():
            self.spawn_eggs.cancel()
            
        await ctx.send("✅ Easter Egg Hunt has been stopped")

    @egghunt.command()
    @commands.has_permissions(administrator=True)
    async def reset(self, ctx):
        """Reset all Easter Egg Hunt data"""
        confirm_msg = await ctx.send("⚠️ This will delete ALL egg hunt data including user scores. Type `confirm` to continue.")
        
        def check(m):
            return m.author == ctx.author and m.content.lower() == "confirm" and m.channel == ctx.channel
            
        try:
            await self.bot.wait_for("message", check=check, timeout=30.0)
        except asyncio.TimeoutError:
            return await confirm_msg.edit(content="❌ Reset cancelled.")
            
        # Stop the event if it's running
        if self.is_active:
            self.redis.set("egghunt:active", "false")
            self.is_active = False
            if self.spawn_eggs.is_running():
                self.spawn_eggs.cancel()
        
        # Get all keys with the egghunt prefix
        keys = self.redis.keys("egghunt:*")
        if keys:
            # Delete all egg hunt data
            self.redis.delete(*keys)
            
        # Reset egg configuration to defaults
        self.eggs = self.load_egg_config()
        self.main_channel = 0
        self.spawn_channels = []
        
        await ctx.send("✅ All Easter Egg Hunt data has been reset")

    @egghunt.command()
    @commands.has_permissions(administrator=True)
    async def announce(self, ctx, *, message: str):
        """Send an announcement to all egg hunt channels"""
        if not self.main_channel and not self.spawn_channels:
            return await ctx.send("❌ No channels configured for the Easter Egg Hunt")
            
        embed = discord.Embed(
            title="🐰 Easter Egg Hunt - Announcement",
            description=message,
            color=0xffb7c5,
            timestamp=datetime.datetime.now()
        )
        
        embed.set_footer(text=f"Announcement by {ctx.author.display_name}")
        
        # Send to main channel
        if self.main_channel:
            main = self.bot.get_channel(self.main_channel)
            if main:
                await main.send(embed=embed)
                
        # Send to additional channels
        for channel_id in self.spawn_channels:
            channel = self.bot.get_channel(channel_id)
            if channel:
                await channel.send(embed=embed)
                
        await ctx.send("✅ Announcement sent to all egg hunt channels")

    @egghunt.command()
    @commands.has_permissions(administrator=True)
    async def showdata(self, ctx):
        """Display current Redis data for the Easter Egg Hunt"""
        # Basic configuration
        is_active = self.redis.get("egghunt:active") == "true"
        main_channel_id = self.redis.get("egghunt:main_channel")
        spawn_rate = self.redis.get("egghunt:spawn_rate") or "30"
        
        # Get top 5 users
        leaderboard = self.redis.zrevrange("egghunt:leaderboard", 0, 4, withscores=True)
        
        # Get egg stats
        eggs_found = int(self.redis.get("egghunt:stats:eggs_found") or 0)
        eggs_spawned = int(self.redis.get("egghunt:stats:eggs_spawned") or 0)
        
        embed = discord.Embed(
            title="🐰 Easter Egg Hunt - Redis Data",
            color=0xffb7c5
        )
        
        # Configuration
        config_text = (
            f"Event active: {'✅' if is_active else '❌'}\n"
            f"Main channel: <#{main_channel_id}>\n"
            f"Spawn rate: {spawn_rate} minutes\n"
            f"Spawn channels: {len(self.spawn_channels)}\n"
            f"Egg types: {len(self.eggs)}"
        )
        embed.add_field(name="📊 Configuration", value=config_text, inline=False)
        
        # Stats
        stats_text = (
            f"Eggs spawned: {eggs_spawned}\n"
            f"Eggs found: {eggs_found}\n"
            f"Collection rate: {(eggs_found/eggs_spawned*100) if eggs_spawned > 0 else 0:.1f}%\n"
            f"Total participants: {self.redis.zcard('egghunt:leaderboard')}"
        )
        embed.add_field(name="📈 Stats", value=stats_text, inline=False)
        
        # Leaderboard
        if leaderboard:
            leader_text = "\n".join([f"<@{user_id}>: {int(score)} points" for user_id, score in leaderboard])
            embed.add_field(name="🏆 Top Collectors", value=leader_text, inline=False)
        else:
            embed.add_field(name="🏆 Top Collectors", value="No eggs have been collected yet", inline=False)
            
        await ctx.send(embed=embed)

    @egghunt.command()
    @commands.has_permissions(administrator=True)
    async def exportdata(self, ctx):
        """Export egg hunt data as JSON"""
        # Get all keys with the egghunt prefix
        keys = self.redis.keys("egghunt:*")
        data = {}
        
        for key in keys:
            key_type = self.redis.type(key)
            
            if key_type == "string":
                data[key] = self.redis.get(key)
            elif key_type == "hash":
                data[key] = self.redis.hgetall(key)
            elif key_type == "list":
                data[key] = self.redis.lrange(key, 0, -1)
            elif key_type == "set":
                data[key] = list(self.redis.smembers(key))
            elif key_type == "zset":
                data[key] = self.redis.zrange(key, 0, -1, withscores=True)
                
        # Convert to JSON
        json_data = json.dumps(data, indent=2)
        
        # Create a file to send
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"egghunt_data_{timestamp}.json"
        
        with open(filename, "w") as f:
            f.write(json_data)
            
        await ctx.send("✅ Data export complete", file=discord.File(filename))

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def egghuntstart(self, ctx):
        """Start the Easter Egg Hunt event with a festive announcement"""
        # Check if already active
        if self.is_active:
            return await ctx.send("❌ The Easter Egg Hunt is already active")
            
        # Check if main channel is set
        if not self.main_channel:
            return await ctx.send("❌ Please set a main channel first with `!egghunt mainchannel #channel`")
            
        # Set event as active in Redis
        start_date = datetime.datetime.now()
        easter_date = datetime.datetime(2025, 4, 20)
        
        self.redis.set("egghunt:active", "true")
        self.redis.set("egghunt:start_date", start_date.isoformat())
        self.redis.set("egghunt:end_date", easter_date.isoformat())
        self.is_active = True
        
        # Get spawn rate or use default
        spawn_rate = int(self.redis.get("egghunt:spawn_rate") or 30)
        
        # Create the Easter-themed embed
        embed = discord.Embed(
            title="🐰 Easter Egg Hunt Begins! 🐰",
            description=(
                "The annual Easter Egg Hunt has begun!\n\n"
                f"Colorful eggs will be appearing in various channels until Easter Sunday (April 20th, 2025).\n"
                "Be the first to type `!findegg` when you see an egg to collect it!"
            ),
            color=0xffb7c5  # Pastel pink
        )
        
        # Add egg types section
        egg_info = "\n".join([
            f"{egg_data['emoji']} **{egg_type.title()} Egg** - {egg_data['points']} points" 
            for egg_type, egg_data in self.eggs.items()
        ])
        
        embed.add_field(
            name="🥚 Egg Types",
            value=egg_info,
            inline=False
        )
        
        # Add reward information
        embed.add_field(
            name="🏆 Rewards",
            value=(
                "**Top Collectors**\n"
                "1st Place - 🥇 Golden Bunny Role\n"
                "2nd Place - 🥈 Silver Bunny Role\n"
                "3rd Place - 🥉 Bronze Bunny Role\n\n"
                "Special rewards will be given to anyone who collects 1000+ points!"
            ),
            inline=False
        )
        
        # Add event timeline
        embed.add_field(
            name="📅 Event Timeline",
            value=(
                f"🗓️ **{start_date.strftime('%B %d')} - April 20th, 2025**\n"
                "• Regular egg spawns throughout the event\n"
                "• Weekend bonus: Double spawns on weekends!\n"
                "• Final day: Special Golden Bunny Egg hunt!"
            ),
            inline=False
        )
        
        # Add footer with commands info
        embed.set_footer(text="Use !eggbasket to see your collection | !eggleaderboard to view the rankings")
        
        # Add Easter-themed image
        embed.set_thumbnail(url="https://i.imgur.com/LsmI0hr.png")  # Bunny emoji image
        
        # Send the announcement to the main channel
        channel = self.bot.get_channel(self.main_channel)
        announcement = await channel.send(embed=embed)
        
        # Pin the message for future reference
        await announcement.pin()
        
        # Confirm to admin
        await ctx.send("✅ Easter Egg Hunt has officially begun! The announcement has been posted.")
        
        # Start the egg spawning background task
        self.spawn_eggs.start(minutes=spawn_rate)

    @tasks.loop(minutes=30.0)
    async def spawn_eggs(self):
        """Randomly spawns eggs in configured channels"""
        if not self.is_active:
            return
            
        # Select a channel to spawn in
        if not self.spawn_channels and not self.main_channel:
            return
            
        channels = [self.main_channel] + self.spawn_channels
        weights = [10] + [int(self.redis.get(f"egghunt:channel:{c}:weight") or 5) for c in self.spawn_channels]
        
        channel_id = random.choices(channels, weights=weights, k=1)[0]
        channel = self.bot.get_channel(channel_id)
        
        if not channel:
            return
            
        # Select an egg type based on rarity chances
        egg_types = list(self.eggs.keys())
        egg_chances = [self.eggs[t]["chance"] for t in egg_types]
        egg_type = random.choices(egg_types, weights=egg_chances, k=1)[0]
        egg_data = self.eggs[egg_type]
        
        # Create a unique ID for this egg
        egg_id = f"{int(datetime.datetime.now().timestamp())}"
        
        # Spawn the egg
        message = await channel.send(
            f"{egg_data['emoji']} An Easter egg has appeared! Type `!findegg` to collect it!"
        )
        
        # Store the egg in Redis
        self.redis.hmset(f"egghunt:egg:{egg_id}", {
            "message_id": str(message.id),
            "channel_id": str(channel.id),
            "type": egg_type,
            "points": str(egg_data["points"]),
            "collected": "false",
            "spawn_time": datetime.datetime.now().isoformat()
        })
        
        # Set expiration on uncollected eggs (5 minutes)
        self.redis.expire(f"egghunt:egg:{egg_id}", 300)
        
        # Update stats
        self.redis.incr("egghunt:stats:eggs_spawned")

    @spawn_eggs.before_loop
    async def before_spawn(self):
        """Wait until the bot is ready before starting the spawn loop"""
        await self.bot.wait_until_ready()

    @commands.command()
    async def findegg(self, ctx):
        """Command to collect a spawned egg"""
        # Check if event is active
        if not self.is_active:
            return
            
        # Find the most recent egg spawned in this channel
        channel_eggs = []
        for egg_id in self.redis.keys("egghunt:egg:*"):
            egg_data = self.redis.hgetall(egg_id)
            if egg_data.get("channel_id") == str(ctx.channel.id) and egg_data.get("collected") == "false":
                channel_eggs.append((egg_id, egg_data))
                
        if not channel_eggs:
            return  # No eggs to collect
            
        # Sort by spawn time (most recent first)
        channel_eggs.sort(key=lambda x: x[1].get("spawn_time", ""), reverse=True)
        egg_id, egg_data = channel_eggs[0]
        
        # Mark as collected
        self.redis.hset(egg_id, "collected", "true")
        self.redis.hset(egg_id, "collected_by", str(ctx.author.id))
        self.redis.hset(egg_id, "collected_at", datetime.datetime.now().isoformat())
        
        # Award points to user
        points = int(egg_data.get("points", 0))
        self.redis.zincrby("egghunt:leaderboard", points, str(ctx.author.id))
        
        # Add to user's egg collection
        egg_type = egg_data.get("type", "unknown")
        self.redis.hincrby(f"egghunt:user:{ctx.author.id}:eggs", egg_type, 1)
        
        # Update stats
        self.redis.incr("egghunt:stats:eggs_found")
        
        # Get user's total points
        total_points = int(self.redis.zscore("egghunt:leaderboard", str(ctx.author.id)) or 0)
        
        # Get the egg's emoji
        egg_emoji = self.eggs.get(egg_type, {}).get("emoji", "🥚")
        
        # Edit the original egg message
        try:
            message = await ctx.channel.fetch_message(int(egg_data.get("message_id", 0)))
            await message.edit(content=f"{egg_emoji} This egg was collected by {ctx.author.mention}! (+{points} points)")
        except:
            pass  # Message might not exist anymore
            
        # Send confirmation to user
        await ctx.send(f"🎉 {ctx.author.mention} found a **{egg_type}** egg! +{points} points (Total: {total_points})")

    @commands.command()
    async def eggbasket(self, ctx, member: Optional[discord.Member] = None):
        """View your collected eggs and total points"""
        target = member or ctx.author
        
        # Get user's points
        points = int(self.redis.zscore("egghunt:leaderboard", str(target.id)) or 0)
        
        # Get user's egg collection
        eggs_collected = self.redis.hgetall(f"egghunt:user:{target.id}:eggs") or {}
        
        # Create embed
        embed = discord.Embed(
            title=f"🧺 {target.display_name}'s Egg Basket",
            description=f"Total points: **{points}**",
            color=0xffb7c5
        )
        
        # Add egg collection
        if eggs_collected:
            collection = []
            for egg_type, count in eggs_collected.items():
                emoji = self.eggs.get(egg_type, {}).get("emoji", "🥚")
                collection.append(f"{emoji} **{egg_type.title()}**: {count}")
                
            embed.add_field(
                name="🥚 Collected Eggs",
                value="\n".join(collection),
                inline=False
            )
        else:
            embed.add_field(
                name="🥚 Collected Eggs",
                value="No eggs collected yet",
                inline=False
            )
        
        # Add rank information
        rank = self.redis.zrevrank("egghunt:leaderboard", str(target.id))
        if rank is not None:
            embed.add_field(
                name="🏆 Current Rank",
                value=f"#{rank + 1} of {self.redis.zcard('egghunt:leaderboard')} participants",
                inline=False
            )
            
        await ctx.send(embed=embed)

    @commands.command()
    async def eggleaderboard(self, ctx):
        """View the top egg collectors"""
        # Get top 10 users
        leaderboard = self.redis.zrevrange("egghunt:leaderboard", 0, 9, withscores=True)
        
        if not leaderboard:
            return await ctx.send("🥚 No eggs have been collected yet!")
            
        embed = discord.Embed(
            title="🏆 Easter Egg Hunt - Leaderboard",
            description="Top egg collectors:",
            color=0xffb7c5
        )
        
        # Get total eggs found
        total_eggs = int(self.redis.get("egghunt:stats:eggs_found") or 0)
        
        for i, (user_id, score) in enumerate(leaderboard):
            # Get user object
            user = self.bot.get_user(int(user_id)) or await self.bot.fetch_user(int(user_id))
            name = user.display_name if user else f"User {user_id}"
            
            # Get medal emoji
            medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i+1}."
            
            # Add to embed
            embed.add_field(
                name=f"{medal} {name}",
                value=f"{int(score)} points",
                inline=True
            )
            
        # Add footer with event stats
        embed.set_footer(text=f"Total eggs found: {total_eggs} | Participants: {self.redis.zcard('egghunt:leaderboard')}")
        
        await ctx.send(embed=embed)
        
    @commands.command()
    async def eggstats(self, ctx):
        """View overall Easter Egg Hunt statistics"""
        # Check if event is active
        is_active = self.redis.get("egghunt:active") == "true"
        
        # Get event dates
        start_date = self.redis.get("egghunt:start_date")
        end_date = self.redis.get("egghunt:end_date")
        
        if start_date:
            try:
                start_dt = datetime.datetime.fromisoformat(start_date)
                start_str = start_dt.strftime("%B %d, %Y")
            except:
                start_str = "Unknown"
        else:
            start_str = "Not started"
            
        if end_date:
            try:
                end_dt = datetime.datetime.fromisoformat(end_date)
                end_str = end_dt.strftime("%B %d, %Y")
            except:
                end_str = "Unknown"
        else:
            end_str = "April 20, 2025"
            
        # Get egg stats
        eggs_spawned = int(self.redis.get("egghunt:stats:eggs_spawned") or 0)
        eggs_found = int(self.redis.get("egghunt:stats:eggs_found") or 0)
        
        # Calculate remaining time if active
        if is_active and end_date:
            try:
                end_dt = datetime.datetime.fromisoformat(end_date)
                now = datetime.datetime.now()
                if end_dt > now:
                    remaining = end_dt - now
                    days = remaining.days
                    hours, remainder = divmod(remaining.seconds, 3600)
                    minutes, _ = divmod(remainder, 60)
                    time_left = f"{days} days, {hours} hours, {minutes} minutes"
                else:
                    time_left = "Event has ended"
            except:
                time_left = "Unknown"
        else:
            time_left = "Not active"
            
        # Create embed
        embed = discord.Embed(
            title="📊 Easter Egg Hunt - Stats",
            description=f"{'🟢 Active' if is_active else '🔴 Inactive'}",
            color=0xffb7c5
        )
        
        # Add event info
        embed.add_field(
            name="🗓️ Event Period",
            value=f"Start: {start_str}\nEnd: {end_str}\nRemaining: {time_left}",
            inline=False
        )
        
        # Add egg stats
        collection_rate = f"{(eggs_found/eggs_spawned*100) if eggs_spawned > 0 else 0:.1f}%"
        embed.add_field(
            name="🥚 Egg Statistics",
            value=f"Spawned: {eggs_spawned}\nFound: {eggs_found}\nCollection rate: {collection_rate}",
            inline=True
        )
        
        # Add participant stats
        participants = self.redis.zcard("egghunt:leaderboard")
        embed.add_field(
            name="👥 Participants",
            value=f"Total: {participants}",
            inline=True
        )
        
        # Add egg type breakdown
        egg_types = {}
        for user_id in self.redis.zrange("egghunt:leaderboard", 0, -1):
            user_eggs = self.redis.hgetall(f"egghunt:user:{user_id}:eggs") or {}
            for egg_type, count in user_eggs.items():
                egg_types[egg_type] = egg_types.get(egg_type, 0) + int(count)
                
        if egg_types:
            breakdown = []
            for egg_type, count in egg_types.items():
                emoji = self.eggs.get(egg_type, {}).get("emoji", "🥚")
                percentage = (count / eggs_found * 100) if eggs_found > 0 else 0
                breakdown.append(f"{emoji} {egg_type.title()}: {count} ({percentage:.1f}%)")
                
            embed.add_field(
                name="📋 Egg Type Breakdown",
                value="\n".join(breakdown) if breakdown else "No eggs found yet",
                inline=False
            )
            
        await ctx.send(embed=embed)
        
    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for messages to potentially spawn eggs"""
        # Ignore bots and non-server messages
        if message.author.bot or not message.guild:
            return
            
        # Check if event is active
        if not self.is_active:
            return
            
        # Check if message is in a spawn channel
        if message.channel.id != self.main_channel and message.channel.id not in self.spawn_channels:
            return
            
        # Random chance to spawn an egg based on activity (0.5% chance per message)
        # This is in addition to the timed spawns
        if random.random() < 0.005:  # 0.5% chance
            # Select an egg type based on rarity
            egg_types = list(self.eggs.keys())
            egg_chances = [self.eggs[t]["chance"] for t in egg_types]
            egg_type = random.choices(egg_types, weights=egg_chances, k=1)[0]
            egg_data = self.eggs[egg_type]
            
            # Create a unique ID for this egg
            egg_id = f"{int(datetime.datetime.now().timestamp())}"
            
            # Spawn the egg
            egg_msg = await message.channel.send(
                f"{egg_data['emoji']} An Easter egg has appeared! Type `!findegg` to collect it!"
            )
            
            # Store the egg in Redis
            self.redis.hmset(f"egghunt:egg:{egg_id}", {
                "message_id": str(egg_msg.id),
                "channel_id": str(message.channel.id),
                "type": egg_type,
                "points": str(egg_data["points"]),
                "collected": "false",
                "spawn_time": datetime.datetime.now().isoformat()
            })
            
            # Set expiration on uncollected eggs (5 minutes)
            self.redis.expire(f"egghunt:egg:{egg_id}", 300)
            
            # Update stats
            self.redis.incr("egghunt:stats:eggs_spawned")
            
        async def cog_unload(self):
            """Clean up when cog is unloaded"""
            if self.spawn_eggs.is_running():
                self.spawn_eggs.cancel()
            
            # Close Redis connection if it exists
            if self.redis:
                await self.redis.close()

async def setup(bot):
    """Add the Easter Hunt cog to the bot."""
    # Create cog instance with Redis URL
    redis_url = "redis://:onepiece0212!@localhost:6379/0"  # MODIFY THIS LINE AS NEEDED
    await bot.add_cog(EasterHunt(bot, redis_url))

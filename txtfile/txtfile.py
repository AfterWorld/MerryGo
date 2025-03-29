import discord
from discord.ext import commands
import os
import inspect

class OwnerCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.command(name="txtfile")
    @commands.is_owner()  # This uses Discord.py's built-in owner check
    async def txtfile(self, ctx, cog_name: str):
        """Generate a text file with the source code of the specified cog."""
        
        # Try to find the cog in the bot's cogs
        cog = self.bot.get_cog(cog_name)
        if cog is None:
            return await ctx.send(f"Cog `{cog_name}` not found.")
        
        # Get the source code using inspect
        source = inspect.getsource(cog.__class__)
        
        # Create a text file with the source code
        file_path = f"temp_{cog_name.lower()}.py"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(source)
        
        # Send the file to Discord
        try:
            await ctx.send(f"Here's the source code for `{cog_name}`:", 
                          file=discord.File(file_path))
        except Exception as e:
            await ctx.send(f"Error sending file: {e}")
        finally:
            # Clean up by removing the temporary file
            if os.path.exists(file_path):
                os.remove(file_path)

async def setup(bot):
    await bot.add_cog(OwnerCommands(bot))

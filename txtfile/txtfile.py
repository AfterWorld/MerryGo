import discord
from discord.ext import commands
import os
import inspect
import json

# Load config for owner check
with open('config.json', 'r') as f:
    config = json.load(f)

def is_owner():
    async def predicate(ctx):
        return ctx.author.id in config["owner_ids"]
    return commands.check(predicate)

class TxtFile(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.command(name="txtfile")
    @is_owner()  # Using your custom owner check
    async def txtfile(self, ctx, cog_name: str):
        """Generate a text file with the source code of the specified cog."""
        
        # Try to find the cog with case-insensitive matching
        found_cog = None
        found_name = None
        
        for name, cog in self.bot.cogs.items():
            if name.lower() == cog_name.lower():
                found_cog = cog
                found_name = name
                break
                
        if found_cog is None:
            available_cogs = ", ".join(self.bot.cogs.keys())
            return await ctx.send(f"Cog `{cog_name}` not found. Available cogs: {available_cogs}")
        
        # Get the source code using inspect
        try:
            source = inspect.getsource(found_cog.__class__)
            
            # Create a text file with the source code
            file_path = f"temp_{found_name.lower()}.py"
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(source)
            
            # Send the file to Discord
            await ctx.send(f"Here's the source code for `{found_name}`:", 
                          file=discord.File(file_path))
                          
            # Clean up by removing the temporary file
            if os.path.exists(file_path):
                os.remove(file_path)
                
        except Exception as e:
            await ctx.send(f"Error retrieving source code: {e}")

async def setup(bot):
    await bot.add_cog(TxtFile(bot))

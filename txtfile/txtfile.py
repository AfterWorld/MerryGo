import discord
from discord.ext import commands
import os
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
        self.cogs_dir = "/home/adam/MerryGo/cogs"  # Set your cogs directory path here
        
    @commands.command(name="txtfile")
    @is_owner()
    async def txtfile(self, ctx, cog_name: str):
        """Send the source code file for a specified cog."""
        
        # First check if the cog exists as a direct Python file
        py_file_path = os.path.join(self.cogs_dir, f"{cog_name}.py")
        if os.path.exists(py_file_path):
            await ctx.send(f"Here's the source code for `{cog_name}`:", 
                          file=discord.File(py_file_path))
            return
            
        # If not found, look for any file that contains the cog name
        possible_files = []
        for filename in os.listdir(self.cogs_dir):
            if filename.endswith('.py') and cog_name.lower() in filename.lower():
                possible_files.append(filename)
                
        if not possible_files:
            return await ctx.send(f"No cog file found with name `{cog_name}`.")
            
        if len(possible_files) == 1:
            # If only one match, send it
            file_path = os.path.join(self.cogs_dir, possible_files[0])
            await ctx.send(f"Here's the source code for `{possible_files[0]}`:", 
                          file=discord.File(file_path))
        else:
            # If multiple matches, ask the user to specify
            await ctx.send(f"Multiple files found for `{cog_name}`. Please specify which one:\n" + 
                          "\n".join(possible_files))

async def setup(bot):
    await bot.add_cog(TxtFile(bot))

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
        self.cogs_dir = "/home/adam/MerryGo/cogs"  # Base cogs directory
        
    @commands.command(name="txtfile")
    @is_owner()
    async def txtfile(self, ctx, cog_name: str):
        """Send the source code file for a specified cog."""
        
        # First check for case-insensitive match in the new structure: cogs/cogname/cogname.py
        for folder_name in os.listdir(self.cogs_dir):
            folder_path = os.path.join(self.cogs_dir, folder_name)
            if os.path.isdir(folder_path) and folder_name.lower() == cog_name.lower():
                # Check with the actual folder name (preserving case) for the file
                file_path = os.path.join(folder_path, f"{folder_name}.py")
                if os.path.exists(file_path):
                    await ctx.send(f"Here's the source code for `{folder_name}`:", 
                                  file=discord.File(file_path))
                    return
        
        # If not exact match, try partial case-insensitive matches in folder names
        possible_folders = []
        for folder_name in os.listdir(self.cogs_dir):
            folder_path = os.path.join(self.cogs_dir, folder_name)
            if os.path.isdir(folder_path) and cog_name.lower() in folder_name.lower():
                # Use the actual folder name for the file path
                main_file = os.path.join(folder_path, f"{folder_name}.py")
                if os.path.exists(main_file):
                    possible_folders.append((folder_name, main_file))
        
        # If folders found with partial matches
        if possible_folders:
            if len(possible_folders) == 1:
                # If only one match, send it
                folder_name, file_path = possible_folders[0]
                await ctx.send(f"Here's the source code for `{folder_name}`:", 
                              file=discord.File(file_path))
            else:
                # If multiple matches, ask the user to specify
                await ctx.send(f"Multiple cogs found with name similar to `{cog_name}`. Please specify which one:\n" + 
                              "\n".join([folder_name for folder_name, _ in possible_folders]))
            return
            
        # As a fallback, check for legacy cog structure (direct in cogs folder)
        # First check exact case match
        legacy_path = os.path.join(self.cogs_dir, f"{cog_name}.py")
        if os.path.exists(legacy_path):
            await ctx.send(f"Here's the source code for legacy cog `{cog_name}`:", 
                          file=discord.File(legacy_path))
            return
        
        # Then check case-insensitive match in the legacy structure
        for filename in os.listdir(self.cogs_dir):
            if filename.lower() == f"{cog_name.lower()}.py":
                legacy_path = os.path.join(self.cogs_dir, filename)
                await ctx.send(f"Here's the source code for legacy cog `{filename[:-3]}`:", 
                              file=discord.File(legacy_path))
                return
            
        # If still not found, do a more thorough search through all Python files (case insensitive)
        possible_files = []
        for root, dirs, files in os.walk(self.cogs_dir):
            for filename in files:
                if filename.endswith('.py') and cog_name.lower() in filename.lower():
                    relative_path = os.path.relpath(os.path.join(root, filename), self.cogs_dir)
                    possible_files.append((relative_path, os.path.join(root, filename)))
        
        if possible_files:
            if len(possible_files) == 1:
                # If only one file match, send it
                relative_path, file_path = possible_files[0]
                await ctx.send(f"Here's the source code for `{relative_path}`:", 
                              file=discord.File(file_path))
            else:
                # If multiple file matches, ask the user to specify
                await ctx.send(f"Multiple files found containing `{cog_name}`. Please specify which one:\n" + 
                              "\n".join([rel_path for rel_path, _ in possible_files]))
        else:
            await ctx.send(f"No cog file found with name `{cog_name}`.")

async def setup(bot):
    await bot.add_cog(TxtFile(bot))

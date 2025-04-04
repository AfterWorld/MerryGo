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
        
        # Check for the new structure: cogs/cogname/cogname.py
        cog_folder_path = os.path.join(self.cogs_dir, cog_name)
        cog_file_path = os.path.join(cog_folder_path, f"{cog_name}.py")
        
        # First check if the cog exists in the new structure
        if os.path.exists(cog_file_path):
            await ctx.send(f"Here's the source code for `{cog_name}`:", 
                          file=discord.File(cog_file_path))
            return
            
        # If not found, look for the old structure (direct Python file)
        old_file_path = os.path.join(self.cogs_dir, f"{cog_name}.py")
        if os.path.exists(old_file_path):
            await ctx.send(f"Here's the source code for `{cog_name}` (old structure):", 
                          file=discord.File(old_file_path))
            return
        
        # If still not found, look for any cog folder that contains the name
        possible_folders = []
        for folder_name in os.listdir(self.cogs_dir):
            folder_path = os.path.join(self.cogs_dir, folder_name)
            if os.path.isdir(folder_path) and cog_name.lower() in folder_name.lower():
                # Check if the matching folder contains a Python file with the same name
                expected_file = os.path.join(folder_path, f"{folder_name}.py")
                if os.path.exists(expected_file):
                    possible_folders.append((folder_name, expected_file))
        
        # If no matching folders found, try the broad file search as a fallback
        if not possible_folders:
            possible_files = []
            for root, dirs, files in os.walk(self.cogs_dir):
                for filename in files:
                    if filename.endswith('.py') and cog_name.lower() in filename.lower():
                        possible_files.append((os.path.relpath(os.path.join(root, filename), self.cogs_dir), 
                                             os.path.join(root, filename)))
            
            if not possible_files:
                return await ctx.send(f"No cog file found with name `{cog_name}`.")
                
            if len(possible_files) == 1:
                # If only one match, send it
                relative_path, file_path = possible_files[0]
                await ctx.send(f"Here's the source code for `{relative_path}`:", 
                              file=discord.File(file_path))
            else:
                # If multiple matches, ask the user to specify
                await ctx.send(f"Multiple files found for `{cog_name}`. Please specify which one:\n" + 
                              "\n".join([rel_path for rel_path, _ in possible_files]))
            return
        
        # Handle the folder matches
        if len(possible_folders) == 1:
            # If only one folder match, send it
            folder_name, file_path = possible_folders[0]
            await ctx.send(f"Here's the source code for `{folder_name}/{os.path.basename(file_path)}`:", 
                          file=discord.File(file_path))
        else:
            # If multiple folder matches, ask the user to specify
            await ctx.send(f"Multiple cogs found for `{cog_name}`. Please specify which one:\n" + 
                          "\n".join([f"{folder_name}/{folder_name}.py" for folder_name, _ in possible_folders]))

async def setup(bot):
    await bot.add_cog(TxtFile(bot))

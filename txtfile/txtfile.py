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
        
        # First check if there's a direct folder match (case-insensitive)
        for folder_name in os.listdir(self.cogs_dir):
            folder_path = os.path.join(self.cogs_dir, folder_name)
            if os.path.isdir(folder_path) and folder_name.lower() == cog_name.lower():
                # Found matching folder, check for the main Python file
                main_file_path = os.path.join(folder_path, f"{folder_name}.py")
                if os.path.exists(main_file_path):
                    await ctx.send(f"Here's the source code for `{folder_name}`:", 
                                  file=discord.File(main_file_path))
                    return
                
                # If main file not found, check for other Python files in the directory
                py_files = [f for f in os.listdir(folder_path) if f.endswith('.py')]
                if py_files:
                    if len(py_files) == 1:
                        file_path = os.path.join(folder_path, py_files[0])
                        await ctx.send(f"Here's the source code for `{folder_name}/{py_files[0]}`:", 
                                      file=discord.File(file_path))
                    else:
                        await ctx.send(f"Multiple Python files found in `{folder_name}`. Please specify which one:\n" + 
                                      "\n".join([f"{folder_name}/{py_file}" for py_file in py_files]))
                    return
        
        # If no matching folder by name, try partial matches
        possible_folders = []
        for folder_name in os.listdir(self.cogs_dir):
            folder_path = os.path.join(self.cogs_dir, folder_name)
            if os.path.isdir(folder_path) and cog_name.lower() in folder_name.lower():
                possible_folders.append(folder_name)
        
        if possible_folders:
            if len(possible_folders) == 1:
                folder_name = possible_folders[0]
                folder_path = os.path.join(self.cogs_dir, folder_name)
                
                # Check for main file first
                main_file_path = os.path.join(folder_path, f"{folder_name}.py")
                if os.path.exists(main_file_path):
                    await ctx.send(f"Here's the source code for `{folder_name}`:", 
                                  file=discord.File(main_file_path))
                    return
                
                # Check for any Python files
                py_files = [f for f in os.listdir(folder_path) if f.endswith('.py')]
                if py_files:
                    if len(py_files) == 1:
                        file_path = os.path.join(folder_path, py_files[0])
                        await ctx.send(f"Here's the source code for `{folder_name}/{py_files[0]}`:", 
                                      file=discord.File(file_path))
                    else:
                        await ctx.send(f"Multiple Python files found in `{folder_name}`. Please specify which one:\n" + 
                                      "\n".join([f"{folder_name}/{py_file}" for py_file in py_files]))
                    return
            else:
                await ctx.send(f"Multiple cogs found with name similar to `{cog_name}`. Please specify which one:\n" + 
                              "\n".join(possible_folders))
                return
        
        # If still not found, look for Python files directly in the cogs folder
        for file_name in os.listdir(self.cogs_dir):
            if file_name.endswith('.py') and cog_name.lower() in file_name.lower():
                file_path = os.path.join(self.cogs_dir, file_name)
                await ctx.send(f"Here's the source code for `{file_name}`:", 
                              file=discord.File(file_path))
                return
        
        # Finally, if nothing found, do a recursive search
        possible_files = []
        for root, dirs, files in os.walk(self.cogs_dir):
            for file_name in files:
                if file_name.endswith('.py') and cog_name.lower() in file_name.lower():
                    relative_path = os.path.relpath(os.path.join(root, file_name), self.cogs_dir)
                    possible_files.append((relative_path, os.path.join(root, file_name)))
        
        if possible_files:
            if len(possible_files) == 1:
                relative_path, file_path = possible_files[0]
                await ctx.send(f"Here's the source code for `{relative_path}`:", 
                              file=discord.File(file_path))
            else:
                await ctx.send(f"Multiple files found containing `{cog_name}`. Please specify which one:\n" + 
                              "\n".join([rel_path for rel_path, _ in possible_files]))
        else:
            await ctx.send(f"No cog file found with name `{cog_name}`.")

async def setup(bot):
    await bot.add_cog(TxtFile(bot))

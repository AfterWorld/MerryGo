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
        
        # Debug message to see what we're looking for
        print(f"Searching for cog: {cog_name}")
        print(f"Available folders: {os.listdir(self.cogs_dir)}")
        
        # First check if there's a direct folder match (case-insensitive)
        folder_match = None
        for folder_name in os.listdir(self.cogs_dir):
            if folder_name.lower() == cog_name.lower() and os.path.isdir(os.path.join(self.cogs_dir, folder_name)):
                folder_match = folder_name
                break
                
        if folder_match:
            folder_path = os.path.join(self.cogs_dir, folder_match)
            print(f"Found folder match: {folder_match}")
            print(f"Files in folder: {os.listdir(folder_path)}")
            
            # Look for any Python files in this folder
            py_files = [f for f in os.listdir(folder_path) if f.endswith('.py')]
            if py_files:
                if len(py_files) == 1:
                    file_path = os.path.join(folder_path, py_files[0])
                    await ctx.send(f"Here's the source code for `{folder_match}/{py_files[0]}`:", 
                                  file=discord.File(file_path))
                    return
                else:
                    # If multiple Python files, first try to find a file named the same as the folder
                    main_file = f"{folder_match}.py"
                    if main_file in py_files:
                        file_path = os.path.join(folder_path, main_file)
                        await ctx.send(f"Here's the source code for `{folder_match}/{main_file}`:", 
                                      file=discord.File(file_path))
                        return
                    else:
                        # Otherwise show all Python files in the folder
                        await ctx.send(f"Multiple Python files found in `{folder_match}`. Please specify which one:\n" + 
                                      "\n".join([f"!txtfile {folder_match}/{py_file}" for py_file in py_files]))
                        return
            else:
                await ctx.send(f"No Python files found in the `{folder_match}` folder.")
                return
        
        # Check if they're trying to access a specific file in a folder with format "folder/file.py"
        if "/" in cog_name:
            folder_part, file_part = cog_name.split("/", 1)
            folder_match = None
            
            # Find the folder (case-insensitive)
            for folder_name in os.listdir(self.cogs_dir):
                if folder_name.lower() == folder_part.lower() and os.path.isdir(os.path.join(self.cogs_dir, folder_name)):
                    folder_match = folder_name
                    break
                    
            if folder_match:
                folder_path = os.path.join(self.cogs_dir, folder_match)
                
                # Find the file (case-insensitive)
                file_match = None
                for file_name in os.listdir(folder_path):
                    if file_name.lower() == file_part.lower() and file_name.endswith('.py'):
                        file_match = file_name
                        break
                
                if file_match:
                    file_path = os.path.join(folder_path, file_match)
                    await ctx.send(f"Here's the source code for `{folder_match}/{file_match}`:", 
                                  file=discord.File(file_path))
                    return
                else:
                    await ctx.send(f"No Python file named `{file_part}` found in the `{folder_match}` folder.")
                    return
            else:
                await ctx.send(f"No folder named `{folder_part}` found.")
                return
        
        # If no direct match, try partial matches on folder names
        possible_folders = []
        for folder_name in os.listdir(self.cogs_dir):
            folder_path = os.path.join(self.cogs_dir, folder_name)
            if os.path.isdir(folder_path) and cog_name.lower() in folder_name.lower():
                possible_folders.append(folder_name)
        
        if possible_folders:
            if len(possible_folders) == 1:
                folder_name = possible_folders[0]
                folder_path = os.path.join(self.cogs_dir, folder_name)
                
                # Look for Python files in this folder
                py_files = [f for f in os.listdir(folder_path) if f.endswith('.py')]
                if py_files:
                    if len(py_files) == 1:
                        file_path = os.path.join(folder_path, py_files[0])
                        await ctx.send(f"Here's the source code for `{folder_name}/{py_files[0]}`:", 
                                      file=discord.File(file_path))
                        return
                    else:
                        # Look for a file with the same name as the folder
                        main_file = f"{folder_name}.py"
                        if main_file in py_files:
                            file_path = os.path.join(folder_path, main_file)
                            await ctx.send(f"Here's the source code for `{folder_name}/{main_file}`:", 
                                          file=discord.File(file_path))
                            return
                        else:
                            # Otherwise show all Python files
                            await ctx.send(f"Multiple Python files found in `{folder_name}`. Please specify which one:\n" + 
                                          "\n".join([f"!txtfile {folder_name}/{py_file}" for py_file in py_files]))
                            return
                else:
                    await ctx.send(f"No Python files found in the `{folder_name}` folder.")
                    return
            else:
                await ctx.send(f"Multiple folders found with name similar to `{cog_name}`. Please specify which one:\n" + 
                              "\n".join(possible_folders))
                return
        
        # If still not found, check for Python files directly in the cogs folder
        direct_matches = []
        for file_name in os.listdir(self.cogs_dir):
            if file_name.endswith('.py') and cog_name.lower() in file_name.lower():
                direct_matches.append(file_name)
        
        if direct_matches:
            if len(direct_matches) == 1:
                file_path = os.path.join(self.cogs_dir, direct_matches[0])
                await ctx.send(f"Here's the source code for `{direct_matches[0]}`:", 
                              file=discord.File(file_path))
                return
            else:
                await ctx.send(f"Multiple Python files found with name similar to `{cog_name}`. Please specify which one:\n" + 
                              "\n".join(direct_matches))
                return
        
        # Finally, do a recursive search for Python files in all subdirectories
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

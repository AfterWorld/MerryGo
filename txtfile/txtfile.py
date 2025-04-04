import discord
from discord.ext import commands
import os
import json
import asyncio

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
        self.active_menus = {}  # Store active menu sessions
        
    @commands.command(name="txtfile")
    @is_owner()
    async def txtfile(self, ctx, folder_name: str = None):
        """Browse and view cog source files using interactive menus."""
        
        # If no folder specified, show the main folder menu
        if not folder_name:
            await self.show_folders_menu(ctx)
            return
            
        # If folder is specified, show the files in that folder
        folder_path = os.path.join(self.cogs_dir, folder_name)
        if os.path.isdir(folder_path):
            await self.show_files_menu(ctx, folder_name)
        else:
            await ctx.send(f"Folder `{folder_name}` not found.")
    
    async def show_folders_menu(self, ctx):
        """Show a menu of all cog folders."""
        folders = [d for d in os.listdir(self.cogs_dir) 
                  if os.path.isdir(os.path.join(self.cogs_dir, d))]
        
        # Sort alphabetically
        folders.sort()
        
        # Create an embed for the folders menu
        embed = discord.Embed(
            title="📂 Cog Folders",
            description="Select a folder to view its files:",
            color=discord.Color.blue()
        )
        
        # Add folders to the embed
        folder_list = []
        for i, folder in enumerate(folders, 1):
            folder_list.append(f"`{i}.` {folder}")
            
            # Add fields in groups to avoid hitting Discord's limits
            if i % 25 == 0 or i == len(folders):
                embed.add_field(name="Folders", value="\n".join(folder_list), inline=False)
                folder_list = []
        
        # Send the menu
        menu_msg = await ctx.send(embed=embed)
        
        # Add number reactions for selection (up to 10 for simplicity)
        num_reactions = min(10, len(folders))
        reactions = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        
        for i in range(num_reactions):
            await menu_msg.add_reaction(reactions[i])
        
        # Add pagination reactions if needed
        if len(folders) > 10:
            await menu_msg.add_reaction("⬅️")
            await menu_msg.add_reaction("➡️")
        
        # Store this menu in active menus
        self.active_menus[menu_msg.id] = {
            "type": "folders",
            "page": 0,
            "items": folders,
            "user_id": ctx.author.id
        }
        
        # Set up a reaction check
        def check(reaction, user):
            return (
                user.id == ctx.author.id and 
                reaction.message.id == menu_msg.id and 
                (str(reaction.emoji) in reactions[:num_reactions] or 
                 str(reaction.emoji) in ["⬅️", "➡️"])
            )
        
        # Wait for reaction response
        try:
            reaction, user = await self.bot.wait_for("reaction_add", check=check, timeout=60.0)
            
            # Handle pagination
            if str(reaction.emoji) == "⬅️":
                # Previous page
                await self.change_page(ctx, menu_msg.id, -1)
                return
            elif str(reaction.emoji) == "➡️":
                # Next page
                await self.change_page(ctx, menu_msg.id, 1)
                return
            
            # Handle selection
            selection_idx = reactions.index(str(reaction.emoji))
            if 0 <= selection_idx < len(folders):
                selected_folder = folders[selection_idx]
                # Show files in the selected folder
                await self.show_files_menu(ctx, selected_folder)
            
        except asyncio.TimeoutError:
            # Clean up on timeout
            if menu_msg.id in self.active_menus:
                del self.active_menus[menu_msg.id]
            await menu_msg.clear_reactions()
            await menu_msg.edit(content="Menu timed out.", embed=None)
    
    async def show_files_menu(self, ctx, folder_name):
        """Show a menu of Python files in the specified folder."""
        folder_path = os.path.join(self.cogs_dir, folder_name)
        
        # Get all Python files in the folder
        py_files = [f for f in os.listdir(folder_path) if f.endswith('.py')]
        py_files.sort()  # Sort alphabetically
        
        if not py_files:
            await ctx.send(f"No Python files found in folder `{folder_name}`.")
            return
        
        # Create an embed for the files menu
        embed = discord.Embed(
            title=f"📁 Files in {folder_name}",
            description="Select a file to view its source code:",
            color=discord.Color.green()
        )
        
        # Add files to the embed
        file_list = []
        for i, file in enumerate(py_files, 1):
            file_list.append(f"`{i}.` {file}")
            
            # Add fields in groups to avoid hitting Discord's limits
            if i % 25 == 0 or i == len(py_files):
                embed.add_field(name="Files", value="\n".join(file_list), inline=False)
                file_list = []
        
        # Add a "Go Back" option
        embed.add_field(name="Return", value="`0.` Go back to folder list", inline=False)
        
        # Send the menu
        menu_msg = await ctx.send(embed=embed)
        
        # Add number reactions for selection (up to 10 for simplicity)
        await menu_msg.add_reaction("0️⃣")  # For going back
        
        num_reactions = min(10, len(py_files))
        reactions = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        
        for i in range(num_reactions):
            await menu_msg.add_reaction(reactions[i])
        
        # Add pagination reactions if needed
        if len(py_files) > 10:
            await menu_msg.add_reaction("⬅️")
            await menu_msg.add_reaction("➡️")
        
        # Store this menu in active menus
        self.active_menus[menu_msg.id] = {
            "type": "files",
            "folder": folder_name,
            "page": 0,
            "items": py_files,
            "user_id": ctx.author.id
        }
        
        # Set up a reaction check
        def check(reaction, user):
            return (
                user.id == ctx.author.id and 
                reaction.message.id == menu_msg.id and 
                (str(reaction.emoji) in ["0️⃣"] + reactions[:num_reactions] or 
                 str(reaction.emoji) in ["⬅️", "➡️"])
            )
        
        # Wait for reaction response
        try:
            reaction, user = await self.bot.wait_for("reaction_add", check=check, timeout=60.0)
            
            # Handle pagination
            if str(reaction.emoji) == "⬅️":
                # Previous page
                await self.change_page(ctx, menu_msg.id, -1)
                return
            elif str(reaction.emoji) == "➡️":
                # Next page
                await self.change_page(ctx, menu_msg.id, 1)
                return
            
            # Handle "Go Back"
            if str(reaction.emoji) == "0️⃣":
                await self.show_folders_menu(ctx)
                return
            
            # Handle file selection
            selection_idx = reactions.index(str(reaction.emoji))
            if 0 <= selection_idx < len(py_files):
                selected_file = py_files[selection_idx]
                # Send the selected file
                file_path = os.path.join(folder_path, selected_file)
                await ctx.send(f"Here's the source code for `{folder_name}/{selected_file}`:", 
                              file=discord.File(file_path))
            
        except asyncio.TimeoutError:
            # Clean up on timeout
            if menu_msg.id in self.active_menus:
                del self.active_menus[menu_msg.id]
            await menu_msg.clear_reactions()
            await menu_msg.edit(content="Menu timed out.", embed=None)
    
    async def change_page(self, ctx, menu_id, direction):
        """Change the page of a paginated menu."""
        if menu_id not in self.active_menus:
            return
        
        menu_data = self.active_menus[menu_id]
        items = menu_data["items"]
        
        # Calculate the new page number
        total_pages = (len(items) + 9) // 10  # Ceiling division
        new_page = (menu_data["page"] + direction) % total_pages
        
        # Update the menu data
        menu_data["page"] = new_page
        
        # Get the items for this page
        start_idx = new_page * 10
        end_idx = min(start_idx + 10, len(items))
        page_items = items[start_idx:end_idx]
        
        # Create a new embed for the updated page
        if menu_data["type"] == "folders":
            embed = discord.Embed(
                title="📂 Cog Folders",
                description=f"Select a folder to view its files (Page {new_page + 1}/{total_pages}):",
                color=discord.Color.blue()
            )
            
            # Add folders to the embed
            folder_list = []
            for i, folder in enumerate(page_items, start_idx + 1):
                folder_list.append(f"`{i}.` {folder}")
                
            embed.add_field(name="Folders", value="\n".join(folder_list), inline=False)
            
        else:  # Files menu
            folder_name = menu_data["folder"]
            embed = discord.Embed(
                title=f"📁 Files in {folder_name}",
                description=f"Select a file to view its source code (Page {new_page + 1}/{total_pages}):",
                color=discord.Color.green()
            )
            
            # Add files to the embed
            file_list = []
            for i, file in enumerate(page_items, start_idx + 1):
                file_list.append(f"`{i}.` {file}")
                
            embed.add_field(name="Files", value="\n".join(file_list), inline=False)
            embed.add_field(name="Return", value="`0.` Go back to folder list", inline=False)
        
        # Edit the message with the new embed
        message = await ctx.channel.fetch_message(menu_id)
        await message.edit(embed=embed)
        
        # Re-create this menu session with updated data
        await message.clear_reactions()
        
        # Add reactions for this page
        if menu_data["type"] == "files":
            await message.add_reaction("0️⃣")  # For going back
            
        # Add number reactions
        reactions = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        num_reactions = min(10, len(page_items))
        
        for i in range(num_reactions):
            await message.add_reaction(reactions[i])
        
        # Add pagination reactions
        await message.add_reaction("⬅️")
        await message.add_reaction("➡️")
        
        # Wait for a new reaction
        def check(reaction, user):
            valid_reactions = ["⬅️", "➡️"]
            if menu_data["type"] == "files":
                valid_reactions.append("0️⃣")
            valid_reactions.extend(reactions[:num_reactions])
            
            return (
                user.id == menu_data["user_id"] and 
                reaction.message.id == menu_id and 
                str(reaction.emoji) in valid_reactions
            )
        
        try:
            reaction, user = await self.bot.wait_for("reaction_add", check=check, timeout=60.0)
            
            # Handle pagination
            if str(reaction.emoji) == "⬅️":
                await self.change_page(ctx, menu_id, -1)
                return
            elif str(reaction.emoji) == "➡️":
                await self.change_page(ctx, menu_id, 1)
                return
            
            # Handle "Go Back" for files menu
            if menu_data["type"] == "files" and str(reaction.emoji) == "0️⃣":
                await self.show_folders_menu(ctx)
                return
            
            # Handle selection
            if str(reaction.emoji) in reactions[:num_reactions]:
                selection_idx = reactions.index(str(reaction.emoji))
                actual_idx = start_idx + selection_idx
                
                if actual_idx < len(items):
                    selected_item = items[actual_idx]
                    
                    if menu_data["type"] == "folders":
                        # Show files in the selected folder
                        await self.show_files_menu(ctx, selected_item)
                    else:
                        # Send the selected file
                        folder_name = menu_data["folder"]
                        file_path = os.path.join(self.cogs_dir, folder_name, selected_item)
                        await ctx.send(f"Here's the source code for `{folder_name}/{selected_item}`:", 
                                      file=discord.File(file_path))
            
        except asyncio.TimeoutError:
            # Clean up on timeout
            if menu_id in self.active_menus:
                del self.active_menus[menu_id]
            message = await ctx.channel.fetch_message(menu_id)
            await message.clear_reactions()
            await message.edit(content="Menu timed out.", embed=None)
    
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        """Handle reactions to menus."""
        # Skip reactions from the bot itself
        if payload.user_id == self.bot.user.id:
            return
            
        # Check if this is a reaction to one of our active menus
        if payload.message_id in self.active_menus:
            menu_data = self.active_menus[payload.message_id]
            
            # Verify this is the menu owner
            if payload.user_id != menu_data["user_id"]:
                return
                
            # Get the channel and process the reaction
            channel = self.bot.get_channel(payload.channel_id)
            if channel:
                ctx = await self.bot.get_context(await channel.fetch_message(payload.message_id))
                
                # Handle pagination reactions
                if str(payload.emoji) == "⬅️":
                    await self.change_page(ctx, payload.message_id, -1)
                elif str(payload.emoji) == "➡️":
                    await self.change_page(ctx, payload.message_id, 1)
                    
                # Other reactions are handled by the wait_for in the respective menu methods

async def setup(bot):
    await bot.add_cog(TxtFile(bot))

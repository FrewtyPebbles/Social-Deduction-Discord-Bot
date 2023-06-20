from discord.ext import commands
import discord
from bot_class import DBBot
from discord import app_commands

#TODO:
# - make a "gamechannel" command that will prevent users from using game commands in channels other than the ones you use the "gamechannel" command in

class Admin(commands.Cog):
    def __init__(self, bot:DBBot):
        self.bot = bot
        self.db = bot.db

    @commands.command(name='susbotsync', description='Owner only')
    @commands.has_permissions(administrator=True)
    async def sync(self, ctx: commands.Context):
        fmt = await ctx.bot.tree.sync()
        await ctx.send(f'{len(fmt)} commands synced with server.')

    @app_commands.command(name='gamechannel', description='Marks a channel as a channel that members of the server can use sus bot in.')
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(action=[
        app_commands.Choice(name="add", value="add"),
        app_commands.Choice(name="remove", value="remove")
    ])
    async def gamechannel(self, interaction:discord.Interaction, action:str):
        if action == "add":
            await self.db.gamechannel.insert_one({"guild_id":interaction.guild_id, "channel_id":interaction.channel_id})
            await interaction.response.send_message("Channel added as a game channel.")
        elif action == "remove":
            await self.db.gamechannel.delete_one({"guild_id":interaction.guild_id, "channel_id":interaction.channel_id})
            await interaction.response.send_message("Channel removed as a game channel.")



async def setup(client):
    await client.add_cog(Admin(client))
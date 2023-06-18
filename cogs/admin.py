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


async def setup(client):
    await client.add_cog(Admin(client))
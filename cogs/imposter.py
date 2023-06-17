from discord.ext import commands
import discord
from bot_class import DBBot
from discord import app_commands



class Imposter(commands.Cog):
    def __init__(self, bot:DBBot):
        self.bot = bot
        self.db = bot.db

    

async def setup(client):
    await client.add_cog(Imposter(client))
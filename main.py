import asyncio
import os
import discord
from bot_class import DBBot
from dotenv import load_dotenv
import logging

#SUSBOT
VER = "0.1.0"

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')

bot = DBBot(command_prefix = "/", intents=intents)
bot.remove_command("help")

async def load_exts():
    for f in os.listdir("./cogs"):
        if f.endswith(".py"):
            await bot.load_extension("cogs." + f[:-3])

async def main():
    await load_exts()

asyncio.run(main())
bot.run(os.getenv("DISCORD_TOKEN"), log_handler=handler)
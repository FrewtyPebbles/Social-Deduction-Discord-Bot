from discord.ext import commands
from os import getenv
from motor.motor_asyncio import AsyncIOMotorClient

class DBBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        mongo_client = AsyncIOMotorClient(getenv("DB_HOST"))
        self.db = mongo_client[getenv("DB_NAME")]
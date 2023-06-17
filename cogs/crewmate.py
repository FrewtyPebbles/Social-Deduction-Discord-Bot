import math
import time
from typing import Optional
from discord.ext import commands
import discord
from bot_class import DBBot
from discord import app_commands
from discord.ext import tasks
from bson import ObjectId

#TODO:
# - Rework the system so that there is only one crew per guild
# - Make loop check the state of of every crew every minute and behave based on wether it is "match", "voting", or "intermission".
#   "match":
#   match means that people are responding to prompts that were sent to their dms.
#   "voting":
#   voting means that people are currently voting on who to send out the airlock.
#   "intermission":
#   this is a 1 minute cooldown between matches.

class Crewmate(commands.Cog):
    def __init__(self, bot:DBBot):
        self.bot = bot
        self.db = bot.db

    @commands.Cog.listener()
    async def on_ready(self):
        await self.db.crew.update_many({},{"$set":{"state":"none"}})
        self.game_loop.start()

    async def get_crew_members(self, guild_id:int):
        crew = await self.db.crew.find_one({"guild_id":guild_id})
        if crew:
            return [await self.db.crew_member.find_one({"_id":ObjectId(member_id)}) for member_id in crew["crew"]]
        else:
            return []

    @commands.command(name='susbotsync', description='Owner only')
    @commands.has_permissions(administrator=True)
    async def sync(self, ctx: commands.Context):
        fmt = await ctx.bot.tree.sync()
        await ctx.send(f'{len(fmt)} commands synced with server.')

    @app_commands.command(name='join', description='Joins the crew.')
    async def join(self, interaction:discord.Interaction):
        await self.db.crew_member.update_one({"user_id":interaction.user.id, "guild_id":interaction.guild_id},{"$set":{
            "guild_id":interaction.guild_id,
            "user_id":interaction.user.id,
            "imposter": False,
            "alive": True,
            "answer":"",
            "votes":0,
        }}, upsert= True)
        member = await self.db.crew_member.find_one({"user_id":interaction.user.id, "guild_id":interaction.guild_id})
        crew = await self.db.crew.find_one({"guild_id":interaction.guild_id, "channel_id":interaction.channel_id})
        if crew is None:
            await self.db.crew.insert_one({
                "guild_id":interaction.guild_id,
                "channel_id":interaction.channel_id,
                "state":"none",
                "state_switch_time": time.time(),
                "can_answer":False,
                "crew":[ObjectId(member["_id"])]
            })
        else:
            if ObjectId(member["_id"]) not in crew["crew"]:
                await self.db.crew.update_one({
                    "guild_id":interaction.guild_id
                },{
                    "$push":{
                        "crew":ObjectId(member["_id"])
                    }
                })
            else:
                await interaction.response.send_message(f"You are already in the crew!")
                return
        await interaction.response.send_message(f"*{interaction.user.name}* has joined the crew!")

    @app_commands.command(name='leave', description='Leaves the crew.')
    async def leave(self, interaction:discord.Interaction):
        member = await self.db.crew_member.find_one({"user_id":interaction.user.id, "guild_id":interaction.guild_id})
        await self.db.crew.update_one({
            "guild_id":interaction.guild_id,
        },{"$pull":{
            "crew":{"$in":[ObjectId(member["_id"])]}
        }})
        await self.db.crew_member.delete_one({"user_id":interaction.user.id, "guild_id":interaction.guild_id})
        await interaction.response.send_message(f"*{interaction.user.name}* has left the crew!")
        
    @app_commands.command(name='respond', description='Joins or creates a new crew if the specified crew does not exist.')
    async def write_response(self, interaction:discord.Interaction, response:str):
        member = await self.db.crew_member.find_one({"user_id":interaction.user.id, "guild_id":interaction.guild_id})
        crew = await self.db.crew.find_one({"guild_id":interaction.guild_id})
        if crew is None:
            await interaction.response.send_message(f"You are not in a crew.  Please join a crew with /join if you wish to play!")
        elif crew["state"] == "match" and member["alive"]:
            await self.db.crew_member.update_one({"user_id":interaction.user.id, "guild_id":interaction.guild_id},{"$set":{
                "answer":response
            }})
            await interaction.response.send_message(f"**{interaction.user.name}** Has responded to the prompt!")
        else:
            if member["alive"]:
                await interaction.response.send_message(f"It is not time to write a response yet!")
            else:
                await interaction.response.send_message(f"Dead crew members cannot write a response!")

    async def crew_members_autocomplete(self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:

        ret_list = [
            app_commands.Choice(name=(usr_name := (await self.bot.fetch_user(choice["user_id"]))).name, value=usr_name.id)
            for choice in await self.get_crew_members(interaction.guild_id)
            if
            choice["user_id"] != interaction.user.id
        ]
        print(ret_list)
        return ret_list

    @app_commands.command(name='vote', description='Joins or creates a new crew if the specified crew does not exist.')
    @app_commands.autocomplete(user_id=crew_members_autocomplete)
    async def vote(self, interaction:discord.Interaction, user_id:int):
        user = await self.bot.fetch_user(user_id)
        me = await self.db.crew_member.find_one({"user_id":interaction.user.id, "guild_id":interaction.guild_id})
        if me["can_vote"] and me["alive"]:
            await self.db.crew_member.update_one({"user_id":user.id, "guild_id":interaction.guild_id},{"$set":{
                "votes": {"$add": ["$votes", 1]}
            }})
            await self.db.crew_member.update_one({"user_id":interaction.user.id, "guild_id":interaction.guild_id},{"$set":{
                "can_vote": False
            }})
            await interaction.response.send_message(f"{interaction.user.name} has voted for {user.name}")
        else:
            if not me["alive"]:
                await interaction.response.send_message(f"You are dead and cannot vote!")
            elif not me["can_vote"]:
                await interaction.response.send_message(f"It is not time to vote yet!")

    # gameplay loop
    # def cog_unload(self):
    #     self.game_loop.cancel()

    @tasks.loop(seconds=30, count=None, reconnect=True)
    async def game_loop(self):
        print("game_loop")
        for crew_data in await self.db.crew.find().to_list(None):
            guild = await self.bot.fetch_guild(crew_data["guild_id"])
            channel = await guild.fetch_channel(crew_data["channel_id"])
            #users = [await self.bot.fetch_user(crew_member_data["user_id"]) for crew_member_data in await self.db.crew_member.find({"guild_id":crew_data["guild_id"]}).to_list(None)]
            
            # state machine
            
            if crew_data["state"] == "match":
                if time.time() >= crew_data["state_switch_time"]:
                    #time is up
                    await self.db.crew.update_one({"guild_id":guild.id}, {"$set":{
                        "state":"voting",
                        "state_switch_time":time.time() + 420, # voting ends in 7 minutes
                        "can_answer":False
                    }})
                    # show all the responses to the prompt and their names
                    embed = discord.Embed(
                        title="Responses",
                        description="You have 7 minutes to vote out whoever you believe might be an imposter.  Use /vote to vote against them!",
                        color=16777215
                    )
                    for crew_member in await self.db.crew.find({"guild_id":guild.id}).to_list(None):
                        user = await self.bot.fetch_user(crew_member["user_id"])
                        embed.add_field(name=user.name, value=crew_member["answer"])
                    await channel.send(embed=embed)
                    continue
                if math.floor((crew_data['state_switch_time'] - time.time())/60) != 0:
                    await channel.send(f"You have {math.floor((crew_data['state_switch_time'] - time.time())/60)} minutes and {round((crew_data['state_switch_time'] - time.time()) % 60)} seconds left to respond!")
                elif round(crew_data['state_switch_time'] - time.time()) < 30:
                    await channel.send("You have 30 more seconds to respond!")
                else:
                    await channel.send("You have 1 minute left to respond!")
                print(f"{(crew_data['state_switch_time'] - time.time())/60} minutes left to respond!")


            elif crew_data["state"] == "voting":
                if time.time() >= crew_data["state_switch_time"]:
                    #time is up
                    await self.db.crew.update_one({"guild_id":guild.id}, {"$set":{
                        "state":"intermission",
                        "state_switch_time":time.time() + 60 # Intermission ends in 1 minute
                    }})
                    await channel.send("next round will begin in 1 minute!")
                    continue
                await channel.send(f"You have {math.floor((crew_data['state_switch_time'] - time.time())/60)} minutes and {round((crew_data['state_switch_time'] - time.time()) % 60)} seconds left to vote!")

            
            elif crew_data["state"] == "intermission":
                if time.time() >= crew_data["state_switch_time"]:
                    #time is up
                    #if some team has won then do this:
                    await self.db.crew.update_one({"guild_id":guild.id}, {"$set":{
                        "state":"none",
                        "state_switch_time":time.time() # Intermission ends in 1 minute
                    }})
                    await channel.send("Use /start to play again!")
                    continue

    @game_loop.before_loop
    async def before_game_loop(self):
        await self.bot.wait_until_ready()



    @app_commands.command(name='start', description='Starts the game.  This command can only be used by the crew host.')
    async def start(self, interaction:discord.Interaction):
        member = await self.db.crew_member.find_one({"user_id":interaction.user.id, "guild_id":interaction.guild_id})
        # Send the prompt via DM to everyone in the crew
        async for crew_member in self.db.crew_member.find({"guild_id":interaction.guild.id}):
            user = await self.bot.fetch_user(crew_member["user_id"])
            if crew_member["imposter"]:
                await user.send("***You are an IMPOSTER!***\nimposter prompt")
            else:
                await user.send("***You are a CREW MEMBER!***\nprompt")
        crew = await self.db.crew.update_one({"guild_id":interaction.guild_id}, {"$set":{
            "state":"match",
            "state_switch_time":time.time() + 300, # in 5 min switch states
            "can_answer":True
        }})
        embed = discord.Embed(
                        title="There are one or more imposters among your crew!",
                        description="The same prompt has been sent to all of you in DM except for the imposters who were sent a similar but different prompt.  You have 5 minutes to use `/respond` in this text channel to respond to the prompt.  You must find out who the imposters are based on how they responded to the prompt and vote them out once voting starts in order to win.  Check your DMs now and start `/respond`ing!",
                        color=16777215
                    )
        # change crew state to match
        await interaction.response.send_message(embed=embed)


async def setup(client):
    await client.add_cog(Crewmate(client))
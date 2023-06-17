import json
import math
import os
import random
import time
from typing import Optional, Tuple
from discord.ext import commands
import discord
from bot_class import DBBot
from discord import app_commands
from discord.ext import tasks
from bson import ObjectId

#TODO:
# - add a prompt queue to the crew collection so there are no repeat questions.
# - make it so people can only vote once (add a can_vote parameter to crew_member collection)

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
                "prompt":"",
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
        crew = await self.db.crew.find_one({"guild_id":interaction.guild_id})
        if crew["state"] == "voting" and me["alive"]:
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
            elif crew["state"] != "voting":
                await interaction.response.send_message(f"It is not time to vote yet!")

    # gameplay loop
    # def cog_unload(self):
    #     self.game_loop.cancel()

    @tasks.loop(seconds=30, count=None, reconnect=True)
    async def game_loop(self):
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
                        "state_switch_time":time.time() + 60 * 7, # voting ends in 7 minutes
                        "can_answer":False
                    }})
                    # show all the responses to the prompt and their names
                    embed = discord.Embed(
                        title="Its time to vote!  Here was the prompt:",
                        description=crew_data["prompt"],
                        color=16777215
                    )
                    embed.set_thumbnail(url="https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTBF55Nobpf8Es6Nu4h8K0ajveKPKZj83iKCPlsZK4NAw&usqp=CAU&ec=48665701")
                    for crew_member in await self.db.crew_member.find({"guild_id":guild.id}).to_list(None):
                        user = await self.bot.fetch_user(crew_member["user_id"])
                        embed.add_field(name=f"{user.name} replied:", value=crew_member["answer"])
                    await channel.send(embed=embed)
                    continue
                if math.floor((crew_data['state_switch_time'] - time.time())/60) != 0:
                    await channel.send(f"You have {math.floor((crew_data['state_switch_time'] - time.time())/60)} minutes and {round((crew_data['state_switch_time'] - time.time()) % 60)} seconds left to respond!")
                elif round(crew_data['state_switch_time'] - time.time()) < 30:
                    await channel.send("You have 30 more seconds to respond!")
                else:
                    await channel.send("You have 1 minute left to respond!")

            elif crew_data["state"] == "voting":
                if time.time() >= crew_data["state_switch_time"]:
                    #time is up
                    # THROW SOMEONE OUT THE AIRLOCK
                    highest_voted = [0, 0, False]
                    embed = discord.Embed(
                            title="",
                            description="",
                            color=16777215
                        )
                    crew_members = await self.db.crew_member.find({"guild_id":guild.id, "alive":True}).to_list(None)
                    for crew_member in crew_members:
                        if crew_member["votes"] > highest_voted[1]:
                            highest_voted = [crew_member["user_id"], crew_member["votes"], crew_member["imposter"]]
                        elif crew_member["votes"] == highest_voted[1]:
                            highest_voted[0] = 0
                    if highest_voted[0] == 0:
                        # noone is voted out due to tie
                        embed = discord.Embed(
                            title="Noone was voted out due to a tie!",
                            description="",
                            color=16777215
                        )
                        for crew_member in crew_members:
                            user = await self.bot.fetch_user(crew_member["user_id"])
                            embed.add_field(name=f"{user.name}'s votes:", value=crew_member["votes"])
                    else:
                        dead_user = await self.bot.fetch_user(highest_voted[1])
                        embed = discord.Embed(
                            title=f"***{dead_user.name}*** has been thrown out of the airlock!",
                            description=f"He was a **{'IMPOSTER' if highest_voted[2] else 'CREW MEMBER'}**!",
                            color=16777215
                        )
                        for crew_member in crew_members:
                            user = await self.bot.fetch_user(crew_member["user_id"])
                            embed.add_field(name=f"{user.name}'s votes:", value=crew_member["votes"])
                        # someone was voted out
                        await self.db.crew_member.update_one({"user_id":highest_voted[0], "guild_id":guild.id}, {"$set":{
                            "alive": False
                        }})
                    embed.set_thumbnail(url="https://media.discordapp.net/attachments/1113324969045282856/1119437109854490725/images_27.jpg")
                    # END THROW SOMEONE OUT THE AIRLOCK
                    
                    await channel.send(embed=embed)
                    #CHECK IF ANYONE HAS WON
                    alive_members = await self.db.crew_member.find({"guild_id":guild.id, "alive":True}).to_list(None)
                    alive_imposters = []
                    alive_crew = []

                    for member in alive_members:
                        if member["imposter"]:
                            alive_imposters.append(member["user_id"])
                        else:
                            alive_crew.append(member["user_id"])
                    
                    #If they won
                    if (len(alive_imposters) != 0 and len(alive_crew) == 0) or (len(alive_imposters) == 0 and len(alive_crew) != 0):
                        if len(alive_crew) == 0:
                            win_embed = discord.Embed(
                                title=f"***IMPOSTERS*** have won!",
                                description=f"Use `/start` to play again!",
                                color=16777215
                            )
                            
                            for crew_id in alive_imposters:
                                user = await self.bot.fetch_user(crew_id)
                                win_embed.add_field(name=f"{user.name} was an ***IMPOSTER***", value="")
                            win_embed.set_thumbnail(url="https://media.discordapp.net/attachments/1113324969045282856/1119437111611904041/images_28.jpg")
                            await channel.send(embed=win_embed)
                        else:
                            win_embed = discord.Embed(
                                title=f"***CREW MEMBERS*** have won!",
                                description=f"Use `/start` to play again!",
                                color=16777215
                            )

                            for crew_id in alive_crew:
                                user = await self.bot.fetch_user(crew_id)
                                win_embed.add_field(name=f"{user.name} survived", value="")
                            win_embed.set_thumbnail(url="https://media.discordapp.net/attachments/1113324969045282856/1119437110492024863/images_24.jpg")
                            await channel.send(embed=win_embed)
                        await self.db.crew.update_one({"guild_id":guild.id}, {"$set":{
                            "state":"none",
                            "state_switch_time":time.time() # Intermission ends in 1 minute
                        }})
                    else:
                        #if noone has won
                        await self.db.crew.update_one({"guild_id":guild.id}, {"$set":{
                            "state":"intermission",
                            "state_switch_time":time.time() + 60 # Intermission ends in 1 minute
                        }})
                        continue_embed = discord.Embed(
                            title=f"There are still imposters among you!",
                            description=f"The next round will begin in 1 minute.",
                            color=16777215
                        )
                        continue_embed.set_thumbnail(url="https://media.discordapp.net/attachments/1113324969045282856/1119437109573451827/images_32.jpg")
                        await channel.send(embed=continue_embed)
                    continue
                if math.floor((crew_data['state_switch_time'] - time.time())/60) != 0:
                    await channel.send(f"You have {math.floor((crew_data['state_switch_time'] - time.time())/60)} minutes and {round((crew_data['state_switch_time'] - time.time()) % 60)} seconds left to vote!")
                elif round(crew_data['state_switch_time'] - time.time()) < 30:
                    await channel.send("You have 30 more seconds to vote!")
                else:
                    await channel.send("You have 1 minute left to vote!")

            
            elif crew_data["state"] == "intermission":
                if time.time() >= crew_data["state_switch_time"]:
                    #time is up
                    #if some team has won then do this:
                    crew_prompt, imposter_prompt = self._get_prompts()
                    await self.db.crew.update_one({"guild_id":guild.id}, {"$set":{
                        "state":"match",
                        "state_switch_time":time.time() + 60 * 5, # 5 min till match ends
                        "can_answer":True,
                        "prompt":crew_prompt
                    }})
                    await self._send_prompts(guild, crew_prompt, imposter_prompt)
                    new_round_embed = discord.Embed(
                        title="Its time for a new round!",
                        description="A new prompt has been sent to all of you in DM.\nYou have 5 minutes to use `/respond` in this text channel to respond to the prompt.",
                        color=16777215
                    )
                    new_round_embed.set_thumbnail(url="https://media.tenor.com/gQV5VzHLWQIAAAAM/among-us-sus.gif")
                    
                    await channel.send(embed=new_round_embed)
                    continue

    @game_loop.before_loop
    async def before_game_loop(self):
        await self.bot.wait_until_ready()

    def _get_prompts(self) -> Tuple[str, str]:
        json_f = open(os.path.abspath(os.path.join(os.path.dirname( __file__ ), '..', "prompts.json")))
        prompts = json.load(json_f)
        json_f.close()
        prompt = random.choice(prompts)
        imposter_prompt:str = random.choice(prompt["imposter"])
        return (prompt["crew"], imposter_prompt)

    async def _send_prompts(self, guild:discord.Guild, crew_prompt:str, imposter_prompt:str):
        async for crew_member in self.db.crew_member.find({"guild_id":guild.id}):
            user = await self.bot.fetch_user(crew_member["user_id"])
            if crew_member["imposter"]:
                embed = discord.Embed(
                    title="***You are an IMPOSTER!***  Here is your prompt:",
                    description=imposter_prompt,
                    color=16777215
                )
                await user.send(embed=embed)
            else:
                embed = discord.Embed(
                    title="***You are a CREW MEMBER!***  Here is your prompt:",
                    description=crew_prompt,
                    color=16777215
                )
                await user.send(embed=embed)

    @app_commands.command(name='start', description='Starts the game.  This command can only be used by the crew host.')
    async def start(self, interaction:discord.Interaction):
        member = await self.db.crew_member.find_one({"user_id":interaction.user.id, "guild_id":interaction.guild_id})
        crew = await self.db.crew.find_one({"guild_id":interaction.guild_id})
        # set the imposters
        for _ in range(random.randint(1,3 if len(crew["crew"]) > 4 else 1)):
            await self.db.crew_member.update_one({"_id":ObjectId(random.choice(crew["crew"]))}, {"$set":{
                "imposter":True
            }})
        # Send the prompt via DM to everyone in the crew
        crew_prompt, imposter_prompt = self._get_prompts()
        await self.db.crew.update_one({"guild_id":interaction.guild_id}, {"$set":{
            "state":"match",
            "state_switch_time":time.time() + 60 * 5, # in 5 min switch states
            "can_answer":True,
            "prompt":crew_prompt
        }})
        await self._send_prompts(interaction.guild, crew_prompt, imposter_prompt)
        embed = discord.Embed(
                        title="There are one or more imposters among your crew!",
                        description="A prompt has been sent to all of you in DM.\nYou have 5 minutes to use `/respond` in this text channel to respond to the prompt.",
                        color=16777215
                    )
        embed.set_thumbnail(url="https://media.tenor.com/gQV5VzHLWQIAAAAM/among-us-sus.gif")
        
        # change crew state to match
        await interaction.response.send_message(embed=embed)


async def setup(client):
    await client.add_cog(Crewmate(client))
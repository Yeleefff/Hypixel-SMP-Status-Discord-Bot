# Possible things to add:
# Batch addition and remove of usernames/uuids
# Command to change embed color for response embeds

# Notes:
# Bug where documents in was_running are being made or not deleted correctly, leads to it being bloated with messages that dont acutally exist any more and interferes with ones that are working
# Have to set up logging instead of print statements

import os
import logging
import asyncio
import aiohttp

import discord
from discord import app_commands
from discord.ext import commands, tasks

from mojang import API
import mojang.errors
import pymongo

from keep_alive import keep_alive

# logger = logging.getLogger(__name__)
# logger.setLevel(logging.INFO)
# formatter = logging.Formatter('%(levelname)s:%(message)s')
log_handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
# log_handler.setFormatter(formatter)
# logger.addHandler(log_handler)

dbclient = pymongo.MongoClient(f'mongodb+srv://root:{os.getenv("db_pass")}@cluster0.6qx6ad1.mongodb.net/?retryWrites=true&w=majority')
db = dbclient["HypixelSMPBot"]

async def get_smp_status(api_key, guild_id, client):
    players_online, f_players_online = [], ""

    db.validate_collection(str(guild_id))
    
    if db[str(guild_id)].count_documents({}) == 0:
        embed = discord.Embed(colour = discord.Colour.dark_green(), description = 'ERROR: No stored usernames')
        return embed

    async with aiohttp.ClientSession() as session:
        for m in db[str(guild_id)].find():
            async with session.get(f'https://api.hypixel.net/status?key={api_key}&uuid={m["uuid"]}') as data:
                data = await data.json()

                if data['success']:
                    if data['session']['online'] and data['session']['gameType'] == 'SMP':
                        players_online.append(m["username"])
                        
                elif not data['success']:
                    if data['cause'] == 'Invalid API key':
                        print(f'Guild_id: {guild_id} ERROR: Invalid Hypixel API key')
                        embed = discord.Embed(colour = discord.Colour.dark_green(), description = 'ERROR: Invalid Hypixel API key')
                        return embed
                        
                    else:
                        print(f'Guild_id: {guild_id} ERROR: Hypixel API request failed because of {data["cause"]}')
                        embed = discord.Embed(colour = discord.Colour.dark_green(), description = f'ERROR: Hypixel API request failed because of {data["cause"]}')
                        return embed

    if len(players_online) > 0:
        print(f'GUILD_ID: {guild_id} INFO: Player(s) on the SMP {players_online}')
        
        status = '🟢 Online'
        
        for username in players_online:
            f_players_online += username + ", "
        f_players_online = f_players_online.rstrip(", ")
        
    else:
        print(f'Guild_id: {guild_id} INFO: No players on the SMP')
        
        status = '🔴 Offline'
        f_players_online = 'None'

    embed = discord.Embed(
        colour=discord.Colour.dark_green(),
        description=status,
        title='SMP Status')
    embed.set_footer(text='Refreshing every minute!')
    embed.set_thumbnail(url="https://i.imgur.com/hVNyOfJ.jpg")
    embed.add_field(name="Players Online", value=f_players_online, inline=False)
    return embed

def run_bot():
    client = commands.Bot(command_prefix = '~', intents = discord.Intents.default())

    @client.event
    async def on_ready():
        await client.change_presence(activity=discord.Game('Still in Beta'))
        print('INFO: Custom status set')
        synced = await client.tree.sync()
        print(f'INFO: Synced {len(synced)} command(s)')

        if db["was_running"].count_documents({}) > 0:
            for m in db["was_running"].find():
                try:
                    channel = client.get_channel(m["channel_id"])
                    message = await channel.fetch_message(m["message_id"])
                    livestatus_loop.start(channel, message)
                           
                except discord.errors.NotFound:
                    db["was_running"].delete_one(m)
                    print(f'Guild_id: {channel.guild.id} INFO: Live status message was deleted')

        if db["data"].count_documents({}) == 0:
            db["data"].insert_one({"color": discord.Colour.dark_green(),})
        
        print(f'INFO: {client.user} is online')

        # needed for bot owner and other information
        # if not hasattr(client, 'appinfo'):
        #     client.appinfo = await client.application_info()
        # print('INFO: Synced AppInfo')

    @client.tree.command(name="add", description ="Adds a user to the list of usernames to query")
    @app_commands.describe(username = 'Valid username to add')
    @app_commands.checks.has_permissions(kick_members=True)
    async def add(interaction: discord.Interaction, username: str):
        try:
            uuid = API().get_uuid(username)
              
            if db[str(interaction.guild_id)].count_documents({"username": username}) == 0:
                db[str(interaction.guild_id)].insert_one({"username": username,
                                                          "uuid": uuid,})
                
                embed = discord.Embed(
                    colour = discord.Colour.dark_green(),
                    description = f'Added username "{username}"')
                
                await interaction.response.send_message(embed=embed)
                print(f'Guild_id: {interaction.guild_id} INFO: "{username}" was added to db')
                
            else:
                embed = discord.Embed(
                    colour = discord.Colour.dark_green(),
                    description = f'Username "{username}" already exists')
                
                await interaction.response.send_message(embed=embed, ephemeral=True)
                print(f'Guild_id: {interaction.guild_id} INFO: "{username}" already exists')
                
        except mojang.errors.NotFound:
            embed = discord.Embed(
                    colour = discord.Colour.dark_green(),
                    description = f'"{username}" is not a valid username')
          
            await interaction.response.send_message(embed=embed, ephemeral=True)
            print(f'Guild_id: {interaction.guild_id} INFO: User attempted to add invalid username "{username}"')

    @client.tree.command(name="remove", description ="Removes a user from the list of usernames to query")
    @app_commands.describe(username ='Valid username to remove')
    @app_commands.checks.has_permissions(kick_members=True)
    async def remove(interaction: discord.Interaction, username: str):
        try:
            db.validate_collection(str(interaction.guild_id))
            
            remove_result = db[str(interaction.guild_id)].delete_one({"username": username})
            
            if remove_result.deleted_count == 1:
                embed = discord.Embed(
                    colour=discord.Colour.dark_green(),
                    description=f'Removed username "{username}"')
                
                await interaction.response.send_message(embed=embed)
                print(f'Guild_id: {interaction.guild_id} INFO: "{username}" was removed from usernames')
                
            else:
                embed = discord.Embed(
                    colour=discord.Colour.dark_green(),
                    description=f'"{username}" is not a valid username')
                
                await interaction.response.send_message(embed=embed, ephemeral=True)
                print(f'Guild_id: {interaction.guild_id} INFO: User attempted to remove invalid username "{username}"')

        except pymongo.errors.OperationFailure:
            await interaction.response.send_message('No stored usernames')
            print(f'Guild_id: {interaction.guild_id} INFO: No stored usernames')
        
    @client.tree.command(name="stored", description ="Lists the stored usernames")
    @app_commands.checks.has_permissions(kick_members=True)
    async def stored(interaction: discord.Interaction):
        try:
            db.validate_collection(str(interaction.guild_id))
            
            if db[str(interaction.guild_id)].count_documents({}) == 0:
                embed = discord.Embed(
                    colour=discord.Colour.dark_green(),
                    description='None',
                    title='Stored Usernames')
                
                await interaction.response.send_message(embed=embed)
                print(f'Guild_id: {interaction.guild_id} INFO: No stored usernames')
                
            else:
                usernames, f_usernames = [], ""
                for m in db[str(interaction.guild_id)].find():
                    usernames.append(m["username"])
                    f_usernames += m["username"] + ", "
                f_usernames = f_usernames.rstrip(", ")
                
                embed = discord.Embed(
                    colour=discord.Colour.dark_green(),
                    description=f'Count: {len(usernames)}\n{f_usernames}',
                    title='Stored Usernames:')
    
                await interaction.response.send_message(embed=embed)
                print(f'Guild_id: {interaction.guild_id} INFO: Queried stored usernames {usernames}')
                
        except pymongo.errors.OperationFailure:
            embed = discord.Embed(
                colour=discord.Colour.dark_green(),
                description='None',
                title='Stored Usernames')
            await interaction.response.send_message(embed=embed)
            print(f'Guild_id: {interaction.guild_id} INFO: No stored usernames')

    @client.tree.command(name="livestatus", description="Creates an auto updating message that checks if given users are on an Hypixel SMP")
    @app_commands.checks.has_permissions(kick_members=True)
    async def livestatus(interaction: discord.Interaction):
        await interaction.response.send_message(content='SMP status message should appear in a few seconds', ephemeral=True, delete_after=1)

        try:
            channel = interaction.channel
            print(f'Guild_id: {channel.guild.id} INFO: Live status requested SMP data')
            embed = await get_smp_status(os.getenv("hypixel_api_key"), channel.guild.id, client)
            message = await channel.send(embed=embed)

            db["was_running"].insert_one({"guild_id": channel.guild.id,
                                          "message_id": message.id,
                                          "channel_id": channel.id,})
                
            await asyncio.sleep(60)
            livestatus_loop.start(channel, message)

        except pymongo.errors.OperationFailure:
            print(f'Guild_id: {channel.guild.id} INFO: User requested from db without stored usernames')

        except mojang.errors.MojangError:
            print(f'Guild_id: {channel.guild.id} ERROR: Server error or improper request, please try again or in a few minutes')
            
        except Exception as e:
            print(f'Guild_id: {channel.guild.id} ERROR: {e}')
    
    @tasks.loop(seconds=60)
    async def livestatus_loop(channel, message):
        try:
            print(f'Guild_id: {channel.guild.id} INFO: Live status requested SMP data')
            embed = await get_smp_status(os.getenv("hypixel_api_key"), channel.guild.id, client)
            await message.edit(embed=embed)

        except discord.errors.NotFound as e:
            if e.code == 10008:
                livestatus_loop.cancel()
                db["was_running"].delete_one({"message_id": message.id,})
                print(f'Guild_id: {channel.guild.id} INFO: Live status message was deleted')
                
        except pymongo.errors.OperationFailure:
            print(f'Guild_id: {channel.guild.id} INFO: User requested from db without stored usernames')

        except mojang.errors.MojangError:
            print(f'Guild_id: {channel.guild.id} ERROR: Server error or improper request, please try again or in a few minutes')

        except Exception as e:
            print(f'Guild_id: {channel.guild.id} ERROR: {e}')

    @client.tree.command(name="embedcolor", description="Changes the default embed color")
    @app_commands.describe(colors='Colors to choose from')
    @app_commands.checks.has_permissions(kick_members=True)
    @app_commands.choices(colors=[
        discord.app_commands.Choice(name='Dark teal', value=str(discord.Colour.dark_teal()))
    ])
    async def embedcolor(interaction: discord.Interaction, colors: discord.app_commands.Choice[str]):
        if db["data"].count_documents({"guild_id": interaction.guild_id}) == 0:
            db["data"].insert_one({"guild_id": interaction.guild_id,
                                   "color": colors.value,})
        else:
            db["data"].update_one({"guild_id": interaction.guild_id}, {"$set": {"color": colors.value,}})

        embed = discord.Embed(colour=discord.Colour.from_str(colors.value), description= f'Color changed to {colors.name}')
        await interaction.response.send_message(embed=embed)
        
    keep_alive()
    client.run(os.getenv("discord_token"), log_handler=log_handler)

run_bot()

# Possible things to add:
# Batch addition and remove of usernames/uuids

import os
import sys
import typing
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

log_formatter = logging.Formatter('[{levelname:<8}] [{name}] {message}', style='{')
#log_formatter = logging.Formatter('[line {lineno:<5}] [{levelname}] [{name}] {message}', style='{')

file_handler = logging.FileHandler(filename='log.log', encoding='utf-8', mode='w')
file_handler.setFormatter(log_formatter)
console_handler = logging.StreamHandler(stream=sys.stdout)
console_handler.setFormatter(log_formatter)

logger = logging.getLogger('client')
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

console_logger = logging.getLogger('console_logger')
console_logger.setLevel(logging.INFO)
console_logger.addHandler(console_handler)

dbclient = pymongo.MongoClient(f'mongodb+srv://root:{os.getenv("db_pass")}@cluster0.6qx6ad1.mongodb.net/?retryWrites=true&w=majority')
db = dbclient["HypixelSMPBot"]

async def get_smp_status(api_key, guild_id, client):
    players_online, f_players_online = [], ""

    if db[str(guild_id)].count_documents({}) == 0:
        embed = discord.Embed(colour = discord.Colour.from_str(db["data"].find_one({"guild_id": guild_id})["color"]), description = 'No stored usernames')
        logger.info(f'[Guild_id: {guild_id}] - Live status used without having any stored usernames')
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
                        logger.error(f'[Guild_id: {guild_id}] - Invalid Hypixel API key')
                        embed = discord.Embed(colour = discord.Colour.from_str(db["data"].find_one({"guild_id": guild_id})["color"]), description = 'ERROR: Invalid Hypixel API key')
                        return embed

                    else:
                        logger.error(f'[Guild_id: {guild_id}] - Hypixel API request failed because of {data["cause"]}')
                        embed = discord.Embed(colour = discord.Colour.from_str(db["data"].find_one({"guild_id": guild_id})["color"]), description = f'ERROR: Hypixel API request failed because of {data["cause"]}')
                        return embed

    if len(players_online) > 0:
        console_logger.info(f'[GUILD_ID: {guild_id}] - Player(s) on the SMP {players_online}')

        status = '🟢 Online'

        for username in players_online:
            f_players_online += username + ", "
        f_players_online = f_players_online.rstrip(", ")

    else:
        console_logger.info(f'[Guild_id: {guild_id}] - No players on the SMP')

        status = '🔴 Offline'
        f_players_online = 'None'

    embed = discord.Embed(
        colour=discord.Colour.from_str(db["data"].find_one({"guild_id": guild_id})["color"]),
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
        logger.info('- Custom status set')
        synced = await client.tree.sync()
        logger.info(f'- Synced {len(synced)} command(s)')
        logger.info(f'- {client.user} is online')

        if db["was_running"].count_documents({}) > 0:
            for m in db["was_running"].find():
                try:
                    channel = client.get_channel(m["channel_id"])
                    message = await channel.fetch_message(m["message_id"])
                    live_status_loop.start(channel, message)
                    logger.info(f'[Guild_id: {channel.guild.id}] - Live status message resuming')

                except discord.errors.NotFound:
                    db["was_running"].delete_one(m)
                    logger.info(f'[Guild_id: {channel.guild.id}] - Live status message was deleted')

        # needed for bot owner and other information
        # if not hasattr(client, 'appinfo'):
        #     client.appinfo = await client.application_info()
        # print('INFO: Synced AppInfo')

    @client.event
    async def on_guild_join(guild):
        db["data"].insert_one({"guild_id": guild.id,
                               "color": str(discord.Colour.dark_green()),})

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
                    colour = discord.Colour.from_str(db["data"].find_one({"guild_id": interaction.guild_id})["color"]),
                    description = f'Added username "{username}"')

                await interaction.response.send_message(embed=embed)
                logger.info(f'[Guild_id: {interaction.guild_id}] - "{username}" was added to db')

            else:
                embed = discord.Embed(
                    colour = discord.Colour.from_str(db["data"].find_one({"guild_id": interaction.guild_id})["color"]),
                    description = f'Username "{username}" already exists')

                await interaction.response.send_message(embed=embed, ephemeral=True)
                logger.info(f'[Guild_id: {interaction.guild_id}] - "{username}" already exists')

        except mojang.errors.NotFound:
            embed = discord.Embed(
                    colour = discord.Colour.from_str(db["data"].find_one({"guild_id": interaction.guild_id})["color"]),
                    description = f'"{username}" is not a valid username')

            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info(f'[Guild_id: {interaction.guild_id}] - User attempted to add invalid username "{username}"')

    @client.tree.command(name="remove", description ="Removes a user from the list of usernames to query")
    @app_commands.describe(username ='Valid username to remove')
    @app_commands.checks.has_permissions(kick_members=True)
    async def remove(interaction: discord.Interaction, username: str):
        try:
            if db[str(interaction.guild_id)].count_documents({}) == 0:
                embed = discord.Embed(
                    colour=discord.Colour.from_str(db["data"].find_one({"guild_id": interaction.guild_id})["color"]),
                    description='No stored usernames')

                await interaction.response.send_message(embed=embed)
                logger.info(f'[Guild_id: {interaction.guild_id}] - User attempted to remove a username without having any stored usernames')

            else:        
                remove_result = db[str(interaction.guild_id)].delete_one({"username": username})

                if remove_result.deleted_count == 1:
                    embed = discord.Embed(
                        colour=discord.Colour.from_str(db["data"].find_one({"guild_id": interaction.guild_id})["color"]),
                        description=f'Removed username "{username}"')

                    await interaction.response.send_message(embed=embed)
                    logger.info(f'[Guild_id: {interaction.guild_id}] - "{username}" was removed from usernames')

                else:
                    embed = discord.Embed(
                        colour=discord.Colour.from_str(db["data"].find_one({"guild_id": interaction.guild_id})["color"]),
                        description=f'"{username}" is not a valid username')

                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    logger.info(f'[Guild_id: {interaction.guild_id}] - User attempted to remove invalid username "{username}"')

        except Exception as e:
            logger.exception(f'Guild_id: {interaction.guild_id} ERROR: {e}')

    @client.tree.command(name="stored", description ="Lists the stored usernames")
    @app_commands.checks.has_permissions(kick_members=True)
    async def stored(interaction: discord.Interaction):
        try:
            if db[str(interaction.guild_id)].count_documents({}) == 0:
                embed = discord.Embed(
                    colour=discord.Colour.from_str(db["data"].find_one({"guild_id": interaction.guild_id})["color"]),
                    description='None',
                    title='Stored Usernames')

                await interaction.response.send_message(embed=embed)
                logger.info(f'[Guild_id: {interaction.guild_id}] - No stored usernames')

            else:
                usernames, f_usernames = [], ""
                for m in db[str(interaction.guild_id)].find():
                    usernames.append(m["username"])
                    f_usernames += m["username"] + ", "
                f_usernames = f_usernames.rstrip(", ")

                embed = discord.Embed(
                    colour=discord.Colour.from_str(db["data"].find_one({"guild_id": interaction.guild_id})["color"]),
                    description=f'Count: {len(usernames)}\n{f_usernames}',
                    title='Stored Usernames:')

                await interaction.response.send_message(embed=embed)
                logger.info(f'[Guild_id: {interaction.guild_id}] - Queried stored usernames {usernames}')

        except Exception as e:
            logger.exception(f'[Guild_id: {interaction.guild_id}] - {e}')

    @client.tree.command(name="lives_status", description="Creates an auto updating message that checks if given users are on a Hypixel SMP")
    @app_commands.checks.has_permissions(kick_members=True)
    async def live_status(interaction: discord.Interaction):
        await interaction.response.send_message(content='SMP status message should appear in a few seconds', ephemeral=True, delete_after=1)

        try:
            channel = interaction.channel
            logger.info(f'[Guild_id: {interaction.guild_id}] - User created live status message')
            embed = await get_smp_status(os.getenv("hypixel_api_key"), interaction.guild_id, client)
            message = await channel.send(embed=embed)

            db["was_running"].insert_one({"guild_id": interaction.guild_id,
                                          "message_id": message.id,
                                          "channel_id": channel.id,})

            await asyncio.sleep(60)
            live_status_loop.start(channel, message)

        except mojang.errors.MojangError:
            logger.error(f'[Guild_id: {interaction.guild_id}] - Mojang API server error or improper request')

        except Exception as e:
            logger.exception(f'[Guild_id: {interaction.guild_id}] - {e}')

    @tasks.loop(seconds=60)
    async def live_status_loop(channel, message):
        try:
            console_logger.info(f'[Guild_id: {channel.guild.id}] - Live status requested SMP data')
            embed = await get_smp_status(os.getenv("hypixel_api_key"), channel.guild.id, client)
            await message.edit(embed=embed)

        except discord.errors.NotFound as e:
            if e.code == 10008:
                live_status_loop.cancel()
                db["was_running"].delete_one({"message_id": message.id,})
                logger.info(f'[Guild_id: {channel.guild.id}] - Live status message was deleted')

        except mojang.errors.MojangError:
            logger.error(f'[Guild_id: {channel.guild.id}] - Mojang API server error or improper request')

        except Exception as e:
            logger.exception(f'[Guild_id: {channel.guild.id}] - {e}')

    @client.tree.command(name="embed_color", description="Changes the default embed color")
    @app_commands.describe(colors='Colors to choose from')
    @app_commands.choices(colors=[
        discord.app_commands.Choice(name='Purple', value=str(discord.Colour.purple())),
        discord.app_commands.Choice(name='Dark purple', value=str(discord.Colour.dark_purple())),
        discord.app_commands.Choice(name='Blurple', value=str(discord.Colour.blurple())),
        discord.app_commands.Choice(name='Blue', value=str(discord.Colour.blue())),
        discord.app_commands.Choice(name='Dark blue', value=str(discord.Colour.dark_blue())),
        discord.app_commands.Choice(name='Teal', value=str(discord.Colour.teal())),
        discord.app_commands.Choice(name='Dark teal', value=str(discord.Colour.dark_teal())),
        discord.app_commands.Choice(name='Green', value=str(discord.Colour.green())),
        discord.app_commands.Choice(name='Dark green', value=str(discord.Colour.dark_green())),
        discord.app_commands.Choice(name='Yellow', value=str(discord.Colour.yellow())),
        discord.app_commands.Choice(name='Gold', value=str(discord.Colour.gold())),
        discord.app_commands.Choice(name='Dark gold', value=str(discord.Colour.dark_gold())),
        discord.app_commands.Choice(name='Orange', value=str(discord.Colour.orange())),
        discord.app_commands.Choice(name='Dark orange', value=str(discord.Colour.dark_orange())),
        discord.app_commands.Choice(name='Red', value=str(discord.Colour.red())),
        discord.app_commands.Choice(name='Dark Red', value=str(discord.Colour.dark_red())),
        discord.app_commands.Choice(name='Pink', value=str(discord.Colour.pink())),
        discord.app_commands.Choice(name='Magenta', value=str(discord.Colour.magenta())),
        discord.app_commands.Choice(name='Dark magenta', value=str(discord.Colour.dark_magenta())),
        discord.app_commands.Choice(name='Light gray', value=str(discord.Colour.light_gray())),
        discord.app_commands.Choice(name='Dark gray', value=str(discord.Colour.dark_gray())),
        discord.app_commands.Choice(name='L̵i̵g̵h̵t̵ ̵t̵h̵e̵m̵e̵ Horrible shit color', value=str(discord.Colour.light_embed())),
        discord.app_commands.Choice(name='Dark Theme', value=str(discord.Colour.dark_theme()))
    ])
    @app_commands.checks.has_permissions(kick_members=True)
    async def embed_color(interaction: discord.Interaction, colors: discord.app_commands.Choice[str]):
        try:
            db["data"].update_one({"guild_id": interaction.guild_id}, {"$set": {"color": colors.value,}})

            embed = discord.Embed(colour=discord.Colour.from_str(colors.value), description= f'Color changed to {colors.name.lower()}')
            logger.info(f'[Guild_id: {interaction.guild_id}] - Embed color changed to {colors.name.lower()}')
            await interaction.response.send_message(embed=embed)

        except Exception as e:
            logger.exception(f'[Guild_id: {interaction.guild_id}] - {e}')
    
    # keep_alive()
    client.run(os.getenv("discord_token"), log_handler=file_handler, log_formatter=log_formatter)

run_bot()
